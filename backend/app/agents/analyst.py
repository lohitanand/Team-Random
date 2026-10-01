"""Analyst Q&A (stretch): answers business questions using the same read-only tools.
Answers must cite only numbers returned by the tools (grounding guardrail), else a deterministic answer."""
from __future__ import annotations

import json
import time
from typing import Any

from backend.app.agents.tools import Tools, call_tool, openai_tools
from backend.app.config import Settings, get_settings
from backend.app.llm.client import LLMClient, LLMError
from backend.app.llm.guardrails import check_grounding, check_policy, parse_json
from backend.app.schemas.llm import AnalystOut

SYSTEM = ("You answer business questions about an e-commerce store's customer-journey friction using ONLY the "
          "tools provided. Call the tools you need (max 6), then reply with JSON only: "
          '{"answer": "<2-4 sentences>", "numbers_cited": ["<numbers you used>"]}. '
          "Use only numbers returned by tools. Never invent numbers.")


def _route(question: str) -> list[tuple[str, dict[str, Any]]]:
    q = question.lower()
    steps: list[tuple[str, dict[str, Any]]] = []
    if any(w in q for w in ("gateway", "payment", "upi")):
        steps += [("gateway_health", {"gateway": g, "around": "2026-09-22T20:00"}) for g in ("A", "B", "C")]
    if any(w in q for w in ("courier", "delivery", "delay", "eta")):
        steps.append(("courier_health", {"courier": "CourierX", "around": "2026-09-19T12:00"}))
        steps.append(("drop_off_by_segment", {"step": "checkout", "segment": "city"}))
    if any(w in q for w in ("drop", "funnel", "abandon", "leave", "device")):
        steps.append(("drop_off_by_segment", {"step": "payment", "segment": "device"}))
        steps.append(("compare_converters_vs_abandoners", {}))
    if not steps or any(w in q for w in ("revenue", "top", "biggest", "friction", "why")):
        steps.insert(0, ("top_frictions", {"limit": 5}))
    return steps[:6]


def _deterministic_answer(results: list[dict[str, Any]]) -> str:
    parts = []
    for r in results:
        name, out = r["tool"], r["result"]
        if name == "top_frictions" and "frictions" in out:
            top = out["frictions"][:3]
            parts.append("Top frictions by revenue at risk: " + "; ".join(
                f"{f['friction_type'].replace('_', ' ')} ({f['sessions']} sessions, {f['revenue_at_risk']:,.0f} at risk)"
                for f in top) + ".")
        elif name == "gateway_health":
            parts.append(f"Gateway {out['gateway']}: {out['failure_rate']:.0%} failure rate in the window vs "
                         f"{out['baseline_failure_rate']:.0%} baseline.")
        elif name == "courier_health":
            parts.append(f"{out['courier']}: {out['delayed_share']:.0%} of orders delayed vs "
                         f"{out['baseline_delayed_share']:.0%} baseline.")
        elif name == "drop_off_by_segment" and out.get("segments"):
            top = out["segments"][0]
            parts.append(f"At {out['step']}, overall exit rate is {out['overall_exit_rate']:.0%}; highest is "
                         f"{top[out['segment']]} at {top['exit_rate']:.0%}.")
        elif name == "compare_converters_vs_abandoners" and out.get("features"):
            f = out["features"][0]
            parts.append(f"Abandoners differ most on {f['feature'].replace('_', ' ')} "
                         f"({f['abandoners']} vs {f['converters']} for converters).")
    return " ".join(parts) or "No data found for that question."


def ask(question: str, tools: Tools, client: LLMClient | None = None, settings: Settings | None = None,
        on_tool_call=None) -> dict[str, Any]:
    s = settings or get_settings()
    client = client or LLMClient(s)
    calls: list[dict[str, Any]] = []

    def run(name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = call_tool(tools, name, args)
        calls.append({"tool": name, "args": args, "result": result})
        if on_tool_call:
            on_tool_call(name, args, result)
        return result

    if client.active:
        try:
            deadline = time.monotonic() + s.agent_timeout_seconds
            messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM},
                                              {"role": "user", "content": question[:1000]}]
            content = None
            for _ in range(s.agent_max_tool_calls + 1):
                reply = client.chat(messages, role="agent", tools=openai_tools(),
                                    timeout=max(deadline - time.monotonic(), 1))
                if not reply.tool_calls or len(calls) >= s.agent_max_tool_calls:
                    content = reply.content
                    break
                messages.append({"role": "assistant", "content": reply.content or "", "tool_calls": reply.tool_calls})
                for call in reply.tool_calls[: s.agent_max_tool_calls - len(calls)]:
                    result = run(call["function"]["name"], json.loads(call["function"].get("arguments") or "{}"))
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                     "content": json.dumps(result, default=str)[:4000]})
            parsed, failures = parse_json(content or "", AnalystOut)
            if parsed is not None:
                payload = {"tool_results": [c["result"] for c in calls]}
                failures = check_grounding([parsed.answer], payload) + check_policy([parsed.answer], [])
                if not failures and calls:
                    return {"answer": parsed.answer, "source": "llm", "tool_calls": calls}
        except (LLMError, ValueError, KeyError):
            pass
        calls.clear()

    for name, args in _route(question):
        run(name, args)
    return {"answer": _deterministic_answer(calls), "source": "deterministic", "tool_calls": calls}
