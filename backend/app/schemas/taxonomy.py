"""Fixed vocabularies shared by every module (CLAUDE.md §3, §7.4)."""
from __future__ import annotations

from typing import Literal, get_args

FrictionType = Literal[
    "unclear_product_info",
    "delivery_uncertainty",
    "payment_failure",
    "poor_recommendations",
    "post_purchase_concern",
    "price_shock",
    "coupon_failure",
    "login_otp_issue",
    "out_of_stock",
    "technical_glitch",
]
FRICTION_TYPES: tuple[str, ...] = get_args(FrictionType)
CORE_FRICTION_TYPES: tuple[str, ...] = FRICTION_TYPES[:5]

TextTheme = Literal[
    "delivery_delay",
    "size_fit",
    "payment_trust",
    "money_deducted",
    "missing_info",
    "return_refund",
    "login_issue",
    "stock",
    "price_fees",
    "app_bug",
    "other",
]
TEXT_THEMES: tuple[str, ...] = get_args(TextTheme)

FunnelStep = Literal["browse", "product", "cart", "checkout", "payment", "order", "post_purchase"]
FUNNEL_STEPS: tuple[str, ...] = get_args(FunnelStep)
