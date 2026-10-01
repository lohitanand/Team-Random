"""Fixed mappings from detector outputs to friction keys (used by classify.py and confidence.py)."""
from __future__ import annotations

from collections.abc import Iterable

# SHAP signal groups: which friction a feature is evidence for.
FEATURE_GROUPS: dict[str, list[str]] = {
    "payment_failure": [
        "payment_attempts", "payment_failures", "method_switches", "payment_timeouts", "failed_debited_payments",
        "exit_after_payment_failure", "n_payment_records", "n_gateways", "dwell_payment_s", "dwell_z_payment"],
    "coupon_failure": ["coupon_attempts", "coupon_failures", "coupons_applied", "exit_after_coupon_failure"],
    "login_otp_issue": ["login_walls", "otp_sends", "otp_resends", "otp_failures", "login_successes",
                        "exit_after_login", "logged_in_at_start"],
    "technical_glitch": ["rage_clicks", "rage_clicks_checkout", "dead_clicks", "js_errors", "slow_loads",
                         "max_load_ms", "fatal_errors", "exit_after_error", "is_android_app", "device_code"],
    "price_shock": ["total_shown_count", "max_total_delta_pct", "max_extra_fees", "cod_selected",
                    "checkout_cart_loops", "exit_after_total_shown", "cart_removals"],
    "unclear_product_info": ["size_chart_opens", "size_chart_unavailable", "spec_opens", "review_opens",
                             "max_review_page", "pdp_loops", "unique_products", "product_views",
                             "exit_after_product_info", "info_mismatch_returns", "dwell_product_s", "dwell_z_product"],
    "delivery_uncertainty": ["pincode_checks", "delivery_info_views", "max_eta_days", "max_delivery_fee",
                             "fee_first_shown", "exit_after_delivery_info", "city_tier_num", "dwell_checkout_s",
                             "dwell_z_checkout"],
    "poor_recommendations": ["searches", "zero_result_searches", "rec_impressions", "rec_clicks",
                             "exit_after_search", "exit_after_recs", "dwell_browse_s", "dwell_z_browse"],
    "out_of_stock": ["size_unavailable_clicks", "notify_me", "oos_removals", "oos_product_views", "exit_after_oos"],
    "post_purchase_concern": [
        "tracking_views", "help_views", "orders_cancelled", "returns_initiated", "quality_returns",
        "refund_pending_views", "delayed_status_views", "max_last_update_hours", "exit_after_tracking",
        "is_post_purchase", "order_delay_days", "order_is_delayed", "order_refund_pending",
        "order_return_requested", "n_tickets", "dwell_post_purchase_s", "dwell_z_post_purchase"],
}
FEATURE_FRICTIONS: dict[str, set[str]] = {}
for _friction, _features in FEATURE_GROUPS.items():
    for _feature in _features:
        FEATURE_FRICTIONS.setdefault(_feature, set()).add(_friction)

# Text themes -> frictions they corroborate. "other" corroborates nothing.
THEME_FRICTIONS: dict[str, list[str]] = {
    "delivery_delay": ["delivery_uncertainty", "post_purchase_concern"],
    "size_fit": ["unclear_product_info", "out_of_stock"],
    "payment_trust": ["payment_failure"],
    "money_deducted": ["payment_failure"],
    "missing_info": ["unclear_product_info"],
    "return_refund": ["post_purchase_concern", "unclear_product_info"],
    "login_issue": ["login_otp_issue"],
    "stock": ["out_of_stock", "poor_recommendations"],
    "price_fees": ["price_shock", "coupon_failure", "delivery_uncertainty"],
    "app_bug": ["technical_glitch"],
    "other": [],
}

# Funnel position of each friction: when several are evidenced, the latest one is what the
# customer hit last and is chosen as primary (earlier ones become secondary).
FRICTION_STAGE: dict[str, int] = {
    "poor_recommendations": 0, "unclear_product_info": 1, "out_of_stock": 1, "login_otp_issue": 3,
    "delivery_uncertainty": 4, "coupon_failure": 5, "price_shock": 6, "technical_glitch": 6,
    "payment_failure": 7, "post_purchase_concern": 9,
}


def signal_supports(features: Iterable[str], friction: str) -> bool:
    return any(friction in FEATURE_FRICTIONS.get(f, ()) for f in features)


def theme_frictions(themes: Iterable[str]) -> list[str]:
    out: list[str] = []
    for theme in themes:
        for friction in THEME_FRICTIONS.get(theme, []):
            if friction not in out:
                out.append(friction)
    return out
