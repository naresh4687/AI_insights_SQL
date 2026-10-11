"""Configurable, reproducible cleaning of an uploaded table.

``clean(raw, options)`` never modifies ``raw`` and gives the same result for the same input
and options (options can be saved with ``to_dict`` and restored with ``from_dict``).
Every change is reported as a ``Step`` with the rows, columns and values it affected.
Steps that remove rows or columns, or replace values (with empty or with other values),
are marked ``destructive``; the UI requires confirmation for them. Nothing is removed by
default except rows with no values at all, and that is reported too.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field

import pandas as pd

from src.core.models import IDENTIFIER
from src.ingest import types
from src.ingest.profiling import Outliers, find_outliers
from src.ingest.readers import RawTable
from src.ingest.validation import ERROR, Check

COLUMN_TYPES = ("auto",) + types.TYPES
MISSING_ACTIONS = ("keep", "drop_rows", "fill_value", "fill_mean", "fill_median", "fill_mode")
TEXT_CASES = ("none", "lower", "upper", "title")
OUTLIER_ACTIONS = ("flag", "remove_rows")
DATE_KINDS = ("date", "datetime")
NUMERIC_KINDS = ("integer", "float")

# Column names that would need quoting in SQL, or that SQLite treats specially. An imported
# column with such a name gets a trailing underscore (order → order_).
RESERVED_WORDS = frozenset("""
    abort action add after all alter analyze and as asc attach autoincrement before begin between by cascade
    case cast check collate column commit conflict constraint create cross current current_date current_time
    current_timestamp database default deferred delete desc detach distinct drop each else end escape except
    exclusive exists explain fail filter for foreign from full glob group having if ignore immediate in index
    indexed initially inner insert instead intersect into is isnull join key left like limit match natural no
    not notnull null of offset on or order outer over partition plan pragma primary query raise range recursive
    references regexp reindex release rename replace restrict right rollback row rowid oid _rowid_ rows
    savepoint select set table temp temporary then to transaction trigger union unique update using vacuum
    values view virtual when where window with without
""".split())


@dataclass
class ColumnOptions:
    keep: bool = True
    name: str = ""  # "" = the header, normalised
    type: str = "auto"  # one of COLUMN_TYPES
    date_format: str = ""  # "" = the detected format
    missing: str = "keep"  # one of MISSING_ACTIONS
    fill_value: str = ""
    text_case: str = "none"  # one of TEXT_CASES
    required: bool = False  # the column must exist and have no empty values


@dataclass
class CleanOptions:
    trim_whitespace: bool = True
    missing_markers: tuple[str, ...] = ()  # text treated as an empty value, e.g. ("N/A",)
    drop_empty_rows: bool = True  # rows with no values at all
    drop_empty_columns: bool = False
    remove_duplicate_rows: bool = False
    outliers: str = "flag"  # one of OUTLIER_ACTIONS
    columns: dict[int, ColumnOptions] = field(default_factory=dict)  # by column position

    def column(self, position: int) -> ColumnOptions:
        return self.columns.get(position, ColumnOptions())

    def to_dict(self) -> dict:
        data = asdict(self)
        data["missing_markers"] = list(self.missing_markers)
        data["columns"] = {str(k): asdict(v) for k, v in sorted(self.columns.items())}
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CleanOptions":
        data = dict(data)
        data["missing_markers"] = tuple(data.get("missing_markers", ()))
        data["columns"] = {int(k): ColumnOptions(**v) for k, v in data.get("columns", {}).items()}
        return cls(**data)


@dataclass(frozen=True)
class Step:
    name: str
    detail: str
    rows: int = 0  # rows removed
    columns: int = 0  # columns removed or renamed
    cells: int = 0  # values changed
    destructive: bool = False


@dataclass(frozen=True)
class OutputColumn:
    position: int
    header: str  # as in the file
    name: str  # in the stored table
    kind: str  # one of types.TYPES
    required: bool

    @property
    def sql_type(self) -> str:
        return types.SQL_TYPES[self.kind]


@dataclass
class CleanResult:
    frame: pd.DataFrame  # final columns and values
    columns: list[OutputColumn]
    steps: list[Step]
    checks: list[Check]  # problems that block saving
    rows_before: int
    removed_columns: list[str] = field(default_factory=list)
    outliers: dict[str, Outliers] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(c.level == ERROR for c in self.checks)

    @property
    def destructive_steps(self) -> list[Step]:
        return [s for s in self.steps if s.destructive]


def normalize_name(header: str, position: int) -> str:
    """A safe SQL column name from a header: lower case, a-z 0-9 _, not a reserved word."""
    ascii_text = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_") or f"column_{position + 1}"
    if name[0].isdigit():
        name = f"c_{name}"
    name = name[:60].rstrip("_")
    return f"{name}_" if name in RESERVED_WORDS else name


def name_problem(name: str) -> str | None:
    if not IDENTIFIER.match(name):
        return "use only lower-case letters, digits and _, starting with a letter or _ (at most 63 characters)"
    if name in RESERVED_WORDS:
        return "it is a reserved SQL word"
    return None


def clean(raw: RawTable, options: CleanOptions) -> CleanResult:
    _check_options(options)
    run = _Run(raw, options)
    run.trim()
    run.mark_missing()
    run.drop_empty_rows()
    run.remove_columns()
    run.name_columns()
    run.convert_types()
    run.handle_missing()
    run.remove_duplicates()
    run.handle_outliers()
    return run.finish()


def _check_options(options: CleanOptions) -> None:
    if options.outliers not in OUTLIER_ACTIONS:
        raise ValueError(f"Unknown outlier action: {options.outliers}")
    for opts in options.columns.values():
        if opts.type not in COLUMN_TYPES or opts.missing not in MISSING_ACTIONS or opts.text_case not in TEXT_CASES:
            raise ValueError(f"Invalid column options: {opts}")
        if opts.date_format and opts.date_format not in types.FORMATS:
            raise ValueError(f"Unknown date format: {opts.date_format}")


class _Run:
    """The state of one cleaning run; each method is one step, applied in a fixed order."""

    def __init__(self, raw: RawTable, options: CleanOptions):
        self.raw, self.options = raw, options
        self.frame = raw.frame.copy()
        self.steps: list[Step] = []
        self.checks: list[Check] = []
        self.kept = list(range(raw.columns))
        self.names: dict[int, str] = {}
        self.kinds: dict[int, str] = {}
        self.removed: list[str] = []
        self.outliers: dict[str, Outliers] = {}

    def label(self, position: int) -> str:
        return self.raw.headers[position] or f"Column {position + 1}"

    def error(self, code: str, message: str, column: str | None = None) -> None:
        self.checks.append(Check(ERROR, code, message, column))

    def step(self, *args, **kwargs) -> None:
        self.steps.append(Step(*args, **kwargs))

    # 1. Spaces
    def trim(self) -> None:
        text = self.frame.astype(str)
        if not self.options.trim_whitespace or self.frame.empty:
            return
        trimmed = text.apply(lambda s: s.str.strip())
        changed = int((trimmed != text).sum().sum())
        self.frame = trimmed.astype(object)
        if changed:
            self.step("Trim spaces", f"Removed spaces at the start or end of {changed:,} values.", cells=changed)

    # 2. Empty cells and missing-value markers
    def mark_missing(self) -> None:
        if self.frame.empty:
            return
        empty = self.frame.astype(str).apply(lambda s: s.str.strip() == "")
        self.frame = self.frame.mask(empty, None)
        markers = list(self.options.missing_markers)
        if markers:
            hits = self.frame.isin(markers)
            count = int(hits.sum().sum())
            self.frame = self.frame.mask(hits, None)
            if count:
                self.step("Treat markers as empty", f"Replaced {count:,} values written as "
                          f"{', '.join(repr(m) for m in markers)} with empty values.", cells=count, destructive=True)

    # 3. Rows with no values
    def drop_empty_rows(self) -> None:
        if not self.options.drop_empty_rows or self.frame.empty:
            return
        empty = self.frame.isna().all(axis=1)
        count = int(empty.sum())
        if count:
            self.frame = self.frame[~empty]
            self.step("Remove empty rows", f"Removed {count:,} rows that had no values.", rows=count)

    # 4. Columns
    def remove_columns(self) -> None:
        chosen = [p for p in self.kept if not self.options.column(p).keep]
        empty = [p for p in self.kept if p not in chosen and self.options.drop_empty_columns
                 and self.frame[p].isna().all()]
        for positions, name, destructive in ((chosen, "Remove columns", True), (empty, "Remove empty columns", False)):
            if positions:
                labels = [self.label(p) for p in positions]
                self.removed += labels
                self.step(name, f"Removed {len(positions)} columns: {', '.join(labels)}.",
                          columns=len(positions), destructive=destructive)
        self.kept = [p for p in self.kept if p not in chosen and p not in empty]
        self.frame = self.frame[self.kept]
        for position in range(self.raw.columns):
            if self.options.column(position).required and position not in self.kept:
                self.error("required_removed", f"'{self.label(position)}' is required but was removed.",
                           self.label(position))

    # 5. Names
    def name_columns(self) -> None:
        chosen = {p: self.options.column(p).name.strip() for p in self.kept}
        taken = {n for n in chosen.values() if n}
        for position, name in chosen.items():
            if name:
                problem = name_problem(name)
                if problem:
                    self.error("invalid_name", f"'{name}' cannot be used as a column name: {problem}.",
                               self.label(position))
                self.names[position] = name
        for position in self.kept:
            if position in self.names:
                continue
            base = normalize_name(self.raw.headers[position], position)
            name, n = base, 2
            while name in taken:
                name, n = f"{base}_{n}", n + 1
            self.names[position] = name
            taken.add(name)
        counts: dict[str, int] = {}
        for name in self.names.values():
            counts[name] = counts.get(name, 0) + 1
        for name, n in counts.items():
            if n > 1:
                self.error("duplicate_name", f"The column name '{name}' is used {n} times.", name)
        renamed = [p for p in self.kept if self.names[p] != self.raw.headers[p]]
        if renamed:
            pairs = ", ".join(f"{self.label(p)} → {self.names[p]}" for p in renamed[:8])
            more = f" and {len(renamed) - 8} more" if len(renamed) > 8 else ""
            self.step("Column names", f"Renamed {len(renamed)} columns to safe names: {pairs}{more}.",
                      columns=len(renamed))

    # 6. Text case and types
    def convert_types(self) -> None:
        cased, detected = 0, []
        for position in self.kept:
            opts, name = self.options.column(position), self.names[position]
            column = self.frame[position]
            values = column.dropna().astype(str)
            if opts.text_case != "none":
                changed = _apply_case(values, opts.text_case)
                cased += int((changed != values).sum())
                values = changed
            detection = types.detect(values)
            kind = opts.type if opts.type != "auto" else ("text" if detection.kind == "empty" else detection.kind)
            fmt = opts.date_format or detection.date_format or detection.best_format
            if kind in DATE_KINDS and not fmt:
                self.error("date_format", f"Choose a date format for '{name}'.", name)
                kind, fmt = "text", None
            if kind in DATE_KINDS and types.is_datetime_format(fmt) != (kind == "datetime"):
                self.error("date_format", f"The format {fmt} does not match the type {kind} for '{name}'.", name)
                kind = "text"
            converted, failed = types.convert(values, kind, fmt)
            out = pd.Series(pd.NA if kind in NUMERIC_KINDS + ("boolean",) else None, index=column.index,
                            dtype=_dtype(kind))
            out.loc[converted.index] = converted
            self.frame[position] = out
            self.kinds[position] = kind
            if kind != "text":
                detected.append(f"{name}: {kind}" + (f" ({fmt})" if kind in DATE_KINDS else ""))
            if failed:
                examples = ", ".join(repr(v) for v in values[converted.isna()].drop_duplicates().head(3))
                self.step(f"Convert '{name}'", f"{failed:,} values could not be read as {kind} and are now "
                          f"empty (e.g. {examples}).", cells=failed, destructive=True)
        if cased:
            self.step("Text case", f"Changed the letter case of {cased:,} values.", cells=cased)
        if detected:
            self.step("Column types", "Typed columns: " + "; ".join(detected) + ". Other columns are text.")

    # 7. Missing values
    def handle_missing(self) -> None:
        for position in self.kept:
            opts, name, kind = self.options.column(position), self.names[position], self.kinds[position]
            column = self.frame[position]
            missing = int(column.isna().sum())
            if opts.missing == "keep" or not missing:
                continue
            if opts.missing == "drop_rows":
                self.frame = self.frame[column.notna()]
                self.step(f"Empty '{name}'", f"Removed {missing:,} rows with no value in '{name}'.",
                          rows=missing, destructive=True)
                continue
            value = self._fill_value(opts, name, kind, column.dropna())
            if value is None:
                continue
            self.frame[position] = column.fillna(value) if kind in NUMERIC_KINDS + ("boolean",) else \
                column.where(column.notna(), value)
            how = {"fill_value": "the value", "fill_mean": "the average", "fill_median": "the median",
                   "fill_mode": "the most common value"}[opts.missing]
            self.step(f"Fill '{name}'", f"Filled {missing:,} empty values in '{name}' with {how} {value!r}.",
                      cells=missing, destructive=True)

    def _fill_value(self, opts: ColumnOptions, name: str, kind: str, values: pd.Series):
        if opts.missing == "fill_value":
            text = opts.fill_value.strip()
            fmt = None
            if kind in DATE_KINDS:  # the fill value may be written in any supported date format
                fmt = opts.date_format or types.detect(pd.Series([text])).date_format
            failed = 1
            if text and (kind not in DATE_KINDS or fmt):
                converted, failed = types.convert(pd.Series([text]), kind, fmt)
            if failed:
                self.error("fill_value", f"The fill value {opts.fill_value!r} is not a valid {kind} for '{name}'.", name)
                return None
            return converted.iloc[0]
        if values.empty:
            self.error("fill_value", f"'{name}' has no values to calculate a fill value from.", name)
            return None
        if opts.missing in ("fill_mean", "fill_median"):
            if kind not in NUMERIC_KINDS:
                self.error("fill_value", f"'{name}' is not numeric, so it cannot be filled with an average.", name)
                return None
            value = float(values.mean() if opts.missing == "fill_mean" else values.median())
            return int(round(value)) if kind == "integer" else value
        return values.mode().sort_values().iloc[0]  # fill_mode; ties → smallest, for reproducibility

    # 8. Duplicates
    def remove_duplicates(self) -> None:
        if not self.options.remove_duplicate_rows or self.frame.empty:
            return
        duplicated = self.frame.duplicated()
        count = int(duplicated.sum())
        if count:
            self.frame = self.frame[~duplicated]
            self.step("Remove duplicate rows", f"Removed {count:,} rows that were copies of an earlier row.",
                      rows=count, destructive=True)

    # 9. Outliers
    def handle_outliers(self) -> None:
        outside = pd.Series(False, index=self.frame.index)
        for position in self.kept:
            if self.kinds[position] not in NUMERIC_KINDS:
                continue
            column = self.frame[position]
            found = find_outliers(column)
            if found:
                self.outliers[self.names[position]] = found
                numbers = column.astype("Float64")
                outside |= ((numbers < found.low) | (numbers > found.high)).fillna(False).astype(bool)
        if not self.outliers:
            return
        listed = "; ".join(f"{n}: {o.count:,}" for n, o in self.outliers.items())
        if self.options.outliers == "remove_rows":
            count = int(outside.sum())
            self.frame = self.frame[~outside]
            self.step("Remove outliers", f"Removed {count:,} rows with possible outliers ({listed}).",
                      rows=count, destructive=True)
        else:
            self.step("Flag outliers", f"Possible outliers found and kept ({listed}).")

    def finish(self) -> CleanResult:
        columns = []
        for position in self.kept:
            name = self.names[position]
            required = self.options.column(position).required
            if required:
                empty = int(self.frame[position].isna().sum())
                if empty:
                    self.error("required_missing", f"'{name}' is required but has {empty:,} empty values. Remove "
                               "those rows or fill them.", name)
            columns.append(OutputColumn(position, self.raw.headers[position], name, self.kinds[position], required))
        if not columns:
            self.error("no_columns", "Every column was removed.")
        if self.frame.empty:
            self.error("no_rows", "No rows are left after cleaning.")
        frame = self.frame.reset_index(drop=True)
        frame.columns = [c.name for c in columns]
        return CleanResult(frame=frame, columns=columns, steps=self.steps, checks=self.checks,
                           rows_before=self.raw.rows, removed_columns=self.removed, outliers=self.outliers)


def _apply_case(values: pd.Series, case: str) -> pd.Series:
    return {"lower": values.str.lower, "upper": values.str.upper, "title": values.str.title}[case]()


def _dtype(kind: str) -> str:
    return {"integer": "Int64", "boolean": "Int64", "float": "Float64"}.get(kind, "object")
