"""Decision-layer output and alert records (CLAUDE.md §7.6, §7.9)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Gate = Literal["high", "medium", "low"]
Priority = Literal["critical", "high", "normal"]
AlertStatus = Literal["open", "needs_review", "approved", "assigned", "dismissed", "resolved"]
WorkflowAction = Literal["approve", "assign", "create_ticket", "dismiss", "resolve"]


class PlaybookAction(BaseModel):
    id: str
    description: str
    channel: str
    auto_allowed: bool
    template_id: str
    moment: str | None = None
    allows_terms: list[str] = Field(default_factory=list)
    when: dict[str, Any] = Field(default_factory=dict)


class ConfidenceBreakdown(BaseModel):
    rule_supports: bool
    model_supports: bool
    text_supports: bool
    aggregate_supports: bool
    score: float


class Decision(BaseModel):
    packet_id: str
    packet_type: Literal["session", "aggregate"]
    friction_type: str
    secondary_friction: str | None
    classification_source: Literal["aggregate_metric", "rules", "classifier", "themes", "weak_classifier"]
    confidence: float
    breakdown: ConfidenceBreakdown
    gate: Gate
    owner_team: str
    priority: Priority
    impact: float
    revenue_at_risk: float
    customers_affected: int
    trend_factor: float
    customer_action: PlaybookAction | None
    team_action: PlaybookAction
    investigated: bool = False
    needs_review: bool = False


class AlertOut(BaseModel):
    id: int
    packet_id: str
    alert_type: str
    title: str
    friction_type: str
    confidence: float
    gate: str
    priority: str
    owner_team: str
    status: AlertStatus
    revenue_at_risk: float
    affected_sessions: int
    session_id: str | None
    explanation: dict[str, Any]
    key_evidence: dict[str, Any]
    team_action: dict[str, Any]
    customer_action: dict[str, Any] | None
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowRequest(BaseModel):
    action: WorkflowAction
    actor: str = Field(default="dashboard_user", max_length=80)
    assignee: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)
