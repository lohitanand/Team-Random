"""Run every session-level detector (rules, risk model + SHAP, friction classifier + SHAP).

Used by the batch pipeline and by live scoring of tracker events.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.app.config import MODELS_DIR
from backend.app.detection.friction_classifier import FrictionClassifier, as_dict, top_frictions
from backend.app.detection.risk_model import RiskModel
from backend.app.detection.rules import evaluate_rules
from backend.app.ingestion.features import compute_features, add_dwell_z, live_view
from backend.app.ingestion.joins import JOIN_COLUMNS

RISK_MODEL_FILE = "risk_model.joblib"
FRICTION_MODEL_FILE = "friction_model.joblib"


@dataclass
class Scorer:
    risk: RiskModel
    friction: FrictionClassifier
    baselines: dict[str, dict[str, float]]

    @classmethod
    def load(cls, models_dir: Path = MODELS_DIR) -> "Scorer":
        baselines = json.loads((models_dir / "dwell_baselines.json").read_text(encoding="utf-8"))
        return cls(RiskModel.load(models_dir / RISK_MODEL_FILE),
                   FrictionClassifier.load(models_dir / FRICTION_MODEL_FILE), baselines)

    def score(self, full: pd.DataFrame, risk_view: pd.DataFrame, is_post_purchase: np.ndarray) -> pd.DataFrame:
        """full: full-session features (+joins); risk_view: live-view features for the same rows, same order.

        Post-purchase sessions have no checkout to abandon, so their risk is the probability
        that they carry any friction (max classifier probability).
        """
        probs = self.friction.predict_proba(full)
        risk = self.risk.score(risk_view)
        risk = np.where(is_post_purchase, probs.max(axis=1).to_numpy(), risk)
        top2 = [top_frictions(probs.iloc[i], 2) for i in range(len(full))]
        sig1 = self.friction.explain(full, [t[0] for t in top2])
        sig2 = self.friction.explain(full, [t[1] for t in top2])
        risk_signals = self.risk.explain(risk_view)
        records = full.to_dict("records")
        return pd.DataFrame({
            "session_id": full["session_id"].to_numpy() if "session_id" in full else full.index.to_numpy(),
            "risk_score": np.round(risk, 4),
            "rule_flags": [evaluate_rules(r) for r in records],
            "top_signals": [[s.model_dump() for s in sig] for sig in risk_signals],
            "friction_probs": [as_dict(probs.iloc[i]) for i in range(len(full))],
            "friction_signals": [{t[0]: [s.model_dump() for s in a], t[1]: [s.model_dump() for s in b]}
                                 for t, a, b in zip(top2, sig1, sig2)],
        })

    def score_events(self, session_id: str, events: list[dict[str, Any]],
                     joins: dict[str, float] | None = None) -> dict[str, Any]:
        """Score one live session from its raw events."""
        full = add_dwell_z(pd.DataFrame([compute_features(events)]), self.baselines)
        for col in JOIN_COLUMNS:
            full[col] = float((joins or {}).get(col, 0.0))
        risk_view = add_dwell_z(pd.DataFrame([compute_features(live_view(events) or events[:1])]), self.baselines)
        full.insert(0, "session_id", session_id)
        row = self.score(full, risk_view, np.array([bool(full["is_post_purchase"].iloc[0])])).iloc[0].to_dict()
        row["features"] = {k: float(v) for k, v in full.iloc[0].items() if k != "session_id"}
        return row


def encode_json_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        out[col] = out[col].map(lambda v: json.dumps(v, sort_keys=True))
    return out


def decode_json_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        out[col] = out[col].map(json.loads)
    return out


SCORE_JSON_COLUMNS = ["rule_flags", "top_signals", "friction_probs", "friction_signals"]
