"""Import Data page (AppTest: the real app script and widgets, no browser)."""

import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config, demo_queries
from src.catalog import DatasetCatalog
from tests.test_ingest_readers import workbook_bytes

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
IMPORT, ANALYST = "views/import_data.py", "views/analyst.py"
CSV = b"Order ID,Amount,Region,Region\n1,10.5,East,e\n2,N/A,West,w\n2,N/A,West,w\n3,7,east,\n"


@pytest.fixture
def app(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.switch_page(IMPORT).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def upload(at, name="orders.csv", content=CSV):
    nonce = at.session_state["upload_nonce"]
    at.file_uploader(key=f"import_file_{nonce}").upload(name, content).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def html(at) -> str:
    return "\n".join(element.proto.body for element in at.get("html"))


def frames(at) -> dict:
    """The page's tables by role, identified by their distinctive columns."""
    found = {}
    values = [d.value for d in at.dataframe]
    for i, frame in enumerate(values):
        columns = list(frame.columns)
        if columns and str(columns[0]).startswith("1 · "):
            found["original"] = frame
        elif "Detected type" in columns:
            found["profile"] = frame
        elif "Keep" in columns:
            found["settings"] = frame
        elif "Stored as" in columns:
            found["types"], found["cleaned"] = frame, values[i - 1]
        elif "Dataset id" in columns:
            found["datasets"] = frame
    return found


def texts(elements):
    return [e.value for e in elements]


def sections(at):
    return [m for m in texts(at.markdown) if m.startswith("**")]


def imported_tables():
    path = config.get_datasets_db_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    finally:
        conn.close()


def test_page_is_in_the_navigation_and_starts_empty(app):
    assert sections(app) == ["**1. Choose a file**", "**Imported datasets**"]
    assert "No imported datasets yet" in html(app)


def test_upload_shows_every_step(app):
    upload(app)
    assert sections(app) == [
        "**1. Choose a file**", "**2. Original data** (as in the file, before any change)", "**3. Data quality**",
        "**4. Choose how to clean the data**", "**Columns**", "**5. Cleaned data** (what will be saved)",
        "**6. Summary of changes**", "**7. Save as a dataset**", "**Imported datasets**"]
    original = frames(app)["original"]
    assert list(original.columns) == ["1 · Order ID", "2 · Amount", "3 · Region", "4 · Region"]
    assert original.iloc[1, 1] == "N/A"  # shown exactly as in the file
    warnings = " ".join(texts(app.warning))
    assert "exact copies" in warnings and "'N/A' appears 2 times" in warnings and "Region' appears 2 times" in warnings
    cleaned = frames(app)["cleaned"]
    assert list(cleaned.columns) == ["order_id", "amount", "region", "region_2"]


def test_unreadable_file_is_explained_and_nothing_is_saved(app):
    upload(app, content="name\ncafé\n".encode("cp1252"))
    assert "not UTF-8" in " ".join(texts(app.error))
    assert not app.button and imported_tables() == []


def test_encoding_option_reads_the_file(app):
    upload(app, content="name\ncafé\n".encode("cp1252"))
    app.selectbox(key="import_encoding").set_value("cp1252").run()
    assert frames(app)["original"].iloc[0, 0] == "café"


def test_blocking_validation_error_hides_saving(app):
    upload(app, content=b"a,b\n1,2,3\n")
    assert "more values than there are column headers" in " ".join(texts(app.error))
    assert "**7. Save as a dataset**" not in sections(app)


def test_destructive_change_needs_confirmation_then_saves(app):
    upload(app)
    app.toggle(key="import_duplicates").set_value(True).run()
    assert app.button(key="import_save").disabled
    app.checkbox(key="import_confirm").check().run()
    assert not app.button(key="import_save").disabled
    app.button(key="import_save").click().run()
    assert not app.exception
    assert texts(app.success) == ["Saved **orders** as dataset `orders` (3 rows, 4 columns)."]
    assert imported_tables() == ["orders"]
    assert app.session_state["upload_nonce"] == 1  # the uploader is cleared for the next file
    assert sections(app) == ["**1. Choose a file**", "**Imported datasets**"]
    listed = frames(app)["datasets"]
    assert listed["Dataset id"].tolist() == ["orders"] and listed["Rows"].tolist() == [3]


def test_column_options_change_the_result(app):
    upload(app)
    app.selectbox(key="import_column").set_value(3).run()
    app.checkbox(key="import_keep_3").uncheck().run()
    app.selectbox(key="import_column").set_value(0).run()
    app.text_input(key="import_name_0").set_value("id").run()
    assert list(frames(app)["cleaned"].columns) == ["id", "amount", "region"]
    settings = frames(app)["settings"]
    assert settings["Keep"].tolist() == [True, True, True, False]  # kept after switching columns
    assert "Remove columns" in html(app) and app.button(key="import_save").disabled


def test_markers_and_type_conversion(app):
    upload(app)
    app.multiselect(key="import_markers").set_value(["N/A"]).run()
    types_table = frames(app)["types"]
    assert dict(zip(types_table["Column"], types_table["Type"]))["amount"] == "Decimal number"


def test_invalid_column_name_blocks_saving(app):
    upload(app)
    app.text_input(key="import_name_0").set_value("Bad Name").run()
    assert "cannot be used as a column name" in " ".join(texts(app.error))
    assert app.button(key="import_save").disabled


def test_duplicate_dataset_name_is_refused(app):
    upload(app, content=b"a,b\n1,2\n")
    app.button(key="import_save").click().run()
    upload(app, content=b"a,b\n3,4\n")
    app.button(key="import_save").click().run()
    assert "'orders' already exists" in " ".join(texts(app.error))
    assert imported_tables() == ["orders"]


def test_excel_worksheet_selection(app):
    content = workbook_bytes({"First": [["a"], [1]], "Second": [["b", "c"], ["x", 2], ["y", 3]]})
    upload(app, "book.xlsx", content)
    assert list(frames(app)["original"].columns) == ["1 · a"]
    app.selectbox(key="import_sheet").set_value("Second").run()
    assert list(frames(app)["original"].columns) == ["1 · b", "2 · c"]


def test_demo_mode_still_works_after_an_import(app):
    upload(app, content=b"a,b\n1,2\n")
    app.button(key="import_save").click().run()
    app.switch_page(ANALYST).run()
    app.chat_input(key="chat_question").set_value(demo_queries.demo_questions()[1]).run()
    assert not app.exception and app.session_state["chat"][-1].answer is not None
    assert DatasetCatalog(config.get_app_db_path()).get("orders") is not None
