"""JSON helpers for pandas/numpy values in API responses."""
from __future__ import annotations

import json
from typing import Any

import numpy as np


def _default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def plain(value: Any) -> Any:
    """Round-trip through JSON so numpy scalars, NaN and timestamps become plain JSON values."""
    text = json.dumps(value, default=_default).replace("NaN", "null")
    return json.loads(text)
