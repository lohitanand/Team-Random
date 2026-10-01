"""Journey risk model (CLAUDE.md §7.4): LightGBM abandoned-vs-converted, trained on session prefixes,
isotonic-calibrated, with the top-5 SHAP signals that push a session toward abandonment."""
from __future__ import annotations

import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from lightgbm import LGBMClassifier
from sklearn.isotonic import IsotonicRegression

from backend.app.schemas.evidence import Signal


def shap_matrix(explainer: shap.TreeExplainer, X: pd.DataFrame) -> np.ndarray:
    """SHAP values for the positive class as an (n_rows, n_features) array."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="LightGBM binary classifier with TreeExplainer")
        values = explainer.shap_values(X)
    if isinstance(values, list):
        values = values[1]
    values = np.asarray(values)
    return values[:, :, 1] if values.ndim == 3 else values


def top_signals(row_values: np.ndarray, features: list[str], k: int = 5) -> list[Signal]:
    order = np.argsort(-row_values)
    return [Signal(feature=features[i], shap=round(float(row_values[i]), 4))
            for i in order[:k] if row_values[i] > 0]


class RiskModel:
    def __init__(self, model: LGBMClassifier, calibrator: IsotonicRegression, features: list[str]) -> None:
        self.model = model
        self.calibrator = calibrator
        self.features = features
        self._explainer: shap.TreeExplainer | None = None

    @classmethod
    def fit(cls, X: pd.DataFrame, y: pd.Series, X_cal: pd.DataFrame, y_cal: pd.Series,
            model: LGBMClassifier) -> "RiskModel":
        features = list(X.columns)
        model.fit(X, y)
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        calibrator.fit(model.predict_proba(X_cal[features])[:, 1], y_cal)
        return cls(model, calibrator, features)

    def score(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.model.predict_proba(X[self.features])[:, 1]
        return self.calibrator.predict(raw)

    @property
    def explainer(self) -> shap.TreeExplainer:
        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self.model)
        return self._explainer

    def explain(self, X: pd.DataFrame, k: int = 5) -> list[list[Signal]]:
        values = shap_matrix(self.explainer, X[self.features])
        return [top_signals(row, self.features, k) for row in values]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "calibrator": self.calibrator, "features": self.features}, path)

    @classmethod
    def load(cls, path: Path) -> "RiskModel":
        data = joblib.load(path)
        return cls(data["model"], data["calibrator"], data["features"])
