"""Deterministic holdout and consent assignment (stable hash of the id)."""
from __future__ import annotations

import hashlib


def _bucket(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def in_holdout(session_id: str, share: float) -> bool:
    """`share` of eligible sessions receive no recovery action, to measure real lift."""
    return _bucket(f"holdout:{session_id}") < share


def has_consent(user_id: str, share: float = 0.85) -> bool:
    """Synthetic marketing consent flag (opted-in channels only)."""
    return _bucket(f"consent:{user_id}") < share
