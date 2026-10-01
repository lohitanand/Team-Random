"""One small OpenAI-compatible chat client for Groq (primary) and OpenRouter (fallback).

No vendor SDKs. Callers must validate everything returned (guardrails.py); this client never
decides anything. Order of attempts: primary provider -> fallback provider -> raise LLMError.
"""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.config import ProviderConfig, Settings, get_settings

Role = Literal["fast", "agent"]
PROMPTS_DIR = Path(__file__).with_name("prompts")


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class LLMError(Exception):
    """Any failure to get a usable response (disabled, unconfigured, HTTP error, timeout, bad body)."""


class ToolsUnsupported(LLMError):
    """The provider/model rejected tool calling."""


class ChatResult(BaseModel):
    content: str | None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    provider: str
    model: str
    latency_ms: int


def _rejects(response: httpx.Response, feature: str) -> bool:
    return response.status_code == 400 and feature in response.text.lower()


class LLMClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    @property
    def active(self) -> bool:
        return self.settings.llm_active

    def _post(self, provider: ProviderConfig, body: dict[str, Any], timeout: float) -> httpx.Response:
        with httpx.Client(transport=self.transport, timeout=timeout) as http:
            return http.post(f"{provider.base_url}/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {provider.api_key}"})

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        role: Role = "fast",
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> ChatResult:
        chain = self.settings.provider_chain()
        if not chain:
            raise LLMError("LLM disabled or no provider configured")
        timeout = timeout or self.settings.llm_timeout_seconds
        errors: list[str] = []
        for provider in chain:
            model = provider.model_agent if role == "agent" and provider.model_agent else provider.model_fast
            body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if tools:
                body["tools"], body["tool_choice"] = tools, "auto"
            started = time.perf_counter()
            try:
                response = self._post(provider, body, timeout)
                if json_mode and _rejects(response, "response_format"):
                    body.pop("response_format")  # model lacks JSON mode; guardrails still validate
                    response = self._post(provider, body, timeout)
                if tools and _rejects(response, "tool"):
                    raise ToolsUnsupported(f"{provider.name}/{model} rejected tools")
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                return ChatResult(
                    content=message.get("content"), tool_calls=message.get("tool_calls") or [],
                    provider=provider.name, model=model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            except ToolsUnsupported:
                raise
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}"[:300])
        raise LLMError("; ".join(errors))

    def complete_json(self, system: str, user: str, *, role: Role = "fast", timeout: float | None = None) -> str:
        """Raw JSON text from the model. The caller parses and validates it."""
        result = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                           role=role, json_mode=True, timeout=timeout)
        if not result.content:
            raise LLMError("empty response")
        return result.content
