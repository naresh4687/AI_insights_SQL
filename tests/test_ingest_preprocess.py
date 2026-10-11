"""Cleaning uploaded data (src/ingest/preprocess.py): options, reporting and data integrity."""

import pandas as pd
import pytest

from src.ingest.preprocess import CleanOptions, ColumnOptions, clean, normalize_name
from src.ingest.readers import Limits, ReadOptions, read_file

LIMITS = Limits(max_bytes=1_000_000, max_rows=10_000, max_columns=50)

ORDERS = (
    "Order ID,Order Date,Amount,Region,Zip,Paid\n"
    "1, 2025-01-31 ,10.5,East,007,yes\n"
    "2,2025-02-01,N/A,West,010,no\n"
    "2,2025-02-01,N/A,West,010,no\n"
    ",,,,,\n"
    "3,2025-02-02,1000,east,020,yes\n"
    "4,2025-02-03,12,North,030,no\n"
    "5,2025-02-04,11,North,,no\n"
    "6,2025-02-05,13,,050,no\n"
    "7,2025-02-06,14,North,060,no\n"
    "8,2025-02-07,12,North,070,no\n"
)


def raw_of(text: str = ORDERS):
    return read_file("orders.csv", text.encode(), ReadOptions(), LIMITS)


def step(result, name):
    return next(s for s in result.steps if s.name == name)


def names(result):
    return [s.name for s in result.steps]


# --- Defaults: safe, typed, nothing hidden ----------------------------------------

def test_defaults_type_columns_and_only_remove_empty_rows():
    result = clean(raw_of(), CleanOptions())
    assert result.ok
    assert list(result.frame.columns) == ["order_id", "order_date", "amount", "region", "zip", "paid"]
    kinds = {c.name: c.kind for c in result.columns}
    assert kinds == {"order_id": "integer", "order_date": "date", "amount": "text", "region": "text",
                     "zip": "text", "paid": "boolean"}
    assert len(result.frame) == 9  # 10 data rows in the file, 1 completely empty
    assert step(result, "Remove empty rows").rows == 1
    assert result.frame["zip"].iloc[0] == "007"  # leading zeros kept
    assert result.frame["amount"].iloc[1] == "N/A"  # markers are not treated as empty unless chosen
    assert result.destructive_steps == []


def test_raw_table_is_never_modified():
    raw = raw_of()
    before = raw.frame.copy()
    clean(raw, CleanOptions(missing_markers=("N/A",), remove_duplicate_rows=True,
                            columns={2: ColumnOptions(missing="fill_median")}))
    pd.testing.assert_frame_equal(raw.frame, before)


def test_same_input_and_options_give_the_same_result():
    options = CleanOptions(missing_markers=("N/A",), remove_duplicate_rows=True, outliers="remove_rows",
                           columns={2: ColumnOptions(missing="fill_mean"), 3: ColumnOptions(text_case="title")})
    first, second = clean(raw_of(), options), clean(raw_of(), CleanOptions.from_dict(options.to_dict()))
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.steps == second.steps


def test_options_round_trip_through_json_types():
    options = CleanOptions(missing_markers=("N/A", "-"), columns={4: ColumnOptions(keep=False, name="x")})
    assert CleanOptions.from_dict(options.to_dict()) == options


# --- Every removed row is accounted for --------------------------------------------

@pytest.mark.parametrize("options", [
    CleanOptions(),
    CleanOptions(remove_duplicate_rows=True),
    CleanOptions(missing_markers=("N/A",), columns={2: ColumnOptions(missing="drop_rows")}),
    CleanOptions(outliers="remove_rows", missing_markers=("N/A",)),
    CleanOptions(drop_empty_rows=False),
])
def test_row_counts_add_up(options):
    raw = raw_of()
    result = clean(raw, options)
    assert raw.rows - sum(s.rows for s in result.steps) == len(result.frame)


def test_every_row_removal_except_empty_rows_needs_confirmation():
    result = clean(raw_of(), CleanOptions(missing_markers=("N/A",), remove_duplicate_rows=True,
                                          columns={2: ColumnOptions(missing="drop_rows")}))
    for s in result.steps:
        if s.rows and s.name != "Remove empty rows":
            assert s.destructive, s


# --- Individual options -------------------------------------------------------------

def test_trim_whitespace_reports_cells_and_can_be_turned_off():
    trimmed = clean(raw_of(), CleanOptions())
    assert step(trimmed, "Trim spaces").cells == 1 and trimmed.frame["order_date"].iloc[0] == "2025-01-31"
    untrimmed = clean(raw_of("a\n x \n"), CleanOptions(trim_whitespace=False))
    assert untrimmed.frame["a"].iloc[0] == " x " and "Trim spaces" not in names(untrimmed)


def test_markers_become_empty_only_when_chosen_and_are_destructive():
    result = clean(raw_of(), CleanOptions(missing_markers=("N/A",)))
    s = step(result, "Treat markers as empty")
    assert s.cells == 2 and s.destructive
    assert {c.name: c.kind for c in result.columns}["amount"] == "float"


def test_duplicate_rows_removed_only_when_chosen():
    assert clean(raw_of(), CleanOptions()).frame["order_id"].tolist().count(2) == 2
    result = clean(raw_of(), CleanOptions(remove_duplicate_rows=True))
    assert result.frame["order_id"].tolist().count(2) == 1
    assert step(result, "Remove duplicate rows").rows == 1


def test_remove_and_rename_columns():
    result = clean(raw_of(), CleanOptions(columns={4: ColumnOptions(keep=False), 0: ColumnOptions(name="id")}))
    assert list(result.frame.columns) == ["id", "order_date", "amount", "region", "paid"]
    s = step(result, "Remove columns")
    assert s.columns == 1 and s.destructive and result.removed_columns == ["Zip"]


def test_empty_columns_removed_only_when_chosen():
    raw = raw_of("a,b\n1,\n2,\n")
    assert list(clean(raw, CleanOptions()).frame.columns) == ["a", "b"]
    result = clean(raw, CleanOptions(drop_empty_columns=True))
    assert list(result.frame.columns) == ["a"] and not step(result, "Remove empty columns").destructive


@pytest.mark.parametrize("header, expected", [
    ("Order ID", "order_id"), ("  Total (€)  ", "total"), ("2024 Sales", "c_2024_sales"), ("", "column_3"),
    ("select", "select_"), ("Order", "order_"), ("Café", "cafe"), ("தமிழ்", "column_3"), ("a" * 80, "a" * 60),
    ("rowid", "rowid_"),
])
def test_normalize_name(header, expected):
    assert normalize_name(header, 2) == expected


def test_duplicate_headers_get_numbered_names():
    result = clean(raw_of("a,A,a\n1,2,3\n"), CleanOptions())
    assert list(result.frame.columns) == ["a", "a_2", "a_3"]


@pytest.mark.parametrize("name", ["Has Space", "1abc", "drop", 'x";--', "a" * 64])
def test_invalid_user_names_block_saving(name):
    result = clean(raw_of("a,b\n1,2\n"), CleanOptions(columns={0: ColumnOptions(name=name)}))
    assert not result.ok and result.checks[0].code == "invalid_name"


def test_automatic_names_make_way_for_user_names():
    result = clean(raw_of("a,b\n1,2\n"), CleanOptions(columns={1: ColumnOptions(name="a")}))
    assert result.ok and list(result.frame.columns) == ["a_2", "a"]


def test_user_name_clash_blocks_saving():
    result = clean(raw_of("a,b,c\n1,2,3\n"), CleanOptions(columns={1: ColumnOptions(name="x"),
                                                                    2: ColumnOptions(name="x")}))
    assert any(c.code == "duplicate_name" for c in result.checks)


def test_text_case():
    result = clean(raw_of(), CleanOptions(columns={3: ColumnOptions(text_case="title")}))
    assert result.frame["region"].iloc[3] == "East" and step(result, "Text case").cells == 1


def test_explicit_type_conversion_reports_failures():
    raw = raw_of("amount\n10\nabc\n12.5\n")
    result = clean(raw, CleanOptions(columns={0: ColumnOptions(type="float")}))
    s = step(result, "Convert 'amount'")
    assert s.cells == 1 and s.destructive and "'abc'" in s.detail
    assert result.frame["amount"].isna().tolist() == [False, True, False]


def test_date_format_choice_and_standardisation():
    raw = raw_of("d\n03/04/2025\n05/06/2025\n")
    assert clean(raw, CleanOptions()).frame["d"].tolist() == ["2025-04-03", "2025-06-05"]  # day first
    month_first = clean(raw, CleanOptions(columns={0: ColumnOptions(date_format="%m/%d/%Y")}))
    assert month_first.frame["d"].tolist() == ["2025-03-04", "2025-05-06"]


def test_invalid_dates_need_explicit_conversion():
    raw = raw_of("d\n2025-01-01\n2025-02-30\n2025-03-01\n")
    assert clean(raw, CleanOptions()).frame["d"].tolist() == ["2025-01-01", "2025-02-30", "2025-03-01"]
    result = clean(raw, CleanOptions(columns={0: ColumnOptions(type="date")}))
    assert result.frame["d"].tolist()[1] is None and step(result, "Convert 'd'").destructive


def test_datetime_format_must_match_type():
    result = clean(raw_of("d\n2025-01-01\n"), CleanOptions(columns={0: ColumnOptions(type="datetime")}))
    assert any(c.code == "date_format" for c in result.checks)


@pytest.mark.parametrize("action, expected", [
    ("fill_value", 0.0), ("fill_mean", 11.5), ("fill_median", 11.5), ("fill_mode", 10.0)])
def test_fill_missing_numbers(action, expected):
    # Two columns: in a one-column CSV an empty value is a blank line, which is skipped (and reported).
    raw = raw_of("a,k\n10,1\n,2\n13,3\n" if action != "fill_mode" else "a,k\n10,1\n,2\n13,3\n10,4\n13,5\n")
    result = clean(raw, CleanOptions(columns={0: ColumnOptions(type="float", missing=action, fill_value="0")}))
    assert result.frame["a"].iloc[1] == expected
    assert step(result, "Fill 'a'").destructive and step(result, "Fill 'a'").cells == 1


def test_fill_integer_mean_is_rounded_and_stays_integer():
    result = clean(raw_of("a,k\n1,x\n,y\n2,z\n"), CleanOptions(columns={0: ColumnOptions(missing="fill_mean")}))
    assert result.columns[0].kind == "integer" and result.frame["a"].tolist() == [1, 2, 2]


@pytest.mark.parametrize("column, fill", [
    (ColumnOptions(type="integer", missing="fill_value", fill_value="abc"), "not a valid integer"),
    (ColumnOptions(type="text", missing="fill_mean"), "not numeric"),
    (ColumnOptions(type="integer", missing="fill_value", fill_value="  "), "not a valid"),
])
def test_invalid_fill_blocks_saving(column, fill):
    result = clean(raw_of("a,k\n1,x\n,y\n"), CleanOptions(columns={0: column}))
    assert not result.ok and fill in result.checks[0].message


def test_fill_date_accepts_any_supported_format():
    result = clean(raw_of("d,k\n2025-01-01,x\n,y\n"), CleanOptions(columns={0: ColumnOptions(missing="fill_value",
                                                                                       fill_value="31/12/2025")}))
    assert result.frame["d"].tolist() == ["2025-01-01", "2025-12-31"]


def test_outliers_flagged_by_default_and_removed_only_when_chosen():
    raw = raw_of("amount\n" + "\n".join(["10", "11", "12", "13", "12", "11", "10", "12", "1000"]) + "\n")
    flagged = clean(raw, CleanOptions())
    assert flagged.outliers["amount"].count == 1 and 1000 in flagged.frame["amount"].tolist()
    assert not step(flagged, "Flag outliers").destructive
    removed = clean(raw, CleanOptions(outliers="remove_rows"))
    assert 1000 not in removed.frame["amount"].tolist() and len(removed.frame) == 8
    assert step(removed, "Remove outliers").destructive and step(removed, "Remove outliers").rows == 1


def test_required_columns():
    raw = raw_of("a,b\n1,\n2,x\n")
    missing = clean(raw, CleanOptions(columns={1: ColumnOptions(required=True)}))
    assert any(c.code == "required_missing" for c in missing.checks)
    handled = clean(raw, CleanOptions(columns={1: ColumnOptions(required=True, missing="drop_rows")}))
    assert handled.ok and handled.columns[1].required
    removed = clean(raw, CleanOptions(columns={1: ColumnOptions(required=True, keep=False)}))
    assert any(c.code == "required_removed" for c in removed.checks)


def test_removing_everything_is_an_error():
    raw = raw_of("a\n1\n")
    assert any(c.code == "no_columns" for c in clean(raw, CleanOptions(columns={0: ColumnOptions(keep=False)})).checks)
    assert any(c.code == "no_rows" for c in clean(raw_of("a,b\n,\n"), CleanOptions()).checks)


def test_invalid_options_are_programming_errors():
    with pytest.raises(ValueError):
        clean(raw_of("a\n1\n"), CleanOptions(outliers="delete_all"))
    with pytest.raises(ValueError):
        clean(raw_of("a\n1\n"), CleanOptions(columns={0: ColumnOptions(type="money")}))
