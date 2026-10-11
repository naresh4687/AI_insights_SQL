"""Validation results for an uploaded file: errors (block the import), warnings and passed checks."""

from collections import Counter
from dataclasses import dataclass

from src.ingest.profiling import DatasetProfile
from src.ingest.readers import RawTable

ERROR, WARNING, PASSED = "error", "warning", "passed"
_LEVEL_ORDER = {ERROR: 0, WARNING: 1, PASSED: 2}


@dataclass(frozen=True)
class Check:
    level: str  # ERROR, WARNING or PASSED
    code: str
    message: str
    column: str | None = None
    count: int | None = None


def has_errors(checks: list[Check]) -> bool:
    return any(c.level == ERROR for c in checks)


def summary(checks: list[Check]) -> dict[str, int]:
    counts = Counter(c.level for c in checks)
    return {level: counts.get(level, 0) for level in (ERROR, WARNING, PASSED)}


def _lines(numbers: list[int], limit: int = 5) -> str:
    shown = ", ".join(f"{n:,}" for n in numbers[:limit])
    return shown + (f" and {len(numbers) - limit:,} more" if len(numbers) > limit else "")


def _pct(count: int, total: int) -> str:
    return f"{count / total:.0%}" if total else "0%"


def validate(raw: RawTable, profile: DatasetProfile) -> list[Check]:
    """Checks on the file as uploaded, sorted errors first."""
    checks: list[Check] = []

    def add(level: str, code: str, message: str, column: str | None = None, count: int | None = None) -> None:
        checks.append(Check(level, code, message, column, count))

    source = f"Read as {raw.file_type.upper()}"
    if raw.file_type == "csv":
        source += f" ({raw.encoding}, delimiter {raw.delimiter!r})"
    else:
        source += f" (worksheet '{raw.sheet}')"
    add(PASSED, "readable", f"{source}: {raw.rows:,} rows and {raw.columns:,} columns.")

    # Structure
    if raw.rows == 0:
        add(ERROR, "no_rows", "The file has a header row but no data rows.")
    if raw.long_rows:
        add(ERROR, "long_rows", f"{len(raw.long_rows):,} rows have more values than there are column headers "
            f"(lines {_lines(raw.long_rows)}). Fix the file or choose another delimiter; extra values are "
            "never dropped silently.", count=len(raw.long_rows))
    if raw.short_rows:
        add(WARNING, "short_rows", f"{len(raw.short_rows):,} rows have fewer values than there are columns "
            f"(lines {_lines(raw.short_rows)}); the missing cells are treated as empty.", count=len(raw.short_rows))
    if raw.blank_lines:
        add(WARNING, "blank_lines", f"{raw.blank_lines:,} blank lines were skipped.", count=raw.blank_lines)

    counts = Counter(h.lower() for h in raw.headers if h)
    spelled = {}  # the first spelling in the file, for messages
    for h in raw.headers:
        spelled.setdefault(h.lower(), h)
    duplicates = sorted(h for h, n in counts.items() if n > 1)
    for key in duplicates:
        header = spelled[key]
        add(WARNING, "duplicate_header", f"The column name '{header}' appears {counts[key]} times (ignoring "
            "upper/lower case). The copies get numbered names; you can rename them.", column=header)
    if not duplicates:
        add(PASSED, "unique_headers", "Every column name is unique.")
    for column in profile.columns_profile:
        if not column.header:
            add(WARNING, "empty_header", f"Column {column.position + 1} has no name; it will be called "
                f"column_{column.position + 1} unless you rename it.", column=column.label)

    # Rows
    if profile.duplicate_rows:
        add(WARNING, "duplicate_rows", f"{profile.duplicate_rows:,} rows are exact copies of an earlier row. "
            "They are kept unless you choose to remove them.", count=profile.duplicate_rows)
    elif raw.rows:
        add(PASSED, "no_duplicate_rows", "No duplicate rows.")
    if profile.empty_rows:
        add(WARNING, "empty_rows", f"{profile.empty_rows:,} rows have no values at all.", count=profile.empty_rows)

    # Columns
    issues = False
    for column in profile.columns_profile:
        label, d = column.label, column.detection
        if d.kind == "empty":
            if raw.rows:
                add(WARNING, "empty_column", f"'{label}' has no values.", column=label)
            continue
        if column.missing:
            add(WARNING, "missing_values", f"'{label}': {column.missing:,} empty values "
                f"({_pct(column.missing, raw.rows)}).", column=label, count=column.missing)
        for marker, n in column.markers.items():
            add(WARNING, "missing_marker", f"'{label}': the text '{marker}' appears {n:,} times. It may mean "
                "'no value'; it is kept as text unless you choose to treat it as empty.", column=label, count=n)
        if d.mostly == "float":
            issues = True
            add(WARNING, "mixed_types", f"'{label}': most values are numbers but {d.mismatches:,} are not "
                f"(e.g. {_quoted(d.mismatch_examples)}). The column stays text unless you convert it.",
                column=label, count=d.mismatches)
        if d.mostly == "date":
            issues = True
            add(WARNING, "invalid_dates", f"'{label}': most values are dates but {d.mismatches:,} are not valid "
                f"dates (e.g. {_quoted(d.mismatch_examples)}). The column stays text unless you convert it.",
                column=label, count=d.mismatches)
        if d.ambiguous_formats:
            add(WARNING, "ambiguous_dates", f"'{label}': the dates can be read as {d.date_format} or "
                f"{', '.join(d.ambiguous_formats)}. {d.date_format} is used; choose another if that is wrong.",
                column=label)
        if d.leading_zeros:
            add(WARNING, "leading_zeros", f"'{label}': some values start with 0 (such as codes or ZIP codes), "
                "so the column is kept as text to preserve them.", column=label)
        if column.whitespace:
            add(WARNING, "whitespace", f"'{label}': {column.whitespace:,} values have spaces at the start or end.",
                column=label, count=column.whitespace)
        if column.outliers:
            o = column.outliers
            add(WARNING, "outliers", f"'{label}': {o.count:,} possible outliers outside {o.low:,.4g} to "
                f"{o.high:,.4g}. They are flagged, not removed.", column=label, count=o.count)
    if raw.rows and not issues:
        add(PASSED, "consistent_types", "Every column has values of one consistent type.")
    if raw.rows and not any(c.missing for c in profile.columns_profile if c.detection.kind != "empty"):
        add(PASSED, "no_missing", "No missing values.")

    return sorted(checks, key=lambda c: _LEVEL_ORDER[c.level])


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)
