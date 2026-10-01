from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.config import ROOT_DIR, Settings, get_settings
from backend.app.db.session import resolve_database_url


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_are_valid() -> None:
    settings = make_settings()
    assert settings.llm_provider == "groq"
    assert settings.llm_fallback_provider == "openrouter"
    assert settings.llm_model_fast == "openai/gpt-oss-20b"
    assert settings.llm_model_agent == "openai/gpt-oss-120b"
    assert settings.llm_timeout_seconds == 8
    assert settings.agent_timeout_seconds == 25
    assert settings.agent_max_tool_calls == 6


def test_llm_disabled_from_env() -> None:
    settings = get_settings()  # conftest sets LLM_ENABLED=false
    assert settings.llm_enabled is False
    assert settings.llm_active is False
    assert settings.provider_chain() == []


def test_llm_inactive_without_keys() -> None:
    settings = make_settings(llm_enabled=True)
    assert settings.llm_active is False


def test_provider_chain_primary_then_fallback() -> None:
    settings = make_settings(
        llm_enabled=True,
        groq_api_key="g-key",
        openrouter_api_key="o-key",
        openrouter_model_fast="some/free-model",
    )
    chain = settings.provider_chain()
    assert [p.name for p in chain] == ["groq", "openrouter"]
    assert chain[0].base_url == "https://api.groq.com/openai/v1"
    assert chain[0].model_fast == "openai/gpt-oss-20b"


def test_fallback_skipped_until_model_verified() -> None:
    settings = make_settings(llm_enabled=True, groq_api_key="g", openrouter_api_key="o")
    assert [p.name for p in settings.provider_chain()] == ["groq"]


def test_empty_fallback_provider_disables_fallback() -> None:
    settings = make_settings(llm_fallback_provider="")
    assert settings.llm_fallback_provider is None


def test_confidence_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        make_settings(confidence_weight_rule=0.5)


def test_gates_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        make_settings(gate_medium=0.9, gate_high=0.8)


def test_relative_sqlite_path_resolves_under_repo_root() -> None:
    url = resolve_database_url("sqlite:///data/app.db")
    assert url == f"sqlite:///{(ROOT_DIR / 'data' / 'app.db').as_posix()}"
