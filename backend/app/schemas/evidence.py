"""Evidence packets (CLAUDE.md §7.5): the only input the decision layer and the LLM ever see."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Signal(BaseModel):
    feature: str
    shap: float


class Finding(BaseModel):
    """One read-only tool result gathered by the investigation agent."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str
    numbers: dict[str, float] = Field(default_factory=dict)
    supports: str | None = None          # friction key this evidence supports, decided by code
    evidence_kind: Literal["text", "aggregate", "catalog", "none"] = "none"


class EvidenceBase(BaseModel):
    packet_id: str
    rule_flags: list[str] = Field(default_factory=list)
    top_signals: list[Signal] = Field(default_factory=list)
    friction_probs: dict[str, float] = Field(default_factory=dict)
    friction_signals: dict[str, list[Signal]] = Field(default_factory=dict)
    text_themes: list[str] = Field(default_factory=list)
    aggregate_context: dict[str, Any] = Field(default_factory=dict)
    investigation_findings: list[Finding] = Field(default_factory=list)


class SessionPacket(EvidenceBase):
    packet_type: Literal["session"] = "session"
    session_id: str
    user_id: str
    session_kind: str
    risk_score: float
    cart_value: float
    context: dict[str, Any] = Field(default_factory=dict)


class AggregatePacket(EvidenceBase):
    packet_type: Literal["aggregate"] = "aggregate"
    segment_type: str
    segment_value: str
    metric: str
    friction_hint: str | None
    window_start: datetime
    window_end: datetime
    observed: float
    baseline: float
    z_score: float
    multiplier: float
    affected_sessions: int
    session_ids: list[str] = Field(default_factory=list)
    revenue_at_risk: float
    trend: str


Packet = SessionPacket | AggregatePacket
