"""Explicit, named detection rules (CLAUDE.md §7.4). Each rule maps to exactly one friction key.

Rules read the session feature vector only; the threshold is part of the rule's name.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

Features = Mapping[str, float]


@dataclass(frozen=True)
class Rule:
    name: str
    friction: str
    description: str
    check: Callable[[Features], bool]


def _g(f: Features, key: str) -> float:
    return float(f.get(key, 0.0) or 0.0)


RULES: tuple[Rule, ...] = (
    # payment_failure
    Rule("payment_retry_x2", "payment_failure", "2+ failed payment attempts",
         lambda f: _g(f, "payment_failures") >= 2),
    Rule("money_deducted_failed_payment", "payment_failure", "failed payment where money was debited",
         lambda f: _g(f, "failed_debited_payments") >= 1),
    Rule("exit_after_payment_failure", "payment_failure", "left right after a failed payment",
         lambda f: _g(f, "exit_after_payment_failure") == 1 and _g(f, "payment_failures") >= 1),
    # coupon_failure
    Rule("coupon_retry_x2", "coupon_failure", "2+ rejected coupon attempts",
         lambda f: _g(f, "coupon_failures") >= 2),
    Rule("exit_after_coupon_failure", "coupon_failure", "left right after a coupon was rejected",
         lambda f: _g(f, "exit_after_coupon_failure") == 1),
    # login_otp_issue
    Rule("otp_resend_x2", "login_otp_issue", "OTP resent 2+ times", lambda f: _g(f, "otp_resends") >= 2),
    Rule("otp_failed", "login_otp_issue", "OTP verification failed", lambda f: _g(f, "otp_failures") >= 1),
    Rule("exit_at_login_wall", "login_otp_issue", "left at the login wall without logging in",
         lambda f: _g(f, "exit_after_login") == 1 and _g(f, "login_successes") == 0),
    # technical_glitch
    Rule("rage_click_checkout", "technical_glitch", "rage clicks on checkout/payment pages",
         lambda f: _g(f, "rage_clicks_checkout") >= 1),
    Rule("js_error", "technical_glitch", "JavaScript/app error shown", lambda f: _g(f, "js_errors") >= 1),
    Rule("slow_load_x2", "technical_glitch", "2+ slow page loads or one load over 6 s",
         lambda f: _g(f, "slow_loads") >= 2 or _g(f, "max_load_ms") >= 6000),
    Rule("dead_click_x3", "technical_glitch", "3+ clicks with no response", lambda f: _g(f, "dead_clicks") >= 3),
    Rule("rage_click_x2", "technical_glitch", "2+ rage-click bursts", lambda f: _g(f, "rage_clicks") >= 2),
    # price_shock
    Rule("exit_after_total_shown", "price_shock", "left right after the order total was shown",
         lambda f: _g(f, "exit_after_total_shown") == 1),
    Rule("checkout_cart_loop", "price_shock", "went back from checkout to cart after seeing the total",
         lambda f: _g(f, "checkout_cart_loops") >= 1 and _g(f, "total_shown_count") >= 1),
    Rule("hidden_fees_shown", "price_shock", "extra fees appeared at checkout",
         lambda f: _g(f, "max_extra_fees") > 0),
    # unclear_product_info
    Rule("size_chart_x3", "unclear_product_info", "size chart opened 3+ times",
         lambda f: _g(f, "size_chart_opens") >= 3),
    Rule("spec_open_x3", "unclear_product_info", "specs opened 3+ times", lambda f: _g(f, "spec_opens") >= 3),
    Rule("pdp_compare_loop_x2", "unclear_product_info", "2+ product A-B-A comparison loops",
         lambda f: _g(f, "pdp_loops") >= 2),
    Rule("review_scan_x3", "unclear_product_info", "reviews opened 3+ times", lambda f: _g(f, "review_opens") >= 3),
    Rule("return_not_as_described", "unclear_product_info", "return because item differed from the listing",
         lambda f: _g(f, "info_mismatch_returns") >= 1),
    # delivery_uncertainty
    Rule("pincode_check_x3", "delivery_uncertainty", "delivery pincode checked 3+ times",
         lambda f: _g(f, "pincode_checks") >= 3),
    Rule("long_eta_exit", "delivery_uncertainty", "left after an ETA of 7+ days",
         lambda f: _g(f, "max_eta_days") >= 7 and _g(f, "exit_after_delivery_info") == 1),
    Rule("exit_after_delivery_info", "delivery_uncertainty", "left right after delivery info was shown",
         lambda f: _g(f, "exit_after_delivery_info") == 1),
    Rule("delivery_fee_revealed_late", "delivery_uncertainty", "delivery fee first shown at checkout",
         lambda f: _g(f, "fee_first_shown") >= 1),
    # poor_recommendations
    Rule("zero_result_search_x2", "poor_recommendations", "2+ searches with no results",
         lambda f: _g(f, "zero_result_searches") >= 2),
    Rule("search_reformulation_x3", "poor_recommendations", "3+ searches in one session",
         lambda f: _g(f, "searches") + _g(f, "zero_result_searches") >= 3),
    Rule("recs_ignored_x4", "poor_recommendations", "4+ recommendation slots shown, none clicked",
         lambda f: _g(f, "rec_impressions") >= 4 and _g(f, "rec_clicks") == 0),
    Rule("oos_recs_clicked", "poor_recommendations", "clicked 2+ recommendations that were out of stock",
         lambda f: _g(f, "oos_product_views") >= 2 and _g(f, "rec_clicks") >= 2),
    # out_of_stock
    Rule("size_unavailable_x2", "out_of_stock", "2+ clicks on unavailable sizes",
         lambda f: _g(f, "size_unavailable_clicks") >= 2),
    Rule("notify_me_clicked", "out_of_stock", "asked to be notified when back in stock",
         lambda f: _g(f, "notify_me") >= 1),
    Rule("cart_item_oos_removed", "out_of_stock", "cart item removed because it went out of stock",
         lambda f: _g(f, "oos_removals") >= 1),
    # post_purchase_concern
    Rule("tracking_view_x3", "post_purchase_concern", "order tracking checked 3+ times",
         lambda f: _g(f, "tracking_views") >= 3),
    Rule("order_cancelled", "post_purchase_concern", "order cancelled", lambda f: _g(f, "orders_cancelled") >= 1),
    Rule("refund_pending_check", "post_purchase_concern", "checked a pending refund",
         lambda f: _g(f, "refund_pending_views") >= 1),
    Rule("delayed_order_viewed", "post_purchase_concern", "tracking showed a delayed order",
         lambda f: _g(f, "delayed_status_views") >= 1),
    Rule("return_quality_issue", "post_purchase_concern", "return for damaged/defective/poor quality",
         lambda f: _g(f, "quality_returns") >= 1),
)
RULES_BY_NAME: dict[str, Rule] = {r.name: r for r in RULES}
RULE_FRICTION: dict[str, str] = {r.name: r.friction for r in RULES}


def evaluate_rules(features: Features) -> list[str]:
    """Names of every rule that fires, in RULES order (deterministic)."""
    return [r.name for r in RULES if r.check(features)]


def rule_frictions(flags: list[str]) -> list[str]:
    """Friction keys supported by the flags, in first-fired order, without duplicates."""
    seen: list[str] = []
    for flag in flags:
        friction = RULE_FRICTION.get(flag)
        if friction and friction not in seen:
            seen.append(friction)
    return seen
