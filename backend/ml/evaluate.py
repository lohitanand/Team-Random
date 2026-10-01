"""Evaluation report against planted ground truth (test split only for learned models).

    python -m backend.ml.evaluate      -> prints a summary and writes data/reports/eval.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, precision_recall_fscore_support, roc_auc_score

from backend.app.config import MODELS_DIR, REPORTS_DIR, get_settings
from backend.app.detection.anomaly import detect_anomalies, match_incidents
from backend.app.detection.friction_classifier import FrictionClassifier
from backend.app.detection.risk_model import RiskModel
from backend.app.detection.rules import evaluate_rules, rule_frictions
from backend.app.schemas.taxonomy import FRICTION_TYPES
from backend.app.store import DataStore, get_store
from backend.ml.common import FRICTION_FEATURES, friction_labels, split_mask
from backend.ml.train_friction import FRICTION_MODEL_FILE
from backend.ml.train_risk import RISK_MODEL_FILE, risk_metrics, risk_training_frame


def _prf(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    return {"precision": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f), 4),
            "support": int(np.sum(y_true))}


def evaluate_risk(store: DataStore, models_dir: Path) -> dict[str, Any]:
    model = RiskModel.load(models_dir / RISK_MODEL_FILE)
    frame = risk_training_frame(store)
    test = frame[split_mask(frame["session_id"], get_settings().test_share_mod)]
    scores = model.score(test)
    out = {k: round(v, 4) if isinstance(v, float) else v for k, v in risk_metrics(model, test).items()}
    out["roc_auc_all_prefixes"] = round(float(roc_auc_score(test["label"], scores)), 4)
    out["brier_calibrated"] = round(float(brier_score_loss(test["label"], scores)), 4)
    return out


def evaluate_classifier(store: DataStore, models_dir: Path) -> dict[str, Any]:
    settings = get_settings()
    clf = FrictionClassifier.load(models_dir / FRICTION_MODEL_FILE)
    features = store.features.set_index("session_id")
    labels = friction_labels(store.ground_truth).reindex(features.index).fillna(0).astype(int)
    test = split_mask(features.index.to_series(), settings.test_share_mod)
    probs = clf.predict_proba(features.loc[test, FRICTION_FEATURES])
    per = {f: _prf(labels.loc[test, f].to_numpy(), (probs[f] >= settings.friction_prob_threshold).to_numpy())
           for f in FRICTION_TYPES}
    return {"threshold": settings.friction_prob_threshold, "per_friction": per,
            "macro_f1": round(float(np.mean([v["f1"] for v in per.values()])), 4)}


def evaluate_rules_report(store: DataStore) -> dict[str, Any]:
    features = store.features.set_index("session_id")
    test_ids = features.index[split_mask(features.index.to_series(), get_settings().test_share_mod)]
    labels = friction_labels(store.ground_truth).reindex(test_ids).fillna(0).astype(int)
    fired = {sid: set(rule_frictions(evaluate_rules(features.loc[sid].to_dict()))) for sid in test_ids}
    per = {f: _prf(labels[f].to_numpy(), np.array([f in fired[s] for s in test_ids])) for f in FRICTION_TYPES}
    clean = store.ground_truth.set_index("session_id").reindex(test_ids)["is_clean"].astype(bool)
    return {"per_friction": per, "clean_sessions_with_any_rule": round(float(
        np.mean([bool(fired[s]) for s in clean.index[clean]])), 4)}


def evaluate_incidents(store: DataStore) -> dict[str, Any]:
    packets = detect_anomalies(store.sessions, store.events, store.payments, store.orders, store.reviews)
    matches = match_incidents(packets, store.incidents)
    matched = {pid for ids in matches.values() for pid in ids}
    missing_scope = json.loads(store.incidents.loc[store.incidents["kind"] == "missing_size_info", "scope"].iloc[0])
    flagged_products = {p.segment_value for p in packets if p.packet_id in matched and p.segment_type == "product"}
    return {
        "anomalies": len(packets),
        "incidents": {inc: {"detected": bool(ids), "packets": len(ids)} for inc, ids in matches.items()},
        "missing_size_products_flagged": f"{len(flagged_products)}/{len(missing_scope['product_ids'])}",
        "unmatched_anomalies": [p.packet_id for p in packets if p.packet_id not in matched],
    }


def evaluate_decisions(store: DataStore) -> dict[str, Any]:
    """Cause classification accuracy and alert quality of the full deterministic pipeline (test split)."""
    decisions = pd.read_parquet(store.processed_dir / "decisions.parquet")
    sess = decisions[decisions["packet_type"] == "session"].set_index("session_id")
    gt = store.ground_truth.set_index("session_id")
    test_ids = gt.index[split_mask(gt.index.to_series(), get_settings().test_share_mod)]
    gt = gt.loc[test_ids]
    friction = gt[~gt["is_clean"]]
    covered = friction.index.intersection(sess.index)
    primary = sess.loc[covered, "friction_type"]
    truth_sets = friction.loc[covered, "friction_types"].str.split("|")
    alerts = sess[sess["gate"].isin(["high", "medium"])]
    per = {}
    for f in FRICTION_TYPES:
        idx = friction.index[(friction["primary_friction"] == f)].intersection(covered)
        per[f] = round(float((primary.loc[idx] == f).mean()), 4) if len(idx) else None
    clean_ids = gt.index[gt["is_clean"]]
    return {
        "test_friction_sessions": int(len(friction)),
        "detection_coverage": round(len(covered) / max(len(friction), 1), 4),
        "cause_accuracy_primary": round(float((primary == friction.loc[covered, "primary_friction"]).mean()), 4),
        "cause_accuracy_any_planted": round(float(np.mean([p in t for p, t in zip(primary, truth_sets)])), 4),
        "cause_accuracy_by_friction": per,
        "clean_sessions_alerted": round(float(clean_ids.isin(alerts.index).mean()), 4),
        "alerts_high_confidence_share": round(float((alerts["gate"] == "high").mean()), 4) if len(alerts) else 0.0,
        "gate_counts": sess["gate"].value_counts().to_dict(),
        "aggregate_decisions": decisions.loc[decisions["packet_type"] == "aggregate",
                                             ["packet_id", "friction_type", "gate", "confidence", "priority"]]
                                        .to_dict("records"),
    }


def evaluate_text(reports_dir: Path) -> dict[str, Any]:
    """Written by `backend.ml.train_text` (embedding the corpus again here would be slow)."""
    return json.loads((reports_dir / "text_eval.json").read_text(encoding="utf-8"))


SECTIONS = {
    "risk_model": lambda store, models_dir, reports_dir: evaluate_risk(store, models_dir),
    "friction_classifier": lambda store, models_dir, reports_dir: evaluate_classifier(store, models_dir),
    "rules": lambda store, models_dir, reports_dir: evaluate_rules_report(store),
    "incidents": lambda store, models_dir, reports_dir: evaluate_incidents(store),
    "text_themes": lambda store, models_dir, reports_dir: evaluate_text(reports_dir),
    "decisions": lambda store, models_dir, reports_dir: evaluate_decisions(store),
}


def run(store: DataStore | None = None, models_dir: Path = MODELS_DIR,
        reports_dir: Path = REPORTS_DIR) -> dict[str, Any]:
    store = store or get_store()
    report: dict[str, Any] = {}
    for name, section in SECTIONS.items():
        try:
            report[name] = section(store, models_dir, reports_dir)
        except FileNotFoundError as exc:
            report[name] = {"skipped": f"missing artifact: {Path(str(exc.filename or exc)).name}"}
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "eval.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def _print_prf_table(title: str, per: dict[str, dict[str, float]]) -> None:
    print(f"\n{title}")
    print(f"  {'friction':<24}{'precision':>10}{'recall':>9}{'f1':>8}{'support':>9}")
    for friction, m in per.items():
        print(f"  {friction:<24}{m['precision']:>10.3f}{m['recall']:>9.3f}{m['f1']:>8.3f}{m['support']:>9}")


def print_report(report: dict[str, Any]) -> None:
    risk = report.get("risk_model", {})
    if "pr_auc_all_prefixes" in risk:
        print("Risk model (test prefixes)")
        for key in ("pr_auc_all_prefixes", "positive_rate", "pr_auc_cart_checkout", "roc_auc_all_prefixes",
                    "brier_calibrated"):
            print(f"  {key:<26}{risk[key]}")
    if "per_friction" in report.get("friction_classifier", {}):
        _print_prf_table(f"Friction classifier (threshold {report['friction_classifier']['threshold']})",
                         report["friction_classifier"]["per_friction"])
    if "per_friction" in report.get("rules", {}):
        _print_prf_table("Rules", report["rules"]["per_friction"])
        print(f"  clean sessions with any rule: {report['rules']['clean_sessions_with_any_rule']}")
    for name, section in report.items():
        if name in ("risk_model", "friction_classifier", "rules"):
            continue
        print(f"\n{name}: {json.dumps(section, default=str)[:600]}")


def main() -> int:
    report = run()
    print_report(report)
    print(f"\nWrote {REPORTS_DIR / 'eval.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
