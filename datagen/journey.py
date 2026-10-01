"""Session builder, shared world state and the normal (friction-free) journey steps.

Friction scenarios in scenarios.py reuse these steps and replace one stage each.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np

from datagen.catalog import eta_days, search_query
from datagen.config import DatagenConfig
from datagen.text import TextGenerator

# Journey stages, in order. Post-purchase sessions use the PP_* stages.
BROWSE, PRODUCT, CART, LOGIN, DELIVERY, COUPON, TOTAL, PAYMENT, ORDER = range(9)
PP_LOGIN, PP_TRACK, PP_RESOLVE = 10, 11, 12
SHOPPING_STAGES = (BROWSE, PRODUCT, CART, LOGIN, DELIVERY, COUPON, TOTAL, PAYMENT, ORDER)
POST_PURCHASE_STAGES = (PP_LOGIN, PP_TRACK, PP_RESOLVE)

PAGE_DWELL_S = {
    "home": 18, "search": 14, "category": 22, "product": 45, "cart": 20,
    "checkout_login": 25, "checkout_address": 30, "checkout_delivery": 20,
    "checkout_summary": 22, "checkout_payment": 28, "order_confirmation": 10,
    "order_tracking": 20, "returns": 35, "help": 40,
}
SPEC_SECTIONS = ["specifications", "warranty", "compatibility", "in_the_box", "dimensions"]
TRANSIENT_ERRORS = {
    "UPI": ["timeout", "upi_app_not_responding"],
    "card": ["bank_timeout", "card_declined"],
    "netbanking": ["session_expired"],
    "wallet": ["wallet_timeout"],
}
INVALID_CODES = ["SAV10", "WELCOM100", "FLAT 150", "FESTIVE-20", "FREESHP"]


@dataclass
class User:
    raw_id: str
    user_id: str
    city: str
    tier: str
    device: str
    app_version: str | None
    is_new: bool


@dataclass
class FrictionPlan:
    friction: str
    variant: str
    stage: int
    incident_id: str | None = None
    decisive: bool = False


@dataclass
class World:
    cfg: DatagenConfig
    rng: np.random.Generator
    text: TextGenerator
    products: list[dict[str, Any]]
    popularity: np.ndarray
    tiers: dict[str, str]
    city_courier: dict[str, str]
    start: datetime
    end: datetime
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    users_by_id: dict[str, User] = field(default_factory=dict)
    tables: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {k: [] for k in ("events", "payments", "orders", "tickets", "reviews", "chats")}
    )
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    user_orders: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    incident_orders: list[dict[str, Any]] = field(default_factory=list)
    used_orders: set[str] = field(default_factory=set)
    reviewed_orders: set[str] = field(default_factory=set)
    user_last_end: dict[str, datetime] = field(default_factory=dict)

    @property
    def missing_size_ids(self) -> set[str]:
        return {p["product_id"] for p in self.products if p["sizes"] and not p["has_size_chart"]}

    def next_id(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}_{self.counters[prefix]:06d}"

    def day_number(self, t: datetime) -> int:
        return (t.date() - self.cfg.start_date).days + 1

    def pick_product(
        self,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any] | None:
        idx = [
            i for i, p in enumerate(self.products)
            if (predicate is None or predicate(p)) and (not exclude or p["product_id"] not in exclude)
        ]
        if not idx:
            return None
        weights = self.popularity[idx] / self.popularity[idx].sum()
        return self.products[int(self.rng.choice(idx, p=weights))]


def _py(value: Any) -> Any:
    return value.item() if isinstance(value, np.generic) else value


@dataclass
class Session:
    w: World
    session_id: str
    user: User
    t: datetime
    kind: str
    plans: list[FrictionPlan]
    device: str
    app_version: str | None
    source: str
    courier: str
    logged_in: bool
    bank: str
    noise: set[str] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    page: str | None = None
    cart: list[dict[str, Any]] = field(default_factory=list)
    target: dict[str, Any] | None = None
    reached_cart: bool = False
    converted: bool = False
    order: dict[str, Any] | None = None
    pp_order: dict[str, Any] | None = None
    method: str = "UPI"
    gateway: str | None = "A"
    attempts: int = 0
    last_payment: dict[str, Any] | None = None
    eta: int | None = None
    eta_extra: int = 0
    delivery_fee: int = 0
    discount: int = 0
    coupon_code: str | None = None
    extra_fees: dict[str, int] = field(default_factory=dict)
    hesitate_page: str | None = None
    exit_wait: float | None = None
    exited_at_stage: int | None = None

    # --- randomness helpers ----------------------------------------------
    @property
    def rng(self) -> np.random.Generator:
        return self.w.rng

    @property
    def cfg(self) -> DatagenConfig:
        return self.w.cfg

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def pick(self, seq: list[Any] | tuple[Any, ...]) -> Any:
        return seq[int(self.rng.integers(len(seq)))]

    def randint(self, low: int, high: int) -> int:
        return int(self.rng.integers(low, high + 1))

    # --- state -------------------------------------------------------------
    @property
    def is_clean(self) -> bool:
        return not self.plans

    @property
    def cart_value(self) -> int:
        return int(sum(item["price"] for item in self.cart))

    def plans_at(self, stage: int) -> list[FrictionPlan]:
        return [p for p in self.plans if p.stage == stage]

    # --- event emission ---------------------------------------------------
    def dwell(self, page: str | None) -> float:
        base = PAGE_DWELL_S.get(page or "home", 20) * float(self.rng.lognormal(0, 0.45))
        if page is not None and page == self.hesitate_page:
            base *= float(self.rng.uniform(3, 6))
        return min(base, 900.0)

    def emit(
        self,
        event: str,
        page: str | None = None,
        *,
        wait: float | None = None,
        product_id: str | None = None,
        order_id: str | None = None,
        **metadata: Any,
    ) -> None:
        page = page or self.page or "home"
        if wait is None:
            wait = self.dwell(self.page) if self.page and page != self.page else float(self.rng.uniform(2, 9))
        self.t += timedelta(seconds=max(1, int(wait)))
        self.page = page
        self.events.append({
            "session_id": self.session_id,
            "user_id": self.user.user_id,
            "timestamp": self.t,
            "event": event,
            "page": page,
            "product_id": product_id,
            "order_id": order_id,
            "metadata": {k: _py(v) for k, v in metadata.items() if v is not None},
        })

    def goto(self, page: str, **metadata: Any) -> None:
        if self.page != page:
            self.emit("page_view", page, **metadata)


# --- small shared helpers ---------------------------------------------------

def pincode_prefix(city: str, variant: int = 0) -> str:
    return str((sum(map(ord, city)) * 7 + variant * 13) % 900 + 100)


def similar_product(s: Session, product: dict[str, Any], in_stock: bool = True) -> dict[str, Any]:
    found = s.w.pick_product(
        lambda p: p["subcategory"] == product["subcategory"] and (p["in_stock"] or not in_stock),
        exclude={product["product_id"]},
    )
    return found or s.w.pick_product(lambda p: p["in_stock"], exclude={product["product_id"]}) or product


def available_sizes(product: dict[str, Any]) -> list[str]:
    return [size for size, qty in product["stock"].items() if qty > 0 and size != "ONE"]


def view_product(s: Session, product: dict[str, Any], wait: float | None = None) -> None:
    s.emit("product_view", "product", wait=wait, product_id=product["product_id"], price=product["price"],
           category=product["category"], in_stock=product["in_stock"], rating=product["rating"])


def add_to_cart(s: Session, product: dict[str, Any], size: str | None = None) -> None:
    sizes = available_sizes(product)
    size = size or (s.pick(sizes) if sizes else None)
    s.cart.append({"product": product, "size": size, "price": product["price"]})
    s.reached_cart = True
    s.emit("add_to_cart", "product", product_id=product["product_id"], size=size, qty=1,
           price=product["price"], cart_value=s.cart_value)


def pincode_check(s: Session, variant: int = 0, extra_days: int = 0) -> None:
    product = s.target or s.cart[0]["product"]
    eta = eta_days(s.cfg, s.user.tier, s.user.city, s.courier, product["warehouse_city"]) + extra_days + s.eta_extra
    s.emit("pincode_check", s.page, product_id=product["product_id"],
           pincode_prefix=pincode_prefix(s.user.city, variant), eta_days=eta, deliverable=True)


def delivery_quote(s: Session, extra_days: int = 0) -> dict[str, Any]:
    warehouse = (s.cart[0]["product"] if s.cart else s.target)["warehouse_city"]
    eta = eta_days(s.cfg, s.user.tier, s.user.city, s.courier, warehouse) + s.eta_extra + extra_days
    fee = 0 if s.cart_value >= s.cfg.pricing.free_shipping_threshold else s.cfg.pricing.shipping_fee
    s.eta, s.delivery_fee = eta, fee
    return {"eta_days": eta, "delivery_fee": fee, "courier": s.courier,
            "express_available": eta > 3 and s.user.tier != "tier_3", "express_fee": s.cfg.couriers.express_fee}


def compute_total(s: Session) -> dict[str, Any]:
    pricing = s.cfg.pricing
    subtotal = s.cart_value
    cod_fee = pricing.cod_fee if s.method == "COD" else 0
    extra = sum(s.extra_fees.values())
    total = subtotal + s.delivery_fee + pricing.platform_fee + cod_fee + extra - s.discount
    breakdown: dict[str, Any] = {
        "subtotal": subtotal, "shipping": s.delivery_fee, "platform_fee": pricing.platform_fee,
        "cod_fee": cod_fee, "discount": s.discount, **s.extra_fees, "total": total,
        "delta_pct": round((total - subtotal) / max(subtotal, 1) * 100, 1),
    }
    return breakdown


def best_coupon(s: Session) -> tuple[str | None, int]:
    best: tuple[str | None, int] = (None, 0)
    for code, spec in s.cfg.pricing.coupons.items():
        if s.cart_value < spec.get("min_cart", 0):
            continue
        discount = spec.get("discount", 0) or min(s.cart_value * spec.get("discount_pct", 0) // 100, 300)
        if discount > best[1]:
            best = (code, int(discount))
    return best


def pay(s: Session, method: str, ok: bool, error: str | None = None, debited: bool = False) -> dict[str, Any]:
    gateway = None if method == "COD" else s.gateway
    bank = s.bank if method in ("card", "netbanking") else None
    amount = compute_total(s)["total"]
    s.attempts += 1
    s.emit("payment_attempt", "checkout_payment", method=method, gateway=gateway, bank=bank,
           amount=amount, attempt=s.attempts)
    slow = error is not None and "timeout" in error
    latency = int(s.rng.uniform(15000, 45000)) if slow else int(s.rng.lognormal(7.3, 0.4))
    if ok:
        s.emit("payment_success", wait=latency / 1000, method=method, gateway=gateway, amount=amount)
    else:
        s.emit("payment_failed", wait=latency / 1000, method=method, gateway=gateway, error=error,
               attempt=s.attempts)
    row = {
        "payment_id": s.w.next_id("pay"), "session_id": s.session_id, "user_id": s.user.user_id,
        "order_id": None, "timestamp": s.t, "method": method, "gateway": gateway, "bank": bank,
        "amount": amount, "status": "success" if ok else "failed", "error_code": error,
        "latency_ms": latency, "amount_debited": (ok and method != "COD") or debited,
        "refund_status": "pending" if debited and not ok else "none",
    }
    s.w.tables["payments"].append(row)
    s.last_payment = row
    return row


# --- orders -----------------------------------------------------------------

def set_expected_delivery(w: World, order: dict[str, Any], expected: datetime) -> None:
    order["delay_days"] = max(0, (expected - order["promised_delivery_at"]).days)
    if expected <= w.end:
        order["delivered_at"], order["status"] = expected, "delivered"
    else:
        order["delivered_at"] = None
        order["status"] = "delayed" if w.end > order["promised_delivery_at"] else "in_transit"


def create_order(
    w: World,
    *,
    session_id: str | None,
    user: User,
    placed_at: datetime,
    product_ids: list[str],
    order_value: int,
    payment_method: str,
    courier: str,
    eta: int,
) -> dict[str, Any]:
    cfg, rng = w.cfg, w.rng
    incident = cfg.incidents.courier_delay
    in_scope = (courier == incident.courier and user.city in incident.cities
                and w.day_number(placed_at) in incident.days)
    if in_scope:
        delay = int(rng.integers(incident.order_delay_days[0], incident.order_delay_days[1] + 1))
    elif rng.random() > cfg.couriers.on_time_rate:
        delay = int(rng.integers(1, 4))
    else:
        delay = 0
    promised = placed_at + timedelta(days=eta)
    order: dict[str, Any] = {
        "order_id": w.next_id("o"), "session_id": session_id, "user_id": user.user_id,
        "placed_at": placed_at, "product_ids": product_ids, "n_items": len(product_ids),
        "order_value": order_value, "payment_method": payment_method, "city": user.city,
        "city_tier": user.tier, "courier": courier, "promised_delivery_at": promised,
        "delivered_at": None, "status": "in_transit", "delay_days": 0,
        "cancel_reason": None, "return_reason": None, "refund_status": "none",
    }
    # Non-negative hour jitter keeps delay_days equal to the planned whole-day delay.
    set_expected_delivery(w, order, promised + timedelta(days=delay, hours=float(rng.uniform(0, 10))))
    w.tables["orders"].append(order)
    w.user_orders[user.user_id].append(order)
    if in_scope:
        w.incident_orders.append(order)
    return order


def order_status_at(order: dict[str, Any], t: datetime) -> str:
    if order["status"] in ("cancelled", "returned", "return_requested"):
        return order["status"]
    if order["delivered_at"] is not None and order["delivered_at"] <= t:
        return "delivered"
    return "delayed" if t > order["promised_delivery_at"] else "in_transit"


def force_undelivered(s: Session, order: dict[str, Any]) -> None:
    """Make sure the order has not arrived by the time of this session.

    delivered_at=None already means "not delivered by the end of the window", so it is left alone.
    """
    if order["delivered_at"] is not None and order["delivered_at"] <= s.t + timedelta(hours=12):
        set_expected_delivery(s.w, order, s.t + timedelta(days=s.randint(1, 5), hours=s.randint(1, 20)))


def force_delivered(s: Session, order: dict[str, Any]) -> None:
    if order["delivered_at"] is None or order["delivered_at"] > s.t:
        earliest = order["placed_at"] + timedelta(days=1)
        delivered = max(earliest, s.t - timedelta(days=float(s.rng.uniform(0.5, 3))))
        order["delivered_at"], order["status"] = delivered, "delivered"


def place_order(s: Session) -> None:
    if s.eta is None:
        delivery_quote(s)
    total = compute_total(s)
    order = create_order(
        s.w, session_id=s.session_id, user=s.user, placed_at=s.t,
        product_ids=[item["product"]["product_id"] for item in s.cart],
        order_value=total["total"], payment_method=s.method, courier=s.courier, eta=s.eta or 3,
    )
    if s.last_payment is not None and s.last_payment["status"] == "success":
        s.last_payment["order_id"] = order["order_id"]
    s.emit("order_placed", "checkout_payment", order_id=order["order_id"], order_value=total["total"],
           n_items=len(s.cart), payment_method=s.method)
    s.emit("page_view", "order_confirmation", order_id=order["order_id"])
    s.converted, s.order = True, order


# --- normal stage steps (return True when a clean session exits here) -------

def start_session(s: Session) -> None:
    s.emit("page_view", "home", wait=0, device=s.device, app_version=s.app_version, city=s.user.city,
           city_tier=s.user.tier, source=s.source, is_logged_in=s.logged_in)


def browse_normal(s: Session) -> bool:
    if "slow_load" in s.noise:
        s.emit("slow_load", "home", load_ms=s.randint(3000, 5500), resource="home_feed")
    s.emit("rec_impression", "home", slot="home_top", n_items=8, in_stock_items=s.randint(6, 8))
    p = s.target
    roll = s.rng.random()
    if roll < 0.5:
        s.emit("search", "search", query=search_query(p, s.rng), results_count=s.randint(8, 240))
    elif roll < 0.8:
        s.emit("page_view", "category", category=p["category"])
    else:
        s.emit("rec_click", "home", product_id=p["product_id"], slot="home_top", position=s.randint(1, 8))
    if "ignored_recs" in s.noise:
        s.emit("rec_impression", s.page, slot="browse_feed", n_items=8, in_stock_items=s.randint(5, 8))
    return s.is_clean and s.chance(s.cfg.clean.bounce_rate)


def product_normal(s: Session) -> bool:
    p = s.target
    view_product(s, p)
    if "comparison" in s.noise:
        view_product(s, similar_product(s, p))
        view_product(s, p)
    if p["sizes"] and s.chance(0.35):
        s.emit("size_chart_open", "product", product_id=p["product_id"], available=p["has_size_chart"])
    if p["category"] in ("electronics", "home_kitchen") and s.chance(0.3):
        s.emit("spec_open", "product", product_id=p["product_id"], section=s.pick(SPEC_SECTIONS))
    if s.chance(0.3):
        s.emit("review_open", "product", product_id=p["product_id"], review_page=1, filter="recent")
    if s.chance(0.2) or "extra_pincode_check" in s.noise:
        pincode_check(s)
    if "dead_click" in s.noise:
        s.emit("dead_click", "product", product_id=p["product_id"], element=s.pick(["image_gallery", "offer_banner"]))
    if "rage_click" in s.noise:
        s.emit("rage_click", "product", product_id=p["product_id"], element="image_gallery",
               clicks=3, window_ms=s.randint(1500, 2500))
    if s.is_clean and s.chance(s.cfg.clean.product_exit_rate):
        return True
    add_to_cart(s, p)
    if s.chance(0.18):
        extra = s.w.pick_product(lambda q: q["in_stock"], exclude={p["product_id"]})
        if extra is not None:
            view_product(s, extra)
            add_to_cart(s, extra)
    return False


def cart_normal(s: Session) -> bool:
    s.emit("cart_view", "cart", n_items=len(s.cart), cart_value=s.cart_value)
    s.emit("rec_impression", "cart", slot="cart_upsell", n_items=6, in_stock_items=s.randint(4, 6))
    if s.is_clean and s.chance(s.cfg.clean.cart_abandon_rate):
        return True
    s.emit("checkout_start", "cart", cart_value=s.cart_value)
    return False


def login_normal(s: Session) -> bool:
    if s.logged_in:
        return False
    page = "order_tracking" if s.kind == "post_purchase" else "checkout_login"
    s.emit("login_wall", page, guest_checkout=False)
    s.emit("otp_sent", page, channel="sms")
    if "single_otp_resend" in s.noise:
        s.emit("otp_resend", page, wait=s.randint(30, 50), channel="sms", attempt=2)
    s.emit("login_success", page, wait=s.randint(10, 30), method="otp")
    s.logged_in = True
    return False


def delivery_normal(s: Session) -> bool:
    s.goto("checkout_address")
    s.emit("delivery_info_view", "checkout_delivery", **delivery_quote(s))
    if "extra_pincode_check" in s.noise and s.chance(0.5):
        pincode_check(s, variant=1)
    return False


def coupon_normal(s: Session) -> bool:
    noisy = "single_coupon_fail" in s.noise
    if not (noisy or s.chance(0.3)):
        return False
    s.goto("checkout_summary")
    if noisy:
        bad = s.pick(INVALID_CODES)
        s.emit("coupon_apply", code=bad)
        s.emit("coupon_failed", code=bad, reason="invalid_code")
    code, discount = best_coupon(s)
    if code:
        s.emit("coupon_apply", code=code)
        s.emit("coupon_applied", code=code, discount=discount)
        s.discount, s.coupon_code = discount, code
    return False


def total_normal(s: Session) -> bool:
    s.goto("checkout_summary")
    s.emit("total_shown", "checkout_summary", **compute_total(s))
    return s.is_clean and s.chance(s.cfg.clean.checkout_abandon_rate)


def payment_normal(s: Session) -> bool:
    s.goto("checkout_payment")
    if s.method != "COD" and "single_payment_fail" in s.noise:
        pay(s, s.method, ok=False, error=s.pick(TRANSIENT_ERRORS[s.method]))
    pay(s, s.method, ok=True)
    return False


def order_normal(s: Session) -> bool:
    place_order(s)
    return False


def tracking_normal(s: Session) -> bool:
    order = s.pp_order
    s.goto("order_tracking", order_id=order["order_id"])
    for _ in range(1 + int(s.chance(0.25))):
        s.emit("tracking_view", "order_tracking", order_id=order["order_id"],
               status=order_status_at(order, s.t),
               days_to_promise=(order["promised_delivery_at"] - s.t).days)
    return False


def resolve_normal(s: Session) -> bool:
    if s.chance(0.05):
        s.emit("help_view", "help")
    return False


NORMAL: dict[int, Callable[[Session], bool]] = {
    BROWSE: browse_normal, PRODUCT: product_normal, CART: cart_normal, LOGIN: login_normal,
    DELIVERY: delivery_normal, COUPON: coupon_normal, TOTAL: total_normal,
    PAYMENT: payment_normal, ORDER: order_normal,
    PP_LOGIN: login_normal, PP_TRACK: tracking_normal, PP_RESOLVE: resolve_normal,
}
