"""Primary (and optional secondary) friction type from the evidence packet. Fully deterministic.

Tie-break: rules > classifier > themes (CLAUDE.md §7.6). For aggregate packets the anomaly
metric's fixed friction mapping acts like a rule and comes first.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.app.config import Settings, get_settings
from backend.app.decision.signals import FRICTION_STAGE, theme_frictions
from backend.app.detection.rules import rule_frictions
from backend.app.schemas.evidence import AggregatePacket, Packet
from backend.app.schemas.taxonomy import FRICTION_TYPES


@dataclass(frozen=True)
class Classification:
    primary: str
    secondary: str | None
    source: str


def _by_prob(candidates: list[str], probs: dict[str, float]) -> list[str]:
    return sorted(candidates, key=lambda f: (-probs.get(f, 0.0), FRICTION_TYPES.index(f)))


def _by_stage_then_prob(candidates: list[str], probs: dict[str, float]) -> list[str]:
    return sorted(candidates, key=lambda f: (-FRICTION_STAGE[f], -probs.get(f, 0.0), FRICTION_TYPES.index(f)))


def classify(packet: Packet, settings: Settings | None = None) -> Classification:
    s = settings or get_settings()
    probs = packet.friction_probs
    rules = rule_frictions(packet.rule_flags)
    model = _by_prob([f for f, p in probs.items() if p >= s.friction_prob_threshold], probs)
    themes = theme_frictions(packet.text_themes)

    if isinstance(packet, AggregatePacket) and packet.friction_hint:
        ordered, source = [packet.friction_hint], "aggregate_metric"
    elif rules:
        ordered, source = _by_stage_then_prob(rules, probs), "rules"
    elif model:
        ordered, source = model, "classifier"
    elif themes:
        ordered, source = _by_prob(themes, probs), "themes"
    else:
        ordered, source = _by_prob(list(FRICTION_TYPES), probs), "weak_classifier"

    primary = ordered[0]
    pool = [*ordered[1:], *_by_stage_then_prob(rules, probs), *model, *themes]
    secondary = next((f for f in pool if f != primary), None)
    return Classification(primary=primary, secondary=secondary, source=source)
