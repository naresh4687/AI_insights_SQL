"""Read uploaded CSV and Excel files into text tables.

Every cell is read as text, exactly as written in the file, so nothing is converted or
lost before the user has seen it. Column headers are kept by position, because files can
have duplicate or empty headers. Problems are reported with user-safe messages.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import PurePath

import pandas as pd

ENCODINGS = ("auto", "utf-8", "utf-16", "cp1252", "latin-1")
DELIMITERS = {"auto": None, "comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|"}
CSV_EXTENSIONS = (".csv", ".txt")
EXCEL_EXTENSIONS = (".xlsx", ".xlsm")
MAX_UNCOMPRESSED_FACTOR = 20  # an .xlsx may expand to at most 20× the upload limit (zip bombs)
_EXAMPLE_LINES = 5


class ImportFileError(Exception):
    """The file cannot be imported. ``message`` is safe to show to users."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Limits:
    max_bytes: int
    max_rows: int
    max_columns: int


@dataclass(frozen=True)
class ReadOptions:
    encoding: str = "auto"  # one of ENCODINGS (CSV only)
    delimiter: str = "auto"  # a key of DELIMITERS (CSV only)
    sheet: str | None = None  # Excel worksheet; None = the first
    has_header: bool = True

    def to_dict(self) -> dict:
        return {"encoding": self.encoding, "delimiter": self.delimiter, "sheet": self.sheet,
                "has_header": self.has_header}


@dataclass
class RawTable:
    """The file's content as text. ``frame`` has positional columns 0..n-1."""

    file_name: str
    file_type: str  # "csv" or "excel"
    headers: list[str]
    frame: pd.DataFrame
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    sheets: list[str] = field(default_factory=list)
    blank_lines: int = 0  # completely blank lines skipped (CSV)
    short_rows: list[int] = field(default_factory=list)  # file line numbers, padded with empty cells
    long_rows: list[int] = field(default_factory=list)  # file line numbers with extra values

    @property
    def rows(self) -> int:
        return len(self.frame)

    @property
    def columns(self) -> int:
        return len(self.headers)


def file_type(file_name: str) -> str:
    suffix = PurePath(file_name).suffix.lower()
    if suffix in CSV_EXTENSIONS:
        return "csv"
    if suffix in EXCEL_EXTENSIONS:
        return "excel"
    if suffix == ".xls":
        raise ImportFileError("The old Excel format (.xls) is not supported. Save the file as .xlsx or CSV.")
    raise ImportFileError("Only CSV (.csv, .txt) and Excel (.xlsx, .xlsm) files can be imported.")


def read_file(file_name: str, content: bytes, options: ReadOptions, limits: Limits) -> RawTable:
    """Read ``content`` as a table of text. Raises ``ImportFileError`` when it cannot."""
    kind = file_type(file_name)
    if not content:
        raise ImportFileError("The file is empty.")
    if len(content) > limits.max_bytes:
        raise ImportFileError(f"The file is larger than the limit of {limits.max_bytes / 1_048_576:.0f} MB.")
    if kind == "csv":
        return _read_csv(file_name, content, options, limits)
    return _read_excel(file_name, content, options, limits)


# --- CSV ----------------------------------------------------------------------------

def _decode(content: bytes, encoding: str) -> tuple[str, str]:
    if encoding not in ENCODINGS:
        raise ImportFileError("Unknown encoding.")
    if encoding == "auto":
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        else:
            try:
                return content.decode("utf-8-sig"), "utf-8"
            except UnicodeDecodeError as exc:
                raise ImportFileError(
                    f"The file is not UTF-8 text (first unreadable byte at position {exc.start:,}). "
                    "If it was saved by Excel on Windows, choose the encoding Windows-1252 (cp1252) "
                    "under Read options."
                ) from None
    try:
        text = content.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    except UnicodeDecodeError as exc:
        raise ImportFileError(f"The file cannot be read as {encoding} (problem at byte {exc.start:,}). "
                              "Choose another encoding.") from None
    return text, encoding


def _read_csv(file_name: str, content: bytes, options: ReadOptions, limits: Limits) -> RawTable:
    text, encoding = _decode(content, options.encoding)
    if "\x00" in text:
        raise ImportFileError("The file contains binary data and does not look like a CSV text file.")
    if not text.strip():
        raise ImportFileError("The file is empty.")

    if options.delimiter not in DELIMITERS:
        raise ImportFileError("Unknown delimiter.")
    delimiter = DELIMITERS[options.delimiter] or _sniff_delimiter(text)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    rows, line_numbers, blank = [], [], 0
    try:
        for record in reader:
            if not record or all(not cell for cell in record) and len(record) <= 1:
                blank += 1
                continue
            rows.append(record)
            line_numbers.append(reader.line_num)
            if len(rows) > limits.max_rows + 1:
                raise ImportFileError(f"The file has more than {limits.max_rows:,} rows, the import limit.")
    except csv.Error as exc:
        raise ImportFileError(f"Line {reader.line_num:,} could not be read: {exc}. "
                              "Check the quotes on that line, or choose another delimiter.") from None
    table = _to_table(file_name, "csv", rows, line_numbers, options, limits)
    table.encoding, table.delimiter, table.blank_lines = encoding, delimiter, blank
    return table


def _sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:65_536], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


# --- Excel --------------------------------------------------------------------------

def _read_excel(file_name: str, content: bytes, options: ReadOptions, limits: Limits) -> RawTable:
    import openpyxl  # imported here so CSV-only use does not load it

    if not openpyxl.DEFUSEDXML:  # pragma: no cover - defusedxml is a pinned dependency
        raise ImportFileError("Excel import is unavailable: the defusedxml package is not installed.")
    stream = io.BytesIO(content)
    try:
        with zipfile.ZipFile(stream) as archive:
            expanded = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        raise ImportFileError("The file is not a valid .xlsx workbook.") from None
    if expanded > limits.max_bytes * MAX_UNCOMPRESSED_FACTOR:
        raise ImportFileError("The workbook expands to too much data to import safely.")

    try:
        workbook = openpyxl.load_workbook(stream, read_only=True, data_only=True)
    except Exception:  # openpyxl raises many types for damaged or protected files
        raise ImportFileError("The Excel file could not be read. It may be damaged or password-protected.") from None
    try:
        sheets = list(workbook.sheetnames)
        sheet = options.sheet or sheets[0]
        if sheet not in sheets:
            raise ImportFileError(f"The workbook has no worksheet named '{sheet}'.")
        rows, line_numbers = [], []
        for number, values in enumerate(workbook[sheet].iter_rows(values_only=True), start=1):
            record = [_cell_text(v) for v in values]
            if not any(record):
                continue
            rows.append(record)
            line_numbers.append(number)
            if len(rows) > limits.max_rows + 1:
                raise ImportFileError(f"The worksheet has more than {limits.max_rows:,} rows, the import limit.")
    except ImportFileError:
        raise
    except Exception:
        raise ImportFileError("The Excel file could not be read. It may be damaged.") from None
    finally:
        workbook.close()

    width = max((max((i + 1 for i, c in enumerate(r) if c), default=0) for r in rows), default=0)
    rows = [r[:width] + [""] * (width - len(r)) for r in rows]  # drop trailing empty columns
    table = _to_table(file_name, "excel", rows, line_numbers, options, limits)
    table.sheet, table.sheets = sheet, sheets
    return table


def _cell_text(value) -> str:
    """An Excel cell as the text a user would see, without spreadsheet formatting."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return str(value)


# --- Shared -------------------------------------------------------------------------

def _to_table(file_name: str, kind: str, rows: list[list[str]], line_numbers: list[int],
              options: ReadOptions, limits: Limits) -> RawTable:
    if not rows:
        raise ImportFileError("The file has no data.")
    if options.has_header:
        headers, body, body_lines = rows[0], rows[1:], line_numbers[1:]
    else:
        width = max(len(r) for r in rows)
        headers, body, body_lines = [f"column_{i + 1}" for i in range(width)], rows, line_numbers
    if len(headers) > limits.max_columns:
        raise ImportFileError(f"The file has {len(headers):,} columns; the limit is {limits.max_columns:,}.")
    if len(body) > limits.max_rows:
        raise ImportFileError(f"The file has more than {limits.max_rows:,} rows, the import limit.")

    width = len(headers)
    short, long_, cells = [], [], []
    for record, line in zip(body, body_lines):
        if len(record) < width:
            short.append(line)
            record = record + [""] * (width - len(record))
        elif len(record) > width:
            long_.append(line)
            record = record[:width]  # reported as a blocking error; never stored silently
        cells.append(record)
    frame = pd.DataFrame(cells, columns=range(width), dtype=object) if cells else pd.DataFrame(
        columns=range(width), dtype=object)
    return RawTable(file_name=file_name, file_type=kind, headers=[h.strip() for h in headers], frame=frame,
                    short_rows=short, long_rows=long_)
