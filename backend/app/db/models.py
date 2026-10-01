"""ORM tables. Portable column types only (SQLite in dev, Postgres-compatible)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now()


class PacketRow(Base):
    __tablename__ = "packets"
    id = Column(String(160), primary_key=True)
    packet_type = Column(String(16), index=True)
    session_id = Column(String(64), index=True)
    source = Column(String(16), default="batch")
    friction_type = Column(String(40), index=True)
    gate = Column(String(8), index=True)
    confidence = Column(Float)
    risk_score = Column(Float)
    payload = Column(JSON)
    decision = Column(JSON)
    created_at = Column(DateTime, default=_now, index=True)


class AlertRow(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    packet_id = Column(String(160), index=True)
    alert_type = Column(String(16), index=True)
    source = Column(String(16), default="batch")
    title = Column(String(300))
    friction_type = Column(String(40), index=True)
    confidence = Column(Float)
    gate = Column(String(8))
    priority = Column(String(10), index=True)
    impact = Column(Float, default=0.0)
    owner_team = Column(String(30), index=True)
    status = Column(String(16), index=True)
    revenue_at_risk = Column(Float, default=0.0)
    affected_sessions = Column(Integer, default=1)
    session_id = Column(String(64), index=True)
    explanation = Column(JSON)
    key_evidence = Column(JSON)
    team_action = Column(JSON)
    customer_action = Column(JSON)
    assigned_to = Column(String(80))
    created_at = Column(DateTime, default=_now, index=True)
    updated_at = Column(DateTime, default=_now)


class WorkflowRow(Base):
    __tablename__ = "workflow_executions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, index=True)
    action = Column(String(20))
    actor = Column(String(80))
    assignee = Column(String(80))
    note = Column(Text)
    result = Column(JSON)
    created_at = Column(DateTime, default=_now)


class RecoveryRow(Base):
    __tablename__ = "recovery_actions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True)
    user_id = Column(String(64), index=True)
    packet_id = Column(String(160))
    friction_type = Column(String(40), index=True)
    action_id = Column(String(60))
    moment = Column(String(20))
    channel = Column(String(20))
    status = Column(String(24), index=True)
    auto = Column(Boolean, default=False)
    holdout = Column(Boolean, default=False)
    message = Column(Text)
    message_source = Column(String(12))
    outcome = Column(String(16), default="pending")
    value = Column(Float, default=0.0)
    approved_by = Column(String(80))
    created_at = Column(DateTime, default=_now, index=True)


class AuditRow(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=_now, index=True)
    event_type = Column(String(40), index=True)
    entity_type = Column(String(20), index=True)
    entity_id = Column(String(160), index=True)
    actor = Column(String(80), default="system")
    payload = Column(JSON)


class LiveEventRow(Base):
    __tablename__ = "live_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True)
    user_id = Column(String(64), index=True)
    ts = Column(DateTime, index=True)
    event = Column(String(40))
    page = Column(String(40))
    product_id = Column(String(40))
    order_id = Column(String(40))
    meta = Column(JSON)


class CsDraftRow(Base):
    __tablename__ = "cs_drafts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, index=True)
    session_id = Column(String(64))
    draft = Column(Text)
    source = Column(String(12))
    context = Column(JSON)
    status = Column(String(16), default="pending_approval")
    approved_by = Column(String(80))
    created_at = Column(DateTime, default=_now)
