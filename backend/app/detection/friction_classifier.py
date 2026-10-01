"""Friction classifier (CLAUDE.md §7.4): one LightGBM model per friction key (one-vs-rest).

Its probabilities are ONE input to the deterministic decision layer, never the final answer.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from lightgbm import LGBMClassifier

from backend.app.detection.risk_model import shap_matrix, top_signals
from backend.app.schemas.evidence import Signal
from backend.app.schemas.taxonomy import FRICTION_TYPES


class FrictionClassifier:
    def __init__(self, models: dict[str, LGBMClassifier], features: list[str]) -> None:
        self.models = models
        self.features = features
        self._explainers: dict[str, shap.TreeExplainer] = {}

    @classmethod
    def fit(cls, X: pd.DataFrame, labels: pd.DataFrame, make_model) -> "FrictionClassifier":
        models = {}
        for friction in FRICTION_TYPES:
            model = make_model()
            model.fit(X, labels[friction])
            models[friction] = model
        return cls(models, list(X.columns))

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        data = X[self.features]
        return pd.DataFrame({f: self.models[f].predict_proba(data)[:, 1] for f in FRICTION_TYPES}, index=X.index)

    def _explainer(self, friction: str) -> shap.TreeExplainer:
        if friction not in self._explainers:
            self._explainers[friction] = shap.TreeExplainer(self.models[friction])
        return self._explainers[friction]

    def explain(self, X: pd.DataFrame, frictions: list[str], k: int = 5) -> list[list[Signal]]:
        """Top SHAP signals of row i for friction model frictions[i] (grouped per model for speed)."""
        out: list[list[Signal]] = [[] for _ in range(len(X))]
        data = X[self.features].reset_index(drop=True)
        for friction in set(frictions):
            idx = [i for i, f in enumerate(frictions) if f == friction]
            values = shap_matrix(self._explainer(friction), data.iloc[idx])
            for row_i, row in zip(idx, values):
                out[row_i] = top_signals(row, self.features, k)
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"models": self.models, "features": self.features}, path)

    @classmethod
    def load(cls, path: Path) -> "FrictionClassifier":
        data = joblib.load(path)
        return cls(data["models"], data["features"])


def top_frictions(probs: pd.Series, k: int = 2) -> list[str]:
    ordered = sorted(probs.items(), key=lambda kv: (-kv[1], FRICTION_TYPES.index(kv[0])))
    return [f for f, _ in ordered[:k]]


def as_dict(probs: pd.Series, digits: int = 4) -> dict[str, float]:
    return {f: round(float(np.clip(probs[f], 0, 1)), digits) for f in FRICTION_TYPES}
