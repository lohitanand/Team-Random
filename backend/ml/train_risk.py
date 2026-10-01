"""Train the journey risk model on session prefixes.

    python -m backend.ml.train_risk
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from backend.app.config import MODELS_DIR, get_settings
from backend.app.detection.risk_model import RiskModel
from backend.app.store import DataStore, get_store
from backend.ml.common import RISK_FEATURES, lgbm, split_mask, stable_bucket

RISK_MODEL_FILE = "risk_model.joblib"


def risk_training_frame(store: DataStore) -> pd.DataFrame:
    """Shopping-session prefixes with the session outcome as label (1 = did not convert)."""
    prefixes = store.prefixes.merge(store.sessions[["session_id", "session_kind", "converted"]], on="session_id")
    prefixes = prefixes[prefixes["session_kind"] == "shopping"].copy()
    prefixes["label"] = (~prefixes["converted"]).astype(int)
    return prefixes


def train(store: DataStore | None = None, models_dir: Path = MODELS_DIR) -> dict[str, float]:
    settings = get_settings()
    store = store or get_store()
    frame = risk_training_frame(store)
    test = split_mask(frame["session_id"], settings.test_share_mod)
    train_frame = frame[~test]
    calib = np.array([stable_bucket(f"{s}:calibration", 5) == 0 for s in train_frame["session_id"]])

    model = RiskModel.fit(
        train_frame.loc[~calib, RISK_FEATURES], train_frame.loc[~calib, "label"],
        train_frame.loc[calib, RISK_FEATURES], train_frame.loc[calib, "label"],
        lgbm(settings.ml_seed),
    )
    model.save(models_dir / RISK_MODEL_FILE)

    return risk_metrics(model, frame[test])


def risk_metrics(model: RiskModel, test_frame: pd.DataFrame) -> dict[str, float]:
    """PR-AUC over all test prefixes and at the cart/checkout stage (the early-warning moment)."""
    early = test_frame[test_frame["current_step_idx"].between(2, 3)]  # cart, checkout
    return {
        "test_prefixes": int(len(test_frame)),
        "positive_rate": float(test_frame["label"].mean()),
        "pr_auc_all_prefixes": float(average_precision_score(test_frame["label"], model.score(test_frame))),
        "pr_auc_cart_checkout": float(average_precision_score(early["label"], model.score(early))),
        "positive_rate_cart_checkout": float(early["label"].mean()),
    }


def main() -> int:
    metrics = train()
    for key, value in metrics.items():
        print(f"{key:<22}{value:.4f}" if isinstance(value, float) else f"{key:<22}{value}")
    print(f"Saved {MODELS_DIR / RISK_MODEL_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
