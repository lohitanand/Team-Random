"""Personalised customer message: an approved playbook template, reworded by the LLM (max 300
characters, no new offers), validated by guardrails, else the template itself."""
from __future__ import annotations

import json

from backend.app.decision.playbook import get_playbook
from backend.app.llm.client import LLMClient, LLMError, load_prompt
from backend.app.llm.fallbacks import fallback_message, message_slots
from backend.app.llm.guardrails import validate
from backend.app.schemas.alerts import PlaybookAction
from backend.app.schemas.evidence import Packet
from backend.app.schemas.llm import CustomerMessage, MessageOut


def draft_message(action: PlaybookAction, packet: Packet, friction: str, product_name: str | None = None,
                  client: LLMClient | None = None) -> CustomerMessage:
    client = client or LLMClient()
    template_text = fallback_message(action, packet, product_name).text
    if not client.active:
        return fallback_message(action, packet, product_name)

    payload = {"template": template_text, "action": action.description, "channel": action.channel,
               "slots": message_slots(packet, product_name)}
    try:
        raw = client.complete_json(load_prompt("message"), json.dumps(payload))
    except LLMError as exc:
        return fallback_message(action, packet, product_name, [f"llm_error: {str(exc)[:200]}"])

    # Offer terms are allowed only if the approved template itself already uses them.
    template_low = template_text.lower()
    allowed = [t for t in action.allows_terms if t in template_low]
    parsed, result = validate(raw, MessageOut, ["message"], payload, friction, {action.id}, allowed)
    if parsed is None:
        return fallback_message(action, packet, product_name, result.failures)
    return CustomerMessage(text=parsed.message, template_id=action.template_id, source="llm")


def template_text(action: PlaybookAction) -> str:
    return get_playbook().template(action.template_id)
