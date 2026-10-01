"""One function per friction type. Each plants behaviour for its variant and, when the
customer does not leave, finishes the stage so the journey can continue.

Signature: fn(session, plan, will_exit, complete)
- will_exit: this friction is decisive and the customer leaves here.
- complete: this is the last friction at this stage, so it must finish the stage on recovery.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Callable

from datagen.catalog import reformulations, search_query, zero_result_query
from datagen.journey import (
    BROWSE, CART, COUPON, DELIVERY, LOGIN, NORMAL, PAYMENT, POST_PURCHASE_STAGES, PP_LOGIN,
    PP_RESOLVE, PP_TRACK, PRODUCT, SHOPPING_STAGES, SPEC_SECTIONS, TOTAL, FrictionPlan, Session,
    World, add_to_cart, cart_normal, compute_total, create_order, delivery_quote, force_delivered,
    force_undelivered, order_status_at, pay, pincode_check, product_normal, similar_product,
    start_session, total_normal, tracking_normal, view_product,
)
from datagen.text import TextSample, format_amount

# friction -> variant -> stage. Incident-only variants are injected, never sampled.
VARIANTS: dict[str, dict[str, int]] = {
    "unclear_product_info": {"size_chart_loop": PRODUCT, "spec_loop": PRODUCT, "comparison_loop": PRODUCT,
                             "review_scan_exit": PRODUCT, "not_as_described_return": PP_RESOLVE},
    "delivery_uncertainty": {"pincode_recheck": PRODUCT, "long_eta_exit": DELIVERY, "late_fee_reveal": DELIVERY,
                             "arrival_date_chat": DELIVERY, "courier_delay_incident": DELIVERY},
    "payment_failure": {"upi_timeout": PAYMENT, "card_declined": PAYMENT, "bank_3ds_failure": PAYMENT,
                        "netbanking_down": PAYMENT, "wallet_error": PAYMENT, "money_deducted": PAYMENT,
                        "gateway_incident": PAYMENT},
    "poor_recommendations": {"ignored_recs": BROWSE, "reformulated_search": BROWSE, "zero_results": BROWSE,
                             "oos_recs": BROWSE},
    "post_purchase_concern": {"wismo_tracking": PP_TRACK, "delayed_order": PP_TRACK, "cancellation": PP_RESOLVE,
                              "refund_delay": PP_RESOLVE, "quality_issue": PP_RESOLVE,
                              "courier_delay_wismo": PP_TRACK},
    "price_shock": {"exit_after_total": TOTAL, "back_to_cart": TOTAL, "cod_fee_shock": TOTAL,
                    "free_shipping_miss": TOTAL},
    "coupon_failure": {"expired_code": COUPON, "min_cart_not_met": COUPON, "category_excluded": COUPON,
                       "invalid_code": COUPON},
    "login_otp_issue": {"login_wall_exit": LOGIN, "otp_resend_loop": LOGIN, "otp_failed": LOGIN,
                        "otp_channel_switch": LOGIN, "tracking_login_otp": PP_LOGIN},
    "out_of_stock": {"size_unavailable": PRODUCT, "notify_me_exit": PRODUCT, "alternatives_ignored": PRODUCT,
                     "cart_item_oos": CART},
    "technical_glitch": {"slow_load_browse": BROWSE, "dead_click_product": PRODUCT,
                         "rage_click_checkout": TOTAL, "js_error_payment": PAYMENT,
                         "app_crash_android": CART, "tracking_page_glitch": PP_TRACK},
}
INCIDENT_VARIANTS = {"courier_delay_incident", "gateway_incident", "courier_delay_wismo"}

DEFAULT_THEME = {
    "unclear_product_info": "missing_info", "delivery_uncertainty": "delivery_delay",
    "payment_failure": "payment_trust", "poor_recommendations": "other",
    "post_purchase_concern": "delivery_delay", "price_shock": "price_fees", "coupon_failure": "price_fees",
    "login_otp_issue": "login_issue", "out_of_stock": "stock", "technical_glitch": "app_bug",
}
VARIANT_THEME = {
    "size_chart_loop": "size_fit", "late_fee_reveal": "price_fees", "money_deducted": "money_deducted",
    "oos_recs": "stock", "refund_delay": "return_refund", "quality_issue": "return_refund",
}
PAYMENT_VARIANTS = {
    "upi_timeout": ("UPI", ["timeout", "collect_request_expired", "upi_app_not_responding"]),
    "card_declined": ("card", ["card_declined", "insufficient_funds", "do_not_honour"]),
    "bank_3ds_failure": ("card", ["3ds_auth_failed", "otp_page_timeout"]),
    "netbanking_down": ("netbanking", ["bank_server_down", "session_expired"]),
    "wallet_error": ("wallet", ["wallet_timeout", "insufficient_balance"]),
    "money_deducted": ("UPI", ["timeout", "bank_timeout"]),
    "gateway_incident": ("", ["gateway_timeout", "gateway_5xx"]),
}
EXPIRED_CODES = ["DIWALI50", "SUMMER25", "MONSOON30", "NEWYEAR40"]
INVALID_CODES = ["SAV10", "WELCOM100", "FLAT 150", "FESTIVE-20", "FREESHP"]
JS_ERRORS = [
    "TypeError: Cannot read properties of undefined (reading 'amount')",
    "NetworkError: payment session request failed",
    "ChunkLoadError: Loading chunk payment-widget failed",
]


def kind_of(stage: int) -> str:
    return "post_purchase" if stage in POST_PURCHASE_STAGES else "shopping"


def theme_for(plan: FrictionPlan) -> str:
    return VARIANT_THEME.get(plan.variant, DEFAULT_THEME[plan.friction])


# --- text records -------------------------------------------------------------

def _slots(s: Session) -> dict[str, Any]:
    product = s.target or (s.cart[0]["product"] if s.cart else None)
    if s.last_payment is not None:
        amount = s.last_payment["amount"]
    elif s.pp_order is not None:
        amount = s.pp_order["order_value"]
    else:
        amount = max(s.cart_value, product["price"] if product else 499)
    sizes = product["sizes"] if product and product["sizes"] else ["M", "L", "UK8"]
    days = (s.t - s.pp_order["placed_at"]).days if s.pp_order is not None else s.randint(2, 9)
    return {
        "product": product["subcategory"] if product else "order",
        "amount": format_amount(amount, s.rng),
        "days": max(days, 2),
        "courier": s.pp_order["courier"] if s.pp_order is not None else s.courier,
        "size": (s.cart[0]["size"] if s.cart and s.cart[0]["size"] else s.pick(sizes)),
        "code": s.coupon_code or s.pick(list(s.cfg.pricing.coupons)),
        "method": s.method if s.method != "COD" else "UPI",
        "city": s.user.city,
        "fee": format_amount(s.delivery_fee or s.pick([49, 79, 99]), s.rng),
    }


def _related_ids(s: Session) -> tuple[str | None, str | None]:
    order = s.pp_order or s.order
    product = s.target or (s.cart[0]["product"] if s.cart else None)
    return (order["order_id"] if order else None, product["product_id"] if product else None)


def add_ticket(s: Session, sample: TextSample) -> None:
    order_id, product_id = _related_ids(s)
    created = min(s.t + timedelta(hours=float(s.rng.uniform(0.1, 30))), s.w.end)
    s.w.tables["tickets"].append({
        "ticket_id": s.w.next_id("t"), "session_id": s.session_id, "user_id": s.user.user_id,
        "order_id": order_id, "product_id": product_id, "created_at": created,
        "channel": s.pick(["app", "web_form", "email", "whatsapp"]), "text": sample.text,
        "language": sample.language, "theme_label": sample.theme,
        "secondary_theme_label": sample.secondary_theme, "sentiment": sample.sentiment, "tone": sample.tone,
        "status": s.pick(["open", "open", "resolved"]),
    })


def add_chat(s: Session, sample: TextSample) -> None:
    s.emit("chat_open", s.page)
    turns = s.w.text.chat_turns(sample)
    s.w.tables["chats"].append({
        "chat_id": s.w.next_id("c"), "session_id": s.session_id, "user_id": s.user.user_id,
        "started_at": s.t, "page": s.page, "transcript": json.dumps(turns, ensure_ascii=False),
        "customer_text": " ".join(t["text"] for t in turns if t["role"] == "customer"),
        "language": sample.language, "theme_label": sample.theme,
        "secondary_theme_label": sample.secondary_theme, "sentiment": sample.sentiment,
    })


def add_review(w: World, *, order: dict[str, Any], product_id: str, sample: TextSample, rating: int,
               created_at: Any, session_id: str | None) -> None:
    w.tables["reviews"].append({
        "review_id": w.next_id("r"), "session_id": session_id, "user_id": order["user_id"],
        "order_id": order["order_id"], "product_id": product_id, "created_at": created_at,
        "rating": rating, "text": sample.text, "language": sample.language, "theme_label": sample.theme,
        "secondary_theme_label": sample.secondary_theme, "sentiment": sample.sentiment,
    })
    w.reviewed_orders.add(order["order_id"])


def _text(s: Session, plan: FrictionPlan, theme: str | None = None, in_session: bool = True) -> None:
    tcfg = s.cfg.text
    theme = theme or theme_for(plan)
    overrides = tcfg.variant_overrides.get(plan.variant, {})
    slots = _slots(s)
    if in_session and s.chance(overrides.get("chat", tcfg.chat_prob[plan.friction])):
        add_chat(s, s.w.text.complaint(theme, slots))
    if s.chance(overrides.get("ticket", tcfg.ticket_prob[plan.friction])):
        add_ticket(s, s.w.text.complaint(theme, slots))
    p_review = overrides.get("review", 0.0)
    if p_review and s.pp_order is not None and s.chance(p_review):
        add_review(s.w, order=s.pp_order, product_id=s.pp_order["product_ids"][0],
                   sample=s.w.text.complaint(theme, slots, tone=s.pick(["angry", "neutral"])),
                   rating=s.randint(1, 2), created_at=s.t, session_id=s.session_id)


# --- recovery helpers ---------------------------------------------------------

def _login_success(s: Session) -> None:
    s.emit("login_success", wait=s.randint(10, 30), method="otp")
    s.logged_in = True


def _switch_and_pay(s: Session) -> None:
    s.method = s.pick([m for m in ("UPI", "card", "netbanking", "wallet", "COD") if m != s.method])
    s.gateway = s.pick([g for g in s.cfg.payments.gateway_mix if g != s.gateway])
    pay(s, s.method, ok=True)


# --- one function per friction type ------------------------------------------

def unclear_product_info(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    if plan.variant == "not_as_described_return":
        order = s.pp_order
        force_delivered(s, order)
        s.goto("order_tracking", order_id=order["order_id"])
        s.emit("tracking_view", order_id=order["order_id"], status="delivered")
        s.goto("returns", order_id=order["order_id"])
        sized_gap = bool(s.target["sizes"]) and not s.target["has_size_chart"]
        reason = "size_mismatch" if sized_gap or (s.target["sizes"] and s.chance(0.3)) else \
            s.pick(["not_as_described", "not_as_described", "colour_different"])
        s.emit("return_initiated", "returns", order_id=order["order_id"],
               product_id=s.target["product_id"], reason=reason)
        order.update(status="return_requested", return_reason=reason)
        _text(s, plan, "size_fit" if reason == "size_mismatch" else "missing_info")
        return

    p = s.target
    pid = p["product_id"]
    if plan.variant == "size_chart_loop":
        view_product(s, p)
        for i in range(s.randint(3, 5)):
            s.emit("size_chart_open", "product", wait=s.rng.uniform(15, 60), product_id=pid,
                   available=p["has_size_chart"])
            if s.chance(0.4):
                s.emit("review_open", "product", product_id=pid, review_page=i + 1, filter="size")
    elif plan.variant == "spec_loop":
        view_product(s, p)
        for i in range(s.randint(3, 5)):
            s.emit("spec_open", "product", wait=s.rng.uniform(12, 50), product_id=pid,
                   section=SPEC_SECTIONS[i % len(SPEC_SECTIONS)], missing_fields=len(p["missing_attributes"]))
        s.emit("review_open", "product", product_id=pid, review_page=1, filter="questions")
    elif plan.variant == "comparison_loop":
        other = similar_product(s, p)
        for i in range(s.randint(4, 7)):
            q = p if i % 2 == 0 else other
            view_product(s, q, wait=s.rng.uniform(20, 70))
            if q["sizes"] and s.chance(0.5):
                s.emit("size_chart_open", "product", product_id=q["product_id"], available=q["has_size_chart"])
            elif s.chance(0.5):
                s.emit("spec_open", "product", product_id=q["product_id"], section=s.pick(SPEC_SECTIONS))
    else:  # review_scan_exit
        view_product(s, p)
        for i in range(s.randint(3, 6)):
            s.emit("review_open", "product", wait=s.rng.uniform(20, 80), product_id=pid, review_page=i + 1,
                   filter=s.pick(["negative", "size", "quality", "recent"]))
    s.hesitate_page = "product"
    _text(s, plan)
    if not will_exit and complete:
        product_normal(s)


def delivery_uncertainty(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    v = plan.variant
    theme = None
    if v == "pincode_recheck":
        view_product(s, s.target)
        for i in range(s.randint(3, 5)):
            pincode_check(s, variant=i, extra_days=s.randint(0, 3))
        s.emit("delivery_info_view", "product", product_id=s.target["product_id"], **delivery_quote(s))
        s.hesitate_page = "product"
    else:
        s.goto("checkout_address")
        if v == "courier_delay_incident":
            info = delivery_quote(s)
        elif v == "long_eta_exit":
            info = delivery_quote(s, extra_days=s.randint(0, 3) if s.user.tier == "tier_3" else s.randint(2, 5))
        elif v == "arrival_date_chat":
            info = delivery_quote(s, extra_days=s.randint(1, 3))
        else:  # late_fee_reveal
            info = delivery_quote(s)
            s.delivery_fee = s.pick([49, 79, 99, 149])
            info.update(delivery_fee=s.delivery_fee, fee_first_shown=True)
            theme = "price_fees"
        if v != "late_fee_reveal":
            info["express_available"] = False
        s.emit("delivery_info_view", "checkout_delivery", **info)
        if v in ("long_eta_exit", "courier_delay_incident") or s.chance(0.4):
            pincode_check(s, variant=1)
        s.hesitate_page = "checkout_delivery"
    _text(s, plan, theme)
    if not will_exit and complete and v == "pincode_recheck":
        product_normal(s)


def payment_failure(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    method, errors = PAYMENT_VARIANTS[plan.variant]
    if plan.variant == "money_deducted":
        method = s.pick(["UPI", "card"])
    s.method = method or (s.method if s.method != "COD" else "UPI")
    s.goto("checkout_payment")
    deducted = plan.variant == "money_deducted"
    n_fail = s.randint(1, 2) if deducted else s.randint(2, 3)
    for i in range(n_fail):
        pay(s, s.method, ok=False, error=s.pick(errors), debited=deducted and i == n_fail - 1)
    _text(s, plan)
    if not will_exit and complete:
        _switch_and_pay(s)


def poor_recommendations(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    p = s.target
    if plan.variant == "ignored_recs":
        slots = [("home", "home_top"), ("home", "home_trending"), ("category", "category_top"),
                 ("category", "recently_viewed_based")]
        for page, slot in slots[: s.randint(3, 4)]:
            s.goto(page)
            s.emit("rec_impression", page, wait=s.rng.uniform(8, 30), slot=slot, n_items=8,
                   in_stock_items=s.randint(5, 8))
        unrelated = s.w.pick_product(lambda q: q["category"] != p["category"])
        if unrelated is not None:
            view_product(s, unrelated, wait=s.rng.uniform(20, 40))
            s.emit("page_view", "category", wait=s.rng.uniform(2, 6))
    elif plan.variant == "reformulated_search":
        for query in reformulations(p, s.rng, s.randint(3, 5)):
            s.emit("search", "search", wait=s.rng.uniform(8, 25), query=query, results_count=s.randint(2, 40))
            if s.chance(0.3):
                other = s.w.pick_product()
                if other is not None:
                    view_product(s, other, wait=s.rng.uniform(4, 10))
                    s.emit("page_view", "search", wait=s.rng.uniform(2, 5))
    elif plan.variant == "zero_results":
        for _ in range(s.randint(2, 3)):
            s.emit("search_zero_results", "search", wait=s.rng.uniform(6, 20), query=zero_result_query(p, s.rng))
        if s.chance(0.5):
            s.emit("search", "search", query=search_query(p, s.rng), results_count=s.randint(1, 5))
    else:  # oos_recs
        s.emit("rec_impression", "home", slot="home_top", n_items=8, in_stock_items=s.randint(1, 3))
        for _ in range(s.randint(2, 3)):
            oos = s.w.pick_product(lambda q: not q["in_stock"]) or s.w.pick_product()
            s.emit("rec_click", "home", product_id=oos["product_id"], slot="home_top", position=s.randint(1, 8))
            s.emit("product_view", "product", product_id=oos["product_id"], price=oos["price"],
                   category=oos["category"], in_stock=False, rating=oos["rating"])
            s.emit("page_view", "home", wait=s.rng.uniform(3, 10))
    _text(s, plan)
    if not will_exit and complete:
        s.emit("search", "search", query=search_query(p, s.rng), results_count=s.randint(8, 120))


def post_purchase_concern(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    order = s.pp_order
    oid = order["order_id"]
    theme = None
    v = plan.variant
    if v in ("wismo_tracking", "courier_delay_wismo", "delayed_order"):
        force_undelivered(s, order)
        s.goto("order_tracking", order_id=oid)
        repeats = s.randint(2, 3) if v == "delayed_order" else s.randint(3, 6)
        for _ in range(repeats):
            s.emit("tracking_view", "order_tracking", wait=s.rng.uniform(20, 120), order_id=oid,
                   status="delayed" if v == "delayed_order" else order_status_at(order, s.t),
                   last_update_hours=s.randint(48, 120), courier=order["courier"],
                   new_eta_days=s.randint(2, 5) if v == "delayed_order" else None)
        s.emit("help_view", "help", order_id=oid)
    elif v == "cancellation":
        force_undelivered(s, order)
        s.goto("order_tracking", order_id=oid)
        s.emit("tracking_view", "order_tracking", order_id=oid, status=order_status_at(order, s.t))
        reason = s.pick(["delivery_too_late", "delivery_too_late", "ordered_by_mistake", "found_cheaper"])
        s.emit("order_cancelled", "order_tracking", order_id=oid, reason=reason)
        order.update(status="cancelled", cancel_reason=reason, delivered_at=None,
                     refund_status="initiated" if order["payment_method"] != "COD" else "none")
        theme = "delivery_delay" if reason == "delivery_too_late" else "other"
    elif v == "refund_delay":
        force_delivered(s, order)
        order.update(status="returned", refund_status="pending",
                     return_reason=s.pick(["damaged", "size_mismatch", "poor_quality"]))
        s.goto("returns", order_id=oid)
        s.emit("tracking_view", "returns", order_id=oid, refund_status="pending",
               days_since_return=s.randint(6, 14))
        s.emit("help_view", "help", order_id=oid)
    else:  # quality_issue
        force_delivered(s, order)
        s.goto("order_tracking", order_id=oid)
        s.emit("tracking_view", "order_tracking", order_id=oid, status="delivered")
        s.goto("returns", order_id=oid)
        reason = s.pick(["damaged", "defective", "poor_quality"])
        s.emit("return_initiated", "returns", order_id=oid, product_id=order["product_ids"][0], reason=reason)
        order.update(status="return_requested", return_reason=reason)
    _text(s, plan, theme)


def price_shock(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    s.goto("checkout_summary")
    v = plan.variant
    if v in ("exit_after_total", "back_to_cart"):
        s.extra_fees["handling_fee"] = s.pick([49, 79, 99, 129, 149])
        if s.chance(0.5):
            s.delivery_fee = max(s.delivery_fee, s.pick([49, 79]))
    s.emit("total_shown", "checkout_summary", **compute_total(s))
    if v == "back_to_cart":
        s.emit("cart_view", "cart", n_items=len(s.cart), cart_value=s.cart_value)
        if len(s.cart) > 1 and s.chance(0.6):
            removed = s.cart.pop()
            s.emit("remove_from_cart", "cart", product_id=removed["product"]["product_id"], cart_value=s.cart_value)
        s.emit("checkout_start", "cart", cart_value=s.cart_value)
        s.goto("checkout_summary")
        s.emit("total_shown", "checkout_summary", **compute_total(s))
    elif v == "cod_fee_shock":
        s.method = "COD"
        s.extra_fees["cod_handling"] = s.pick([20, 40, 60])
        s.emit("total_shown", "checkout_summary", payment_method="COD", **compute_total(s))
    elif v == "free_shipping_miss":
        gap = s.cfg.pricing.free_shipping_threshold - s.cart_value
        s.emit("rec_impression", "checkout_summary", slot="free_shipping_nudge", n_items=4,
               in_stock_items=s.randint(2, 4), free_shipping_gap=max(gap, 0))
    s.exit_wait = s.rng.uniform(2, 10)
    _text(s, plan)
    if not will_exit and complete and v == "cod_fee_shock":
        s.method = s.pick(["UPI", "card"])
        s.extra_fees.pop("cod_handling", None)


def coupon_failure(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    s.goto("checkout_summary")
    v = plan.variant
    coupons = s.cfg.pricing.coupons
    for attempt in range(1, s.randint(2, 4) + 1):
        extra: dict[str, Any] = {}
        if v == "expired_code":
            code, reason = s.pick(EXPIRED_CODES), "expired"
        elif v == "min_cart_not_met":
            above = [c for c, spec in coupons.items() if spec.get("min_cart", 0) > s.cart_value]
            code, reason = (s.pick(above) if above else "FESTIVE20"), "min_cart_value"
            extra = {"min_cart": coupons.get(code, {}).get("min_cart", 1499), "cart_value": s.cart_value}
        elif v == "category_excluded":
            code, reason = s.pick(list(coupons)), "not_applicable_category"
            extra = {"category": (s.cart[0]["product"]["category"] if s.cart else "apparel")}
        else:
            code, reason = s.pick(INVALID_CODES), "invalid_code"
        s.emit("coupon_apply", "checkout_summary", wait=s.rng.uniform(5, 25), code=code, attempt=attempt)
        s.emit("coupon_failed", "checkout_summary", code=code, reason=reason, **extra)
        s.coupon_code = code
    _text(s, plan)


def login_otp_issue(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    s.logged_in = False
    page = "order_tracking" if plan.stage == PP_LOGIN else "checkout_login"
    v = plan.variant
    s.emit("login_wall", page, guest_checkout=False)
    if v == "login_wall_exit":
        s.exit_wait = s.rng.uniform(3, 15)
    else:
        s.emit("otp_sent", page, channel="sms")
        if v in ("otp_resend_loop", "tracking_login_otp"):
            for i in range(s.randint(2, 4)):
                s.emit("otp_resend", page, wait=s.rng.uniform(30, 75), channel="sms", attempt=i + 2)
        if v in ("otp_failed", "tracking_login_otp"):
            for i in range(s.randint(1, 3)):
                s.emit("otp_failed", page, wait=s.rng.uniform(20, 60),
                       reason=s.pick(["invalid", "expired"]), attempt=i + 1)
        if v == "otp_channel_switch":
            s.emit("otp_resend", page, wait=s.rng.uniform(30, 60), channel="sms", attempt=2)
            s.emit("otp_sent", page, wait=s.rng.uniform(5, 15), channel=s.pick(["whatsapp", "email"]))
    _text(s, plan)
    if not will_exit and complete:
        if v == "login_wall_exit":
            s.emit("otp_sent", page, channel="sms")
        _login_success(s)


def out_of_stock(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    p = s.target
    v = plan.variant
    if v == "cart_item_oos":
        s.emit("cart_view", "cart", n_items=len(s.cart), cart_value=s.cart_value, oos_items=1)
        item = s.cart.pop(0)
        s.emit("remove_from_cart", "cart", product_id=item["product"]["product_id"], reason="out_of_stock",
               cart_value=s.cart_value)
        s.emit("rec_impression", "cart", slot="similar_in_stock", n_items=6, in_stock_items=s.randint(4, 6))
        _text(s, plan)
        if not will_exit:
            if not s.cart:  # never continue to checkout with an empty cart
                alt = similar_product(s, item["product"])
                view_product(s, alt)
                add_to_cart(s, alt)
            if complete:
                cart_normal(s)
        return

    zero = [size for size, qty in p["stock"].items() if qty == 0 and size != "ONE"] or ["M"]
    view_product(s, p)
    if v in ("size_unavailable", "alternatives_ignored"):
        for _ in range(s.randint(2, 4) if v == "size_unavailable" else s.randint(1, 2)):
            s.emit("size_unavailable_click", "product", wait=s.rng.uniform(3, 15), product_id=p["product_id"],
                   size=s.pick(zero))
    if v == "notify_me_exit" or (v == "size_unavailable" and s.chance(0.4)):
        s.emit("notify_me", "product", product_id=p["product_id"], size=s.pick(zero) if p["sizes"] else None)
    if v in ("notify_me_exit", "alternatives_ignored"):
        s.emit("rec_impression", "product", slot="similar_in_stock", n_items=6, in_stock_items=s.randint(4, 6))
    if v == "alternatives_ignored":
        view_product(s, similar_product(s, p), wait=s.rng.uniform(5, 15))
        view_product(s, p, wait=s.rng.uniform(3, 8))
    _text(s, plan)
    if not will_exit and complete:
        if not p["in_stock"]:
            s.target = similar_product(s, p)
        product_normal(s)


def technical_glitch(s: Session, plan: FrictionPlan, will_exit: bool, complete: bool) -> None:
    v = plan.variant
    if v == "slow_load_browse":
        page = s.pick(["category", "search"])
        s.emit("page_view", page)
        for _ in range(s.randint(2, 3)):
            s.emit("slow_load", page, load_ms=s.randint(6000, 15000),
                   resource=s.pick(["product_grid", "images", "search_api"]))
        if s.chance(0.5):
            s.emit("rage_click", page, element="filter_button", clicks=s.randint(4, 7), window_ms=s.randint(800, 2000))
    elif v == "dead_click_product":
        view_product(s, s.target)
        for _ in range(s.randint(3, 5)):
            s.emit("dead_click", "product", product_id=s.target["product_id"],
                   element=s.pick(["size_selector", "add_to_cart_btn", "image_gallery"]))
        s.emit("rage_click", "product", product_id=s.target["product_id"], element="add_to_cart_btn",
               clicks=s.randint(4, 8), window_ms=s.randint(800, 2000))
    elif v == "rage_click_checkout":
        s.goto("checkout_summary")
        for _ in range(s.randint(2, 3)):
            s.emit("rage_click", "checkout_summary", element=s.pick(["continue_btn", "place_order_btn"]),
                   clicks=s.randint(4, 9), window_ms=s.randint(800, 2000))
        if s.chance(0.4):
            s.emit("js_error", "checkout_summary", component="checkout_summary",
                   message="TypeError: Cannot read properties of undefined (reading 'total')")
    elif v == "js_error_payment":
        s.goto("checkout_payment")
        for _ in range(s.randint(1, 2)):
            s.emit("js_error", "checkout_payment", component="payment_widget", message=s.pick(JS_ERRORS))
        s.emit("dead_click", "checkout_payment", element="pay_now_btn")
    elif v == "app_crash_android":
        s.emit("cart_view", "cart", n_items=len(s.cart), cart_value=s.cart_value)
        s.emit("js_error", "cart", component="cart_screen", message="ANR: application not responding",
               fatal=True, app_version=s.app_version)
        s.emit("slow_load", "cart", load_ms=s.randint(8000, 20000), resource="cart_api")
    else:  # tracking_page_glitch
        order = s.pp_order
        s.goto("order_tracking", order_id=order["order_id"])
        s.emit("slow_load", "order_tracking", load_ms=s.randint(8000, 20000), resource="tracking_api")
        s.emit("js_error", "order_tracking", component="tracking_widget", message="NetworkError: tracking request failed")
        s.emit("rage_click", "order_tracking", element="track_button", clicks=s.randint(4, 8), window_ms=s.randint(800, 2000))
    _text(s, plan)
    if will_exit or not complete:
        return
    if v == "dead_click_product":
        product_normal(s)
    elif v == "rage_click_checkout":
        total_normal(s)
    elif v == "js_error_payment":
        pay(s, s.method, ok=True)
    elif v == "app_crash_android":
        cart_normal(s)
    elif v == "tracking_page_glitch":
        tracking_normal(s)


SCENARIOS: dict[str, Callable[[Session, FrictionPlan, bool, bool], None]] = {
    "unclear_product_info": unclear_product_info,
    "delivery_uncertainty": delivery_uncertainty,
    "payment_failure": payment_failure,
    "poor_recommendations": poor_recommendations,
    "post_purchase_concern": post_purchase_concern,
    "price_shock": price_shock,
    "coupon_failure": coupon_failure,
    "login_otp_issue": login_otp_issue,
    "out_of_stock": out_of_stock,
    "technical_glitch": technical_glitch,
}


# --- session setup -------------------------------------------------------------

def _target_predicates(s: Session) -> list[Callable[[dict[str, Any]], bool]]:
    preds: list[Callable[[dict[str, Any]], bool]] = []
    missing = s.w.missing_size_ids
    for plan in s.plans:
        v = plan.variant
        if v == "size_chart_loop":
            if s.chance(s.cfg.incidents.missing_size_info.pick_prob):
                plan.incident_id = s.cfg.incidents.missing_size_info.id
                preds.append(lambda p: p["product_id"] in missing)
            else:
                preds.append(lambda p: bool(p["sizes"]) and p["in_stock"])
        elif v == "spec_loop":
            preds.append(lambda p: p["category"] in ("electronics", "home_kitchen") and p["spec_completeness"] < 1)
        elif v in ("size_unavailable", "alternatives_ignored"):
            preds.append(lambda p: p["in_stock"] and any(q == 0 for q in p["stock"].values()))
        elif v == "notify_me_exit":
            preds.append(lambda p: not p["in_stock"])
        elif v == "free_shipping_miss":
            preds.append(lambda p: p["in_stock"] and p["price"] < s.cfg.pricing.free_shipping_threshold - 20)
        elif v == "min_cart_not_met":
            preds.append(lambda p: p["in_stock"] and p["price"] < 1300)
    return preds


def choose_target(s: Session) -> None:
    preds = _target_predicates(s)
    target = None
    if preds:
        target = s.w.pick_product(lambda p: all(f(p) for f in preds)) or s.w.pick_product(preds[-1])
    if target is None:
        target = s.w.pick_product(lambda p: p["in_stock"])
    for plan in s.plans:  # an incident label only holds if the product really lacks a size chart
        if plan.variant == "size_chart_loop" and target["product_id"] not in s.w.missing_size_ids:
            plan.incident_id = None
    s.target = target


def _order_candidates(s: Session, pool: list[dict[str, Any]], min_age_days: float) -> list[dict[str, Any]]:
    cutoff = s.t - timedelta(days=min_age_days)
    return [o for o in pool if o["placed_at"] < cutoff and o["order_id"] not in s.w.used_orders
            and o["status"] not in ("cancelled", "returned", "return_requested")]


def prepare_post_purchase(s: Session) -> None:
    w, incidents = s.w, s.cfg.incidents
    order = None
    for plan in s.plans:
        if order is not None:  # one order per session; the first plan that picks one keeps its label
            break
        if plan.friction == "post_purchase_concern" and s.chance(incidents.courier_delay.wismo_share):
            cands = _order_candidates(s, w.incident_orders, 1)
            if cands:
                order = s.pick(cands)
                plan.variant, plan.stage = "courier_delay_wismo", PP_TRACK
                plan.incident_id = incidents.courier_delay.id
        elif plan.variant == "not_as_described_return" and s.chance(incidents.missing_size_info.pick_prob):
            missing = w.missing_size_ids
            pool = [o for o in w.tables["orders"] if o["product_ids"] and o["product_ids"][0] in missing]
            cands = _order_candidates(s, pool, 2)
            if cands:
                order = s.pick(cands)
                plan.incident_id = incidents.missing_size_info.id

    if order is not None and order["user_id"] != s.user.user_id:
        s.user = w.users_by_id[order["user_id"]]
    if order is None:
        own = _order_candidates(s, w.user_orders[s.user.user_id], 2)
        order = own[-1] if own else _historical_order(s)
    if s.plans:
        w.used_orders.add(order["order_id"])
    s.pp_order = order
    s.courier = order["courier"]
    s.target = w.by_id[order["product_ids"][0]]


def _historical_order(s: Session) -> dict[str, Any]:
    product = s.w.pick_product(lambda p: p["in_stock"])
    placed = s.t - timedelta(days=float(s.rng.uniform(3, 12)))
    return create_order(
        s.w, session_id=None, user=s.user, placed_at=placed, product_ids=[product["product_id"]],
        order_value=product["price"] + s.cfg.pricing.platform_fee, payment_method=s.method,
        courier=s.courier, eta=s.cfg.couriers.base_eta_days[s.user.tier],
    )


def assign_decisive(plans: list[FrictionPlan]) -> None:
    plans.sort(key=lambda p: p.stage)
    for i, plan in enumerate(plans):
        plan.decisive = i == len(plans) - 1


def _apply_incidents(s: Session, stage: int) -> None:
    incidents = s.cfg.incidents
    day = s.w.day_number(s.t)
    if stage == PRODUCT:
        ms = incidents.missing_size_info
        has_info_plan = any(p.friction == "unclear_product_info" for p in s.plans)
        if (s.target is not None and s.target["product_id"] in s.w.missing_size_ids and not has_info_plan
                and len(s.plans) < 2 and s.chance(ms.affect_prob)):
            s.plans.append(FrictionPlan("unclear_product_info", "size_chart_loop", PRODUCT, ms.id))
            assign_decisive(s.plans)
    elif stage == DELIVERY:
        cd = incidents.courier_delay
        if s.courier == cd.courier and s.user.city in cd.cities and day in cd.days:
            s.eta_extra = cd.extra_eta_days
            has_delivery = any(p.friction == "delivery_uncertainty" for p in s.plans)
            if not has_delivery and len(s.plans) < 2 and s.chance(cd.affect_prob):
                s.plans.append(FrictionPlan("delivery_uncertainty", "courier_delay_incident", DELIVERY, cd.id))
                assign_decisive(s.plans)
    elif stage == PAYMENT:
        go = incidents.gateway_outage
        in_window = day == go.day and go.start_hour <= s.t.hour < go.start_hour + go.hours
        if in_window and s.method != "COD" and s.gateway == go.gateway:
            existing = [p for p in s.plans if p.friction == "payment_failure"]
            for plan in existing:
                plan.incident_id = go.id
            if not existing and len(s.plans) < 2 and s.chance(go.fail_rate):
                s.plans.append(FrictionPlan("payment_failure", "gateway_incident", PAYMENT, go.id))
                assign_decisive(s.plans)


def _run_stage(s: Session, stage: int) -> bool:
    plans = s.plans_at(stage)
    if not plans:
        return NORMAL[stage](s)
    for i, plan in enumerate(plans):
        recovery = s.cfg.friction.in_session_recovery[plan.friction]
        will_exit = plan.decisive and not s.chance(recovery)
        SCENARIOS[plan.friction](s, plan, will_exit, i == len(plans) - 1)
        if will_exit:
            return True
    return False


def _clean_text(s: Session) -> None:
    if not s.is_clean:
        return
    tcfg = s.cfg.text
    if s.chance(tcfg.chat_prob["clean"]):
        add_chat(s, s.w.text.neutral_query(_slots(s)))
    if s.chance(tcfg.ticket_prob["clean"]):
        add_ticket(s, s.w.text.neutral_query(_slots(s)))


def run_session(s: Session) -> None:
    if s.kind == "post_purchase":
        prepare_post_purchase(s)
    else:
        choose_target(s)
    last_end = s.w.user_last_end.get(s.user.user_id)
    if last_end is not None and s.t < last_end + timedelta(minutes=31):
        s.t = last_end + timedelta(minutes=31 + s.randint(0, 240))
    assign_decisive(s.plans)

    start_session(s)
    stages = POST_PURCHASE_STAGES if s.kind == "post_purchase" else SHOPPING_STAGES
    for stage in stages:
        _apply_incidents(s, stage)
        if _run_stage(s, stage):
            s.exited_at_stage = stage
            break
    _clean_text(s)
    if not s.chance(s.cfg.data_quality.missing_exit_rate):
        s.emit("exit", s.page, wait=s.exit_wait if s.exit_wait is not None else s.dwell(s.page))
    s.w.user_last_end[s.user.user_id] = s.t
