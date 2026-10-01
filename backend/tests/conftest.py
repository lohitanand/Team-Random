"""Shared fixtures. Every test runs with the LLM disabled and a throwaway database."""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.app.config import get_settings
from backend.app.db.session import get_engine, get_session_factory


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


SMALL_SIZES = {"sizes": {"sessions": 2500, "users": 400, "products": 120}}


@pytest.fixture(scope="session")
def small_raw():
    """A small generated dataset (raw tables), shared by pipeline tests."""
    from datagen.config import load_config
    from datagen.generate import generate

    return generate(load_config(overrides=SMALL_SIZES))


@pytest.fixture(scope="session")
def small_processed(small_raw, tmp_path_factory):
    """Raw tables written to disk and run through the Phase 2 ingestion pipeline."""
    from backend.app.ingestion import pipeline
    from datagen.generate import write_tables

    root = tmp_path_factory.mktemp("small")
    write_tables(small_raw, root / "raw")
    tables = pipeline.run(root / "raw", root / "processed", root / "models")
    return {"root": root, **tables}


def fake_embed(texts):
    """Fast deterministic stand-in for the sentence-transformer (no model download in tests)."""
    from sklearn.feature_extraction.text import HashingVectorizer

    hasher = HashingVectorizer(n_features=4096, ngram_range=(1, 2), alternate_sign=False, norm="l2")
    return hasher.transform(texts).toarray()


@pytest.fixture(scope="session")
def small_system(small_processed):
    """Small dataset with all models trained and the batch decision pipeline run."""
    from backend.app import pipeline
    from backend.app.store import DataStore
    from backend.ml import train_friction, train_risk, train_text

    root = small_processed["root"]
    dirs = (root / "processed", root / "raw", root / "models")
    store = DataStore(*dirs)
    train_risk.train(store, root / "models")
    train_friction.train(store, root / "models")
    train_text.train(store, root / "models", root / "processed", root / "reports", embed=fake_embed)
    store = DataStore(*dirs)
    out = pipeline.run(store, root / "models", root / "processed")
    return {"root": root, "store": store, **out}


@pytest.fixture(scope="session")
def full_raw():
    """The full-size generated dataset (the actual deliverable), generated once per test run."""
    from datagen.config import load_config
    from datagen.generate import generate

    return generate(load_config())


@pytest.fixture(scope="session")
def full_processed(full_raw, tmp_path_factory):
    """Full-size raw tables run through ingestion, plus a DataStore pointing at them."""
    from backend.app.ingestion import pipeline
    from backend.app.store import DataStore
    from datagen.generate import write_tables

    root = tmp_path_factory.mktemp("full")
    write_tables(full_raw, root / "raw")
    tables = pipeline.run(root / "raw", root / "processed", root / "models")
    store = DataStore(root / "processed", root / "raw", root / "models")
    return {"root": root, "store": store, **tables}


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    _clear_caches()
    yield
    _clear_caches()
