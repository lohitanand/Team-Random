"""FastAPI entrypoint: `uvicorn backend.app.main:app --reload`."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.api import routes_agents, routes_alerts, routes_dashboard, routes_events, routes_sessions, sse
from backend.app.config import get_settings
from backend.app.db.session import get_session_factory, init_db

APP_VERSION = "1.0.0"
log = logging.getLogger("friction")


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_enabled: bool
    llm_provider: str
    llm_active: bool


def _finalize_idle_sessions() -> None:
    from backend.app.api.deps import get_state

    state = get_state()
    if "live" not in state.__dict__:
        return
    try:
        with get_session_factory()() as db:
            state.live.finalize_idle(db)
    except Exception:  # background job must never crash the scheduler
        log.exception("finalize_idle failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    sse.broadcaster.loop = asyncio.get_running_loop()
    scheduler = BackgroundScheduler()
    scheduler.add_job(_finalize_idle_sessions, "interval", seconds=30, id="finalize_idle", max_instances=1)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Customer Journey Friction Detection & Recovery Assistant", version=APP_VERSION,
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
for module in (routes_events, routes_dashboard, routes_alerts, routes_sessions, routes_agents, sse):
    app.include_router(module.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", version=APP_VERSION, llm_enabled=settings.llm_enabled,
                          llm_provider=settings.llm_provider, llm_active=settings.llm_active)
