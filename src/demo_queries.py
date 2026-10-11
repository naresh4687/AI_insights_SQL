"""Demo Mode: predefined questions mapped to hand-written SQL.

Demo SQL is not trusted blindly — it goes through the same validation and read-only
execution path as AI-generated SQL (see ``query_service.answer_question``).
"""

import re

_REVENUE = "ROUND(SUM(s.quantity * s.unit_price), 2)"

DEMO_QUERIES: dict[str, str] = {
    "Which five products generated the highest revenue?": f"""
        SELECT p.product_name, {_REVENUE} AS revenue
        FROM sales s JOIN products p ON p.product_id = s.product_id
        GROUP BY p.product_id, p.product_name
        ORDER BY revenue DESC
        LIMIT 5""",
    "What is the total revenue by region?": f"""
        SELECT s.region, {_REVENUE} AS revenue
        FROM sales s
        GROUP BY s.region
        ORDER BY revenue DESC""",
    "Which product category sold the most units?": """
        SELECT p.category, SUM(s.quantity) AS units_sold
        FROM sales s JOIN products p ON p.product_id = s.product_id
        GROUP BY p.category
        ORDER BY units_sold DESC""",
    "What were the monthly sales totals?": f"""
        SELECT strftime('%Y-%m', s.sale_date) AS month, {_REVENUE} AS revenue
        FROM sales s
        GROUP BY month
        ORDER BY month""",
    "Which products generated the lowest revenue?": f"""
        SELECT p.product_name, {_REVENUE} AS revenue
        FROM sales s JOIN products p ON p.product_id = s.product_id
        GROUP BY p.product_id, p.product_name
        ORDER BY revenue ASC
        LIMIT 5""",
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


_LOOKUP = {_normalise(question): sql for question, sql in DEMO_QUERIES.items()}


class UnsupportedQuestionError(LookupError):
    """The question is not one of the predefined Demo Mode questions."""


def demo_questions() -> list[str]:
    return list(DEMO_QUERIES)


def lookup_sql(question: str) -> str:
    """Return the predefined SQL for ``question``, ignoring case and punctuation."""
    sql = _LOOKUP.get(_normalise(question))
    if sql is None:
        raise UnsupportedQuestionError(question)
    return sql
