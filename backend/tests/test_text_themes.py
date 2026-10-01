"""Phase 5: text themes. LLM fallback path works and is optional."""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest
from sklearn.feature_extraction.text import HashingVectorizer

from backend.app.config import Settings
from backend.app.detection.text_themes import ThemeClassifier
from backend.app.llm.client import LLMClient
from backend.app.schemas.taxonomy import TEXT_THEMES
from backend.ml.train_text import train as train_text

_hasher = HashingVectorizer(n_features=4096, ngram_range=(1, 2), alternate_sign=False, norm="l2")


def fake_embed(texts: list[str]) -> np.ndarray:
    """Fast deterministic stand-in for the sentence-transformer (no model download in tests)."""
    return _hasher.transform(texts).toarray()


def llm_settings(**overrides) -> Settings:
    return Settings(_env_file=None, llm_enabled=True, groq_api_key="test", **overrides)


def mock_llm(reply: str | None, calls: list | None = None, status: int = 200) -> LLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": "boom"})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return LLMClient(llm_settings(), transport=httpx.MockTransport(handler))


@pytest.fixture(scope="module")
def corpus(small_processed):
    texts = small_processed["texts"]
    return texts["text"].tolist(), texts["theme_label"].tolist()


def make(corpus, llm: LLMClient | None = None, **settings) -> ThemeClassifier:
    texts, labels = corpus
    s = Settings(_env_file=None, llm_enabled=False, **settings)
    return ThemeClassifier.fit(texts, labels, fake_embed, seed=0, settings=s, llm=llm or LLMClient(s))


def test_classifier_learns_the_themes(corpus) -> None:
    model = make(corpus)
    texts, labels = corpus
    preds = [p.theme for p in model.classify(texts, llm_budget=0)]
    assert set(model.classes) == set(TEXT_THEMES)
    assert np.mean([p == t for p, t in zip(preds, labels)]) > 0.7


def test_low_confidence_without_llm_falls_back_to_other(corpus) -> None:
    model = make(corpus, text_theme_min_prob=1.01)  # nothing is confident
    preds = model.classify(["kuch toh gadbad hai"])
    assert preds[0].theme == "other" and preds[0].method == "fallback"


def test_low_confidence_uses_llm_when_enabled(corpus) -> None:
    calls: list = []
    model = make(corpus, llm=mock_llm('{"theme": "money_deducted"}', calls), text_theme_min_prob=1.01)
    pred = model.classify(["paisa gaya"], llm_budget=5)[0]
    assert (pred.theme, pred.method) == ("money_deducted", "llm")
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["model"] == "openai/gpt-oss-20b"


@pytest.mark.parametrize("reply", ["not json at all", '{"theme": "angry_customer"}', '{"theme": 3}',
                                   '{"theme": "stock", "extra": 1}', None])
def test_invalid_llm_output_becomes_other(corpus, reply) -> None:
    model = make(corpus, llm=mock_llm(reply), text_theme_min_prob=1.01)
    pred = model.classify(["hmm"], llm_budget=5)[0]
    assert (pred.theme, pred.method) == ("other", "fallback")


def test_llm_http_error_becomes_other(corpus) -> None:
    model = make(corpus, llm=mock_llm(None, status=500), text_theme_min_prob=1.01)
    assert model.classify(["hmm"], llm_budget=5)[0].theme == "other"


def test_llm_budget_is_respected(corpus) -> None:
    calls: list = []
    model = make(corpus, llm=mock_llm('{"theme": "stock"}', calls), text_theme_min_prob=1.01)
    preds = model.classify(["a", "b", "c", "d"], llm_budget=2)
    assert len(calls) == 2
    assert [p.method for p in preds] == ["llm", "llm", "fallback", "fallback"]


def test_training_script_reports_accuracy(small_processed, tmp_path) -> None:
    from backend.app.store import DataStore

    root = small_processed["root"]
    store = DataStore(root / "processed", root / "raw", root / "models")
    report = train_text(store, tmp_path / "models", tmp_path / "processed", tmp_path / "reports", embed=fake_embed)
    assert report["accuracy"] > 0.7 and "accuracy_by_language" in report
    assert (tmp_path / "processed" / "text_themes.parquet").exists()
    assert (tmp_path / "reports" / "text_eval.json").exists()
