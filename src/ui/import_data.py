"""Import Data: upload a CSV or Excel file, check it, choose how to clean it, and save it.

The work happens in ``src/ingest``; this page collects choices and shows results. Nothing is
stored until the user presses Save, and changes that remove or replace data must be
confirmed first. The original file is always kept unchanged.
"""

import hashlib
from pathlib import PurePath

import pandas as pd
import streamlit as st

from src import accounts, config, data_access
from src.catalog import DatasetCatalog
from src.core.models import Storage
from src.ingest import preprocess, readers, store, types
from src.ingest.profiling import DatasetProfile, profile
from src.ingest.validation import ERROR, PASSED, WARNING, has_errors, summary, validate
from src.ui import components, session, theme

PREVIEW_ROWS = 100
ENCODING_LABELS = {"auto": "Automatic (UTF-8)", "utf-8": "UTF-8", "utf-16": "UTF-16",
                   "cp1252": "Windows-1252 (Excel on Windows)", "latin-1": "Latin-1 (ISO-8859-1)"}
DELIMITER_LABELS = {"auto": "Automatic", "comma": "Comma ( , )", "semicolon": "Semicolon ( ; )", "tab": "Tab",
                    "pipe": "Pipe ( | )"}
TYPE_LABELS = {"auto": "Automatic", "text": "Text", "integer": "Whole number", "float": "Decimal number",
               "boolean": "Yes / no", "date": "Date", "datetime": "Date and time"}
MISSING_LABELS = {"keep": "Keep empty", "drop_rows": "Remove those rows", "fill_value": "Fill with a value",
                  "fill_mean": "Fill with the average", "fill_median": "Fill with the median",
                  "fill_mode": "Fill with the most common value"}
CASE_LABELS = {"none": "Unchanged", "lower": "lower case", "upper": "UPPER CASE", "title": "Title Case"}
OUTLIER_LABELS = {"flag": "Flag them (keep the rows)", "remove_rows": "Remove those rows"}


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _limits() -> readers.Limits:
    return readers.Limits(max_bytes=config.get_import_max_mb() * 1_048_576, max_rows=config.get_import_max_rows(),
                          max_columns=config.get_import_max_columns())


def _catalog() -> DatasetCatalog:
    return data_access.catalog()


def render() -> None:
    theme.page_header("Data", "Import Data",
                      "Upload a CSV or Excel file, check its quality, choose how to clean it, and save it as a "
                      "dataset. Nothing is saved until you press Save, and the original file is kept unchanged.")
    if not session.current_user().can_create:  # the page is not listed for viewers; checked here too
        st.info("Your role (viewer) can read data but not add it. Ask an administrator for editor access.",
                icon=":material/lock:")
        return
    show_saved_message()

    nonce = st.session_state.setdefault("upload_nonce", 0)  # a new value gives an empty uploader
    with st.container(border=True, key="card_import_upload"):
        st.markdown("**1. Choose a file**")
        limits = _limits()
        upload = st.file_uploader(
            "CSV or Excel file", type=["csv", "txt", "xlsx", "xlsm"], key=f"import_file_{nonce}",
            help=f"Up to {config.get_import_max_mb()} MB, {limits.max_rows:,} rows and {limits.max_columns} columns.")
        with st.expander("Read options"):
            left, right = st.columns(2)
            encoding = left.selectbox("Text encoding (CSV)", list(ENCODING_LABELS), format_func=ENCODING_LABELS.get,
                                      key="import_encoding")
            delimiter = right.selectbox("Delimiter (CSV)", list(DELIMITER_LABELS), format_func=DELIMITER_LABELS.get,
                                        key="import_delimiter")
            has_header = st.checkbox("The first row contains column names", value=True, key="import_has_header")

    if upload is None:
        _datasets()
        return

    content = upload.getvalue()
    file_key = hashlib.sha256(content).hexdigest() + upload.name
    if st.session_state.get("import_file_key") != file_key:  # a new file: start from defaults
        st.session_state["import_file_key"] = file_key
        st.session_state["import_columns"] = {}
        st.session_state.pop("import_sheet", None)
    read_options = readers.ReadOptions(encoding=encoding, delimiter=delimiter, has_header=has_header,
                                       sheet=st.session_state.get("import_sheet"))
    try:
        raw, prof, checks = _analyse(upload.name, content, read_options, limits)
    except readers.ImportFileError as exc:
        st.error(f"**The file could not be read:** {components.md_escape(exc.message)}", icon=":material/error:")
        _datasets()
        return

    _review(raw, prof, checks, content, read_options)
    _datasets()


def show_saved_message() -> None:
    saved = st.session_state.pop("import_saved", None)
    if saved:
        st.success(f"Saved **{components.md_escape(saved['name'])}** as dataset `{saved['id']}` "
                   f"({_count(saved['rows'], 'row')}, {_count(saved['columns'], 'column')}).",
                   icon=":material/check_circle:")


def review_table(raw: readers.RawTable, content: bytes, key: str, source: dict | None = None,
                 presets: dict[int, preprocess.ColumnOptions] | None = None) -> None:
    """Steps 2–7 (preview, quality, cleaning, summary, save) for a table from any source, e.g. a
    connection snapshot. ``key`` identifies the data: a new key starts from ``presets``."""
    if st.session_state.get("import_file_key") != key:
        st.session_state["import_file_key"] = key
        st.session_state["import_columns"] = dict(presets or {})
        st.session_state.pop("import_analysis", None)
    cached = st.session_state.get("import_analysis")
    if not cached or cached[0] != key:
        prof = profile(raw)
        cached = (key, (prof, validate(raw, prof)))
        st.session_state["import_analysis"] = cached
    prof, checks = cached[1]
    _review(raw, prof, checks, content, readers.ReadOptions(), source)


def _review(raw, prof, checks, content, read_options, source: dict | None = None) -> None:
    _original(raw)
    _validation(prof, checks)
    if has_errors(checks):
        st.error("This data cannot be imported until the errors above are fixed. Correct the source or change "
                 "the read options, then try again.", icon=":material/block:")
        return
    options = _clean_options(raw, prof)
    result = preprocess.clean(raw, options)
    _cleaned(result)
    _changes(result)
    _save(raw, content, read_options, options, result, checks, source)


def _analyse(name: str, content: bytes, options: readers.ReadOptions, limits: readers.Limits):
    """Read, profile and validate, reusing the last result while the file and options are unchanged."""
    key = (st.session_state["import_file_key"], options, limits)
    cached = st.session_state.get("import_analysis")
    if cached and cached[0] == key:
        return cached[1]
    raw = readers.read_file(name, content, options, limits)
    prof = profile(raw)
    analysis = (raw, prof, validate(raw, prof))
    st.session_state["import_analysis"] = (key, analysis)
    return analysis


def _display_headers(headers: list[str]) -> list[str]:
    """Unique labels for showing a table whose headers may repeat or be empty."""
    return [f"{i + 1} · {h}" if h else f"{i + 1} · (no name)" for i, h in enumerate(headers)]


# --- 2. Original data -------------------------------------------------------------

def _original(raw: readers.RawTable) -> None:
    with st.container(border=True, key="card_import_original"):
        st.markdown("**2. Original data** (as in the file, before any change)")
        if raw.file_type == "excel" and len(raw.sheets) > 1:
            st.selectbox("Worksheet", raw.sheets, key="import_sheet")
        preview = raw.frame.head(PREVIEW_ROWS).copy()
        preview.columns = _display_headers(raw.headers)
        st.dataframe(preview, hide_index=True, width="stretch")
        shown = min(raw.rows, PREVIEW_ROWS)
        st.caption(f"{_count(raw.rows, 'row')} × {_count(raw.columns, 'column')} · showing the first "
                   f"{_count(shown, 'row')}")


# --- 3. Profile and validation ----------------------------------------------------

def _validation(prof: DatasetProfile, checks) -> None:
    counts = summary(checks)
    with st.container(border=True, key="card_import_checks"):
        st.markdown("**3. Data quality**")
        st.html(" ".join([theme.badge("error", f"{counts[ERROR]} errors"),
                          theme.badge("warning", f"{counts[WARNING]} warnings"),
                          theme.badge("success", f"{counts[PASSED]} passed")]))
        for check in checks:
            text = components.md_escape(check.message)
            if check.level == ERROR:
                st.error(text, icon=":material/error:")
            elif check.level == WARNING:
                st.warning(text, icon=":material/warning:")
        with st.expander("Checks that passed"):
            for check in checks:
                if check.level == PASSED:
                    st.markdown(f":material/check: {components.md_escape(check.message)}")
        with st.expander("Column profile", expanded=False):
            st.dataframe(pd.DataFrame([{
                "Column": c.label,
                "Detected type": TYPE_LABELS.get(c.detection.kind, "No values"),
                "Empty": c.missing,
                "Distinct": c.distinct,
                "Min": c.minimum, "Max": c.maximum, "Mean": c.mean,
                "Outliers": c.outliers.count if c.outliers else 0,
                "Examples": ", ".join(c.examples),
            } for c in prof.columns_profile]), hide_index=True, width="stretch")


# --- 4. Cleaning options ----------------------------------------------------------

def _clean_options(raw: readers.RawTable, prof: DatasetProfile) -> preprocess.CleanOptions:
    columns: dict[int, preprocess.ColumnOptions] = st.session_state["import_columns"]
    with st.container(border=True, key="card_import_options"):
        st.markdown("**4. Choose how to clean the data**")
        left, right = st.columns(2)
        trim = left.toggle("Trim spaces at the start and end of values", value=True, key="import_trim")
        empty_rows = left.toggle("Remove rows with no values at all", value=True, key="import_empty_rows")
        empty_cols = left.toggle("Remove columns with no values", value=False, key="import_empty_columns")
        duplicates = right.toggle(f"Remove duplicate rows ({prof.duplicate_rows:,} found)", value=False,
                                  key="import_duplicates")
        outliers = right.radio("Possible outliers", list(OUTLIER_LABELS), format_func=OUTLIER_LABELS.get,
                               key="import_outliers", horizontal=True)
        found = sorted({m for c in prof.columns_profile for m in c.markers})
        markers = st.multiselect(
            "Treat this text as an empty value", found, key="import_markers",
            help="Only text found in this file is offered. Nothing is treated as empty unless you choose it.",
            placeholder="None found" if not found else "Choose…")

        st.markdown("**Columns**")
        position = st.selectbox("Column to change", range(raw.columns), key="import_column",
                                format_func=lambda p: prof.columns_profile[p].label)
        columns[position] = _column_widgets(position, prof, columns.get(position, preprocess.ColumnOptions()))
        options = preprocess.CleanOptions(trim_whitespace=trim, missing_markers=tuple(markers),
                                          drop_empty_rows=empty_rows, drop_empty_columns=empty_cols,
                                          remove_duplicate_rows=duplicates, outliers=outliers,
                                          columns=dict(columns))
        st.dataframe(pd.DataFrame([{
            "Column": c.label,
            "Keep": options.column(c.position).keep,
            "New name": options.column(c.position).name or "(automatic)",
            "Type": TYPE_LABELS[options.column(c.position).type],
            "Empty values": MISSING_LABELS[options.column(c.position).missing],
            "Text case": CASE_LABELS[options.column(c.position).text_case],
            "Required": options.column(c.position).required,
        } for c in prof.columns_profile]), hide_index=True, width="stretch")
    return options


def _column_widgets(position: int, prof: DatasetProfile, current: preprocess.ColumnOptions) -> preprocess.ColumnOptions:
    detection = prof.columns_profile[position].detection
    left, middle, right = st.columns(3)
    keep = left.checkbox("Keep this column", value=current.keep, key=f"import_keep_{position}")
    required = left.checkbox("Required (no empty values allowed)", value=current.required,
                             key=f"import_required_{position}")
    name = left.text_input("New name (optional)", value=current.name, key=f"import_name_{position}",
                           placeholder="automatic", max_chars=63,
                           help="Lower-case letters, digits and _. Leave empty for an automatic safe name.")
    kind = middle.selectbox("Type", preprocess.COLUMN_TYPES, index=preprocess.COLUMN_TYPES.index(current.type),
                            format_func=TYPE_LABELS.get, key=f"import_type_{position}",
                            help=f"Detected: {TYPE_LABELS.get(detection.kind, 'no values')}.")
    date_format = current.date_format
    if kind in preprocess.DATE_KINDS or (kind == "auto" and detection.kind in preprocess.DATE_KINDS):
        choices = ("",) + types.FORMATS
        date_format = middle.selectbox(
            "Date format", choices, index=choices.index(current.date_format), key=f"import_date_format_{position}",
            format_func=lambda f: f"Detected ({detection.date_format or detection.best_format or 'none'})"
            if f == "" else f)
    text_case = middle.selectbox("Text case", preprocess.TEXT_CASES, index=preprocess.TEXT_CASES.index(current.text_case),
                                 format_func=CASE_LABELS.get, key=f"import_case_{position}")
    missing = right.selectbox("Empty values", preprocess.MISSING_ACTIONS,
                              index=preprocess.MISSING_ACTIONS.index(current.missing),
                              format_func=MISSING_LABELS.get, key=f"import_missing_{position}")
    fill_value = current.fill_value
    if missing == "fill_value":
        fill_value = right.text_input("Fill value", value=current.fill_value, key=f"import_fill_{position}")
    return preprocess.ColumnOptions(keep=keep, name=name.strip(), type=kind, date_format=date_format,
                                    missing=missing, fill_value=fill_value, text_case=text_case, required=required)


# --- 5. Cleaned preview and 6. changes ---------------------------------------------

def _cleaned(result: preprocess.CleanResult) -> None:
    with st.container(border=True, key="card_import_cleaned"):
        st.markdown("**5. Cleaned data** (what will be saved)")
        st.dataframe(result.frame.head(PREVIEW_ROWS), hide_index=True, width="stretch")
        st.caption(f"{_count(len(result.frame), 'row')} × {_count(len(result.columns), 'column')} (the file had "
                   f"{_count(result.rows_before, 'row')}) · showing the first "
                   f"{_count(min(len(result.frame), PREVIEW_ROWS), 'row')}")
        with st.expander("Column types"):
            st.dataframe(pd.DataFrame([{"Column": c.name, "From": c.header or f"column {c.position + 1}",
                                        "Type": TYPE_LABELS[c.kind], "Stored as": c.sql_type,
                                        "Required": c.required} for c in result.columns]),
                         hide_index=True, width="stretch")


def _changes(result: preprocess.CleanResult) -> None:
    with st.container(border=True, key="card_import_changes"):
        st.markdown("**6. Summary of changes**")
        if not result.steps:
            st.caption("No changes: the data will be saved exactly as read.")
        for step in result.steps:
            kind, label = ("warning", "Removes or replaces data") if step.destructive else ("muted", "Safe change")
            st.html(f"{theme.badge(kind, label)} <b>{components.md_escape(step.name)}</b>")
            st.markdown(components.md_escape(step.detail))
        for check in result.checks:
            st.error(components.md_escape(check.message), icon=":material/error:")


# --- 7. Save ----------------------------------------------------------------------

def _save(raw, content, read_options, options, result, checks, source: dict | None = None) -> None:
    with st.container(border=True, key="card_import_save"):
        st.markdown("**7. Save as a dataset**")
        default = PurePath(raw.file_name).stem.replace("_", " ").strip()[:store.MAX_NAME_LENGTH]
        name = st.text_input("Dataset name", value=default, key="import_dataset_name", max_chars=store.MAX_NAME_LENGTH)
        description = st.text_area("Description (optional)", key="import_description", height=70)
        confirmed = True
        if result.destructive_steps:
            listed = "; ".join(s.name for s in result.destructive_steps)
            confirmed = st.checkbox(f"I confirm the changes that remove or replace data: {listed}. "
                                    "(The original file is still kept unchanged.)", key="import_confirm")
        if not result.ok:
            st.caption("Saving is disabled until the problems in step 6 are fixed.")
        if st.button("Save dataset", type="primary", icon=":material/save:", key="import_save",
                     disabled=not result.ok or not confirmed):
            try:
                dataset = store.save_import(
                    name=name, description=description or "", raw=raw, content=content, read_options=read_options,
                    clean_options=options, result=result, checks=checks, confirmed_destructive=confirmed,
                    catalog=_catalog(), datasets_db=config.get_datasets_db_path(), uploads_dir=config.get_uploads_dir(),
                    source=source, owner=accounts.owner_of(session.current_user()))
            except readers.ImportFileError as exc:
                st.error(f"**Not saved:** {components.md_escape(exc.message)}", icon=":material/error:")
                return
            session.record("dataset.imported", "dataset", dataset.dataset_id,
                           f"{dataset.name} from {raw.file_name}" if not source else f"{dataset.name} from a connection")
            st.session_state["import_saved"] = {"name": dataset.name, "id": dataset.dataset_id,
                                                "rows": dataset.tables[0].row_count, "columns": len(result.columns)}
            for key in [k for k in st.session_state if str(k).startswith("import_") and k != "import_saved"]:
                del st.session_state[key]  # start the next import from defaults
            # The counter exists only if the Import page was opened; saves can come from Connections too.
            st.session_state["upload_nonce"] = st.session_state.get("upload_nonce", 0) + 1
            st.rerun()


# --- Imported datasets ------------------------------------------------------------

def _datasets() -> None:
    imported = [d for d in session.visible_datasets() if d.storage == Storage.DATASETS]
    with st.container(border=True, key="card_import_datasets"):
        st.markdown("**Imported datasets**")
        if not imported:
            theme.empty_state("No imported datasets yet", "Datasets you save here are listed with their quality status.")
            return
        st.dataframe(pd.DataFrame([{
            "Name": d.name, "Dataset id": d.dataset_id, "Source": d.source_type.value.upper(),
            "File": d.extra.get("original_file", ""), "Rows": d.tables[0].row_count,
            "Columns": len(d.tables[0].columns), "Quality": d.quality_status.value,
            "Imported": components.format_time(d.created_at),
        } for d in imported]), hide_index=True, width="stretch")
