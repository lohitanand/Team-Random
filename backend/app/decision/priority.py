"""Priority (CLAUDE.md §7.6): impact = revenue_at_risk * log1p(customers_affected) * trend_factor."""
from __future__ import annotations

import math

from backend.app.config import Settings, get_settings
from backend.app.schemas.alerts import Priority

MAX_TREND_FACTOR = 5.0


def trend_factor(multiplier: float | None) -> float:
    """Aggregate rate multiplier clamped to [1, 5]; 1.0 when there is no aggregate trend."""
    if multiplier is None or math.isnan(multiplier):
        return 1.0
    return round(min(max(multiplier, 1.0), MAX_TREND_FACTOR), 2)


def impact(revenue_at_risk: float, customers_affected: int, trend: float) -> float:
    return round(max(revenue_at_risk, 0.0) * math.log1p(max(customers_affected, 0)) * trend, 2)


def priority(impact_score: float, settings: Settings | None = None) -> Priority:
    s = settings or get_settings()
    if impact_score >= s.priority_critical_impact:
        return "critical"
    if impact_score >= s.priority_high_impact:
        return "high"
    return "normal"
