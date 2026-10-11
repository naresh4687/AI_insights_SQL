"""Dashboard figures, computed from the database at request time.

Every query here is fixed, read-only SQL that still goes through ``query_service.run_query``
(validation, authorizer, read-only connection, timeout, row cap), the same path as user
questions. Dashboard queries are not written to query history.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.query_service import run_query

_REVENUE = "ROUND(SUM(s.quantity * s.unit_price), 2)"

KPI_SQL = """
    SELECT ROUND(COALESCE(SUM(s.quantity * s.unit_price), 0), 2) AS revenue,
           COUNT(*) AS sales,
           COALESCE(SUM(s.quantity), 0) AS units
    FROM sales s"""
PRODUCT_COUNT_SQL = "SELECT COUNT(*) AS products FROM products"

MONTHLY_REVENUE_SQL = f"""
    SELECT strftime('%Y-%m', s.sale_date) AS month, {_REVENUE} AS revenue
    FROM sales s GROUP BY month ORDER BY month"""
REVENUE_BY_REGION_SQL = f"""
    SELECT s.region, {_REVENUE} AS revenue
    FROM sales s GROUP BY s.region ORDER BY revenue DESC"""
REVENUE_BY_CATEGORY_SQL = f"""
    SELECT p.category, {_REVENUE} AS revenue
    FROM sales s JOIN products p ON p.product_id = s.product_id
    GROUP BY p.category ORDER BY revenue DESC"""
TOP_PRODUCTS_SQL = f"""
    SELECT p.product_name, {_REVENUE} AS revenue
    FROM sales s JOIN products p ON p.product_id = s.product_id
    GROUP BY p.product_id, p.product_name ORDER BY revenue DESC LIMIT 5"""


@dataclass(frozen=True)
class Kpis:
    revenue: float
    sales: int
    units: int
    products: int

    @property
    def average_sale_value(self) -> float | None:
        """Revenue per sale record (each row in ``sales`` is one sale). None if there are no sales."""
        return round(self.revenue / self.sales, 2) if self.sales else None


@dataclass(frozen=True)
class MonthChange:
    month: str
    revenue: float
    previous_month: str
    previous_revenue: float

    @property
    def percent(self) -> float | None:
        if not self.previous_revenue:
            return None
        return (self.revenue - self.previous_revenue) / self.previous_revenue * 100


def kpis(db_path: Path) -> Kpis:
    row = run_query(db_path, KPI_SQL).data.iloc[0]
    products = run_query(db_path, PRODUCT_COUNT_SQL).data.iloc[0, 0]
    return Kpis(revenue=float(row["revenue"]), sales=int(row["sales"]), units=int(row["units"]),
                products=int(products))


def monthly_revenue(db_path: Path) -> pd.DataFrame:
    return run_query(db_path, MONTHLY_REVENUE_SQL).data


def revenue_by_region(db_path: Path) -> pd.DataFrame:
    return run_query(db_path, REVENUE_BY_REGION_SQL).data


def revenue_by_category(db_path: Path) -> pd.DataFrame:
    return run_query(db_path, REVENUE_BY_CATEGORY_SQL).data


def top_products(db_path: Path) -> pd.DataFrame:
    return run_query(db_path, TOP_PRODUCTS_SQL).data


def latest_month_change(monthly: pd.DataFrame) -> MonthChange | None:
    """The last month in the data compared with the month before it — a real comparison,
    only available when there are at least two months."""
    if len(monthly) < 2:
        return None
    previous, latest = monthly.iloc[-2], monthly.iloc[-1]
    return MonthChange(str(latest["month"]), float(latest["revenue"]),
                       str(previous["month"]), float(previous["revenue"]))
