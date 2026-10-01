"""Typed loader for datagen/config.yaml."""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from backend.app.schemas.taxonomy import FRICTION_TYPES

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class Sizes(BaseModel):
    sessions: int = Field(gt=0)
    users: int = Field(gt=0)
    products: int = Field(ge=60)


class Users(BaseModel):
    new_customer_share: float
    logged_in_share_returning: float
    device_mix: dict[str, float]
    android_app_versions: dict[str, float]
    source_mix: dict[str, float]


class Cities(BaseModel):
    tier_1: list[str]
    tier_2: list[str]
    tier_3: list[str]
    tier_mix: dict[str, float]

    def by_tier(self) -> dict[str, list[str]]:
        return {"tier_1": self.tier_1, "tier_2": self.tier_2, "tier_3": self.tier_3}


class Couriers(BaseModel):
    names: list[str]
    base_eta_days: dict[str, int]
    extra_days: dict[str, int]
    primary_share: float
    on_time_rate: float
    express_fee: int


class Payments(BaseModel):
    method_mix: dict[str, float]
    gateway_mix: dict[str, float]
    base_fail_rate: float
    banks: int


class Pricing(BaseModel):
    free_shipping_threshold: int
    shipping_fee: int
    cod_fee: int
    platform_fee: int
    coupons: dict[str, dict[str, int]]


class FrictionMix(BaseModel):
    clean_share: float
    double_share: float
    target_rate_bounds: tuple[float, float]
    weights: dict[str, float]
    variants: dict[str, dict[str, float]]
    in_session_recovery: dict[str, float]
    recovery_propensity: dict[str, float]

    @model_validator(mode="after")
    def _covers_taxonomy(self) -> "FrictionMix":
        expected = set(FRICTION_TYPES)
        for name in ("weights", "variants", "in_session_recovery", "recovery_propensity"):
            keys = set(getattr(self, name))
            if keys != expected:
                raise ValueError(f"friction.{name} keys must equal the taxonomy; diff={keys ^ expected}")
        if self.clean_share + self.double_share >= 1:
            raise ValueError("clean_share + double_share must be < 1")
        return self


class Clean(BaseModel):
    post_purchase_share: float
    bounce_rate: float
    product_exit_rate: float
    cart_abandon_rate: float
    checkout_abandon_rate: float
    noise: dict[str, float]


class DataQuality(BaseModel):
    duplicate_event_rate: float
    missing_exit_rate: float


class GatewayOutage(BaseModel):
    id: str
    gateway: str
    day: int
    start_hour: int
    hours: int
    fail_rate: float


class CourierDelay(BaseModel):
    id: str
    courier: str
    cities: list[str]
    days: list[int]
    extra_eta_days: int
    affect_prob: float
    order_delay_days: tuple[int, int]
    wismo_share: float


class MissingSizeInfo(BaseModel):
    id: str
    n_products: int
    pick_prob: float
    affect_prob: float


class Incidents(BaseModel):
    gateway_outage: GatewayOutage
    courier_delay: CourierDelay
    missing_size_info: MissingSizeInfo


class TextConfig(BaseModel):
    hinglish_share: float
    typo_rate: float
    multi_theme_rate: float
    review_rate: float
    ticket_prob: dict[str, float]
    chat_prob: dict[str, float]
    variant_overrides: dict[str, dict[str, float]]


class DatagenConfig(BaseModel):
    seed: int
    id_hash_salt: str
    start_date: date
    days: int = Field(gt=0)
    sizes: Sizes
    users: Users
    cities: Cities
    couriers: Couriers
    payments: Payments
    pricing: Pricing
    hour_weights: list[float] = Field(min_length=24, max_length=24)
    friction: FrictionMix
    clean: Clean
    data_quality: DataQuality
    incidents: Incidents
    text: TextConfig


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path = CONFIG_PATH, overrides: dict[str, Any] | None = None) -> DatagenConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if overrides:
        raw = _deep_merge(raw, overrides)
    return DatagenConfig.model_validate(raw)
