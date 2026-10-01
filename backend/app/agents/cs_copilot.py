"""Customer-service copilot (CLAUDE.md §7.8): gathers the customer's journey, order/payment/refund
status and tickets (read-only), drafts a reply, and ALWAYS requires human approval."""
from __future__ import annotations

import json
from typing import Any

from backend.app.agents.tools import Tools
from backend.app.decision.playbook import get_playbook
from backend.app.llm.client import LLMClient, LLMError, load_prompt
from backend.app.llm.guardrails import validate
from backend.app.schemas.llm import CSReplyOut


def gather(tools: Tools, session_id: str) -> dict[str, Any]:
    store = tools.store
    sess = store.session_index.loc[session_id].to_dict() if session_id in store.session_index.index else {}
    events = store.session_events(session_id)
    steps = []
    for e in events:
        label = e["event"].replace("_", " ")
        if not steps or steps[-1] != label:
            steps.append(label)
    pay = store.payments[store.payments["session_id"] == session_id]
    order_id = sess.get("order_id")
    order = store.orders[store.orders["order_id"] == order_id].head(1).to_dict("records") if order_id else []
    feedback = tools.sample_feedback(session_id=session_id, user_id=sess.get("user_id"), limit=3)
    product = store.product_by_id.get(sess.get("primary_product_id") or "", {})
    return {
        "journey": steps[:25],
        "product": product.get("subcategory"),
        "payments": {"attempts": int(len(pay)), "failed": int((pay["status"] == "failed").sum()),
                     "debited_without_order": int(((pay["status"] == "failed") & pay["amount_debited"]).sum())},
        "order": {k: order[0][k] for k in ("status", "courier", "delay_days", "refund_status")} if order else None,
        "customer_messages": [s["text"] for s in feedback["samples"]],
        "themes": list(feedback["themes"]),
    }


def fallback_reply(ctx: dict[str, Any], action_id: str | None) -> str:
    action = get_playbook().action(action_id) if action_id else None
    allows = set(action.allows_terms) if action else set()
    lines = ["Hi, thank you for reaching out and sorry for the trouble."]
    order = ctx.get("order") or {}
    if order.get("status") in ("delayed", "in_transit") or (order.get("delay_days") or 0) > 0:
        lines.append("Your order is running late and we are checking with the courier for the latest status.")
    if order.get("refund_status") == "pending" and "refund" in allows:
        lines.append("We can see your refund is being processed.")
    if ctx["payments"]["debited_without_order"] and ({"reversed", "refund"} & allows):
        lines.append("We can see a payment that did not complete; any amount debited is reversed to your account automatically.")
    if action:
        lines.append(get_playbook().template(action.template_id).format(product=ctx.get("product") or "item",
                                                                         method="your payment method", action=""))
    lines.append("Please reply here if you need anything else.")
    return " ".join(lines)[:700]


def draft_reply(ctx: dict[str, Any], friction: str, action_id: str | None,
                client: LLMClient | None = None) -> tuple[str, str, list[str]]:
    """(reply, source, guardrail_failures)."""
    client = client or LLMClient()
    fallback = fallback_reply(ctx, action_id)
    if not client.active:
        return fallback, "fallback", []
    action = get_playbook().action(action_id) if action_id else None
    payload = {"customer_context": ctx, "friction_type": friction,
               "approved_action": action.description if action else None, "reference_reply": fallback}
    try:
        raw = client.complete_json(load_prompt("cs_reply"), json.dumps(payload, default=str))
    except LLMError as exc:
        return fallback, "fallback", [f"llm_error: {str(exc)[:200]}"]
    parsed, result = validate(raw, CSReplyOut, ["reply"], payload, friction, {action_id} if action_id else set(),
                              action.allows_terms if action else [])
    if parsed is None:
        return fallback, "fallback", result.failures
    return parsed.reply, "llm", []
