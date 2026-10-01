"""Clean raw events, sessionize them (30-minute inactivity rule) and map the funnel."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from backend.app.schemas.events import EVENT_NAMES, FORBIDDEN_METADATA_KEYS, PAGE_TO_STEP, PAGES
from backend.app.schemas.taxonomy import FUNNEL_STEPS

EVENT_COLUMNS = ["session_id", "user_id", "timestamp", "event", "page", "product_id", "order_id", "metadata"]
SHOPPING_STEPS = FUNNEL_STEPS[:-1]
POST_PURCHASE_PAGES = {"order_tracking", "returns"}
CONTEXT_KEYS = ["device", "app_version", "city", "city_tier", "source", "is_logged_in"]


def _none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def parse_metadata(value: Any) -> dict[str, Any]:
    """Parse metadata and drop any typed-form keys that must never be stored."""
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str) and value:
        data = json.loads(value)
    else:
        data = {}
    return {k: v for k, v in data.items() if k.lower() not in FORBIDDEN_METADATA_KEYS}


def clean_events(raw: pd.DataFrame) -> pd.DataFrame:
    """Drop exact duplicates and invalid rows, normalise nulls, parse metadata, add funnel step."""
    df = raw[EVENT_COLUMNS].copy()
    hashable = df.assign(metadata=df["metadata"].map(lambda m: m if isinstance(m, str) else json.dumps(m, sort_keys=True)))
    df = df[~hashable.duplicated()]
    df = df[df["event"].isin(EVENT_NAMES) & df["page"].isin(PAGES)].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in ("product_id", "order_id"):
        df[col] = pd.Series([_none(v) for v in df[col].astype(object)], index=df.index, dtype=object)
    df["metadata"] = df["metadata"].map(parse_metadata)
    df["step"] = df["page"].map(PAGE_TO_STEP)
    return df.sort_values(["user_id", "timestamp"], kind="stable").reset_index(drop=True)


def sessionize(events: pd.DataFrame, gap_minutes: int = 30) -> pd.DataFrame:
    """Split each user's events into sessions.

    A new session starts after `gap_minutes` of inactivity or when the tracker's session id
    changes. A tracker session that spans an inactivity gap is split into `<id>_2`, `<id>_3`, ...
    """
    df = events.sort_values(["user_id", "timestamp"], kind="stable").reset_index(drop=True)
    gap = df.groupby("user_id")["timestamp"].diff()
    changed = df["session_id"] != df.groupby("user_id")["session_id"].shift()
    new_session = gap.isna() | (gap > pd.Timedelta(minutes=gap_minutes)) | changed
    segment = new_session.cumsum()
    rank = segment.groupby(df["session_id"]).rank(method="dense").astype(int)
    df["session_id"] = np.where(rank > 1, df["session_id"] + "_" + rank.astype(str), df["session_id"])
    return df.sort_values(["session_id", "timestamp"], kind="stable").reset_index(drop=True)


def _furthest_step(steps: list[str]) -> str:
    shopping = [s for s in steps if s in SHOPPING_STEPS]
    return max(shopping, key=SHOPPING_STEPS.index) if shopping else "browse"


def session_table(events: pd.DataFrame) -> pd.DataFrame:
    """One row per session: context, funnel position, outcome flags and join keys."""
    rows: list[dict[str, Any]] = []
    for sid, g in events.groupby("session_id", sort=False):
        names = g["event"].tolist()
        pages = g["page"].tolist()
        metas = g["metadata"].tolist()
        body = [i for i, n in enumerate(names) if n != "exit"] or [0]
        steps = [PAGE_TO_STEP[pages[i]] for i in body]
        first = metas[0]
        is_pp = bool(POST_PURCHASE_PAGES & set(pages)) and "add_to_cart" not in names and "checkout_start" not in names
        payments = [m for n, m in zip(names, metas) if n == "payment_attempt"]
        couriers = [m["courier"] for n, m in zip(names, metas) if n == "delivery_info_view" and "courier" in m]
        carts = [m["cart_value"] for m in metas if "cart_value" in m]
        product_ids = [p for p in g["product_id"].tolist() if isinstance(p, str)]
        order_ids = [o for o in g["order_id"].tolist() if isinstance(o, str)]
        rows.append({
            "session_id": sid,
            "user_id": g["user_id"].iloc[0],
            "start": g["timestamp"].iloc[0],
            "end": g["timestamp"].iloc[-1],
            "duration_s": (g["timestamp"].iloc[-1] - g["timestamp"].iloc[0]).total_seconds(),
            "n_events": len(g),
            **{k: first.get(k) for k in CONTEXT_KEYS},
            "session_kind": "post_purchase" if is_pp else "shopping",
            "furthest_step": "post_purchase" if is_pp else _furthest_step(steps),
            "exit_step": steps[-1],
            "exit_page": pages[body[-1]],
            "reached_cart": "add_to_cart" in names,
            "converted": "order_placed" in names,
            "has_exit_event": names[-1] == "exit",
            "gateway": payments[-1].get("gateway") if payments else None,
            "payment_method": payments[-1].get("method") if payments else None,
            "courier": couriers[-1] if couriers else None,
            "primary_product_id": Counter(product_ids).most_common(1)[0][0] if product_ids else None,
            "order_id": order_ids[0] if order_ids else None,
            "cart_value": float(max(carts)) if carts else 0.0,
        })
    df = pd.DataFrame(rows)
    df["abandoned"] = df["reached_cart"] & ~df["converted"]
    order = df.sort_values(["user_id", "start"]).groupby("user_id").cumcount()
    df["is_returning"] = (order.reindex(df.index) > 0) | df["is_logged_in"].fillna(False).astype(bool)
    return df
