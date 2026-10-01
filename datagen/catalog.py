"""Product catalog, cities, couriers, ETAs and search queries."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from faker import Faker

from datagen.config import DatagenConfig

APPAREL_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
FOOTWEAR_SIZES = ["UK6", "UK7", "UK8", "UK9", "UK10", "UK11"]
POPULAR_SIZES = {"M", "L", "UK8", "UK9"}
COLORS = ["black", "white", "navy", "red", "olive", "beige", "grey", "maroon", "blue", "pink"]

CATEGORIES: dict[str, dict[str, Any]] = {
    "apparel": {
        "share": 0.34,
        "sizes": APPAREL_SIZES,
        "brand_suffix": ["Wear", "Threads", "Fashions", "Studio"],
        "attributes": ["material", "fit", "care", "length", "fabric_weight"],
        "subcategories": {
            "t-shirt": (299, 999), "shirt": (599, 1799), "jeans": (799, 2499),
            "kurta": (499, 1999), "dress": (699, 2999), "jacket": (1299, 4999),
        },
    },
    "footwear": {
        "share": 0.16,
        "sizes": FOOTWEAR_SIZES,
        "brand_suffix": ["Steps", "Footwear", "Kicks"],
        "attributes": ["material", "sole", "fit", "closure", "heel_height"],
        "subcategories": {
            "running shoes": (999, 3999), "sneakers": (899, 3499),
            "sandals": (399, 1499), "formal shoes": (1199, 3999),
        },
    },
    "electronics": {
        "share": 0.20,
        "sizes": [],
        "brand_suffix": ["Tech", "Audio", "Electronics", "Labs"],
        "attributes": ["battery_life", "warranty", "connectivity", "compatibility", "water_resistance"],
        "subcategories": {
            "earbuds": (999, 4999), "smartwatch": (1499, 7999), "power bank": (699, 2499),
            "bluetooth speaker": (1199, 5999), "phone case": (199, 799),
        },
    },
    "home_kitchen": {
        "share": 0.18,
        "sizes": [],
        "brand_suffix": ["Home", "Living", "Kitchenware"],
        "attributes": ["material", "dimensions", "capacity", "warranty", "care"],
        "subcategories": {
            "bedsheet": (499, 1999), "mixer grinder": (1999, 5999), "cookware set": (1299, 4499),
            "water bottle": (199, 899), "table lamp": (599, 2499),
        },
    },
    "beauty": {
        "share": 0.12,
        "sizes": [],
        "brand_suffix": ["Naturals", "Botanics", "Care"],
        "attributes": ["skin_type", "volume_ml", "ingredients", "shelf_life", "usage"],
        "subcategories": {
            "face serum": (299, 1299), "sunscreen": (249, 899), "shampoo": (199, 699),
            "face wash": (149, 499), "perfume": (499, 2499),
        },
    },
}

QUERY_MODIFIERS = ["for men", "for women", "under {price}", "best", "cheap", "premium", "new", "combo"]
ZERO_RESULT_WORDS = ["vegan leather", "size 13", "glow in dark", "extra long", "handloom organic",
                     "waterproof ip69", "left handed", "kids xxl", "titanium", "bamboo fibre"]
MISSPELL = {"t-shirt": "tshrt", "sneakers": "snekers", "earbuds": "earbudz", "smartwatch": "smart wach",
            "jeans": "jens", "kurta": "kurtaa", "perfume": "perfum", "sunscreen": "sunscren",
            "bedsheet": "bed shet", "sandals": "sandels", "power bank": "powerbank 50000mah"}


def _price(rng: np.random.Generator, low: int, high: int) -> int:
    return int(rng.uniform(low, high) // 10 * 10 + 9)


def _brands(fake: Faker, rng: np.random.Generator) -> dict[str, list[str]]:
    brands: dict[str, list[str]] = {}
    used: set[str] = set()
    for cat, spec in CATEGORIES.items():
        names: list[str] = []
        while len(names) < 8:
            name = f"{fake.first_name()} {spec['brand_suffix'][int(rng.integers(len(spec['brand_suffix'])))]}"
            if name not in used:
                used.add(name)
                names.append(name)
        brands[cat] = names
    return brands


def _stock(rng: np.random.Generator, sizes: list[str]) -> dict[str, int]:
    keys = sizes or ["ONE"]
    stock = {s: int(rng.integers(1, 40)) for s in keys}
    if sizes and rng.random() < 0.25:
        for s in POPULAR_SIZES.intersection(keys):
            stock[s] = 0
    if rng.random() < 0.05:
        stock = {s: 0 for s in keys}
    return stock


def build_catalog(cfg: DatagenConfig, rng: np.random.Generator, fake: Faker) -> list[dict[str, Any]]:
    cats = list(CATEGORIES)
    shares = np.array([CATEGORIES[c]["share"] for c in cats])
    shares = shares / shares.sum()
    brands = _brands(fake, rng)
    window_minutes = cfg.days * 24 * 60
    start = datetime.combine(cfg.start_date, datetime.min.time())
    products: list[dict[str, Any]] = []

    for i in range(cfg.sizes.products):
        cat = str(rng.choice(cats, p=shares))
        spec = CATEGORIES[cat]
        sub = str(rng.choice(list(spec["subcategories"])))
        price = _price(rng, *spec["subcategories"][sub])
        brand = brands[cat][int(rng.integers(len(brands[cat])))]
        color = str(rng.choice(COLORS)) if cat in ("apparel", "footwear", "electronics") else ""
        attributes: list[str] = spec["attributes"]
        vague = rng.random() < 0.12
        n_missing = int(rng.integers(3, 5)) if vague else int(rng.integers(0, 2))
        missing = sorted(str(a) for a in rng.choice(attributes, size=n_missing, replace=False))
        stock = _stock(rng, spec["sizes"])
        products.append({
            "product_id": f"p_{i + 1:03d}",
            "name": " ".join(x for x in (brand, color.title(), sub.title()) if x),
            "brand": brand,
            "category": cat,
            "subcategory": sub,
            "color": color,
            "price": price,
            "mrp": int(price * rng.uniform(1.15, 1.8) // 10 * 10 + 9),
            "rating": round(float(rng.uniform(2.9, 3.8) if vague else rng.uniform(3.4, 4.7)), 1),
            "n_reviews": int(rng.integers(3, 2500)),
            "sizes": list(spec["sizes"]),
            "stock": stock,
            "in_stock": any(q > 0 for q in stock.values()),
            "has_size_chart": bool(spec["sizes"]),
            "missing_attributes": missing,
            "spec_completeness": round(1 - n_missing / len(attributes), 2),
            "description": fake.sentence(nb_words=int(rng.integers(6, 30)) if not vague else 4),
            "image_count": int(rng.integers(1, 3)) if vague else int(rng.integers(3, 9)),
            "warehouse_city": str(rng.choice(cfg.cities.tier_1)),
            "return_window_days": int(rng.choice([7, 10, 15, 30])),
            "cod_allowed": bool(rng.random() < 0.85),
            "catalog_updated_at": start + timedelta(minutes=int(rng.integers(0, window_minutes))),
        })

    sized = [p for p in products if p["sizes"]]
    picks = rng.choice(len(sized), size=cfg.incidents.missing_size_info.n_products, replace=False)
    for idx in sorted(int(i) for i in picks):
        sized[idx]["has_size_chart"] = False
    return products


def products_frame(products: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(products)
    for col in ("sizes", "stock", "missing_attributes"):
        df[col] = df[col].map(json.dumps)
    return df


def city_tiers(cfg: DatagenConfig) -> dict[str, str]:
    return {city: tier for tier, cities in cfg.cities.by_tier().items() for city in cities}


def assign_city_couriers(cfg: DatagenConfig, rng: np.random.Generator) -> dict[str, str]:
    incident = cfg.incidents.courier_delay
    mapping: dict[str, str] = {}
    for city in city_tiers(cfg):
        mapping[city] = incident.courier if city in incident.cities else str(rng.choice(cfg.couriers.names))
    return mapping


def eta_days(cfg: DatagenConfig, tier: str, city: str, courier: str, warehouse_city: str) -> int:
    days = cfg.couriers.base_eta_days[tier] + cfg.couriers.extra_days.get(courier, 0)
    if city == warehouse_city:
        days -= 1
    return max(days, 1)


def search_query(product: dict[str, Any], rng: np.random.Generator) -> str:
    base = product["subcategory"]
    roll = rng.random()
    if roll < 0.3:
        return base
    if roll < 0.55 and product["color"]:
        return f"{product['color']} {base}"
    if roll < 0.75:
        return f"{product['brand'].split()[0].lower()} {base}"
    modifier = str(rng.choice(QUERY_MODIFIERS)).format(price=(product["price"] // 500 + 1) * 500)
    return f"{base} {modifier}"


def reformulations(product: dict[str, Any], rng: np.random.Generator, n: int) -> list[str]:
    base = product["subcategory"]
    variants = [
        base,
        f"{base} {rng.choice(QUERY_MODIFIERS)}".format(price=(product["price"] // 500 + 1) * 500),
        f"{product['color'] or 'best'} {base} {rng.choice(['latest', 'trending', 'original'])}",
        f"{base} {rng.choice(['size', 'fit', 'quality', 'brand'])} {rng.choice(['good', 'best', 'top rated'])}",
        f"{rng.choice(['buy', 'show', 'need'])} {base} {rng.choice(['online', 'fast delivery', 'cod'])}",
        f"{base.split()[-1]} {rng.choice(COLORS)}",
    ]
    order = rng.permutation(len(variants))[:n]
    return [variants[int(i)] for i in order]


def zero_result_query(product: dict[str, Any], rng: np.random.Generator) -> str:
    base = product["subcategory"]
    if base in MISSPELL and rng.random() < 0.5:
        return MISSPELL[base]
    return f"{base} {rng.choice(ZERO_RESULT_WORDS)}"
