"""Read-only access to generated and processed tables, loaded lazily and cached."""
from __future__ import annotations

import json
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.config import MODELS_DIR, PROCESSED_DIR, RAW_DIR


def _objects(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Missing IDs as None (not NaN) so lookups and JSON output behave."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


class DataStore:
    def __init__(self, processed_dir: Path = PROCESSED_DIR, raw_dir: Path = RAW_DIR,
                 models_dir: Path = MODELS_DIR) -> None:
        self.processed_dir = processed_dir
        self.raw_dir = raw_dir
        self.models_dir = models_dir

    def _processed(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.processed_dir / f"{name}.parquet")

    def _raw(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.raw_dir / f"{name}.parquet")

    def has(self, name: str) -> bool:
        return (self.processed_dir / f"{name}.parquet").exists()

    # --- processed ------------------------------------------------------------
    @cached_property
    def events(self) -> pd.DataFrame:
        df = self._processed("events_clean")
        df["metadata"] = df["metadata"].map(json.loads)
        return _objects(df, ["product_id", "order_id"])

    @cached_property
    def sessions(self) -> pd.DataFrame:
        return _objects(self._processed("sessions"), ["gateway", "courier", "primary_product_id", "order_id",
                                                      "payment_method", "app_version"])

    @cached_property
    def features(self) -> pd.DataFrame:
        return self._processed("features")

    @cached_property
    def prefixes(self) -> pd.DataFrame:
        return self._processed("prefix_features")

    @cached_property
    def texts(self) -> pd.DataFrame:
        return _objects(self._processed("texts"), ["session_id", "order_id", "product_id"])

    @cached_property
    def text_themes(self) -> pd.DataFrame:
        return _objects(self._processed("text_themes"), ["session_id", "order_id", "product_id"])

    @cached_property
    def scores(self) -> pd.DataFrame:
        return self._processed("session_scores")

    # --- raw source systems -------------------------------------------------
    @cached_property
    def products(self) -> pd.DataFrame:
        df = self._raw("products")
        for col in ("sizes", "stock", "missing_attributes"):
            df[col] = df[col].map(json.loads)
        return df

    @cached_property
    def product_by_id(self) -> dict[str, dict[str, Any]]:
        return self.products.set_index("product_id", drop=False).to_dict("index")

    @cached_property
    def orders(self) -> pd.DataFrame:
        df = self._raw("orders")
        df["product_ids"] = df["product_ids"].map(json.loads)
        return _objects(df, ["session_id", "cancel_reason", "return_reason"])

    @cached_property
    def payments(self) -> pd.DataFrame:
        return _objects(self._raw("payments"), ["order_id", "gateway", "bank", "error_code"])

    @cached_property
    def tickets(self) -> pd.DataFrame:
        return _objects(self._raw("tickets"), ["order_id", "product_id", "secondary_theme_label"])

    @cached_property
    def reviews(self) -> pd.DataFrame:
        return _objects(self._raw("reviews"), ["session_id", "secondary_theme_label"])

    @cached_property
    def chats(self) -> pd.DataFrame:
        return _objects(self._raw("chats"), ["secondary_theme_label"])

    @cached_property
    def ground_truth(self) -> pd.DataFrame:
        return _objects(self._raw("ground_truth"), ["primary_friction", "secondary_friction", "incident_id",
                                                    "primary_variant", "secondary_variant", "order_id"])

    @cached_property
    def incidents(self) -> pd.DataFrame:
        return self._raw("ground_truth_incidents")

    # --- helpers ----------------------------------------------------------------
    @cached_property
    def session_index(self) -> pd.DataFrame:
        return self.sessions.set_index("session_id", drop=False)

    @cached_property
    def events_by_session(self) -> dict[str, pd.DataFrame]:
        return {sid: g for sid, g in self.events.groupby("session_id", sort=False)}

    def session_events(self, session_id: str) -> list[dict[str, Any]]:
        g = self.events_by_session.get(session_id)
        if g is None:
            return []
        return g[["timestamp", "event", "page", "product_id", "order_id", "metadata"]].to_dict("records")


@lru_cache
def get_store() -> DataStore:
    return DataStore()
