from __future__ import annotations

import httpx

from scripts import list_models


def test_missing_key_exits_without_network(monkeypatch, capsys) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("network must not be called without a key")

    monkeypatch.setattr(list_models.httpx, "get", fail)
    assert list_models.main([]) == 1
    assert "GROQ_API_KEY" in capsys.readouterr().out


def test_lists_models_and_marks_configured(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    list_models.get_settings.cache_clear()

    def fake_get(url, headers, timeout):
        assert url == "https://api.groq.com/openai/v1/models"
        assert headers["Authorization"] == "Bearer test-key"
        request = httpx.Request("GET", url)
        data = {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "whisper-large-v3"}]}
        return httpx.Response(200, json=data, request=request)

    monkeypatch.setattr(list_models.httpx, "get", fake_get)
    assert list_models.main([]) == 0
    out = capsys.readouterr().out
    assert "openai/gpt-oss-20b   <- LLM fast model" in out
    assert "WARNING: configured agent model 'openai/gpt-oss-120b'" in out
