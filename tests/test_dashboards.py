"""Dashboard Studio logic (src/dashboards.py): storage, layout, filters, safety, export."""

import json
import sqlite3

import pandas as pd
import pytest

from src import config, dashboards as dsh, data_access, demo_queries
from src.dashboards import DashboardError, Filter, Widget

Q = demo_queries.DEMO_QUERIES
TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()


@pytest.fixture
def store():
    return dsh.DashboardStore(config.get_app_db_path())


@pytest.fixture
def board(store, seeded_db):
    d = store.create("Sales overview", "Demo")
    store.add_widget(d.dashboard_id, "Monthly revenue", MONTHLY, "demo_sales", Q[MONTHLY], "line", "full", seeded_db)
    store.add_widget(d.dashboard_id, "By region", BY_REGION, "demo_sales", Q[BY_REGION], "pie", "half", seeded_db)
    store.add_widget(d.dashboard_id, "By category", BY_CATEGORY, "demo_sales", Q[BY_CATEGORY], "bar", "half", seeded_db)
    return store.get(d.dashboard_id)


def widget(**overrides) -> Widget:
    base = dict(widget_id=1, dashboard_id="d", position=0, title="t", question="", dataset_id="demo_sales",
                sql="SELECT 1", chart_kind="bar", width="half")
    return Widget(**{**base, **overrides})


# --- Storage ------------------------------------------------------------------------------

def test_create_get_list_and_positions(board, store):
    assert board.dashboard_id == "sales_overview" and board.description == "Demo"
    assert [(w.title, w.position, w.chart_kind, w.width) for w in board.widgets] == [
        ("Monthly revenue", 0, "line", "full"), ("By region", 1, "pie", "half"), ("By category", 2, "bar", "half")]
    assert [d.name for d in store.list()] == ["Sales overview"]


def test_stored_sql_is_the_validated_form(board):
    assert board.widgets[0].sql.startswith("SELECT STRFTIME('%Y-%m', s.sale_date) AS month")


@pytest.mark.parametrize("sql, message", [
    ("DELETE FROM sales", "cannot be added"),
    ("SELECT * FROM query_history", "cannot be added"),
    ("SELECT 1; SELECT 2", "cannot be added"),
])
def test_unsafe_sql_cannot_be_added(store, seeded_db, sql, message):
    d = store.create("X")
    with pytest.raises(DashboardError, match=message):
        store.add_widget(d.dashboard_id, "t", "", "demo_sales", sql, "bar", "half", seeded_db)
    assert store.get(d.dashboard_id).widgets == ()


@pytest.mark.parametrize("kwargs, message", [
    (dict(dataset_id="gone"), "not available"), (dict(chart_kind="radar"), "valid chart"),
    (dict(width="huge"), "valid chart"), (dict(title="  "), "chart title"),
])
def test_invalid_widgets(store, seeded_db, kwargs, message):
    d = store.create("X")
    args = dict(title="t", question="", dataset_id="demo_sales", sql=Q[BY_REGION], chart_kind="bar", width="half")
    with pytest.raises(DashboardError, match=message):
        store.add_widget(d.dashboard_id, demo_db=seeded_db, **{**args, **kwargs})


def test_widget_limit(store, seeded_db, monkeypatch):
    monkeypatch.setattr(dsh, "MAX_WIDGETS", 2)
    d = store.create("X")
    for _ in range(2):
        store.add_widget(d.dashboard_id, "t", "", "demo_sales", Q[BY_REGION], "bar", "half", seeded_db)
    with pytest.raises(DashboardError, match="at most 2"):
        store.add_widget(d.dashboard_id, "t", "", "demo_sales", Q[BY_REGION], "bar", "half", seeded_db)


def test_names_must_be_unique(store):
    store.create("A")
    with pytest.raises(DashboardError, match="already exists"):
        store.create("A")
    b = store.create("B")
    with pytest.raises(DashboardError, match="already exists"):
        store.rename(b.dashboard_id, "A")
    assert store.rename(b.dashboard_id, "C").name == "C"


def test_duplicate_copies_widgets_and_filters_independently(board, store):
    store.add_filter(board.dashboard_id, "category", "region")
    copy = store.duplicate(board.dashboard_id, "Copy")
    assert [w.title for w in copy.widgets] == [w.title for w in board.widgets]
    assert [(f.kind, f.column) for f in copy.filters] == [("category", "region")]
    store.remove_widget(copy.widgets[0].widget_id)
    assert len(store.get(board.dashboard_id).widgets) == 3  # the original is unaffected


def test_delete_removes_widgets_and_filters(board, store):
    store.add_filter(board.dashboard_id, "category", "region")
    store.delete(board.dashboard_id)
    conn = sqlite3.connect(config.get_app_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM dashboard_widgets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM dashboard_filters").fetchone()[0] == 0
    finally:
        conn.close()


def test_move_update_and_remove_keep_positions_contiguous(board, store):
    first, second, third = board.widgets
    store.move_widget(third.widget_id, -1)
    store.move_widget(third.widget_id, -1)
    store.move_widget(third.widget_id, -1)  # already first: stays
    assert [w.title for w in store.get(board.dashboard_id).widgets] == ["By category", "Monthly revenue", "By region"]
    store.update_widget(second.widget_id, title="Regions", width="third", chart_kind="donut")
    store.remove_widget(first.widget_id)
    widgets = store.get(board.dashboard_id).widgets
    assert [(w.title, w.position, w.width, w.chart_kind) for w in widgets] == [
        ("By category", 0, "half", "bar"), ("Regions", 1, "third", "donut")]
    with pytest.raises(DashboardError):
        store.update_widget(second.widget_id, width="huge")


# --- Layout -------------------------------------------------------------------------------

@pytest.mark.parametrize("widths, rows", [
    (["full", "half", "half"], [1, 2]),
    (["half", "third", "half"], [2, 1]),
    (["third", "third", "third", "full"], [3, 1]),
    (["half", "full", "half"], [1, 1, 1]),
    ([], []),
])
def test_layout_fills_rows(widths, rows):
    widgets = [widget(widget_id=i, width=w) for i, w in enumerate(widths)]
    assert [len(r) for r in dsh.layout(widgets)] == rows


# --- Filters ------------------------------------------------------------------------------

def run_all(board, seeded_db, values=()):
    return {r.widget.title: r for r in (dsh.run(w, seeded_db, list(values)) for w in board.widgets)}


def test_unfiltered_results_and_charts(board, seeded_db):
    results = run_all(board, seeded_db)
    assert {t: (r.chart.kind, len(r.data)) for t, r in results.items()} == {
        "Monthly revenue": ("line", 12), "By region": ("pie", 4), "By category": ("bar", 4)}


def test_date_filter_narrows_monthly_results_only(board, store, seeded_db):
    flt = store.add_filter(board.dashboard_id, "date", "month")
    results = run_all(board, seeded_db, [(flt, ("2025-03-15", "2025-05-02"))])
    monthly = results["Monthly revenue"]
    assert monthly.data["month"].tolist() == ["2025-03", "2025-04", "2025-05"] and monthly.applied == ["Month"]
    assert len(results["By region"].data) == 4 and results["By region"].applied == []  # no month column


def test_date_filter_matches_pandas_on_daily_and_datetime_values(seeded_db, store):
    d = store.create("Days")
    w = store.add_widget(d.dashboard_id, "Daily", "", "demo_sales",
                         "SELECT sale_date, SUM(quantity) AS units FROM sales GROUP BY sale_date ORDER BY sale_date",
                         "line", "full", seeded_db)
    flt = Filter(1, d.dashboard_id, "date", "sale_date", "Day")
    result = dsh.run(w, seeded_db, [(flt, ("2025-02-01", "2025-02-28"))])
    expected = result.unfiltered[result.unfiltered["sale_date"].between("2025-02-01", "2025-02-28")]
    assert result.data.values.tolist() == expected.values.tolist() and len(expected) > 0
    stamps = pd.DataFrame({"t": ["2025-02-28 23:59:59", "2025-03-01 00:00:00"]})
    sql, params, _ = dsh.filtered_sql("SELECT 1", [(Filter(2, "d", "date", "t", "T"), ("2025-02-01", "2025-02-28"))],
                                      stamps)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE x (t TEXT)")
    conn.executemany("INSERT INTO x VALUES (?)", [(v,) for v in stamps["t"]])
    kept = conn.execute(sql.replace("SELECT 1", "SELECT * FROM x"), params).fetchall()
    assert kept == [("2025-02-28 23:59:59",)]  # the whole last day is included


def test_category_and_number_filters(board, store, seeded_db):
    region = store.add_filter(board.dashboard_id, "category", "region")
    revenue = store.add_filter(board.dashboard_id, "number", "revenue")
    unfiltered = run_all(board, seeded_db)["By region"].data
    low, high = 65_000, 80_000
    result = run_all(board, seeded_db, [(region, ["East", "West", "South"]), (revenue, (low, high))])["By region"]
    expected = unfiltered[unfiltered["region"].isin(["East", "West", "South"]) & unfiltered["revenue"].between(low, high)]
    assert result.data.values.tolist() == expected.values.tolist() and result.applied == ["Region", "Revenue"]
    monthly = run_all(board, seeded_db, [(revenue, (low, high))])["Monthly revenue"]
    assert monthly.data.empty  # revenue column exists there too; no month is that high


def test_filter_values_are_parameters_not_sql(board, store, seeded_db):
    region = store.add_filter(board.dashboard_id, "category", "region")
    evil = ["East' OR '1'='1", "x'); DROP TABLE sales; --"]
    result = run_all(board, seeded_db, [(region, evil)])["By region"]
    assert result.error is None and result.data.empty
    sql, params, _ = dsh.filtered_sql(board.widgets[1].sql, [(region, evil)], result.unfiltered)
    assert evil[0] not in sql and list(params) == evil
    assert len(run_all(board, seeded_db)["By region"].data) == 4  # sales intact


def test_column_names_are_quoted():
    data = pd.DataFrame({'we"ird col': ["a"]})
    sql, params, _ = dsh.filtered_sql("SELECT 1", [(Filter(1, "d", "category", 'we"ird col', "W"), ["a"])], data)
    assert '"we""ird col" IN (?)' in sql and params == ("a",)


@pytest.mark.parametrize("kind, column, data, expected", [
    ("number", "v", pd.DataFrame({"v": [1, 2]}), True),
    ("number", "v", pd.DataFrame({"v": ["a"]}), False),
    ("date", "m", pd.DataFrame({"m": ["2025-01", "2025-02"]}), True),
    ("date", "m", pd.DataFrame({"m": ["East"]}), False),
    ("category", "missing", pd.DataFrame({"v": [1]}), False),
])
def test_compatibility(kind, column, data, expected):
    assert dsh.compatible(Filter(1, "d", kind, column, "L"), data) is expected


def test_unset_filters_change_nothing(board, store, seeded_db):
    flt = store.add_filter(board.dashboard_id, "category", "region")
    for value in ([], None):
        assert run_all(board, seeded_db, [(flt, value)])["By region"].applied == []


def test_choices_come_from_the_charts_data(board, store, seeded_db):
    results = list(run_all(board, seeded_db).values())
    assert dsh.choices(Filter(1, "d", "category", "region", "R"), results) == ["East", "North", "South", "West"]
    assert dsh.choices(Filter(2, "d", "date", "month", "M"), results) == ("2025-01", "2025-12")
    assert dsh.choices(Filter(3, "d", "category", "nothing", "N"), results) is None


# --- Safety and robustness ----------------------------------------------------------------

@pytest.mark.parametrize("sql", ["SELECT * FROM query_history", "DELETE FROM sales", "SELECT * FROM sqlite_master"])
def test_tampered_stored_sql_is_rejected_when_shown(board, seeded_db, sql):
    conn = sqlite3.connect(config.get_app_db_path())
    with conn:
        conn.execute("UPDATE dashboard_widgets SET sql = ? WHERE position = 0", (sql,))
    conn.close()
    result = dsh.run(dsh.store().get(board.dashboard_id).widgets[0], seeded_db)
    assert result.error and result.data is None


def test_widget_of_an_imported_dataset_stays_in_its_scope(seeded_db, store):
    from tests.test_dataset_integration import ORDERS_CSV, STAFF_CSV, import_csv
    import_csv("Orders", ORDERS_CSV)
    import_csv("Staff", STAFF_CSV)
    d = store.create("Imported")
    w = store.add_widget(d.dashboard_id, "Orders", "", "orders", "SELECT customer, SUM(amount) AS total FROM orders "
                         "GROUP BY customer", "bar", "half", seeded_db)
    assert dsh.run(w, seeded_db).data["total"].sum() == pytest.approx(37.75)
    with pytest.raises(DashboardError):
        store.add_widget(d.dashboard_id, "Staff", "", "orders", "SELECT * FROM staff", "bar", "half", seeded_db)


def test_removed_dataset_shows_an_error(seeded_db, store):
    from tests.test_dataset_integration import STAFF_CSV, import_csv
    import_csv("Staff", STAFF_CSV)
    d = store.create("X")
    w = store.add_widget(d.dashboard_id, "Staff", "", "staff", "SELECT * FROM staff", "bar", "half", seeded_db)
    data_access.catalog().remove("staff")
    assert dsh.run(w, seeded_db).error == "The dataset of this chart is no longer available."


def test_chart_type_falls_back_when_it_no_longer_fits(board, store, seeded_db):
    region = store.add_filter(board.dashboard_id, "category", "region")
    result = run_all(board, seeded_db, [(region, ["East"])])["By region"]  # one row: no pie
    assert result.chart.kind != "pie" and "does not suit" in result.note


# --- Export -------------------------------------------------------------------------------

def test_export_has_the_definition_and_no_data(board, store):
    store.add_filter(board.dashboard_id, "category", "region")
    exported = json.loads(dsh.export_json(board.dashboard_id))
    assert exported["format"] == "insightsql-dashboard" and exported["name"] == "Sales overview"
    assert [w["title"] for w in exported["widgets"]] == ["Monthly revenue", "By region", "By category"]
    assert exported["widgets"][1]["dataset_name"] == "Demo sales" and exported["filters"][0]["column"] == "region"
    assert set(exported) == {"format", "version", "name", "description", "exported_at", "widgets", "filters"}
    assert all(set(w) == {"title", "question", "dataset_id", "dataset_name", "sql", "chart_kind", "width"}
               for w in exported["widgets"])
    assert set(exported["filters"][0]) == {"kind", "column", "label"}
    text = json.dumps(exported)
    assert "102900" not in text and "Laptop Pro" not in text  # no result data


def test_free_name_numbers_copies(board, store):
    first = store.duplicate(board.dashboard_id, store.free_name("Sales overview (copy)"))
    second = store.duplicate(board.dashboard_id, store.free_name("Sales overview (copy)"))
    assert (first.name, second.name) == ("Sales overview (copy)", "Sales overview (copy) (2)")
    assert store.free_name("sales OVERVIEW") == "sales OVERVIEW (2)"  # names differing only in case are avoided


def test_number_categories_sort_numerically(seeded_db, store):
    d = store.create("Products")
    store.add_widget(d.dashboard_id, "Units", "", "demo_sales",
                     "SELECT product_id, SUM(quantity) AS units FROM sales GROUP BY product_id", "bar", "half", seeded_db)
    flt = store.add_filter(d.dashboard_id, "category", "product_id")
    results = [dsh.run(w, seeded_db) for w in store.get(d.dashboard_id).widgets]
    options = dsh.choices(flt, results)
    assert options == sorted(options) and options[:3] == [1, 2, 3]
    picked = dsh.run(store.get(d.dashboard_id).widgets[0], seeded_db, [(flt, options[:2])])
    assert picked.data["product_id"].tolist() == [1, 2]


def test_removing_a_filter_updates_the_dashboard_time(board, store):
    flt = store.add_filter(board.dashboard_id, "category", "region")
    conn = sqlite3.connect(config.get_app_db_path())
    with conn:
        conn.execute("UPDATE dashboards SET updated_at = '2000-01-01' WHERE dashboard_id = ?", (board.dashboard_id,))
    conn.close()
    store.remove_filter(flt.filter_id)
    assert store.get(board.dashboard_id).updated_at > "2000-01-01" and not store.get(board.dashboard_id).filters
