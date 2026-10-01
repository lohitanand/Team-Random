"""Shared ML helpers: deterministic splits, labels, feature lists, LightGBM factory."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

from backend.app.ingestion.features import FEATURE_COLUMNS
from backend.app.ingestion.joins import JOIN_COLUMNS
from backend.app.schemas.taxonomy import FRICTION_TYPES

RISK_FEATURES = list(FEATURE_COLUMNS)
FRICTION_FEATURES = list(FEATURE_COLUMNS) + list(JOIN_COLUMNS)


def stable_bucket(key: str, mod: int) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % mod


def is_test(session_id: str, mod: int = 5) -> bool:
    """Deterministic 1-in-`mod` test split by session id (same split in every script)."""
    return stable_bucket(session_id, mod) == 0


def split_mask(session_ids: pd.Series, mod: int = 5) -> np.ndarray:
    return np.array([is_test(s, mod) for s in session_ids])


def friction_labels(ground_truth: pd.DataFrame) -> pd.DataFrame:
    """Multi-hot labels (session_id index, one column per friction key)."""
    types = ground_truth.set_index("session_id")["friction_types"].str.split("|")
    return pd.DataFrame({f: types.map(lambda xs, f=f: f in xs).astype(int) for f in FRICTION_TYPES})


def lgbm(seed: int, n_estimators: int = 300) -> LGBMClassifier:
    return LGBMClassifier(
        n_estimators=n_estimators, learning_rate=0.05, num_leaves=31, min_child_samples=30,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
        random_state=seed, deterministic=True, force_row_wise=True, n_jobs=4, verbose=-1,
    )
