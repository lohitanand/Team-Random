"""Synthetic data generator entrypoint.

    python -m datagen.generate                    # full size -> data/raw/*.parquet
    python -m datagen.generate --sessions 3000    # quick run
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from faker import Faker

from backend.app.config import DATA_DIR
from backend.app.schemas.events import PAGE_TO_STEP
from backend.app.schemas.taxonomy import FRICTION_TYPES, FUNNEL_STEPS
from datagen.catalog import assign_city_couriers, build_catalog, city_tiers, products_frame
from datagen.config import DatagenConfig, load_config
from datagen.journey import FrictionPlan, Session, User, World
from datagen.scenarios import VARIANTS, add_review, kind_of, run_session
from datagen.text import TextGenerator

HESITATION_PAGES = ["product", "cart", "checkout_delivery", "checkout_summary", "checkout_payment"]
TABLES = ["events", "payments", "orders", "tickets", "reviews", "chats", "products",
          "ground_truth", "ground_truth_incidents"]


def hash_user_id(raw_id: str, salt: str) -> str:
    return "u_" + hashlib.sha256(f"{salt}:{raw_id}".encode()).hexdigest()[:12]


def _choice(rng: np.random.Generator, mix: dict[str, float]) -> str:
    keys = list(mix)
    probs = np.array([mix[k] for k in keys], dtype=float)
    return str(keys[int(rng.choice(len(keys), p=probs / probs.sum()))])


def build_users(cfg: DatagenConfig, rng: np.random.Generator) -> list[User]:
    by_tier = cfg.cities.by_tier()
    users: list[User] = []
    for i in range(cfg.sizes.users):
        tier = _choice(rng, cfg.cities.tier_mix)
        device = _choice(rng, cfg.users.device_mix)
        raw_id = f"u_{i + 1}"
        users.append(User(
            raw_id=raw_id,
            user_id=hash_user_id(raw_id, cfg.id_hash_salt),
            city=str(rng.choice(by_tier[tier])),
            tier=tier,
            device=device,
            app_version=_choice(rng, cfg.users.android_app_versions) if device == "android_app" else None,
            is_new=bool(rng.random() < cfg.users.new_customer_share),
        ))
    return users


def sample_start_times(cfg: DatagenConfig, rng: np.random.Generator) -> list[datetime]:
    n = cfg.sizes.sessions
    start = datetime.combine(cfg.start_date, datetime.min.time())
    hours = np.array(cfg.hour_weights) / sum(cfg.hour_weights)
    days = rng.integers(0, cfg.days, size=n)
    hour = rng.choice(24, size=n, p=hours)
    seconds = rng.integers(0, 3600, size=n)
    times = [start + timedelta(days=int(d), hours=int(h), seconds=int(s)) for d, h, s in zip(days, hour, seconds)]
    return sorted(times)


def _variant(cfg: DatagenConfig, rng: np.random.Generator, friction: str, kind: str | None = None) -> str | None:
    weights = {v: w for v, w in cfg.friction.variants[friction].items()
               if w > 0 and (kind is None or kind_of(VARIANTS[friction][v]) == kind)}
    return _choice(rng, weights) if weights else None


def plan_frictions(cfg: DatagenConfig, rng: np.random.Generator) -> list[FrictionPlan]:
    mix = cfg.friction
    roll = rng.random()
    if roll < mix.clean_share:
        return []
    types = list(FRICTION_TYPES)
    probs = np.array([mix.weights[t] for t in types])
    probs = probs / probs.sum()
    if roll < mix.clean_share + mix.double_share:
        for _ in range(20):
            first, second = (types[int(i)] for i in rng.choice(len(types), size=2, replace=False, p=probs))
            v1 = _variant(cfg, rng, first)
            v2 = _variant(cfg, rng, second, kind_of(VARIANTS[first][v1]))
            if v2 is not None:
                return [FrictionPlan(first, v1, VARIANTS[first][v1]), FrictionPlan(second, v2, VARIANTS[second][v2])]
    friction = types[int(rng.choice(len(types), p=probs))]
    variant = _variant(cfg, rng, friction)
    return [FrictionPlan(friction, variant, VARIANTS[friction][variant])]


def make_session(w: World, session_id: str, user: User, start: datetime) -> Session:
    cfg, rng = w.cfg, w.rng
    plans = plan_frictions(cfg, rng)
    if plans:
        kind = kind_of(plans[0].stage)
    else:
        kind = "post_purchase" if rng.random() < cfg.clean.post_purchase_share else "shopping"

    device = user.device if rng.random() < 0.8 else _choice(rng, cfg.users.device_mix)
    app_version = user.app_version if device == user.device else None
    if device == "android_app" and app_version is None:
        app_version = _choice(rng, cfg.users.android_app_versions)
    if any(p.variant == "app_crash_android" for p in plans):
        device, app_version = "android_app", "5.2.0"

    method = _choice(rng, cfg.payments.method_mix)
    primary = w.city_courier[user.city]
    s = Session(
        w=w, session_id=session_id, user=user, t=start, kind=kind, plans=plans,
        device=device, app_version=app_version,
        source=_choice(rng, cfg.users.source_mix) if kind == "shopping" else str(rng.choice(["direct", "push", "email"])),
        courier=primary if rng.random() < cfg.couriers.primary_share else str(rng.choice(cfg.couriers.names)),
        logged_in=(not user.is_new) and bool(rng.random() < cfg.users.logged_in_share_returning),
        bank=f"BANK_{int(rng.integers(1, cfg.payments.banks + 1)):02d}",
        method=method,
        gateway=None if method == "COD" else _choice(rng, cfg.payments.gateway_mix),
    )
    noise_pool = cfg.clean.noise if not plans else {"hesitation": cfg.clean.noise["hesitation"]}
    s.noise = {name for name, p in noise_pool.items() if rng.random() < p}
    if "hesitation" in s.noise:
        s.hesitate_page = str(rng.choice(HESITATION_PAGES))
    return s


def ground_truth_row(s: Session) -> dict[str, Any]:
    plans = sorted(s.plans, key=lambda p: p.stage)
    primary = plans[-1] if plans else None
    secondary = plans[0] if len(plans) > 1 else None
    pages = [e["page"] for e in s.events if e["event"] != "exit"]
    steps = [PAGE_TO_STEP[p] for p in pages]
    shopping_steps = [st for st in steps if st != "post_purchase"] or ["browse"]
    furthest = max(shopping_steps, key=FUNNEL_STEPS.index) if s.kind == "shopping" else "post_purchase"
    return {
        "session_id": s.session_id,
        "user_id": s.user.user_id,
        "session_start": s.events[0]["timestamp"],
        "session_end": s.t,
        "session_kind": s.kind,
        "device": s.device,
        "city": s.user.city,
        "city_tier": s.user.tier,
        "is_clean": not plans,
        "n_frictions": len(plans),
        "friction_types": "|".join(p.friction for p in plans),
        "primary_friction": primary.friction if primary else None,
        "primary_variant": primary.variant if primary else None,
        "secondary_friction": secondary.friction if secondary else None,
        "secondary_variant": secondary.variant if secondary else None,
        "incident_id": next((p.incident_id for p in plans if p.incident_id), None),
        "noise_tags": "|".join(sorted(s.noise)),
        "reached_cart": s.reached_cart,
        "converted": s.converted,
        "abandoned": s.reached_cart and not s.converted,
        "furthest_step": furthest,
        "exit_step": steps[-1],
        "order_id": s.order["order_id"] if s.order else None,
    }


def add_order_reviews(w: World) -> None:
    """Reviews for delivered orders that no friction scenario already reviewed."""
    cfg, rng, text = w.cfg, w.rng, w.text
    missing = w.missing_size_ids
    for order in w.tables["orders"]:
        if order["order_id"] in w.reviewed_orders or order["status"] != "delivered":
            continue
        if rng.random() >= cfg.text.review_rate:
            continue
        created = order["delivered_at"] + timedelta(days=float(rng.uniform(1, 5)))
        if created > w.end:
            continue
        pid = order["product_ids"][0]
        product = w.by_id[pid]
        slots = {"product": product["subcategory"], "days": max(order["delay_days"], 2),
                 "courier": order["courier"], "city": order["city"],
                 "size": product["sizes"][2] if product["sizes"] else "M"}
        if pid in missing and rng.random() < 0.4:
            sample, rating = text.complaint("size_fit", slots), int(rng.integers(1, 3))
        elif order["delay_days"] > 0 and rng.random() < 0.35:
            sample, rating = text.complaint("delivery_delay", slots), int(rng.integers(1, 4))
        elif rng.random() < 0.88:
            sample, rating = text.positive_review(slots), int(rng.integers(4, 6))
        else:
            theme = str(rng.choice(["size_fit", "missing_info", "return_refund", "delivery_delay"]))
            sample, rating = text.complaint(theme, slots), int(rng.integers(1, 4))
        add_review(w, order=order, product_id=pid, sample=sample, rating=rating,
                   created_at=created, session_id=order["session_id"])


def _add_duplicates(events: list[dict[str, Any]], rng: np.random.Generator, rate: float) -> list[dict[str, Any]]:
    dup = rng.random(len(events)) < rate
    out: list[dict[str, Any]] = []
    for event, is_dup in zip(events, dup):
        out.append(event)
        if is_dup and event["event"] != "exit":
            out.append(dict(event))
    return out


def _incident_table(cfg: DatagenConfig, w: World, gt: pd.DataFrame) -> pd.DataFrame:
    inc = cfg.incidents
    start = datetime.combine(cfg.start_date, datetime.min.time())
    go, cd, ms = inc.gateway_outage, inc.courier_delay, inc.missing_size_info
    go_start = start + timedelta(days=go.day - 1, hours=go.start_hour)
    rows = [
        {"incident_id": go.id, "kind": "gateway_outage",
         "scope": json.dumps({"gateway": go.gateway}),
         "start": go_start, "end": go_start + timedelta(hours=go.hours),
         "description": f"Gateway {go.gateway} failure spike for {go.hours} hours on day {go.day}"},
        {"incident_id": cd.id, "kind": "courier_delay",
         "scope": json.dumps({"courier": cd.courier, "cities": cd.cities}),
         "start": start + timedelta(days=min(cd.days) - 1),
         "end": start + timedelta(days=max(cd.days)),
         "description": f"{cd.courier} delays of +{cd.extra_eta_days} days in {', '.join(cd.cities)}"},
        {"incident_id": ms.id, "kind": "missing_size_info",
         "scope": json.dumps({"product_ids": sorted(w.missing_size_ids)}),
         "start": start, "end": w.end,
         "description": f"{ms.n_products} sized products have no size chart"},
    ]
    df = pd.DataFrame(rows)
    df["affected_sessions"] = df["incident_id"].map(gt["incident_id"].value_counts()).fillna(0).astype(int)
    return df


def generate(cfg: DatagenConfig) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)
    fake = Faker("en_IN")
    fake.seed_instance(cfg.seed)

    products = build_catalog(cfg, rng, fake)
    users = build_users(cfg, rng)
    start = datetime.combine(cfg.start_date, datetime.min.time())
    w = World(
        cfg=cfg, rng=rng, text=TextGenerator(cfg.text, rng), products=products,
        popularity=rng.lognormal(0, 1, size=len(products)), tiers=city_tiers(cfg),
        city_courier=assign_city_couriers(cfg, rng), start=start, end=start + timedelta(days=cfg.days),
        by_id={p["product_id"]: p for p in products}, users_by_id={u.user_id: u for u in users},
    )

    activity = rng.lognormal(0, 1, size=len(users))
    user_idx = rng.choice(len(users), size=cfg.sizes.sessions, p=activity / activity.sum())
    gt_rows: list[dict[str, Any]] = []
    for i, (t, u) in enumerate(zip(sample_start_times(cfg, rng), user_idx)):
        s = make_session(w, f"s_{i + 1:06d}", users[int(u)], t)
        run_session(s)
        w.tables["events"].extend(s.events)
        gt_rows.append(ground_truth_row(s))

    add_order_reviews(w)
    events = _add_duplicates(w.tables["events"], rng, cfg.data_quality.duplicate_event_rate)

    ev = pd.DataFrame(events)
    ev["metadata"] = ev["metadata"].map(lambda m: json.dumps(m, sort_keys=True, ensure_ascii=False))
    ev = ev.sort_values(["timestamp", "session_id"], kind="stable").reset_index(drop=True)
    orders = pd.DataFrame(w.tables["orders"])
    orders["product_ids"] = orders["product_ids"].map(json.dumps)
    gt = pd.DataFrame(gt_rows)

    tables = {
        "events": ev,
        "payments": pd.DataFrame(w.tables["payments"]),
        "orders": orders,
        "tickets": pd.DataFrame(w.tables["tickets"]),
        "reviews": pd.DataFrame(w.tables["reviews"]),
        "chats": pd.DataFrame(w.tables["chats"]),
        "products": products_frame(products),
        "ground_truth": gt,
        "ground_truth_incidents": _incident_table(cfg, w, gt),
    }
    return tables


def friction_rates(gt: pd.DataFrame) -> dict[str, float]:
    return {f: float(gt["friction_types"].str.split("|").map(lambda xs, f=f: f in xs).mean()) for f in FRICTION_TYPES}


def summarize(tables: dict[str, pd.DataFrame], cfg: DatagenConfig) -> str:
    gt = tables["ground_truth"]
    low, high = cfg.friction.target_rate_bounds
    lines = ["Table sizes:"]
    lines += [f"  {name:<24}{len(df):>9,}" for name, df in tables.items()]
    lines.append("")
    lines.append(f"Clean sessions:   {gt['is_clean'].mean():6.1%}  (target {cfg.friction.clean_share:.0%})")
    lines.append(f"Double friction:  {(gt['n_frictions'] == 2).mean():6.1%}  (target {cfg.friction.double_share:.0%})")
    lines.append(f"Reached cart:     {gt['reached_cart'].mean():6.1%}")
    lines.append(f"Converted:        {gt['converted'].mean():6.1%}   clean shopping: "
                 f"{gt[gt['is_clean'] & (gt['session_kind'] == 'shopping')]['converted'].mean():.1%}")
    lines.append(f"Abandoned carts:  {gt['abandoned'].mean():6.1%}")
    lines.append("")
    lines.append(f"Friction rates (target {low:.0%}-{high:.0%}):")
    for friction, rate in friction_rates(gt).items():
        flag = "ok" if low <= rate <= high else "OUT OF RANGE"
        variants = pd.concat([
            gt.loc[gt["primary_friction"] == friction, "primary_variant"],
            gt.loc[gt["secondary_friction"] == friction, "secondary_variant"],
        ]).nunique()
        lines.append(f"  {friction:<24}{rate:6.1%}  {variants} variants  {flag}")
    lines.append("")
    lines.append("Incidents:")
    for row in tables["ground_truth_incidents"].itertuples():
        lines.append(f"  {row.incident_id:<24}{row.affected_sessions:>6} sessions  {row.description}")
    texts = pd.concat([tables[t]["theme_label"] for t in ("tickets", "reviews", "chats")])
    langs = pd.concat([tables[t]["language"] for t in ("tickets", "reviews", "chats")])
    lines.append("")
    lines.append(f"Text records: {len(texts):,}  (Hinglish {(langs == 'hinglish').mean():.0%})")
    lines += [f"  {theme:<24}{count:>6}" for theme, count in texts.value_counts().sort_index().items()]
    return "\n".join(lines)


def write_tables(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out_dir / f"{name}.parquet", index=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic e-commerce journey data.")
    parser.add_argument("--out", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--sessions", type=int)
    parser.add_argument("--users", type=int)
    parser.add_argument("--products", type=int)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)

    sizes = {k: v for k, v in {"sessions": args.sessions, "users": args.users, "products": args.products}.items() if v}
    overrides: dict[str, Any] = {"sizes": sizes} if sizes else {}
    if args.seed is not None:
        overrides["seed"] = args.seed
    cfg = load_config(overrides=overrides)

    tables = generate(cfg)
    write_tables(tables, args.out)
    print(summarize(tables, cfg))
    print(f"\nWrote {len(tables)} tables to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
