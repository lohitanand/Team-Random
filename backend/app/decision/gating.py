"""Confidence gating (CLAUDE.md §7.6): high -> alert with triggers; medium -> investigate, then
"needs review" with no auto actions; low -> log and monitor only."""
from __future__ import annotations

from backend.app.config import Settings, get_settings
from backend.app.schemas.alerts import Gate


def gate(confidence: float, settings: Settings | None = None) -> Gate:
    s = settings or get_settings()
    if confidence >= s.gate_high:
        return "high"
    if confidence >= s.gate_medium:
        return "medium"
    return "low"
