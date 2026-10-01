"""Fixed friction -> owner team routing (CLAUDE.md §3)."""
from __future__ import annotations

OWNER_TEAM: dict[str, str] = {
    "unclear_product_info": "product",
    "delivery_uncertainty": "operations",
    "payment_failure": "operations_tech",
    "poor_recommendations": "marketing",
    "post_purchase_concern": "customer_service",
    "price_shock": "marketing",
    "coupon_failure": "marketing",
    "login_otp_issue": "customer_service",
    "out_of_stock": "product",
    "technical_glitch": "operations_tech",
}

# Dashboard team views. Operations and Operations/Tech are shown together in one Operations view.
TEAM_VIEWS: dict[str, list[str]] = {
    "customer_service": ["customer_service"],
    "marketing": ["marketing"],
    "product": ["product"],
    "operations": ["operations", "operations_tech"],
}


def route(friction: str) -> str:
    return OWNER_TEAM[friction]
