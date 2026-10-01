"""Read-only investigation tools (CLAUDE.md §7.8). No tool writes data or sends anything.

Every tool returns a JSON-serialisable dict with the numbers it computed.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.app.store import DataStore

ToolFn = Callable[..., dict[str, Any]]


def _ts(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value) if value else pd.Timestamp(datetime.now())


class Tools:
    """Bound to a DataStore (historical) and an optional live-events frame."""

    def __init__(self, store: DataStore, live_events: Callable[[], pd.DataFrame] | None = None) -> None:
        self.store = store
        self._live = live_events

    def live(self) -> pd.DataFrame:
        return self._live() if self._live else pd.DataFrame(columns=["session_id", "ts", "event", "page", "meta"])

    # --- funnel ------------------------------------------------------------------------
    def drop_off_by_segment(self, step: str = "payment", segment: str = "device") -> dict[str, Any]:
        s = self.store.sessions
        s = s[s["session_kind"] == "shopping"]
        order = ["browse", "product", "cart", "checkout", "payment", "order"]
        if step not in order or segment not in s.columns:
            return {"error": f"unknown step or segment ({step}, {segment})"}
        reached = s[s["furthest_step"].map(order.index) >= order.index(step)]
        left = reached[(reached["exit_step"] == step) & ~reached["converted"]]
        overall = len(left) / max(len(reached), 1)
        grp = reached.groupby(segment).size().to_frame("reached").join(left.groupby(segment).size().rename("left"))
        grp = grp.fillna(0)
        grp["exit_rate"] = (grp["left"] / grp["reached"]).round(4)
        rows = grp.sort_values("exit_rate", ascending=False).head(8).reset_index()
        return {"step": step, "segment": segment, "overall_exit_rate": round(overall, 4),
                "segments": rows.to_dict("records")}

    def compare_converters_vs_abandoners(self, features: list[str] | None = None) -> dict[str, Any]:
        f = self.store.features.merge(self.store.sessions[["session_id", "converted", "reached_cart"]], on="session_id")
        f = f[f["reached_cart"]]
        cols = features or ["payment_failures", "coupon_failures", "otp_resends", "size_chart_opens", "pincode_checks",
                            "max_eta_days", "max_extra_fees", "rage_clicks", "js_errors", "dwell_checkout_s"]
        cols = [c for c in cols if c in f.columns]
        conv, aband = f[f["converted"]][cols].mean(), f[~f["converted"]][cols].mean()
        diff = [{"feature": c, "converters": round(float(conv[c]), 3), "abandoners": round(float(aband[c]), 3),
                 "ratio": round(float(aband[c] / conv[c]), 2) if conv[c] else None} for c in cols]
        diff.sort(key=lambda d: -(d["ratio"] or 99))
        return {"n_converters": int(f["converted"].sum()), "n_abandoners": int((~f["converted"]).sum()),
                "features": diff}

    # --- feedback / orders ---------------------------------------------------------------
    def sample_feedback(self, session_id: str | None = None, user_id: str | None = None,
                        product_id: str | None = None, theme: str | None = None, limit: int = 5,
                        session_ids: list[str] | None = None) -> dict[str, Any]:
        t = self.store.text_themes
        mask = pd.Series(False, index=t.index)
        if session_id:
            mask |= t["session_id"] == session_id
        if session_ids:
            mask |= t["session_id"].isin(session_ids)
        if user_id:
            mask |= t["user_id"] == user_id
        if product_id:
            mask |= t["product_id"] == product_id
        if not (session_id or user_id or product_id or session_ids):
            mask[:] = True
        if theme:
            mask &= t["theme"] == theme
        rows = t[mask].sort_values("ts", ascending=False)
        themes = rows["theme"].value_counts().to_dict()
        sample = rows.head(limit)[["source", "ts", "theme", "language", "text"]].copy()
        sample["ts"] = sample["ts"].astype(str)
        return {"matched": int(len(rows)), "themes": {k: int(v) for k, v in themes.items()},
                "samples": sample.to_dict("records")}

    def order_status_for_sessions(self, session_ids: list[str]) -> dict[str, Any]:
        s = self.store.sessions
        order_ids = [o for o in s[s["session_id"].isin(session_ids)]["order_id"].tolist() if o]
        o = self.store.orders[self.store.orders["order_id"].isin(order_ids)]
        return {"orders": int(len(o)), "status_counts": o["status"].value_counts().to_dict(),
                "delayed": int((o["delay_days"] > 0).sum()),
                "mean_delay_days": round(float(o["delay_days"].mean()), 2) if len(o) else 0.0,
                "refunds_pending": int((o["refund_status"] == "pending").sum()),
                "orders_detail": o[["order_id", "status", "courier", "delay_days", "refund_status"]]
                .head(10).to_dict("records")}

    # --- catalog ---------------------------------------------------------------------------
    def recent_catalog_changes(self, days: int = 3, before: str | None = None) -> dict[str, Any]:
        p = self.store.products
        end = _ts(before) if before else p["catalog_updated_at"].max()
        recent = p[(p["catalog_updated_at"] <= end) & (p["catalog_updated_at"] >= end - timedelta(days=days))]
        return {"window_days": days, "changed_products": int(len(recent)),
                "products": recent[["product_id", "name", "catalog_updated_at"]].astype(str).head(10).to_dict("records")}

    def product_details(self, product_id: str) -> dict[str, Any]:
        p = self.store.product_by_id.get(product_id)
        if not p:
            return {"error": f"unknown product {product_id}"}
        return {k: (str(v) if isinstance(v, (pd.Timestamp, datetime)) else v) for k, v in p.items()
                if k in ("product_id", "name", "category", "subcategory", "price", "rating", "n_reviews",
                         "has_size_chart", "sizes", "missing_attributes", "spec_completeness", "image_count",
                         "return_window_days", "in_stock")}

    def stock_check(self, product_id: str) -> dict[str, Any]:
        p = self.store.product_by_id.get(product_id)
        if not p:
            return {"error": f"unknown product {product_id}"}
        out = [size for size, q in p["stock"].items() if q == 0]
        return {"product_id": product_id, "in_stock": bool(p["in_stock"]), "stock": p["stock"],
                "sizes_out_of_stock": out, "share_sizes_out": round(len(out) / max(len(p["stock"]), 1), 2)}

    # --- operations ----------------------------------------------------------------------------
    def gateway_health(self, gateway: str, around: str | None = None, window_minutes: int = 60) -> dict[str, Any]:
        pay = self.store.payments
        pay = pay[pay["gateway"] == gateway]
        per = pay.groupby("session_id").agg(ts=("timestamp", "min"), failed=("status", lambda x: (x == "failed").any()))
        baseline = float(per["failed"].mean()) if len(per) else 0.0
        t = _ts(around)
        lo, hi = t - timedelta(minutes=window_minutes), t + timedelta(minutes=window_minutes)
        win = per[(per["ts"] >= lo) & (per["ts"] <= hi)]
        n, failed = len(win), int(win["failed"].sum())
        live = self.live()
        if len(live):
            lp = live[live["event"].isin(["payment_attempt", "payment_failed"])]
            lp = lp[lp["meta"].map(lambda m: (m or {}).get("gateway") == gateway)]
            lp = lp[(pd.to_datetime(lp["ts"]) >= lo) & (pd.to_datetime(lp["ts"]) <= hi)]
            sessions = {sid: bool((g["event"] == "payment_failed").any()) for sid, g in lp.groupby("session_id")}
            n, failed = n + len(sessions), failed + sum(sessions.values())
        rate = failed / n if n else 0.0
        return {"gateway": gateway, "window": f"{lo:%d %b %H:%M} to {hi:%d %b %H:%M}", "sessions_in_window": n,
                "failed_sessions": failed, "failure_rate": round(rate, 4), "baseline_failure_rate": round(baseline, 4),
                "multiplier": round(rate / baseline, 2) if baseline else None}

    def courier_health(self, courier: str, city: str | None = None, around: str | None = None,
                       days: int = 2) -> dict[str, Any]:
        o = self.store.orders
        o = o[o["courier"] == courier]
        if city:
            o = o[o["city"] == city]
        baseline = float((o["delay_days"] >= 2).mean()) if len(o) else 0.0
        t = _ts(around)
        win = o[(pd.to_datetime(o["placed_at"]) >= t - timedelta(days=days)) &
                (pd.to_datetime(o["placed_at"]) <= t + timedelta(days=days))]
        rate = float((win["delay_days"] >= 2).mean()) if len(win) else 0.0
        return {"courier": courier, "city": city, "orders_in_window": int(len(win)),
                "delayed_share": round(rate, 4), "baseline_delayed_share": round(baseline, 4),
                "multiplier": round(rate / baseline, 2) if baseline else None,
                "mean_delay_days": round(float(win["delay_days"].mean()), 2) if len(win) else 0.0}

    def delivery_eta(self, city: str, courier: str | None = None) -> dict[str, Any]:
        e = self.store.events
        info = e[e["event"] == "delivery_info_view"].merge(self.store.sessions[["session_id", "city"]], on="session_id")
        info = info[info["city"] == city]
        meta = pd.DataFrame(info["metadata"].tolist())
        if courier and len(meta):
            meta = meta[meta.get("courier") == courier]
        eta = pd.to_numeric(meta.get("eta_days"), errors="coerce") if len(meta) else pd.Series(dtype=float)
        return {"city": city, "courier": courier, "quotes": int(eta.notna().sum()),
                "median_eta_days": float(np.nanmedian(eta)) if eta.notna().any() else None,
                "p90_eta_days": float(np.nanpercentile(eta.dropna(), 90)) if eta.notna().any() else None}

    def top_frictions(self, limit: int = 5) -> dict[str, Any]:
        """Friction types ranked by revenue at risk (from the decision layer's output)."""
        path = self.store.processed_dir / "decisions.parquet"
        if not path.exists():
            return {"error": "no decisions yet"}
        d = pd.read_parquet(path)
        d = d[d["packet_type"] == "session"]
        g = d.groupby("friction_type").agg(sessions=("packet_id", "size"), revenue_at_risk=("revenue_at_risk", "sum"))
        g = g.sort_values("revenue_at_risk", ascending=False).head(limit).round(2).reset_index()
        return {"frictions": g.to_dict("records")}


TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "drop_off_by_segment", "description": "Exit rate at a funnel step broken down by a segment.",
     "parameters": {"type": "object", "properties": {
         "step": {"type": "string", "enum": ["browse", "product", "cart", "checkout", "payment"]},
         "segment": {"type": "string", "enum": ["device", "city_tier", "city", "source", "gateway", "courier"]}},
         "required": ["step", "segment"]}},
    {"name": "compare_converters_vs_abandoners", "description": "Mean behaviour of converters vs abandoners.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "sample_feedback", "description": "Customer tickets/chats/reviews with their themes.",
     "parameters": {"type": "object", "properties": {
         "session_id": {"type": "string"}, "user_id": {"type": "string"}, "product_id": {"type": "string"},
         "theme": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "order_status_for_sessions", "description": "Order status, delays and refunds for sessions.",
     "parameters": {"type": "object", "properties": {"session_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["session_ids"]}},
    {"name": "recent_catalog_changes", "description": "Products changed in the last N days.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}}},
    {"name": "gateway_health", "description": "Payment failure rate of a gateway around a time vs its baseline.",
     "parameters": {"type": "object", "properties": {"gateway": {"type": "string"}, "around": {"type": "string"}},
                    "required": ["gateway"]}},
    {"name": "courier_health", "description": "Delayed-order share of a courier (optionally in a city) vs baseline.",
     "parameters": {"type": "object", "properties": {"courier": {"type": "string"}, "city": {"type": "string"},
                                                     "around": {"type": "string"}}, "required": ["courier"]}},
    {"name": "product_details", "description": "Catalog attributes of a product (size chart, missing attributes).",
     "parameters": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]}},
    {"name": "delivery_eta", "description": "Typical delivery ETA quoted for a city (and courier).",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "courier": {"type": "string"}},
                    "required": ["city"]}},
    {"name": "stock_check", "description": "Stock by size for a product.",
     "parameters": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]}},
    {"name": "top_frictions", "description": "Friction types ranked by revenue at risk.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
]
TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


def openai_tools() -> list[dict[str, Any]]:
    return [{"type": "function", "function": spec} for spec in TOOL_SPECS]


def call_tool(tools: Tools, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_NAMES:
        return {"error": f"unknown tool {name}"}
    try:
        return getattr(tools, name)(**args)
    except TypeError as exc:
        return {"error": f"bad arguments: {exc}"}
