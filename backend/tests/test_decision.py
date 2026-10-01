"""Phase 6: evidence fusion + decision layer + playbooks. Every rule is deterministic and tested."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.config import Settings
from backend.app.decision.classify import classify
from backend.app.decision.confidence import confidence
from backend.app.decision.engine import decide, decide_once
from backend.app.decision.gating import gate
from backend.app.decision.playbook import get_playbook
from backend.app.decision.priority import impact, priority, trend_factor
from backend.app.decision.routing import OWNER_TEAM, route
from backend.app.fusion.evidence import aggregate_context_index, enrich_aggregate, is_at_risk, session_themes
from backend.app.schemas.evidence import AggregatePacket, Finding, SessionPacket, Signal
from backend.app.schemas.taxonomy import FRICTION_TYPES

S = Settings(_env_file=None)
ZERO = {f: 0.0 for f in FRICTION_TYPES}


def session(**kw) -> SessionPacket:
    base = dict(packet_id="pk_s_1", session_id="s_1", user_id="u_x", session_kind="shopping", risk_score=0.8,
                cart_value=2499.0, friction_probs=dict(ZERO), context={"converted": False})
    base.update(kw)
    return SessionPacket(**base)


def aggregate(**kw) -> AggregatePacket:
    base = dict(packet_id="agg_1", segment_type="gateway", segment_value="B", metric="payment_session_failure_rate",
                friction_hint="payment_failure", window_start=datetime(2026, 9, 22, 19),
                window_end=datetime(2026, 9, 22, 21), observed=0.8, baseline=0.2, z_score=7.0, multiplier=4.0,
                affected_sessions=40, session_ids=[f"s_{i}" for i in range(40)], revenue_at_risk=100000.0,
                trend="rising", friction_probs=dict(ZERO))
    base.update(kw)
    return AggregatePacket(**base)


# --- classify ---------------------------------------------------------------------------

def test_rules_beat_classifier_and_themes() -> None:
    p = session(rule_flags=["coupon_retry_x2"], friction_probs={**ZERO, "payment_failure": 0.95},
                text_themes=["app_bug"])
    c = classify(p, S)
    assert (c.primary, c.source) == ("coupon_failure", "rules")
    assert c.secondary == "payment_failure"


def test_latest_funnel_stage_wins_among_rules() -> None:
    p = session(rule_flags=["size_chart_x3", "payment_retry_x2"])
    assert classify(p, S).primary == "payment_failure"
    assert classify(p, S).secondary == "unclear_product_info"


def test_classifier_used_when_no_rule_fires() -> None:
    p = session(friction_probs={**ZERO, "price_shock": 0.7, "coupon_failure": 0.65})
    c = classify(p, S)
    assert (c.primary, c.secondary, c.source) == ("price_shock", "coupon_failure", "classifier")


def test_themes_used_when_rules_and_classifier_are_silent() -> None:
    p = session(text_themes=["login_issue"], friction_probs={**ZERO, "login_otp_issue": 0.3})
    assert (classify(p, S).primary, classify(p, S).source) == ("login_otp_issue", "themes")


def test_weak_classifier_fallback() -> None:
    p = session(friction_probs={**ZERO, "technical_glitch": 0.2})
    assert (classify(p, S).primary, classify(p, S).source) == ("technical_glitch", "weak_classifier")


def test_aggregate_metric_mapping_comes_first() -> None:
    p = aggregate(rule_flags=["coupon_retry_x2"])
    assert (classify(p, S).primary, classify(p, S).source) == ("payment_failure", "aggregate_metric")


# --- confidence -----------------------------------------------------------------------------

def test_confidence_components_and_weights() -> None:
    p = session(rule_flags=["payment_retry_x2"], friction_probs={**ZERO, "payment_failure": 0.9},
                top_signals=[Signal(feature="payment_failures", shap=0.3)], text_themes=["money_deducted"],
                aggregate_context={"friction_hint": "payment_failure", "multiplier": 4.0})
    b = confidence(p, "payment_failure", S)
    assert (b.rule_supports, b.model_supports, b.text_supports, b.aggregate_supports) == (True, True, True, True)
    assert b.score == pytest.approx(1.0)
    assert confidence(session(rule_flags=["payment_retry_x2"]), "payment_failure", S).score == pytest.approx(0.3)


def test_model_support_needs_matching_shap_signal() -> None:
    probs = {**ZERO, "payment_failure": 0.9}
    unrelated = session(friction_probs=probs, top_signals=[Signal(feature="searches", shap=0.4)])
    related = session(friction_probs=probs, friction_signals={"payment_failure": [Signal(feature="payment_failures", shap=0.2)]})
    assert confidence(unrelated, "payment_failure", S).model_supports is False
    assert confidence(related, "payment_failure", S).model_supports is True


def test_model_support_needs_probability_threshold() -> None:
    p = session(friction_probs={**ZERO, "payment_failure": 0.59},
                top_signals=[Signal(feature="payment_failures", shap=0.3)])
    assert confidence(p, "payment_failure", S).model_supports is False


def test_investigation_findings_add_support() -> None:
    p = session(rule_flags=["tracking_view_x3"], session_kind="post_purchase", investigation_findings=[
        Finding(tool="sample_feedback", summary="3 tickets about delay", supports="post_purchase_concern",
                evidence_kind="text"),
        Finding(tool="courier_health", summary="courier delayed", supports="post_purchase_concern",
                evidence_kind="aggregate")])
    b = confidence(p, "post_purchase_concern", S)
    assert b.text_supports and b.aggregate_supports
    other = Finding(tool="x", summary="y", supports="coupon_failure", evidence_kind="text")
    assert not confidence(session(investigation_findings=[other]), "post_purchase_concern", S).text_supports


def test_aggregate_support_shares() -> None:
    sig = [Signal(feature="payment_failures", shap=0.2)]
    strong = aggregate(aggregate_context={"rule_support_share": 0.6, "model_support_share": 0.5}, top_signals=sig)
    weak = aggregate(aggregate_context={"rule_support_share": 0.1, "model_support_share": 0.1}, top_signals=sig)
    assert confidence(strong, "payment_failure", S).score == pytest.approx(0.8)
    assert confidence(weak, "payment_failure", S).score == pytest.approx(0.2)


# --- gating / routing / priority -------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [(1.0, "high"), (0.8, "high"), (0.79, "medium"), (0.5, "medium"),
                                            (0.49, "low"), (0.0, "low")])
def test_gates(score, expected) -> None:
    assert gate(score, S) == expected


def test_routing_covers_taxonomy() -> None:
    assert set(OWNER_TEAM) == set(FRICTION_TYPES)
    assert route("payment_failure") == "operations_tech" and route("coupon_failure") == "marketing"


def test_priority_formula_and_thresholds() -> None:
    assert impact(100000, 40, 4.0) == pytest.approx(100000 * 3.7136 * 4.0, rel=1e-3)
    assert priority(impact(100000, 40, 4.0), S) == "critical"
    assert priority(impact(30000, 5, 1.5), S) == "high"
    assert priority(impact(2499, 1, 1.0), S) == "normal"
    assert trend_factor(None) == 1.0 and trend_factor(0.4) == 1.0 and trend_factor(12.0) == 5.0


# --- playbook ---------------------------------------------------------------------------------

def test_playbook_covers_every_friction_and_moment() -> None:
    book = get_playbook()
    for f in FRICTION_TYPES:
        assert book.team_action(f, session()).id
        assert book.customer_action(f, session(), "post_session") or book.customer_action(f, session(), "post_purchase")


def test_playbook_conditions() -> None:
    book = get_playbook()
    deducted = session(rule_flags=["money_deducted_failed_payment"])
    assert book.customer_action("payment_failure", deducted, "post_session").id == "refund_reassurance"
    assert book.customer_action("payment_failure", session(), "post_session").id == "retry_payment_link"
    assert book.team_action("payment_failure", aggregate()).id == "check_or_switch_gateway"
    assert book.team_action("payment_failure", session()).id == "review_payment_errors"
    assert book.customer_action("price_shock", session(), "post_purchase") is None


def test_money_actions_never_auto_run() -> None:
    book = get_playbook()
    for actions in book.customer.values():
        for a in actions:
            if {"refund", "coupon"} & set(a.allows_terms):
                assert a.auto_allowed is False or a.id == "explain_coupon_rejection", a.id


# --- engine ----------------------------------------------------------------------------------

def test_decision_is_deterministic_and_complete() -> None:
    p = session(rule_flags=["payment_retry_x2"], friction_probs={**ZERO, "payment_failure": 0.9},
                top_signals=[Signal(feature="payment_failures", shap=0.3)])
    first, second = decide_once(p, S), decide_once(p, S)
    assert first == second
    assert (first.friction_type, first.gate, first.owner_team, first.priority) == \
           ("payment_failure", "medium", "operations_tech", "normal")
    assert first.team_action.id and first.customer_action.id == "retry_payment_link"


def test_medium_goes_to_investigator_then_rescored() -> None:
    p = session(rule_flags=["payment_retry_x2"], friction_probs={**ZERO, "payment_failure": 0.9},
                top_signals=[Signal(feature="payment_failures", shap=0.3)])
    calls = []

    def investigator(packet, decision):
        calls.append(decision.gate)
        return packet.model_copy(update={"investigation_findings": [Finding(
            tool="gateway_health", summary="gateway failing", supports="payment_failure", evidence_kind="aggregate")]})

    decision, enriched = decide(p, investigator, S)
    assert calls == ["medium"]
    assert decision.investigated and decision.gate == "high" and decision.confidence == pytest.approx(0.8)
    assert enriched.investigation_findings


def test_unchanged_packet_stays_needs_review() -> None:
    p = session(rule_flags=["payment_retry_x2"], friction_probs={**ZERO, "payment_failure": 0.9},
                top_signals=[Signal(feature="payment_failures", shap=0.3)])
    decision, _ = decide(p, lambda packet, d: packet, S)
    assert decision.gate == "medium" and decision.needs_review and decision.investigated


def test_high_and_low_are_not_investigated() -> None:
    called = []
    high = aggregate(aggregate_context={"rule_support_share": 1, "model_support_share": 1},
                     top_signals=[Signal(feature="payment_failures", shap=0.2)])
    low = session(friction_probs={**ZERO, "technical_glitch": 0.2})
    for p in (high, low):
        decide(p, lambda packet, d: called.append(1) or packet, S)
    assert called == []


# --- fusion -------------------------------------------------------------------------------

def test_at_risk_rules() -> None:
    assert is_at_risk(0.1, ["payment_retry_x2"], [], True, S)
    assert is_at_risk(0.1, [], ["money_deducted"], True, S)
    assert not is_at_risk(0.1, [], ["other"], False, S)
    assert is_at_risk(0.7, [], [], False, S) and not is_at_risk(0.7, [], [], True, S)


def test_aggregate_context_and_enrichment() -> None:
    agg = aggregate(session_ids=["s_1", "s_2"])
    index = aggregate_context_index([agg])
    assert index["s_1"]["friction_hint"] == "payment_failure" and index["s_1"]["multiplier"] == 4.0
    scores = {"s_1": {"rule_flags": ["payment_retry_x2"], "friction_probs": {**ZERO, "payment_failure": 0.9},
                      "top_signals": [{"feature": "payment_failures", "shap": 0.3}]},
              "s_2": {"rule_flags": [], "friction_probs": dict(ZERO), "top_signals": []}}
    enriched = enrich_aggregate(agg, scores, {"s_1": ["money_deducted"]}, S)
    assert enriched.aggregate_context["rule_support_share"] == 0.5
    assert enriched.text_themes == ["money_deducted"] and enriched.rule_flags == ["payment_retry_x2"]


def test_session_themes_join_by_session_and_order() -> None:
    import pandas as pd

    texts = pd.DataFrame([{"session_id": "s_1", "order_id": None, "theme": "app_bug"},
                          {"session_id": None, "order_id": "o_9", "theme": "delivery_delay"}])
    assert session_themes(texts, {"s_1": None, "s_2": "o_9"}) == {"s_1": ["app_bug"], "s_2": ["delivery_delay"]}


def test_pipeline_decides_every_packet(small_system) -> None:
    decisions = small_system["decisions"]
    assert len(decisions) > 0
    for col in ("friction_type", "confidence", "gate", "owner_team", "priority", "team_action_id"):
        assert decisions[col].notna().all(), col
    assert set(decisions["friction_type"]) <= set(FRICTION_TYPES)
    assert decisions["team_action_id"].isin(get_playbook().action_ids).all()
    assert (decisions["owner_team"] == decisions["friction_type"].map(OWNER_TEAM)).all()
