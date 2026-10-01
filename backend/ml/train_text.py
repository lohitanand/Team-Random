"""Train the text theme classifier, report accuracy, and label every text for evidence fusion.

    python -m backend.ml.train_text
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from backend.app.config import MODELS_DIR, PROCESSED_DIR, REPORTS_DIR, get_settings
from backend.app.detection.text_themes import THEME_MODEL_FILE, Embed, ThemeClassifier, sentence_embedder
from backend.app.store import DataStore, get_store
from backend.ml.common import is_test


def cached_embedder(texts: list[str], embed: Embed) -> Embed:
    unique = list(dict.fromkeys(texts))
    vectors = embed(unique)
    cache = {t: vectors[i] for i, t in enumerate(unique)}
    return lambda batch: np.vstack([cache[t] if t in cache else embed([t])[0] for t in batch])


def evaluate_themes(model: ThemeClassifier, test: pd.DataFrame) -> dict[str, Any]:
    texts, truth = test["text"].tolist(), test["theme_label"].tolist()
    probs = model.predict_proba(texts)
    raw = [model.classes[int(i)] for i in probs.argmax(axis=1)]
    confident = probs.max(axis=1) >= model.settings.text_theme_min_prob
    gated = [p.theme for p in model.classify(texts, llm_budget=0)]  # deterministic path, no LLM
    by_lang = {lang: round(float(accuracy_score(test.loc[test["language"] == lang, "theme_label"],
                                                np.array(raw)[test["language"].to_numpy() == lang])), 4)
               for lang in sorted(test["language"].unique())}
    return {
        "test_texts": len(test),
        "accuracy": round(float(accuracy_score(truth, raw)), 4),
        "macro_f1": round(float(f1_score(truth, raw, average="macro")), 4),
        "coverage_at_min_prob": round(float(confident.mean()), 4),
        "accuracy_when_confident": round(float(accuracy_score(np.array(truth)[confident],
                                                              np.array(raw)[confident])), 4),
        "accuracy_with_fallback_to_other": round(float(accuracy_score(truth, gated)), 4),
        "accuracy_by_language": by_lang,
    }


def train(store: DataStore | None = None, models_dir: Path = MODELS_DIR, processed_dir: Path = PROCESSED_DIR,
          reports_dir: Path = REPORTS_DIR, embed: Embed | None = None) -> dict[str, Any]:
    settings = get_settings()
    store = store or get_store()
    texts = store.texts.reset_index(drop=True)
    embed = cached_embedder(texts["text"].tolist(), embed or sentence_embedder())
    test = np.array([is_test(t, settings.test_share_mod) for t in texts["text_id"]])

    model = ThemeClassifier.fit(texts.loc[~test, "text"].tolist(), texts.loc[~test, "theme_label"].tolist(),
                                embed, settings.ml_seed, settings=settings)
    model.save(models_dir / THEME_MODEL_FILE)
    report = evaluate_themes(model, texts[test])

    predictions = model.classify(texts["text"].tolist())
    labelled = texts.drop(columns=["theme_label"]).assign(
        theme=[p.theme for p in predictions], theme_prob=[p.prob for p in predictions],
        theme_method=[p.method for p in predictions])
    processed_dir.mkdir(parents=True, exist_ok=True)
    labelled.to_parquet(processed_dir / "text_themes.parquet", index=False)
    report["methods_used"] = labelled["theme_method"].value_counts().to_dict()
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "text_eval.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = train()
    for key, value in report.items():
        print(f"{key:<34}{value}")
    print(f"Saved {MODELS_DIR / THEME_MODEL_FILE} and {PROCESSED_DIR / 'text_themes.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
