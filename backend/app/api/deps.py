"""Process-wide API state: data store, models, tools, live engine (loaded lazily, once)."""
from __future__ import annotations

from functools import cached_property, lru_cache

import pandas as pd
from fastapi import HTTPException

from backend.app.agents.investigator import Investigator
from backend.app.agents.tools import Tools
from backend.app.api.sse import broadcaster
from backend.app.config import MODELS_DIR
from backend.app.detection.scorer import Scorer
from backend.app.store import DataStore, get_store


class AppState:
    def __init__(self, store: DataStore | None = None) -> None:
        self.store = store or get_store()

    @cached_property
    def scorer(self) -> Scorer:
        try:
            return Scorer.load(self.store.models_dir if self.store.models_dir else MODELS_DIR)
        except FileNotFoundError as exc:
            raise HTTPException(503, "models not trained yet - run scripts\\build_all.ps1") from exc

    def live_events(self) -> pd.DataFrame:
        rows = [{"session_id": sid, "ts": e["timestamp"], "event": e["event"], "page": e["page"], "meta": e["metadata"]}
                for sid, st in list(self.live.sessions.items()) for e in list(st["events"])]
        return pd.DataFrame(rows, columns=["session_id", "ts", "event", "page", "meta"])

    @cached_property
    def tools(self) -> Tools:
        return Tools(self.store, self.live_events)

    def investigator(self, on_tool_call=None, use_llm: bool = True) -> Investigator:
        return Investigator(self.tools, on_tool_call=on_tool_call, use_llm=use_llm)

    @cached_property
    def live(self):
        from backend.app.live import LiveEngine

        return LiveEngine(self.store, self.scorer, broadcaster, self.investigator(use_llm=True))


@lru_cache
def get_state() -> AppState:
    return AppState()
