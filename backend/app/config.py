"""Application settings, read from environment variables and `.env`.

All thresholds live here so detection/decision code never hardcodes them.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"
REPORTS_DIR = DATA_DIR / "reports"

ProviderName = Literal["groq", "openrouter"]


class ProviderConfig(BaseModel):
    """Connection details for one OpenAI-compatible LLM provider."""

    name: ProviderName
    base_url: str
    api_key: str
    api_key_env: str
    model_fast: str
    model_agent: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model_fast)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---------------------------------------------------------------
    llm_enabled: bool = True
    llm_provider: ProviderName = "groq"
    llm_fallback_provider: ProviderName | None = "openrouter"

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_model_fast: str = "openai/gpt-oss-20b"
    llm_model_agent: str = "openai/gpt-oss-120b"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model_fast: str = ""
    openrouter_model_agent: str = ""

    llm_timeout_seconds: float = Field(default=8.0, gt=0)
    agent_timeout_seconds: float = Field(default=25.0, gt=0)
    agent_max_tool_calls: int = Field(default=6, ge=1)

    # --- Storage -----------------------------------------------------------
    database_url: str = "sqlite:///data/app.db"

    # --- Ingestion ---------------------------------------------------------
    session_gap_minutes: int = 30
    max_prefixes_per_session: int = 8

    # --- ML ------------------------------------------------------------------
    ml_seed: int = 42
    test_share_mod: int = 5                # session hash % 5 == 0 -> test split (20%)
    at_risk_threshold: float = 0.5         # risk score at which a session gets an evidence packet

    # --- Detection ---------------------------------------------------------
    friction_prob_threshold: float = 0.6   # classifier prob that "supports" a type
    text_theme_min_prob: float = 0.6       # below this, text themes go to the LLM zero-shot
    text_llm_max_calls: int = 50           # zero-shot LLM budget per batch run (rate limits)
    anomaly_z_threshold: float = 3.0
    anomaly_rate_multiplier: float = 2.5
    anomaly_window_minutes: list[int] = [15, 30, 60]
    anomaly_min_count: int = 8              # minimum affected sessions before a window can be flagged
    anomaly_baseline_hours: int = 48        # trailing baseline for intraday (gateway) windows
    anomaly_daily_baseline_days: int = 7    # trailing baseline for daily (courier/city) windows

    # --- Decision: aggregate support (share of affected sessions that must agree)
    aggregate_rule_support_share: float = 0.2
    aggregate_model_support_share: float = 0.3

    # --- Decision: confidence weights and gates ----------------------------
    confidence_weight_rule: float = 0.30
    confidence_weight_model: float = 0.30
    confidence_weight_text: float = 0.20
    confidence_weight_aggregate: float = 0.20
    gate_high: float = 0.80
    gate_medium: float = 0.50

    # --- Decision: priority (impact = revenue_at_risk * log1p(customers) * trend)
    priority_critical_impact: float = 500_000.0
    priority_high_impact: float = 50_000.0

    # --- Batch / live ------------------------------------------------------------
    batch_investigate_limit: int = 400      # deterministic investigations per batch run
    live_idle_minutes: float = 2.0          # live session considered ended after this idle time
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174",
                               "http://127.0.0.1:5173", "http://127.0.0.1:5174"]

    # --- Recovery ----------------------------------------------------------
    recovery_max_messages_per_user_24h: int = 2
    holdout_share: float = 0.10

    @field_validator("llm_fallback_provider", mode="before")
    @classmethod
    def _empty_fallback_is_none(cls, value: object) -> object:
        return None if value in ("", "none", "None") else value

    @model_validator(mode="after")
    def _check_thresholds(self) -> "Settings":
        weights = (
            self.confidence_weight_rule
            + self.confidence_weight_model
            + self.confidence_weight_text
            + self.confidence_weight_aggregate
        )
        if abs(weights - 1.0) > 1e-9:
            raise ValueError(f"confidence weights must sum to 1.0, got {weights}")
        if not 0 < self.gate_medium < self.gate_high <= 1:
            raise ValueError("gates must satisfy 0 < gate_medium < gate_high <= 1")
        if self.priority_high_impact >= self.priority_critical_impact:
            raise ValueError("priority_high_impact must be below priority_critical_impact")
        if self.llm_fallback_provider == self.llm_provider:
            raise ValueError("llm_fallback_provider must differ from llm_provider")
        return self

    def provider(self, name: ProviderName) -> ProviderConfig:
        if name == "groq":
            return ProviderConfig(
                name="groq",
                base_url=self.groq_base_url,
                api_key=self.groq_api_key,
                api_key_env="GROQ_API_KEY",
                model_fast=self.llm_model_fast,
                model_agent=self.llm_model_agent,
            )
        return ProviderConfig(
            name="openrouter",
            base_url=self.openrouter_base_url,
            api_key=self.openrouter_api_key,
            api_key_env="OPENROUTER_API_KEY",
            model_fast=self.openrouter_model_fast,
            model_agent=self.openrouter_model_agent,
        )

    def provider_chain(self) -> list[ProviderConfig]:
        """Providers to try in order; empty when the LLM is disabled or unconfigured."""
        if not self.llm_enabled:
            return []
        names: list[ProviderName] = [self.llm_provider]
        if self.llm_fallback_provider:
            names.append(self.llm_fallback_provider)
        return [p for p in (self.provider(n) for n in names) if p.is_configured]

    @property
    def llm_active(self) -> bool:
        return bool(self.provider_chain())


@lru_cache
def get_settings() -> Settings:
    return Settings()
