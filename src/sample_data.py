"""Deterministic synthetic sales data used for demos and tests.

All randomness comes from a fixed-seed ``random.Random`` instance, so every run
produces identical rows and tests can rely on exact values.
"""

import random
from datetime import date, timedelta

SEED = 42
NUM_SALES = 600
START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 12, 31)

REGIONS = ("North", "South", "East", "West")

# (product_id, product_name, category, unit_price)
PRODUCTS = (
    (1, "Laptop Pro 14", "Electronics", 1200.00),
    (2, "Wireless Mouse", "Electronics", 25.00),
    (3, "Noise-Cancelling Headphones", "Electronics", 180.00),
    (4, "Office Chair", "Furniture", 220.00),
    (5, "Standing Desk", "Furniture", 450.00),
    (6, "Bookshelf", "Furniture", 95.00),
    (7, "A4 Paper Ream", "Stationery", 6.50),
    (8, "Gel Pen Pack", "Stationery", 4.00),
    (9, "Spiral Notebook", "Stationery", 3.25),
    (10, "Coffee Beans 1kg", "Pantry", 18.00),
    (11, "Green Tea Box", "Pantry", 7.50),
    (12, "Protein Bars (12)", "Pantry", 22.00),
)

# Discounts applied at sale time, so sale-level prices can differ from the catalogue.
DISCOUNTS = (0.0, 0.0, 0.0, 0.05, 0.10)


def _quantity_for(price: float, rng: random.Random) -> int:
    """Cheaper items sell in larger quantities, which keeps the data realistic."""
    if price >= 400:
        return rng.randint(1, 3)
    if price >= 100:
        return rng.randint(1, 5)
    if price >= 20:
        return rng.randint(1, 10)
    return rng.randint(5, 40)


def generate_sales(seed: int = SEED, count: int = NUM_SALES) -> list[tuple]:
    """Return sales rows as (sale_id, product_id, quantity, sale_date, region, unit_price)."""
    rng = random.Random(seed)
    span_days = (END_DATE - START_DATE).days
    rows = []
    for sale_id in range(1, count + 1):
        product_id, _, _, list_price = rng.choice(PRODUCTS)
        quantity = _quantity_for(list_price, rng)
        sale_date = START_DATE + timedelta(days=rng.randint(0, span_days))
        region = rng.choice(REGIONS)
        unit_price = round(list_price * (1 - rng.choice(DISCOUNTS)), 2)
        rows.append((sale_id, product_id, quantity, sale_date.isoformat(), region, unit_price))
    return rows
