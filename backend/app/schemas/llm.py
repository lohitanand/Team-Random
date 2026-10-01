"""Strict schemas for everything an LLM may return. Anything that does not parse is rejected."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.taxonomy import TextTheme


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplanationOut(_Strict):
    summary: str = Field(min_length=1, max_length=400)
    behavior_observed: str = Field(min_length=1, max_length=400)
    likely_business_cause: str = Field(min_length=1, max_length=400)
    evidence_used: list[str] = Field(min_length=1, max_length=12)


class MessageOut(_Strict):
    message: str = Field(min_length=1, max_length=300)


class ThemeOut(_Strict):
    theme: TextTheme


class CSReplyOut(_Strict):
    reply: str = Field(min_length=1, max_length=700)


class AnalystOut(_Strict):
    answer: str = Field(min_length=1, max_length=1200)
    numbers_cited: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    """A validated explanation plus where it came from."""

    summary: str
    behavior_observed: str
    likely_business_cause: str
    evidence_used: list[str]
    source: Literal["llm", "fallback"]
    guardrail_failures: list[str] = Field(default_factory=list)


class CustomerMessage(BaseModel):
    text: str
    template_id: str
    source: Literal["llm", "fallback"]
    guardrail_failures: list[str] = Field(default_factory=list)
