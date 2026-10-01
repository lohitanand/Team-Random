from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_reports_llm_disabled() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_enabled"] is False
    assert body["llm_active"] is False
    assert body["llm_provider"] == "groq"
