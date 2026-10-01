"""Tracker ingest (POST /events) and the storefront catalog."""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_state
from backend.app.api.insights import clear_cache
from backend.app.api.util import plain
from backend.app.db.session import get_db
from backend.app.ingestion.collect import store_events
from backend.app.schemas.events import Event

router = APIRouter(tags=["events"])


@router.post("/events")
def ingest(events: list[Event] | Event, db: Session = Depends(get_db)) -> dict[str, Any]:
    batch = events if isinstance(events, list) else [events]
    cleaned = store_events(db, batch)
    db.commit()
    result = get_state().live.add(db, cleaned)
    clear_cache()
    return result


@router.get("/store/products")
def products(limit: int = 24) -> list[dict[str, Any]]:
    p = get_state().store.products
    p = p.sort_values(["in_stock", "rating"], ascending=[False, False])
    cols = ["product_id", "name", "brand", "category", "subcategory", "color", "price", "mrp", "rating", "n_reviews",
            "sizes", "stock", "in_stock", "has_size_chart", "missing_attributes", "warehouse_city", "cod_allowed"]
    picked = [g.head(max(limit // 5, 3)) for _, g in p.groupby("category")]
    return plain(pd.concat(picked)[cols].head(limit).to_dict("records"))
