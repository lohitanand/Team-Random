"""Phase 4: risk model + friction classifier + SHAP + evaluation report."""
from __future__ import annotations

import json

import numpy as np
import pytest

from backend.app.detection.friction_classifier import FrictionClassifier, top_frictions
from backend.app.detection.risk_model import RiskModel
from backend.app.schemas.taxonomy import FRICTION_TYPES
from backend.ml import evaluate, train_friction, train_risk
from backend.ml.common import FRICTION_FEATURES, is_test, split_mask


@pytest.fixture(scope="module")
def trained(full_processed, tmp_path_factory):
    models_dir = tmp_path_factory.mktemp("models")
    store = full_processed["store"]
    risk = train_risk.train(store, models_dir)
    friction = train_friction.train(store, models_dir)
    return {"store": store, "models_dir": models_dir, "risk": risk, "friction": friction}


def test_split_is_deterministic_and_about_20_percent() -> None:
    ids = [f"s_{i:06d}" for i in range(5000)]
    mask = split_mask(__import__("pandas").Series(ids))
    assert 0.17 < mask.mean() < 0.23
    assert all(is_test(s) == m for s, m in zip(ids[:50], mask[:50]))


def test_risk_model_beats_base_rate(trained) -> None:
    m = trained["risk"]
    assert m["pr_auc_all_prefixes"] > m["positive_rate"] + 0.15
    assert m["pr_auc_cart_checkout"] > m["positive_rate_cart_checkout"] + 0.15


def test_risk_scores_are_calibrated_probabilities_with_shap(trained) -> None:
    model = RiskModel.load(trained["models_dir"] / train_risk.RISK_MODEL_FILE)
    frame = train_risk.risk_training_frame(trained["store"]).head(200)
    scores = model.score(frame)
    assert ((scores >= 0) & (scores <= 1)).all()
    signals = model.explain(frame.head(20))
    assert all(len(s) <= 5 for s in signals)
    assert all(sig.shap > 0 and sig.feature in model.features for s in signals for sig in s)


def test_friction_classifier_quality(trained) -> None:
    assert all(v > 0.8 for v in trained["friction"].values()), trained["friction"]


def test_friction_classifier_outputs_all_types(trained) -> None:
    clf = FrictionClassifier.load(trained["models_dir"] / train_friction.FRICTION_MODEL_FILE)
    rows = trained["store"].features.head(30)
    probs = clf.predict_proba(rows[FRICTION_FEATURES])
    assert list(probs.columns) == list(FRICTION_TYPES)
    firsts = [top_frictions(probs.iloc[i], 1)[0] for i in range(len(probs))]
    signals = clf.explain(rows, firsts)
    assert len(signals) == len(rows)


def test_training_is_deterministic(trained, tmp_path) -> None:
    again = train_risk.train(trained["store"], tmp_path)
    assert again["pr_auc_all_prefixes"] == pytest.approx(trained["risk"]["pr_auc_all_prefixes"])


def test_evaluation_report(trained, tmp_path) -> None:
    report = evaluate.run(trained["store"], trained["models_dir"], tmp_path)
    assert {"risk_model", "friction_classifier", "rules", "incidents"} <= set(report)
    assert set(report["friction_classifier"]["per_friction"]) == set(FRICTION_TYPES)
    assert all(v["detected"] for v in report["incidents"]["incidents"].values())
    saved = json.loads((tmp_path / "eval.json").read_text(encoding="utf-8"))
    assert saved["risk_model"]["pr_auc_all_prefixes"] == report["risk_model"]["pr_auc_all_prefixes"]
    assert np.isfinite(saved["risk_model"]["brier_calibrated"])
