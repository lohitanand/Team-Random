"""Outcome tracking. Outcomes on historical data are SIMULATED from the generator's per-friction
recovery propensity (synthetic world), so holdout lift can be demonstrated end to end."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import RecoveryRow

NATURAL_RECOVERY_RATE = 0.06  # customers who come back on their own, with no action


@lru_cache
def propensities() -> dict[str, float]:
    from datagen.config import load_config

    return dict(load_config().friction.recovery_propensity)


def _u(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def simulate_outcome(session_id: str, friction: str, treated: bool) -> bool:
    p = NATURAL_RECOVERY_RATE
    if treated:
        p = p + (1 - p) * propensities().get(friction, 0.2)
    return _u(f"outcome:{session_id}") < p


def recovery_stats(db: Session) -> dict[str, Any]:
    rows = db.query(RecoveryRow).all()
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    treated = [r for r in rows if r.status in ("sent", "approved") and r.outcome in ("recovered", "not_recovered")]
    hold = [r for r in rows if r.holdout and r.outcome in ("recovered", "not_recovered")]
    t_rate = sum(r.outcome == "recovered" for r in treated) / len(treated) if treated else 0.0
    h_rate = sum(r.outcome == "recovered" for r in hold) / len(hold) if hold else 0.0
    per: dict[str, dict[str, float]] = {}
    for r in treated + hold:
        d = per.setdefault(r.friction_type, {"treated": 0, "treated_recovered": 0, "holdout": 0, "holdout_recovered": 0})
        key = "holdout" if r.holdout else "treated"
        d[key] += 1
        d[f"{key}_recovered"] += r.outcome == "recovered"
    return {
        "total": len(rows), "by_status": by_status,
        "treated": len(treated), "holdout": len(hold),
        "treated_recovery_rate": round(t_rate, 4), "holdout_recovery_rate": round(h_rate, 4),
        "lift_pp": round((t_rate - h_rate) * 100, 2),
        "recovered_revenue": round(sum(r.value or 0 for r in treated if r.outcome == "recovered"), 2),
        "by_friction": per, "simulated": True,
    }
