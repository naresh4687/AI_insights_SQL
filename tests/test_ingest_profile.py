"""Type detection, profiling and validation of uploaded data."""

import pandas as pd
import pytest

from src.ingest import types
from src.ingest.profiling import find_outliers, profile
from src.ingest.readers import Limits, ReadOptions, read_file
from src.ingest.validation import ERROR, PASSED, WARNING, has_errors, summary, validate

LIMITS = Limits(max_bytes=1_000_000, max_rows=1_000, max_columns=20)


def raw_of(text: str):
    return read_file("data.csv", text.encode(), ReadOptions(), LIMITS)


def checks_of(text: str):
    raw = raw_of(text)
    return validate(raw, profile(raw))


def codes(checks, level=None):
    return [c.code for c in checks if level is None or c.level == level]


# --- Type detection ---------------------------------------------------------------

@pytest.mark.parametrize("values, kind", [
    (["1", "-2", "+3"], "integer"),
    (["1.5", "2", ".5", "1e3"], "float"),
    (["9223372036854775808"], "float"),  # beyond 64-bit integers
    (["yes", "No", "TRUE", "false"], "boolean"),
    (["2025-01-31", "2025-12-01"], "date"),
    (["31/01/2025", "01/02/2025"], "date"),
    (["2025-01-31 10:00:00"], "datetime"),
    (["Pen", "Desk"], "text"),
    (["007", "123"], "text"),  # leading zeros are kept
    (["1", "0"], "integer"),  # not boolean: 0/1 are numbers unless the user chooses otherwise
    ([], "empty"),
])
def test_detection(values, kind):
    assert types.detect(pd.Series(values, dtype=object)).kind == kind


def test_ambiguous_day_month_order_is_reported():
    d = types.detect(pd.Series(["03/04/2025", "05/06/2025"]))
    assert d.kind == "date" and d.date_format == "%d/%m/%Y" and "%m/%d/%Y" in d.ambiguous_formats


def test_unambiguous_month_first_dates():
    d = types.detect(pd.Series(["12/31/2025", "01/15/2025"]))
    assert d.date_format == "%m/%d/%Y" and not d.ambiguous_formats


def test_mostly_numeric_and_mostly_dates_stay_text_with_examples():
    numeric = types.detect(pd.Series(["1", "2", "3", "4", "x"]))
    assert (numeric.kind, numeric.mostly, numeric.mismatches, numeric.mismatch_examples) == ("text", "float", 1, ("x",))
    dates = types.detect(pd.Series(["2025-01-01", "2025-02-30", "2025-03-01", "2025-04-01", "2025-05-01"]))
    assert (dates.kind, dates.mostly, dates.mismatch_examples) == ("text", "date", ("2025-02-30",))


@pytest.mark.parametrize("values, kind, expected, failed", [
    (["1", "2.0", "x"], "integer", [1, 2, None], 1),
    (["1.5", "abc"], "float", [1.5, None], 1),
    (["yes", "no", "1", "0", "maybe"], "boolean", [1, 0, 1, 0, None], 1),
    (["31/01/2025", "31/02/2025"], "date", ["2025-01-31", None], 1),
    (["99999999999999999999"], "integer", [None], 1),
    (["12345678901234567"], "integer", [12345678901234567], 0),  # exact, no float rounding
])
def test_conversion_counts_failures(values, kind, expected, failed):
    fmt = "%d/%m/%Y" if kind == "date" else None
    converted, count = types.convert(pd.Series(values), kind, fmt)
    assert [None if pd.isna(v) else v for v in converted] == expected and count == failed


def test_outliers_use_tukey_fences_and_need_enough_values():
    assert find_outliers(pd.Series([10, 11, 12, 13, 12, 11, 10, 500])).count == 1
    assert find_outliers(pd.Series([1, 2, 1000])) is None  # too few values to judge
    assert find_outliers(pd.Series([5] * 10)) is None  # no spread


# --- Profile ----------------------------------------------------------------------

def test_profile_counts():
    raw = raw_of("a,b,c\n1, x ,\n1, x ,\n,,\n3,y,\n")
    p = profile(raw)
    assert (p.rows, p.columns, p.duplicate_rows, p.empty_rows) == (4, 3, 1, 1)
    a, b, c = p.columns_profile
    assert (a.missing, a.distinct, a.detection.kind, a.minimum, a.maximum) == (1, 2, "integer", 1.0, 3.0)
    assert (b.whitespace, b.detection.kind) == (2, "text")
    assert c.detection.kind == "empty" and p.empty_columns == [c]


def test_profile_does_not_change_the_raw_table():
    raw = raw_of("a,b\n 1 ,N/A\n")
    before = raw.frame.copy()
    profile(raw)
    pd.testing.assert_frame_equal(raw.frame, before)


# --- Validation -------------------------------------------------------------------

def test_clean_file_passes():
    checks = checks_of("id,name\n1,Pen\n2,Desk\n")
    assert not has_errors(checks) and summary(checks)[WARNING] == 0
    assert set(codes(checks, PASSED)) >= {"readable", "unique_headers", "no_duplicate_rows", "consistent_types",
                                          "no_missing"}


@pytest.mark.parametrize("text, code, level", [
    ("a,b\n", "no_rows", ERROR),
    ("a,b\n1,2,3\n", "long_rows", ERROR),
    ("a,b\n1\n", "short_rows", WARNING),
    ("a,b\n1,2\n\n3,4\n", "blank_lines", WARNING),
    ("a,A\n1,2\n", "duplicate_header", WARNING),
    ("a,\n1,2\n", "empty_header", WARNING),
    ("a,b\n1,2\n1,2\n", "duplicate_rows", WARNING),
    ("a,b\n1,2\n,\n", "empty_rows", WARNING),
    ("a,b\n1,\n2,\n", "empty_column", WARNING),
    ("a,b\n1,x\n,y\n", "missing_values", WARNING),
    ("a\nN/A\n1\n", "missing_marker", WARNING),
    ("a\n1\n2\n3\n4\nfive\n", "mixed_types", WARNING),
    ("d\n2025-01-01\n2025-01-02\n2025-01-03\n2025-01-04\n2025-02-30\n", "invalid_dates", WARNING),
    ("d\n03/04/2025\n05/06/2025\n", "ambiguous_dates", WARNING),
    ("zip\n007\n010\n", "leading_zeros", WARNING),
    ("a\n x\n", "whitespace", WARNING),
    ("n\n10\n11\n12\n13\n12\n11\n10\n500\n", "outliers", WARNING),
])
def test_each_problem_is_reported(text, code, level):
    checks = checks_of(text)
    assert code in codes(checks, level), [c.message for c in checks]


def test_errors_come_first_and_block():
    checks = checks_of("a,b\n1,2,3\n1,2\n")
    assert checks[0].level == ERROR and has_errors(checks)


def test_messages_name_duplicate_columns_uniquely():
    checks = checks_of("r,r\n1,\n,2\n")
    missing = [c.message for c in checks if c.code == "missing_values"]
    assert any("r (column 1)" in m for m in missing) and any("r (column 2)" in m for m in missing)


def test_long_rows_list_file_lines():
    checks = checks_of("a,b\n1,2\n1,2,3\n4,5,6\n")
    message = next(c.message for c in checks if c.code == "long_rows")
    assert "lines 3, 4" in message and "never dropped silently" in message
