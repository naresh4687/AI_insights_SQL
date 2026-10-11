"""PostgreSQL and MySQL: test a connection, list tables and columns, preview, and fetch a snapshot.

Safety:
- The host must pass ``network.check`` and the connection is made to the checked address.
- Every session is read-only on the server (PostgreSQL ``default_transaction_read_only``,
  MySQL ``SET SESSION TRANSACTION READ ONLY``) with statement and connect timeouts. A read-only
  database account is still recommended.
- Only tables and columns that the server itself lists can be read; queries are built by
  SQLAlchemy from those names (quoted), never from text typed by a user or an AI.
- Errors are mapped to user-safe messages; driver details are logged (secrets redacted).
"""

import logging
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from src import config
from src.connectors import network
from src.connectors.profiles import ConnectorError, Profile

logger = logging.getLogger(__name__)

SYSTEM_SCHEMAS = {
    "postgres": {"pg_catalog", "information_schema", "pg_toast"},
    "mysql": {"mysql", "information_schema", "performance_schema", "sys"},
}
MAX_TABLES = 2000
PREVIEW_ROWS = 100


@dataclass(frozen=True)
class SourceColumn:
    name: str
    source_type: str  # as the server describes it, e.g. "NUMERIC(10, 2)"
    kind: str  # InsightSQL type: integer, float, boolean, date, datetime, text, or "unsupported"
    timezone: bool = False  # a time-zone-aware timestamp (values are converted to UTC)


def _kind(column_type) -> str:
    try:
        python_type = column_type.python_type
    except (NotImplementedError, AttributeError):
        return "text"
    if python_type is bool:
        return "boolean"
    if python_type is int:
        return "integer"
    if python_type in (float, Decimal):
        return "float"
    if python_type is datetime:
        return "datetime"
    if python_type is date:
        return "date"
    if python_type in (bytes, bytearray, memoryview):
        return "unsupported"
    return "text"


def _engine(profile: Profile, password: str) -> sa.Engine:
    s = profile.settings
    destination = network.check(s["host"], s["port"])
    address = destination.addresses[0]
    timeout = config.get_connector_timeout()
    if profile.kind == "postgres":
        url = URL.create("postgresql+psycopg", username=s["username"], password=password, host=s["host"],
                         port=s["port"], database=s["database"])
        connect_args = {
            "hostaddr": address,  # connect to the checked address; host stays for TLS verification
            "connect_timeout": max(1, int(timeout)),
            "sslmode": s["ssl"],
            "application_name": "InsightSQL",
            "options": f"-c default_transaction_read_only=on -c statement_timeout={int(timeout * 1000)}",
        }
    else:
        tls = s["ssl"] == "require"
        url = URL.create("mysql+pymysql", username=s["username"], password=password,
                         host=s["host"] if tls else address, port=s["port"], database=s["database"])
        connect_args = {"connect_timeout": max(1, int(timeout)), "read_timeout": int(timeout),
                        "write_timeout": int(timeout), "charset": "utf8mb4"}
        if tls:
            connect_args["ssl"] = {"ca": ssl.get_default_verify_paths().cafile, "check_hostname": True}
    return sa.create_engine(url, poolclass=NullPool, connect_args=connect_args)


@contextmanager
def _connect(profile: Profile, password: str):
    engine = None
    try:
        engine = _engine(profile, password)  # inside the try: a refused destination is a ConnectorError too
        with engine.connect() as conn:
            if profile.kind == "mysql":
                conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
                conn.exec_driver_sql(f"SET SESSION max_execution_time = {int(config.get_connector_timeout() * 1000)}")
            yield conn
    except network.DestinationError as exc:
        raise ConnectorError(exc.message) from None
    except ConnectorError:
        raise
    except sa.exc.SQLAlchemyError as exc:
        raise _safe_error(profile, exc) from None
    finally:
        if engine is not None:
            engine.dispose()


def _safe_error(profile: Profile, exc: Exception) -> ConnectorError:
    text = str(getattr(exc, "orig", exc)).lower()
    logger.warning("Connection %s failed: %s", profile.connection_id, type(exc).__name__)
    s = profile.settings
    if any(k in text for k in ("password authentication failed", "access denied", "authentication failed")):
        return ConnectorError("The server rejected the user name or password.")
    if any(k in text for k in ("does not exist", "unknown database")) and "database" in text:
        return ConnectorError(f"The database '{s['database']}' does not exist on this server, or the user cannot see it.")
    if any(k in text for k in ("timeout", "timed out", "canceling statement")):
        return ConnectorError("The server did not answer in time. Check the host, port and firewall, or try again.",
                              retryable=True)
    if any(k in text for k in ("connection refused", "can't connect", "could not connect", "no route",
                               "network is unreachable", "lost connection")):
        return ConnectorError(f"Could not reach {s['host']}:{s['port']}. Check the host, port and that the server is "
                              "running.", retryable=True)
    if "ssl" in text or "tls" in text or "certificate" in text:
        return ConnectorError("The encrypted (SSL/TLS) connection failed. Check the encryption setting.")
    if "read-only" in text or "read only" in text:
        return ConnectorError("The server refused a write: InsightSQL connections are read-only.")
    if "permission denied" in text or "command denied" in text:
        return ConnectorError("The user does not have permission to read this table.")
    return ConnectorError("The database server returned an error. See the server log for details.")


def test(profile: Profile, password: str) -> str:
    """Connect and return the server version. Raises ``ConnectorError``."""
    with _connect(profile, password) as conn:
        version = conn.exec_driver_sql("SELECT version()").scalar()
        read_only = (conn.exec_driver_sql("SHOW transaction_read_only").scalar() if profile.kind == "postgres"
                     else conn.exec_driver_sql("SELECT @@session.transaction_read_only").scalar())
    if str(read_only).lower() not in ("on", "1"):
        raise ConnectorError("The session could not be made read-only, so the connection is not used.")
    return str(version).split(" on ")[0][:120]


def list_tables(profile: Profile, password: str) -> list[tuple[str, str]]:
    """(schema, table) pairs the user can see, excluding system schemas; views included."""
    found = []
    with _connect(profile, password) as conn:
        inspector = sa.inspect(conn)
        default = inspector.default_schema_name
        schemas = [default] if profile.kind == "mysql" else inspector.get_schema_names()
        for schema in schemas:
            if schema in SYSTEM_SCHEMAS[profile.kind]:
                continue
            for name in inspector.get_table_names(schema=schema) + inspector.get_view_names(schema=schema):
                found.append((schema, name))
                if len(found) >= MAX_TABLES:
                    return sorted(found)
    return sorted(found)


def _require_table(profile: Profile, password: str, schema: str, table: str) -> None:
    if (schema, table) not in list_tables(profile, password):
        raise ConnectorError(f"The table {schema}.{table} is not available on this connection.")


def columns(profile: Profile, password: str, schema: str, table: str) -> list[SourceColumn]:
    _require_table(profile, password, schema, table)
    with _connect(profile, password) as conn:
        described = sa.inspect(conn).get_columns(table, schema=schema)
    return [SourceColumn(c["name"], str(c["type"]), _kind(c["type"]), bool(getattr(c["type"], "timezone", False)))
            for c in described]


def cursor_value(column: SourceColumn, text: str):
    """A stored cursor (text from ``to_text``) as a value to compare with the column on the server."""
    if column.kind == "integer":
        return int(text)
    if column.kind == "float":
        return Decimal(text)
    if column.kind == "datetime":
        value = datetime.fromisoformat(text)
        return value.replace(tzinfo=timezone.utc) if column.timezone else value
    if column.kind == "date":
        return date.fromisoformat(text)
    return text


def fetch(profile: Profile, password: str, schema: str, table: str, column_names: list[str],
          limit: int, since: tuple[str, str | None] | None = None) -> tuple[pd.DataFrame, bool]:
    """Up to ``limit`` rows of the chosen columns, as text (see ``to_text``), and whether the table
    has more rows than that. Columns must be among those the server lists for the table.

    ``since=(cursor_column, last_value)`` fetches only rows whose cursor is at least ``last_value``
    (all rows if it is None), in cursor order: the incremental part of a refresh."""
    available = {c.name: c for c in columns(profile, password, schema, table)}
    chosen = [c for c in column_names if c in available and available[c].kind != "unsupported"]
    if not chosen or len(chosen) != len(column_names):
        raise ConnectorError("Choose at least one column, and only columns of this table that can be imported.")
    with _connect(profile, password) as conn:
        reflected = sa.Table(table, sa.MetaData(), schema=schema, autoload_with=conn)
        query = sa.select(*[reflected.c[name] for name in chosen])
        if since is not None:
            cursor, last = since
            if cursor not in chosen:
                raise ConnectorError(f"The cursor column '{cursor}' must be one of the imported columns.")
            query = query.order_by(reflected.c[cursor])
            if last is not None:  # a bound parameter, never text in the SQL
                query = query.where(reflected.c[cursor] >= cursor_value(available[cursor], last))
        query = query.limit(limit + 1)
        rows = conn.execute(query).fetchall()
    truncated = len(rows) > limit
    frame = pd.DataFrame([[to_text(v) for v in row] for row in rows[:limit]], columns=chosen, dtype=object)
    return frame, truncated


def preview(profile: Profile, password: str, schema: str, table: str, column_names: list[str]) -> pd.DataFrame:
    return fetch(profile, password, schema, table, column_names, PREVIEW_ROWS)[0]


def to_text(value) -> str:
    """A database value as the text the import pipeline reads (types are restored from the
    server's column types). Times are kept to the second; time zones are converted to UTC."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    return str(value)
