"""Phase 7: LLM assist + guardrails + fallbacks. Deliberately bad LLM outputs must be rejected, and
everything must work with LLM_ENABLED=false."""
from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from backend.app.config import Settings
from backend.app.decision.engine import decide_once
from backend.app.decision.playbook import get_playbook
from backend.app.llm.client import LLMClient, LLMError, ToolsUnsupported
from backend.app.llm.explain import explain, explanation_payload
from backend.app.llm.fallbacks import fallback_explanation, fallback_message
from backend.app.llm.guardrails import check_consistency, check_grounding, check_policy
from backend.app.llm.messages import draft_message
from backend.app.schemas.evidence import AggregatePacket, SessionPacket, Signal
from backend.app.schemas.taxonomy import FRICTION_TYPES

S = Settings(_env_file=None)
ZERO = {f: 0.0 for f in FRICTION_TYPES}


def payment_packet(**kw) -> SessionPacket:
    base = dict(packet_id="pk_s_000042", session_id="s_000042", user_id="u_0123456789ab", session_kind="shopping",
                risk_score=0.82, cart_value=2499.0, rule_flags=["payment_retry_x2"],
                friction_probs={**ZERO, "payment_failure": 0.88},
                top_signals=[Signal(feature="payment_failures", shap=0.31)], text_themes=["money_deducted"],
                aggregate_context={"segment_type": "gateway", "segment": "B", "metric": "payment_session_failure_rate",
                                   "friction_hint": "payment_failure", "multiplier": 4.0, "affected_sessions": 23},
                context={"device": "android_app", "city_tier": "tier_2", "gateway": "B", "payment_method": "UPI",
                         "exit_step": "payment", "converted": False})
    base.update(kw)
    return SessionPacket(**base)


def gateway_packet() -> AggregatePacket:
    return AggregatePacket(packet_id="agg_gw_b", segment_type="gateway", segment_value="B",
                           metric="payment_session_failure_rate", friction_hint="payment_failure",
                           window_start=datetime(2026, 9, 22, 19), window_end=datetime(2026, 9, 22, 21),
                           observed=0.82, baseline=0.2, z_score=6.7, multiplier=4.1, affected_sessions=23,
                           session_ids=["s_1"], revenue_at_risk=41500.0, trend="rising",
                           friction_probs={**ZERO, "payment_failure": 0.7},
                           aggregate_context={"rule_support_share": 0.8, "model_support_share": 0.7},
                           top_signals=[Signal(feature="payment_failures", shap=0.2)])


def llm(reply: str | None = None, status: int = 200, handler=None) -> LLMClient:
    settings = Settings(_env_file=None, llm_enabled=True, groq_api_key="k")

    def default(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="error")
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return LLMClient(settings, transport=httpx.MockTransport(handler or default))


GOOD = {"summary": "Payment failures on gateway B are 4.0x the baseline.",
        "behavior_observed": "The customer had 2 failed payment attempts with a cart of 2499 and then left.",
        "likely_business_cause": "Gateway B instability, not price.",
        "evidence_used": ["rule_flags", "multiplier", "cart_value"]}


@pytest.fixture
def decision():
    return decide_once(payment_packet(), S)


# --- the happy path ------------------------------------------------------------------------

def test_valid_llm_explanation_is_used(decision) -> None:
    out = explain(payment_packet(), decision, llm(json.dumps(GOOD)))
    assert out.source == "llm" and out.guardrail_failures == []
    assert out.summary == GOOD["summary"]


# --- deliberately bad outputs -------------------------------------------------------------------

@pytest.mark.parametrize("bad,reason", [
    ("{not json", "schema"),
    (json.dumps({"summary": "x"}), "schema"),
    (json.dumps({**GOOD, "extra_field": "sneaky"}), "schema"),
    (json.dumps({**GOOD, "behavior_observed": "The customer failed 7 payments worth 9,999."}), "grounding: number"),
    (json.dumps({**GOOD, "evidence_used": ["gateway_latency_ms"]}), "grounding: evidence key"),
    (json.dumps({**GOOD, "likely_business_cause": "A coupon failure on checkout."}), "consistency"),
    (json.dumps({**GOOD, "summary": "Recommend check_or_switch_gateway right away."}), "consistency: mentions a different action"),
    (json.dumps({**GOOD, "summary": "Give every customer a 20% discount."}), "policy"),
    (json.dumps({**GOOD, "summary": "Offer cashback to affected users."}), "policy"),
    (json.dumps({**GOOD, "summary": "Customer u_0123456789ab failed twice."}), "policy: contains a customer"),
    (json.dumps({**GOOD, "summary": "Call the customer at 9876543210."}), "policy"),
    (json.dumps({**GOOD, "summary": "We guarantee it is fixed."}), "policy: banned phrase"),
])
def test_bad_explanations_fall_back(decision, bad, reason) -> None:
    out = explain(payment_packet(), decision, llm(bad))
    assert out.source == "fallback"
    assert any(f.startswith(reason) for f in out.guardrail_failures), out.guardrail_failures


def test_llm_http_error_and_timeout_fall_back(decision) -> None:
    assert explain(payment_packet(), decision, llm(status=500)).source == "fallback"

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    out = explain(payment_packet(), decision, llm(handler=timeout))
    assert out.source == "fallback" and out.guardrail_failures[0].startswith("llm_error")


def test_llm_disabled_uses_fallback_without_network(decision) -> None:
    def boom(request):
        raise AssertionError("no network call allowed when LLM is disabled")

    disabled = LLMClient(Settings(_env_file=None, llm_enabled=False, groq_api_key="k"),
                         transport=httpx.MockTransport(boom))
    out = explain(payment_packet(), decision, disabled)
    assert out.source == "fallback" and out.guardrail_failures == []


# --- grounding / consistency / policy units ---------------------------------------------------

def test_grounding_accepts_rounding_and_percentages() -> None:
    payload = {"observed": 0.82, "baseline": 0.2, "multiplier": 4.1, "revenue": 41500.0}
    assert check_grounding(["82% vs 20% baseline, 4.1x, about 41,500"], payload) == []
    assert check_grounding(["95% of sessions"], payload) != []


def test_consistency_allows_decided_type_only() -> None:
    assert check_consistency(["Payment failure on gateway B"], "payment_failure", set(), set()) == []
    assert check_consistency(["Looks like price shock"], "payment_failure", set(), set()) != []


def test_policy_allows_terms_only_for_the_action() -> None:
    assert check_policy(["Any debited amount will be reversed"], ["reversed"]) == []
    assert check_policy(["Any debited amount will be reversed"], []) != []
    assert check_policy(["Visit www.shop.example"], []) != []


# --- messages -----------------------------------------------------------------------------------

def test_message_llm_valid_and_bad(decision) -> None:
    action = get_playbook().action("retry_payment_link")
    ok = draft_message(action, payment_packet(), "payment_failure", "earbuds",
                       llm(json.dumps({"message": "Your payment did not complete, but your cart is saved. "
                                                  "Tap to try again with another method."})))
    assert ok.source == "llm"
    offer = draft_message(action, payment_packet(), "payment_failure", "earbuds",
                          llm(json.dumps({"message": "Pay now and get 10% cashback!"})))
    assert offer.source == "fallback" and offer.guardrail_failures
    too_long = draft_message(action, payment_packet(), "payment_failure", "earbuds",
                             llm(json.dumps({"message": "x" * 301})))
    assert too_long.source == "fallback"


def test_refund_term_only_when_template_uses_it() -> None:
    packet = payment_packet(rule_flags=["money_deducted_failed_payment"])
    refund = get_playbook().action("refund_reassurance")
    out = draft_message(refund, packet, "payment_failure", None,
                        llm(json.dumps({"message": "If any amount was debited it is reversed automatically. "
                                                   "Your cart is saved."})))
    assert out.source == "llm"
    retry = get_playbook().action("retry_payment_link")
    out = draft_message(retry, packet, "payment_failure", None,
                        llm(json.dumps({"message": "We will refund you. Your cart is saved."})))
    assert out.source == "fallback"


# --- fallbacks are themselves safe --------------------------------------------------------------

def test_every_fallback_message_passes_policy_and_length() -> None:
    book = get_playbook()
    packet = payment_packet()
    for friction, actions in book.customer.items():
        for action in actions:
            msg = fallback_message(action, packet, "earbuds")
            assert len(msg.text) <= 300
            assert check_policy([msg.text], action.allows_terms) == [], action.id


def test_fallback_explanation_is_grounded_and_consistent() -> None:
    for packet in (payment_packet(), gateway_packet()):
        decision = decide_once(packet, S)
        exp = fallback_explanation(packet, decision)
        texts = [exp.summary, exp.behavior_observed, exp.likely_business_cause]
        payload = explanation_payload(packet, decision)
        assert check_grounding(texts, payload) == []
        assert check_consistency(texts, decision.friction_type, set(), set()) == []


# --- client ---------------------------------------------------------------------------------------

def test_client_falls_back_to_openrouter_then_raises() -> None:
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if "groq" in request.url.host:
            return httpx.Response(503, text="down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    settings = Settings(_env_file=None, llm_enabled=True, groq_api_key="g", openrouter_api_key="o",
                        openrouter_model_fast="some/free-model")
    client = LLMClient(settings, transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]).provider == "openrouter"
    assert seen == ["api.groq.com", "openrouter.ai"]

    only_groq = LLMClient(Settings(_env_file=None, llm_enabled=True, groq_api_key="g"),
                          transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(LLMError):
        only_groq.chat([{"role": "user", "content": "hi"}])


def test_client_retries_without_json_mode_and_detects_tool_rejection() -> None:
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format is not supported by this model")
        if "tools" in body:
            return httpx.Response(400, text="this model does not support tool use")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = LLMClient(Settings(_env_file=None, llm_enabled=True, groq_api_key="g"),
                       transport=httpx.MockTransport(handler))
    assert client.complete_json("sys", "user") == "{}"
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]
    with pytest.raises(ToolsUnsupported):
        client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "x"}}])
