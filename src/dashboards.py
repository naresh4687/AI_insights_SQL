"""Dashboard Studio: saved dashboards of charts taken from AI Analyst (or SQL Explorer) answers.

A widget stores the **validated SQL**, the dataset it was asked about and a chart type — never an
AI call. Every time a dashboard is shown, each widget's SQL runs through ``run_query`` again with
its dataset's scope, so a dashboard can read exactly what the AI Analyst could, and nothing more
(a widget whose SQL reaches outside its dataset is rejected, even if the stored text was altered).

Filters narrow the columns a chart shows: a widget is filtered when its result has the filter's
column. The original SQL is wrapped as ``SELECT * FROM (<sql>) WHERE …`` with the chosen values
bound as parameters, and the wrapped query is validated like any other.

Access (``accounts``): a dashboard has an owner and can be shared read-only with every signed-in
user. Showing a chart also needs read access to its dataset, checked each time with the viewer's
account, so sharing a dashboard never reveals a dataset that is not shared too.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import accounts, config, data_access
from src.analysis import CHART_LABELS, Chart, chart_options
from src.core.models import IDENTIFIER
from src.insights import is_period_column
from src.query_service import QueryError, run_query
from src.sql_guard import UnsafeSQLError, validate_sql
from src.storage import app_db

WIDTHS = {"full": "Full width", "half": "Half width", "third": "One third"}
WIDTH_UNITS = {"full": 6, "half": 3, "third": 2}  # a row holds 6 units
FILTER_KINDS = {"date": "Date range", "category": "Categories", "number": "Number range"}
MAX_NAME_LENGTH = 80
MAX_TITLE_LENGTH = 120
MAX_WIDGETS = 24
MAX_FILTERS = 6
_DATE_LIKE = re.compile(r"^\d{4}(-\d{2}(-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?)?)?$")


class DashboardError(Exception):
    """A dashboard operation was refused. ``message`` is safe to show to users."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Widget:
    widget_id: int
    dashboard_id: str
    position: int
    title: str
    question: str
    dataset_id: str
    sql: str
    chart_kind: str
    width: str


@dataclass(frozen=True)
class Filter:
    filter_id: int
    dashboard_id: str
    kind: str
    column: str
    label: str


@dataclass(frozen=True)
class Dashboard:
    dashboard_id: str
    name: str
    description: str
    widgets: tuple[Widget, ...] = ()
    filters: tuple[Filter, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None
    owner: str | None = None
    shared: bool = False


def _clean_name(name: str, limit: int, what: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name or len(name) > limit:
        raise DashboardError(f"Enter a {what} (at most {limit} characters).")
    return name


class DashboardStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        app_db.migrate(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return app_db.connect(self.db_path)

    # --- Dashboards ---------------------------------------------------------------------

    def create(self, name: str, description: str = "", owner: str | None = None) -> Dashboard:
        name = _clean_name(name, MAX_NAME_LENGTH, "dashboard name")
        conn = self._conn()
        try:
            dashboard_id = self._new_id(conn, name)
            with conn:
                now = app_db.utc_now()
                conn.execute("INSERT INTO dashboards (dashboard_id, name, description, created_at, updated_at, owner) "
                             "VALUES (?, ?, ?, ?, ?, ?)", (dashboard_id, name, (description or "").strip(), now, now,
                                                           owner))
        except sqlite3.IntegrityError:
            raise DashboardError(f"A dashboard named '{name}' already exists.") from None
        finally:
            conn.close()
        return self.get(dashboard_id)

    @staticmethod
    def _new_id(conn: sqlite3.Connection, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "dashboard"
        if not IDENTIFIER.match(base):
            base = f"d_{base}"[:40]
        taken = {r[0] for r in conn.execute("SELECT dashboard_id FROM dashboards")}
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}_{n}", n + 1
        return candidate

    def get(self, dashboard_id: str) -> Dashboard | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM dashboards WHERE dashboard_id = ?", (dashboard_id,)).fetchone()
            if row is None:
                return None
            widgets = tuple(Widget(**{k: r[k] for k in r.keys() if k != "created_at"}) for r in conn.execute(
                "SELECT * FROM dashboard_widgets WHERE dashboard_id = ? ORDER BY position, widget_id", (dashboard_id,)))
            filters = tuple(Filter(r["filter_id"], r["dashboard_id"], r["kind"], r["column_name"], r["label"])
                            for r in conn.execute("SELECT * FROM dashboard_filters WHERE dashboard_id = ? "
                                                  "ORDER BY filter_id", (dashboard_id,)))
        finally:
            conn.close()
        return Dashboard(row["dashboard_id"], row["name"], row["description"], widgets, filters,
                         row["created_at"], row["updated_at"], row["owner"], bool(row["shared"]))

    def list(self, user: "accounts.User | None" = None) -> list[Dashboard]:
        """The dashboards ``user`` may see (all of them for the system), by name."""
        conn = self._conn()
        try:
            ids = [r[0] for r in conn.execute("SELECT dashboard_id FROM dashboards ORDER BY name COLLATE NOCASE")]
        finally:
            conn.close()
        return [d for d in (self.get(i) for i in ids) if d is not None and visible(d, user)]

    def set_shared(self, dashboard_id: str, shared: bool) -> Dashboard:
        self._require(dashboard_id)
        conn = self._conn()
        try:
            with conn:
                conn.execute("UPDATE dashboards SET shared = ? WHERE dashboard_id = ?", (int(bool(shared)), dashboard_id))
                self._touch(conn, dashboard_id)
        finally:
            conn.close()
        return self.get(dashboard_id)

    def _require(self, dashboard_id: str) -> Dashboard:
        dashboard = self.get(dashboard_id)
        if dashboard is None:
            raise DashboardError("This dashboard no longer exists.")
        return dashboard

    def _touch(self, conn: sqlite3.Connection, dashboard_id: str) -> None:
        conn.execute("UPDATE dashboards SET updated_at = ? WHERE dashboard_id = ?", (app_db.utc_now(), dashboard_id))

    def rename(self, dashboard_id: str, name: str, description: str | None = None) -> Dashboard:
        self._require(dashboard_id)
        name = _clean_name(name, MAX_NAME_LENGTH, "dashboard name")
        conn = self._conn()
        try:
            with conn:
                conn.execute("UPDATE dashboards SET name = ?, description = COALESCE(?, description) "
                             "WHERE dashboard_id = ?", (name, description, dashboard_id))
                self._touch(conn, dashboard_id)
        except sqlite3.IntegrityError:
            raise DashboardError(f"A dashboard named '{name}' already exists.") from None
        finally:
            conn.close()
        return self.get(dashboard_id)

    def free_name(self, name: str) -> str:
        """``name``, or ``name (2)``, ``name (3)``… — the first not used by another dashboard."""
        taken = {d.name.casefold() for d in self.list()}
        candidate, n = name, 2
        while candidate.casefold() in taken:
            candidate, n = f"{name} ({n})", n + 1
        return candidate

    def duplicate(self, dashboard_id: str, name: str, owner: str | None = None) -> Dashboard:
        """A copy with the same widgets and filters (in one transaction), owned by ``owner`` and
        not shared."""
        source = self._require(dashboard_id)
        name = _clean_name(name, MAX_NAME_LENGTH, "dashboard name")
        conn = self._conn()
        try:
            copy_id = self._new_id(conn, name)
            now = app_db.utc_now()
            with conn:
                conn.execute("INSERT INTO dashboards (dashboard_id, name, description, created_at, updated_at, owner) "
                             "VALUES (?, ?, ?, ?, ?, ?)", (copy_id, name, source.description, now, now, owner))
                for w in source.widgets:
                    conn.execute("INSERT INTO dashboard_widgets (dashboard_id, position, title, question, dataset_id, "
                                 "sql, chart_kind, width, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (copy_id, w.position, w.title, w.question, w.dataset_id, w.sql, w.chart_kind,
                                  w.width, now))
                for f in source.filters:
                    conn.execute("INSERT INTO dashboard_filters (dashboard_id, kind, column_name, label) "
                                 "VALUES (?, ?, ?, ?)", (copy_id, f.kind, f.column, f.label))
        except sqlite3.IntegrityError:
            raise DashboardError(f"A dashboard named '{name}' already exists.") from None
        finally:
            conn.close()
        return self.get(copy_id)

    def delete(self, dashboard_id: str) -> None:
        conn = self._conn()
        try:
            with conn:
                conn.execute("DELETE FROM dashboards WHERE dashboard_id = ?", (dashboard_id,))
        finally:
            conn.close()

    # --- Widgets ------------------------------------------------------------------------

    def add_widget(self, dashboard_id: str, title: str, question: str, dataset_id: str, sql: str,
                   chart_kind: str, width: str = "half", demo_db: Path | None = None,
                   user: "accounts.User | None" = None) -> Widget:
        """Add a chart. The SQL must pass validation for its dataset now (and is checked again
        whenever the dashboard is shown); ``user`` must be able to read that dataset."""
        dashboard = self._require(dashboard_id)
        if len(dashboard.widgets) >= MAX_WIDGETS:
            raise DashboardError(f"A dashboard can hold at most {MAX_WIDGETS} charts.")
        title = _clean_name(title, MAX_TITLE_LENGTH, "chart title")
        if chart_kind not in CHART_LABELS or width not in WIDTHS:
            raise DashboardError("Choose a valid chart type and width.")
        try:
            target = data_access.target(dataset_id, Path(demo_db or config.get_db_path()), user)
            safe_sql = validate_sql(sql, target.scope)
        except data_access.UnknownDatasetError:
            raise DashboardError("The dataset of this chart is not available.") from None
        except UnsafeSQLError as exc:
            raise DashboardError(f"This query cannot be added: {exc}") from None
        conn = self._conn()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO dashboard_widgets (dashboard_id, position, title, question, dataset_id, sql, "
                    "chart_kind, width, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (dashboard_id, len(dashboard.widgets), title, (question or "")[:500], dataset_id, safe_sql,
                     chart_kind, width, app_db.utc_now()))
                self._touch(conn, dashboard_id)
            widget_id = cursor.lastrowid
        finally:
            conn.close()
        return next(w for w in self.get(dashboard_id).widgets if w.widget_id == widget_id)

    def _widget(self, widget_id: int) -> Widget:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM dashboard_widgets WHERE widget_id = ?", (widget_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise DashboardError("This chart no longer exists.")
        return Widget(**{k: row[k] for k in row.keys() if k != "created_at"})

    def update_widget(self, widget_id: int, title: str | None = None, width: str | None = None,
                      chart_kind: str | None = None) -> Widget:
        widget = self._widget(widget_id)
        title = _clean_name(title, MAX_TITLE_LENGTH, "chart title") if title is not None else widget.title
        width = width or widget.width
        chart_kind = chart_kind or widget.chart_kind
        if width not in WIDTHS or chart_kind not in CHART_LABELS:
            raise DashboardError("Choose a valid chart type and width.")
        conn = self._conn()
        try:
            with conn:
                conn.execute("UPDATE dashboard_widgets SET title = ?, width = ?, chart_kind = ? WHERE widget_id = ?",
                             (title, width, chart_kind, widget_id))
                self._touch(conn, widget.dashboard_id)
        finally:
            conn.close()
        return self._widget(widget_id)

    def move_widget(self, widget_id: int, step: int) -> None:
        """Move a chart earlier (step -1) or later (+1); positions are renumbered 0..n-1."""
        widget = self._widget(widget_id)
        order = [w.widget_id for w in self._require(widget.dashboard_id).widgets]
        index = order.index(widget_id)
        target = max(0, min(len(order) - 1, index + step))
        order.insert(target, order.pop(index))
        conn = self._conn()
        try:
            with conn:
                for position, wid in enumerate(order):
                    conn.execute("UPDATE dashboard_widgets SET position = ? WHERE widget_id = ?", (position, wid))
                self._touch(conn, widget.dashboard_id)
        finally:
            conn.close()

    def remove_widget(self, widget_id: int) -> None:
        """Remove a chart and renumber the rest 0..n-1 (in one transaction)."""
        widget = self._widget(widget_id)
        conn = self._conn()
        try:
            with conn:
                conn.execute("DELETE FROM dashboard_widgets WHERE widget_id = ?", (widget_id,))
                remaining = [r[0] for r in conn.execute(
                    "SELECT widget_id FROM dashboard_widgets WHERE dashboard_id = ? ORDER BY position, widget_id",
                    (widget.dashboard_id,))]
                for position, wid in enumerate(remaining):
                    conn.execute("UPDATE dashboard_widgets SET position = ? WHERE widget_id = ?", (position, wid))
                self._touch(conn, widget.dashboard_id)
        finally:
            conn.close()

    # --- Filters ------------------------------------------------------------------------

    def add_filter(self, dashboard_id: str, kind: str, column: str, label: str | None = None) -> Filter:
        dashboard = self._require(dashboard_id)
        if kind not in FILTER_KINDS:
            raise DashboardError("Choose a date, category or number filter.")
        if len(dashboard.filters) >= MAX_FILTERS:
            raise DashboardError(f"A dashboard can have at most {MAX_FILTERS} filters.")
        column = (column or "").strip()
        if not column or len(column) > 128:
            raise DashboardError("Choose the column to filter.")
        label = _clean_name(label or column.replace("_", " ").capitalize(), MAX_TITLE_LENGTH, "filter label")
        conn = self._conn()
        try:
            with conn:
                cursor = conn.execute("INSERT INTO dashboard_filters (dashboard_id, kind, column_name, label) "
                                      "VALUES (?, ?, ?, ?)", (dashboard_id, kind, column, label))
                self._touch(conn, dashboard_id)
        except sqlite3.IntegrityError:
            raise DashboardError(f"There is already a filter on '{column}'.") from None
        finally:
            conn.close()
        return next(f for f in self.get(dashboard_id).filters if f.filter_id == cursor.lastrowid)

    def remove_filter(self, filter_id: int) -> None:
        conn = self._conn()
        try:
            with conn:
                row = conn.execute("SELECT dashboard_id FROM dashboard_filters WHERE filter_id = ?",
                                   (filter_id,)).fetchone()
                conn.execute("DELETE FROM dashboard_filters WHERE filter_id = ?", (filter_id,))
                if row:
                    self._touch(conn, row[0])
        finally:
            conn.close()

    # --- Export -------------------------------------------------------------------------

    def export(self, dashboard_id: str) -> dict:
        """The dashboard's definition (no data and no secrets), for backup or review."""
        dashboard = self._require(dashboard_id)
        names = {d.dataset_id: d.name for d in data_access.datasets()}
        return {
            "format": "insightsql-dashboard", "version": 1, "name": dashboard.name,
            "description": dashboard.description,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "widgets": [{"title": w.title, "question": w.question, "dataset_id": w.dataset_id,
                         "dataset_name": names.get(w.dataset_id), "sql": w.sql, "chart_kind": w.chart_kind,
                         "width": w.width} for w in dashboard.widgets],
            "filters": [{"kind": f.kind, "column": f.column, "label": f.label} for f in dashboard.filters],
        }


def store() -> DashboardStore:
    return DashboardStore(config.get_app_db_path())


def export_json(dashboard_id: str) -> bytes:
    return json.dumps(store().export(dashboard_id), indent=2, ensure_ascii=False).encode("utf-8")


# --- Layout ---------------------------------------------------------------------------

def layout(widgets: tuple[Widget, ...] | list[Widget]) -> list[list[Widget]]:
    """Rows of widgets in order; a row is filled until its width (6 units) is used."""
    rows: list[list[Widget]] = []
    used = 6
    for widget in widgets:
        units = WIDTH_UNITS[widget.width]
        if used + units > 6:
            rows.append([])
            used = 0
        rows[-1].append(widget)
        used += units
    return rows


# --- Filters --------------------------------------------------------------------------

def quote(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def compatible(flt: Filter, data: pd.DataFrame) -> bool:
    """Whether ``flt`` can narrow a result with these columns."""
    if flt.column not in data.columns:
        return False
    values = data[flt.column].dropna()
    if flt.kind == "number":
        return pd.api.types.is_numeric_dtype(data[flt.column]) and not pd.api.types.is_bool_dtype(data[flt.column])
    if flt.kind == "date":
        return bool(not values.empty and values.astype(str).map(lambda v: bool(_DATE_LIKE.match(v))).all())
    return True


def condition(flt: Filter, value) -> tuple[str, list] | None:
    """SQL condition and parameters for a filter value; None when the filter is not set."""
    column = quote(flt.column)
    if flt.kind == "category":
        if not value:
            return None
        return f"{column} IN ({', '.join('?' for _ in value)})", list(value)
    if not value or value[0] is None or value[1] is None:
        return None
    if flt.kind == "number":
        return f"{column} BETWEEN ? AND ?", [value[0], value[1]]
    # Dates: compare at the column's own precision (YYYY-MM months, YYYY-MM-DD days, datetimes by day).
    part = f"SUBSTR({column}, 1, 10)"
    return (f"({part} >= SUBSTR(?, 1, LENGTH({part})) AND {part} <= SUBSTR(?, 1, LENGTH({part})))",
            [str(value[0]), str(value[1])])


def filtered_sql(sql: str, filters: list[tuple[Filter, object]], data: pd.DataFrame) -> tuple[str, tuple, list[str]]:
    """Wrap ``sql`` with the conditions of the set, compatible filters. Returns the SQL, its
    parameters and the labels of the filters applied."""
    parts, params, applied = [], [], []
    for flt, value in filters:
        if not compatible(flt, data):
            continue
        built = condition(flt, value)
        if built:
            parts.append(built[0])
            params += built[1]
            applied.append(flt.label)
    if not parts:
        return sql, (), []
    return f"SELECT * FROM ({sql}) AS dashboard_filter WHERE {' AND '.join(parts)}", tuple(params), applied


# --- Running widgets ------------------------------------------------------------------

@dataclass
class WidgetResult:
    widget: Widget
    data: pd.DataFrame | None = None
    unfiltered: pd.DataFrame | None = None
    truncated: bool = False
    chart: Chart | None = None
    error: str | None = None
    applied: list[str] = field(default_factory=list)
    note: str | None = None


def visible(dashboard: Dashboard, user: "accounts.User | None") -> bool:
    return accounts.can_view(user, dashboard.owner, dashboard.shared)


def run(widget: Widget, demo_db: Path, filters: list[tuple[Filter, object]] = (),
        user: "accounts.User | None" = None) -> WidgetResult:
    """Run a widget's SQL for its dataset (validated again), with the dashboard's filters, if
    ``user`` may read that dataset."""
    result = WidgetResult(widget)
    try:
        target = data_access.target(widget.dataset_id, demo_db, user)
    except data_access.UnknownDatasetError:
        result.error = ("The dataset of this chart is no longer available, or it is not shared with you."
                        if user is not None else "The dataset of this chart is no longer available.")
        return result
    try:
        base = run_query(target.db_path, widget.sql, allowed_tables=target.scope)
        result.unfiltered = base.data
        sql, params, result.applied = filtered_sql(widget.sql, list(filters), base.data)
        final = run_query(target.db_path, sql, allowed_tables=target.scope, params=params) if params else base
    except QueryError as exc:
        result.error = exc.message
        return result
    result.data, result.truncated = final.data, final.truncated
    options = chart_options(final.data)
    chosen = next((o for o in options if o.kind == widget.chart_kind), None)
    if chosen is None and options:
        chosen = options[0]
        result.note = (f"Shown as {chosen.label.lower()}: a {CHART_LABELS[widget.chart_kind].lower()} chart does "
                       "not suit the current data.")
    result.chart = chosen
    return result


def choices(flt: Filter, results: list[WidgetResult]) -> object:
    """What the filter can be set to, from the unfiltered data of the charts it applies to:
    categories (sorted values) or (minimum, maximum) for dates and numbers. None if no chart fits."""
    frames = [r.unfiltered for r in results if r.unfiltered is not None and compatible(flt, r.unfiltered)]
    if not frames:
        return None
    values = pd.concat([f[flt.column] for f in frames]).dropna()
    if flt.kind == "category":
        unique = {str(v) if not isinstance(v, (int, float)) else v for v in values}
        # Numbers in numeric order, then text in text order (never 1, 10, 2).
        return sorted(unique, key=lambda v: (isinstance(v, str), v if not isinstance(v, str) else 0, str(v)))
    if flt.kind == "date":
        days = values.astype(str).str.slice(0, 10)
        return days.min(), days.max()
    return float(values.min()), float(values.max())
