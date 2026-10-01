"""Confidence = weighted agreement of independent detectors for the chosen type (CLAUDE.md §7.6):

    w_rule * rule_supports
  + w_model * model_supports   (friction_prob >= threshold AND a SHAP signal maps to the type)
  + w_text * text_supports
  + w_aggregate * aggregate_supports
"""
from __future__ import annotations

from backend.app.config import Settings, get_settings
from backend.app.decision.signals import signal_supports, theme_frictions
from backend.app.detection.rules import rule_frictions
from backend.app.schemas.alerts import ConfidenceBreakdown
from backend.app.schemas.evidence import AggregatePacket, Packet


def _finding_supports(packet: Packet, friction: str, kinds: set[str]) -> bool:
    return any(f.supports == friction and f.evidence_kind in kinds for f in packet.investigation_findings)


def confidence(packet: Packet, friction: str, settings: Settings | None = None) -> ConfidenceBreakdown:
    """For aggregate packets, rule/model support means enough of the affected sessions agree
    (aggregate_*_support_share in config), since one anomaly spans many sessions."""
    s = settings or get_settings()
    signals = [sig.feature for sig in packet.top_signals] + \
              [sig.feature for sig in packet.friction_signals.get(friction, [])]
    text = friction in theme_frictions(packet.text_themes) or _finding_supports(packet, friction, {"text"})
    if isinstance(packet, AggregatePacket):
        ctx = packet.aggregate_context
        on_hint = packet.friction_hint == friction
        rule = on_hint and ctx.get("rule_support_share", 0.0) >= s.aggregate_rule_support_share
        model = (on_hint and ctx.get("model_support_share", 0.0) >= s.aggregate_model_support_share
                 and signal_supports(signals, friction))
        aggregate = on_hint
    else:
        rule = friction in rule_frictions(packet.rule_flags)
        model = (packet.friction_probs.get(friction, 0.0) >= s.friction_prob_threshold
                 and signal_supports(signals, friction))
        aggregate = packet.aggregate_context.get("friction_hint") == friction
    aggregate = aggregate or _finding_supports(packet, friction, {"aggregate", "catalog"})
    score = (s.confidence_weight_rule * rule + s.confidence_weight_model * model
             + s.confidence_weight_text * text + s.confidence_weight_aggregate * aggregate)
    return ConfidenceBreakdown(rule_supports=rule, model_supports=model, text_supports=text,
                               aggregate_supports=aggregate, score=round(score, 4))
