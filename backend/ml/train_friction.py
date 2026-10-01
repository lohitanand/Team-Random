"""Train the one-vs-rest friction classifier on full-session features + joins.

    python -m backend.ml.train_friction
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score

from backend.app.config import MODELS_DIR, get_settings
from backend.app.detection.friction_classifier import FrictionClassifier
from backend.app.schemas.taxonomy import FRICTION_TYPES
from backend.app.store import DataStore, get_store
from backend.ml.common import FRICTION_FEATURES, friction_labels, lgbm, split_mask

FRICTION_MODEL_FILE = "friction_model.joblib"


def friction_training_frame(store: DataStore) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = store.features.set_index("session_id")
    labels = friction_labels(store.ground_truth).reindex(features.index).fillna(0).astype(int)
    return features, labels


def train(store: DataStore | None = None, models_dir: Path = MODELS_DIR) -> dict[str, float]:
    settings = get_settings()
    store = store or get_store()
    features, labels = friction_training_frame(store)
    test = split_mask(features.index.to_series(), settings.test_share_mod)

    clf = FrictionClassifier.fit(features.loc[~test, FRICTION_FEATURES], labels[~test],
                                 lambda: lgbm(settings.ml_seed, n_estimators=200))
    clf.save(models_dir / FRICTION_MODEL_FILE)

    probs = clf.predict_proba(features[test])
    return {f"pr_auc_{f}": float(average_precision_score(labels.loc[test, f], probs[f])) for f in FRICTION_TYPES}


def main() -> int:
    for key, value in train().items():
        print(f"{key:<36}{value:.4f}")
    print(f"Saved {MODELS_DIR / FRICTION_MODEL_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
