"""Clickstream event schema (CLAUDE.md §7.2), shared by the generator and the tracker."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.taxonomy import FunnelStep

EventName = Literal[
    "page_view", "product_view", "size_chart_open", "spec_open", "review_open",
    "search", "search_zero_results", "rec_impression", "rec_click",
    "add_to_cart", "remove_from_cart", "cart_view", "checkout_start",
    "pincode_check", "delivery_info_view", "total_shown",
    "coupon_apply", "coupon_failed", "login_wall", "otp_sent", "otp_resend", "otp_failed",
    "payment_attempt", "payment_failed", "payment_success", "order_placed", "tracking_view",
    "rage_click", "dead_click", "js_error", "slow_load",
    "size_unavailable_click", "notify_me", "exit",
    # Extensions (CLAUDE.md allows extending "only if needed"):
    "login_success",     # OTP flow completed; separates recovered logins from stuck ones
    "coupon_applied",    # successful coupon; separates one-off typos from coupon failure
    "chat_open",         # in-session support chat (transcript lives in the chats table)
    "help_view",         # help centre / contact page
    "return_initiated",  # post-purchase return request
    "order_cancelled",   # post-purchase cancellation
]
EVENT_NAMES: tuple[str, ...] = get_args(EventName)

Page = Literal[
    "home", "search", "category", "product", "cart",
    "checkout_login", "checkout_address", "checkout_delivery", "checkout_summary",
    "checkout_payment", "order_confirmation", "order_tracking", "returns", "help",
]
PAGES: tuple[str, ...] = get_args(Page)

PAGE_TO_STEP: dict[str, FunnelStep] = {
    "home": "browse",
    "search": "browse",
    "category": "browse",
    "product": "product",
    "cart": "cart",
    "checkout_login": "checkout",
    "checkout_address": "checkout",
    "checkout_delivery": "checkout",
    "checkout_summary": "checkout",
    "checkout_payment": "payment",
    "order_confirmation": "order",
    "order_tracking": "post_purchase",
    "returns": "post_purchase",
    "help": "post_purchase",
}

# Typed form values must never be captured (CLAUDE.md §2.5, §11).
FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset({
    "card_number", "card", "cvv", "cvc", "expiry", "password", "otp", "otp_code",
    "pin", "upi_pin", "upi_id", "vpa", "address", "phone", "email", "name", "pincode",
})


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    event: EventName
    page: Page
    product_id: str | None = None
    order_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _no_sensitive_fields(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        leaked = sorted(k for k in metadata if k.lower() in FORBIDDEN_METADATA_KEYS)
        if leaked:
            raise ValueError(f"sensitive metadata keys are not allowed: {leaked}")
        return metadata
