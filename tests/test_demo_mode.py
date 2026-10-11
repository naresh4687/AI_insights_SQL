"""Integration tests for Demo Mode: predefined questions answered through the safe pipeline."""

import socket
import sqlite3
from collections import defaultdict

import pytest

from src import database, demo_queries, sample_data
from src.query_service import MAX_QUESTION_LENGTH, Answer, QueryError, answer_question
from src.sql_guard import validate_sql

TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()


# --- Independent Python oracle built from the generated rows -----------------

_PRODUCTS = {pid: (name, category) for pid, name, category, _ in sample_data.PRODUCTS}


def _totals(key, value):
    totals = defaultdict(float)
    for sale in sample_data.generate_sales():
        _, product_id, quantity, sale_date, region, unit_price = sale
        row = {"product": _PRODUCTS[product_id][0], "category": _PRODUCTS[product_id][1],
               "region": region, "month": sale_date[:7],
               "revenue": quantity * unit_price, "units": quantity}
        totals[row[key]] += row[value]
    return totals


def _ranked(totals, descending=True, limit=None):
    items = sorted(totals.items(), key=lambda kv: kv[1], reverse=descending)
    return items[:limit] if limit else items


def _assert_rows(answer, expected):
    actual = answer.data.values.tolist()
    assert [row[0] for row in actual] == [name for name, _ in expected]
    assert [row[1] for row in actual] == pytest.approx([value for _, value in expected], abs=0.01)


# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def no_network(monkeypatch):
    """Fail the test if anything tries to open a network connection."""
    def blocked(*args, **kwargs):
        raise AssertionError("Network access attempted in Demo Mode")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


# --- Correct answers ----------------------------------------------------------

def test_there_are_five_demo_questions():
    assert len(demo_queries.demo_questions()) == 5


def test_top_five_products_by_revenue(seeded_db):
    _assert_rows(answer_question(seeded_db, TOP5), _ranked(_totals("product", "revenue"), limit=5))


def test_revenue_by_region(seeded_db):
    _assert_rows(answer_question(seeded_db, BY_REGION), _ranked(_totals("region", "revenue")))


def test_units_sold_by_category(seeded_db):
    _assert_rows(answer_question(seeded_db, BY_CATEGORY), _ranked(_totals("category", "units")))


def test_monthly_sales_totals(seeded_db):
    expected = sorted(_totals("month", "revenue").items())  # chronological
    answer = answer_question(seeded_db, MONTHLY)
    assert len(answer.data) == 12
    _assert_rows(answer, expected)


def test_lowest_revenue_products(seeded_db):
    expected = _ranked(_totals("product", "revenue"), descending=False, limit=5)
    _assert_rows(answer_question(seeded_db, BOTTOM5), expected)


def test_answer_reports_demo_source_and_validated_sql(seeded_db):
    answer = answer_question(seeded_db, TOP5)
    assert isinstance(answer, Answer)
    assert answer.source == "demo"
    assert answer.question == TOP5
    assert answer.sql == validate_sql(demo_queries.lookup_sql(TOP5))
    assert answer.truncated is False


@pytest.mark.parametrize("question", demo_queries.demo_questions())
def test_validated_sql_returns_same_rows_as_original(seeded_db, question):
    """Regenerating SQL from the AST must not change what the query returns."""
    conn = database.connect(seeded_db)
    original = conn.execute(demo_queries.lookup_sql(question)).fetchall()
    conn.close()
    assert [tuple(r) for r in answer_question(seeded_db, question).data.values.tolist()] == original


@pytest.mark.parametrize(
    "variant",
    ["what is the total revenue by region", "  WHAT IS THE TOTAL REVENUE BY REGION?? ", "What is the total revenue, by region"],
)
def test_question_matching_ignores_case_spacing_and_punctuation(seeded_db, variant):
    assert answer_question(seeded_db, variant).data.values.tolist() == \
        answer_question(seeded_db, BY_REGION).data.values.tolist()


# --- Works without an AI key or network ---------------------------------------

def test_demo_mode_works_without_api_key_or_network(seeded_db, monkeypatch, no_network):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "HF_TOKEN", "HF_BASE_URL", "HF_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for question in demo_queries.demo_questions():
        answer = answer_question(seeded_db, question)
        assert not answer.data.empty
        assert answer.source == "demo"


# --- Unsupported, unsafe, and invalid questions --------------------------------

def test_unsupported_question_is_rejected_and_recorded(seeded_db):
    with pytest.raises(QueryError, match="Demo Mode only answers the example questions") as exc_info:
        answer_question(seeded_db, "Who is our best salesperson?")
    assert exc_info.value.status == "rejected"

    entry = database.recent_history(seeded_db)[0]
    assert (entry["question"], entry["generated_sql"], entry["status"]) == \
        ("Who is our best salesperson?", None, "rejected")


def test_sql_typed_as_a_question_is_not_executed(seeded_db):
    with pytest.raises(QueryError) as exc_info:
        answer_question(seeded_db, "DROP TABLE sales")
    assert exc_info.value.status == "rejected"
    conn = database.connect(seeded_db)
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 600
    conn.close()


@pytest.mark.parametrize("question", ["", "   ", "\n", None])
def test_empty_question_is_rejected_without_history(seeded_db, question):
    with pytest.raises(QueryError, match="Please enter a question"):
        answer_question(seeded_db, question)
    assert database.recent_history(seeded_db) == []


def test_overlong_question_is_rejected_without_history(seeded_db):
    with pytest.raises(QueryError, match="too long"):
        answer_question(seeded_db, "x" * (MAX_QUESTION_LENGTH + 1))
    assert database.recent_history(seeded_db) == []


def test_question_at_length_limit_is_accepted_for_lookup(seeded_db):
    with pytest.raises(QueryError, match="Demo Mode only answers"):  # reaches lookup, not length check
        answer_question(seeded_db, "x" * MAX_QUESTION_LENGTH)


# --- Pipeline guarantees (generator is injected to simulate bad SQL) -----------

def test_generated_sql_cannot_bypass_validation(seeded_db):
    with pytest.raises(QueryError) as exc_info:
        answer_question(seeded_db, "anything", generate_sql=lambda q: "DELETE FROM sales")
    assert exc_info.value.status == "rejected"
    assert database.recent_history(seeded_db)[0]["status"] == "rejected"
    conn = database.connect(seeded_db)
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 600
    conn.close()


def test_execution_error_is_recorded_as_error(seeded_db):
    with pytest.raises(QueryError, match="no such column") as exc_info:
        answer_question(seeded_db, "q", generate_sql=lambda q: "SELECT revenue FROM sales")
    assert exc_info.value.status == "error"
    entry = database.recent_history(seeded_db)[0]
    assert (entry["generated_sql"], entry["status"]) == (None, "error")


def test_generator_crash_gives_safe_message(seeded_db):
    def broken(question):
        raise RuntimeError("internal details /secret/path")

    with pytest.raises(QueryError) as exc_info:
        answer_question(seeded_db, "q", generate_sql=broken, source="ai")
    assert "/secret/path" not in exc_info.value.message
    assert database.recent_history(seeded_db)[0]["status"] == "error"


def test_success_is_recorded_with_validated_sql(seeded_db):
    answer = answer_question(seeded_db, BY_REGION)
    entry = database.recent_history(seeded_db)[0]
    assert entry["question"] == BY_REGION
    assert entry["generated_sql"] == answer.sql
    assert entry["status"] == "success"


def test_history_failure_does_not_break_answer(seeded_db, monkeypatch):
    def failing_add_history(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(database, "add_history", failing_add_history)
    assert not answer_question(seeded_db, TOP5).data.empty
