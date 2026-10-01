"""Phase 2 entrypoint: raw tables -> clean events, sessions, features, prefixes, joins.

    python -m backend.app.ingestion.pipeline
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from backend.app.config import MODELS_DIR, PROCESSED_DIR, RAW_DIR, get_settings
from backend.app.ingestion.features import add_dwell_z, build_feature_tables, fit_dwell_baselines
from backend.app.ingestion.joins import join_session_data, session_texts
from backend.app.ingestion.sessionize import clean_events, session_table, sessionize

RAW_TABLES = ["events", "payments", "orders", "tickets", "reviews", "chats", "products"]


def load_raw(raw_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    missing = [t for t in RAW_TABLES if not (raw_dir / f"{t}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"missing raw tables {missing}; run `python -m datagen.generate` first")
    return {t: pd.read_parquet(raw_dir / f"{t}.parquet") for t in RAW_TABLES}


def run(raw_dir: Path = RAW_DIR, out_dir: Path = PROCESSED_DIR, models_dir: Path = MODELS_DIR) -> dict[str, pd.DataFrame]:
    settings = get_settings()
    raw = load_raw(raw_dir)

    events = sessionize(clean_events(raw["events"]), settings.session_gap_minutes)
    sessions = session_table(events)
    full, prefixes = build_feature_tables(events, settings.max_prefixes_per_session)
    baselines = fit_dwell_baselines(full)
    joins = join_session_data(sessions, raw["payments"], raw["orders"], raw["tickets"], raw["reviews"])
    features = add_dwell_z(full, baselines).merge(joins, on="session_id", how="left")
    prefixes = add_dwell_z(prefixes, baselines)
    texts = session_texts(raw["tickets"], raw["chats"], raw["reviews"])

    out_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    events.assign(metadata=events["metadata"].map(lambda m: json.dumps(m, sort_keys=True, ensure_ascii=False))) \
        .to_parquet(out_dir / "events_clean.parquet", index=False)
    sessions.to_parquet(out_dir / "sessions.parquet", index=False)
    features.to_parquet(out_dir / "features.parquet", index=False)
    prefixes.to_parquet(out_dir / "prefix_features.parquet", index=False)
    texts.to_parquet(out_dir / "texts.parquet", index=False)
    (models_dir / "dwell_baselines.json").write_text(json.dumps(baselines, indent=2), encoding="utf-8")
    return {"events": events, "sessions": sessions, "features": features, "prefixes": prefixes, "texts": texts}


def main() -> int:
    started = time.perf_counter()
    tables = run()
    print(f"Clean events:    {len(tables['events']):>9,}")
    print(f"Sessions:        {len(tables['sessions']):>9,}")
    print(f"Feature rows:    {len(tables['features']):>9,}  ({tables['features'].shape[1] - 1} columns)")
    print(f"Prefix rows:     {len(tables['prefixes']):>9,}")
    print(f"Text records:    {len(tables['texts']):>9,}")
    print(f"Done in {time.perf_counter() - started:.1f}s -> {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
