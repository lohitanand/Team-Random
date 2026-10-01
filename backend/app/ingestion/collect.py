"""Tracker ingest: validate events against the schema, hash user ids, store them (CLAUDE.md §7.10)."""
from __future__ import annotations

import hashlib
import re

from sqlalchemy.orm import Session

from backend.app.db.models import LiveEventRow
from backend.app.schemas.events import Event

HASHED = re.compile(r"u_[0-9a-f]{12}")


def hash_user_id(raw: str) -> str:
    """Tracker ids are anonymous browser ids; they are hashed again server-side unless already hashed."""
    if HASHED.fullmatch(raw):
        return raw
    return "u_" + hashlib.sha256(f"live:{raw}".encode()).hexdigest()[:12]


def store_events(db: Session, events: list[Event]) -> list[Event]:
    cleaned: list[Event] = []
    for e in events:
        ts = e.timestamp.astimezone().replace(tzinfo=None) if e.timestamp.tzinfo else e.timestamp
        e = e.model_copy(update={"user_id": hash_user_id(e.user_id), "timestamp": ts})
        db.add(LiveEventRow(session_id=e.session_id, user_id=e.user_id, ts=ts,
                            event=e.event, page=e.page, product_id=e.product_id, order_id=e.order_id,
                            meta=e.metadata))
        cleaned.append(e)
    return cleaned
