"""Bounded investigation agent (CLAUDE.md §7.8).

Triggered for medium-confidence packets. It only gathers read-only evidence; it never decides.
- LLM enabled: the model chooses tools via OpenAI-style tool calling.
- LLM disabled: a fixed, deterministic tool plan per friction type.
In both modes the *code* turns each tool result into a Finding (what it supports), limits are
enforced (max tool calls, timeout), and on any failure the original packet is returned unchanged.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from backend.app.agents.tools import Tools, call_tool, openai_tools
from backend.app.config import Settings, get_settings
from backend.app.decision.signals import theme_frictions
from backend.app.llm.client import LLMClient, LLMError, load_prompt
from backend.app.schemas.alerts import Decision
from backend.app.schemas.evidence import AggregatePacket, Finding, Packet

OnToolCall = Callable[[str, dict[str, Any], dict[str, Any]], None]
LIVE_MIN_FAILED_SESSIONS = 2


def assess(tool: str, args: dict[str, Any], result: dict[str, Any], friction: str) -> Finding:
    """Deterministic interpretation of one tool result for the decided friction."""
    supports, kind, summary, numbers = None, "none", f"{tool}: no supporting evidence", {}
    if "error" in result:
        return Finding(tool=tool, args=args, summary=f"{tool}: {result['error']}")
    if tool == "gateway_health":
        numbers = {k: result[k] for k in ("failure_rate", "baseline_failure_rate", "failed_sessions")}
        summary = (f"Gateway {result['gateway']} failure rate {result['failure_rate']:.0%} vs "
                   f"{result['baseline_failure_rate']:.0%} baseline ({result['failed_sessions']} failed sessions)")
        if (result.get("multiplier") or 0) >= 2.0 and result["failed_sessions"] >= LIVE_MIN_FAILED_SESSIONS \
                and friction == "payment_failure":
            supports, kind = friction, "aggregate"
    elif tool == "courier_health":
        numbers = {k: result[k] for k in ("delayed_share", "baseline_delayed_share", "orders_in_window")}
        summary = (f"{result['courier']} delayed-order share {result['delayed_share']:.0%} vs "
                   f"{result['baseline_delayed_share']:.0%} baseline ({result['orders_in_window']} orders)")
        if (result.get("multiplier") or 0) >= 2.0 and result["orders_in_window"] >= 3 \
                and friction in ("delivery_uncertainty", "post_purchase_concern"):
            supports, kind = friction, "aggregate"
    elif tool == "sample_feedback":
        themes = result.get("themes", {})
        numbers = {"matched_texts": result["matched"]}
        summary = f"{result['matched']} customer texts; themes: " + (", ".join(themes) or "none")
        if friction in theme_frictions(themes):
            supports, kind = friction, "text"
    elif tool == "product_details":
        missing = result.get("missing_attributes") or []
        no_chart = bool(result.get("sizes")) and not result.get("has_size_chart")
        numbers = {"missing_attributes": len(missing)}
        summary = f"Product {result['product_id']}: size chart {'missing' if no_chart else 'present'}, " \
                  f"{len(missing)} missing attributes"
        if friction == "unclear_product_info" and (no_chart or len(missing) >= 2):
            supports, kind = friction, "catalog"
    elif tool == "stock_check":
        out = result.get("sizes_out_of_stock", [])
        numbers = {"sizes_out_of_stock": len(out)}
        summary = f"Product {result['product_id']}: {len(out)} sizes out of stock"
        if friction == "out_of_stock" and (out or not result.get("in_stock")):
            supports, kind = friction, "catalog"
    elif tool == "order_status_for_sessions":
        numbers = {k: result[k] for k in ("orders", "delayed", "refunds_pending")}
        summary = f"{result['orders']} orders: {result['delayed']} delayed, {result['refunds_pending']} refunds pending"
        if friction == "post_purchase_concern" and (result["delayed"] or result["refunds_pending"]):
            supports, kind = friction, "aggregate"
    elif tool == "drop_off_by_segment":
        numbers = {"overall_exit_rate": result["overall_exit_rate"]}
        top = result["segments"][0] if result["segments"] else None
        summary = f"Exit rate at {result['step']}: {result['overall_exit_rate']:.0%} overall" + (
            f", highest {top[result['segment']]} {top['exit_rate']:.0%}" if top else "")
        if friction == "technical_glitch" and top and top["exit_rate"] >= 1.5 * max(result["overall_exit_rate"], 1e-3):
            supports, kind = friction, "aggregate"
    else:
        summary = f"{tool} returned {len(json.dumps(result, default=str))} bytes of context"
    return Finding(tool=tool, args=args, summary=summary, numbers=numbers, supports=supports, evidence_kind=kind)


def plan(packet: Packet, decision: Decision) -> list[tuple[str, dict[str, Any]]]:
    f = decision.friction_type
    if isinstance(packet, AggregatePacket):
        around = packet.window_start.isoformat()
        sample = packet.session_ids[:200]
        steps: list[tuple[str, dict[str, Any]]] = [("sample_feedback", {"session_ids": sample})]
        if packet.segment_type == "gateway":
            steps.insert(0, ("gateway_health", {"gateway": packet.segment_value, "around": around}))
        elif packet.segment_type == "courier_city":
            courier, _, city = packet.segment_value.partition("|")
            steps.insert(0, ("courier_health", {"courier": courier, "city": city, "around": around}))
            steps.append(("order_status_for_sessions", {"session_ids": sample}))
        elif packet.segment_type == "product":
            steps = [("product_details", {"product_id": packet.segment_value}),
                     ("sample_feedback", {"product_id": packet.segment_value})]
        return steps

    ctx, sid, uid = packet.context, packet.session_id, packet.user_id
    around, product = ctx.get("start"), ctx.get("primary_product_id")
    feedback = ("sample_feedback", {"session_id": sid, "user_id": uid})
    if f == "payment_failure" and ctx.get("gateway"):
        return [("gateway_health", {"gateway": ctx["gateway"], "around": around}), feedback]
    if f == "delivery_uncertainty" and ctx.get("courier"):
        return [("courier_health", {"courier": ctx["courier"], "city": ctx.get("city"), "around": around}), feedback]
    if f == "post_purchase_concern":
        steps = [("order_status_for_sessions", {"session_ids": [sid]}), feedback]
        if ctx.get("courier"):
            steps.append(("courier_health", {"courier": ctx["courier"], "city": ctx.get("city"), "around": around}))
        return steps
    if f == "unclear_product_info" and product:
        return [("product_details", {"product_id": product}), ("sample_feedback", {"product_id": product})]
    if f == "out_of_stock" and product:
        return [("stock_check", {"product_id": product}), feedback]
    if f == "technical_glitch":
        return [("drop_off_by_segment", {"step": ctx.get("exit_step") or "payment", "segment": "device"}), feedback]
    return [feedback]


class Investigator:
    def __init__(self, tools: Tools, client: LLMClient | None = None, settings: Settings | None = None,
                 on_tool_call: OnToolCall | None = None, use_llm: bool = True) -> None:
        self.tools = tools
        self.settings = settings or get_settings()
        self.client = client or LLMClient(self.settings)
        self.on_tool_call = on_tool_call
        self.use_llm = use_llm

    def _run(self, name: str, args: dict[str, Any], friction: str) -> Finding:
        result = call_tool(self.tools, name, args)
        if self.on_tool_call:
            self.on_tool_call(name, args, result)
        return assess(name, args, result, friction)

    def __call__(self, packet: Packet, decision: Decision) -> Packet:
        try:
            if self.use_llm and self.client.active:
                findings = self._llm(packet, decision)
            else:
                findings = self._deterministic(packet, decision)
        except (LLMError, TimeoutError, ValueError, KeyError):
            return packet  # any failure: original packet unchanged
        if not findings:
            return packet
        return packet.model_copy(update={"investigation_findings": [*packet.investigation_findings, *findings]})

    def _deterministic(self, packet: Packet, decision: Decision) -> list[Finding]:
        deadline = time.monotonic() + self.settings.agent_timeout_seconds
        findings = []
        for name, args in plan(packet, decision)[: self.settings.agent_max_tool_calls]:
            if time.monotonic() > deadline:
                raise TimeoutError("investigation timed out")
            findings.append(self._run(name, args, decision.friction_type))
        return findings

    def _llm(self, packet: Packet, decision: Decision) -> list[Finding]:
        deadline = time.monotonic() + self.settings.agent_timeout_seconds
        brief = {"friction_type": decision.friction_type, "confidence": decision.confidence,
                 "packet": json.loads(packet.model_dump_json(exclude={"session_ids"} if isinstance(packet, AggregatePacket)
                                                             else set()))}
        messages: list[dict[str, Any]] = [{"role": "system", "content": load_prompt("investigator")},
                                          {"role": "user", "content": json.dumps(brief, default=str)[:12000]}]
        findings: list[Finding] = []
        calls = 0
        while calls < self.settings.agent_max_tool_calls:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("investigation timed out")
            reply = self.client.chat(messages, role="agent", tools=openai_tools(), timeout=remaining)
            if not reply.tool_calls:
                break
            messages.append({"role": "assistant", "content": reply.content or "", "tool_calls": reply.tool_calls})
            for call in reply.tool_calls:
                if calls >= self.settings.agent_max_tool_calls:
                    break
                calls += 1
                name = call["function"]["name"]
                args = json.loads(call["function"].get("arguments") or "{}")
                finding = self._run(name, args, decision.friction_type)
                findings.append(finding)
                messages.append({"role": "tool", "tool_call_id": call.get("id", name),
                                 "content": json.dumps({"summary": finding.summary, "numbers": finding.numbers})})
        return findings
