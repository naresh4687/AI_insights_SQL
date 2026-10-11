"""SQL safety layer.

Defence in depth — a query must pass every layer:

1. ``validate_sql()`` parses the SQL into an AST with sqlglot and accepts only a single
   read-only SELECT over the allowed tables. Anything it cannot parse is rejected.
   It returns SQL regenerated from the AST (comments stripped), so the text that runs
   is exactly the text that was validated.
2. ``ReadOnlyAuthorizer`` is installed on the SQLite connection and is consulted by the
   engine itself for every table read and function call, denying anything not
   explicitly allowed. This catches anything the parser layer might misjudge.
3. The connection is opened read-only (``mode=ro``) with ``PRAGMA query_only = ON``
   (see ``query_service``), with a timeout and a row cap.
"""

import sqlite3

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MAX_SQL_LENGTH = 5000

ALLOWED_TABLES = frozenset({"products", "sales"})

# Functions the engine may call. Deliberately excludes load_extension, randomblob,
# zeroblob, printf/format (unbounded string growth), and sqlite_* internals.
ALLOWED_FUNCTIONS = frozenset({
    # aggregates
    "count", "sum", "total", "avg", "min", "max", "group_concat",
    # scalar
    "abs", "round", "coalesce", "ifnull", "nullif", "iif", "upper", "lower", "length",
    "substr", "substring", "trim", "ltrim", "rtrim", "replace", "instr", "cast",
    # date/time
    "date", "time", "datetime", "julianday", "strftime",
    # window
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile",
    "lag", "lead", "first_value", "last_value",
})

# Statement types that must never appear anywhere in the tree.
_FORBIDDEN_NODES = tuple(
    node for node in (
        getattr(exp, name, None) for name in (
            "Insert", "Update", "Delete", "Merge", "Drop", "Alter", "Create", "Command",
            "Pragma", "Attach", "Detach", "Transaction", "Commit", "Rollback", "Into",
        )
    ) if node is not None
)


class UnsafeSQLError(ValueError):
    """Raised when SQL fails validation. The message is safe to show to users."""


def validate_sql(sql: str) -> str:
    """Validate ``sql`` and return the normalised, safe SQL to execute.

    Raises ``UnsafeSQLError`` with a user-facing reason if the query is not allowed.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise UnsafeSQLError("No SQL query was provided.")
    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeSQLError(f"The query is too long (limit {MAX_SQL_LENGTH} characters).")

    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except SqlglotError:
        raise UnsafeSQLError("The query could not be parsed as valid SQL.") from None

    if len(statements) != 1:
        raise UnsafeSQLError("Exactly one SQL statement is allowed.")
    statement = statements[0]

    if not isinstance(statement, exp.Query):
        raise UnsafeSQLError("Only read-only SELECT queries are allowed.")
    if any(True for _ in statement.find_all(*_FORBIDDEN_NODES)):
        raise UnsafeSQLError("Only read-only SELECT queries are allowed.")

    for with_clause in statement.find_all(exp.With):
        if with_clause.args.get("recursive"):
            raise UnsafeSQLError("Recursive queries are not allowed.")

    _check_tables(statement)

    return statement.sql(dialect="sqlite", comments=False)


def _check_tables(statement: exp.Expression) -> None:
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeSQLError("Table-valued functions are not allowed.")
        if table.args.get("db") or table.args.get("catalog"):
            raise UnsafeSQLError("Schema-qualified table names are not allowed.")
        name = table.name.lower()
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise UnsafeSQLError(
                f"Table '{table.name}' is not available. "
                f"Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}."
            )


class ReadOnlyAuthorizer:
    """SQLite authorizer callback that allows only reads of permitted tables.

    Records the reason for the first denial so callers can report it clearly.
    """

    def __init__(self) -> None:
        self.denied_reason: str | None = None

    def __call__(self, action, arg1, arg2, db_name, trigger_name):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and arg1 in ALLOWED_TABLES:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and arg2 and arg2.lower() in ALLOWED_FUNCTIONS:
            return sqlite3.SQLITE_OK

        if self.denied_reason is None:
            if action == sqlite3.SQLITE_READ:
                self.denied_reason = f"Reading from '{arg1}' is not allowed."
            elif action == sqlite3.SQLITE_FUNCTION:
                self.denied_reason = f"The function '{arg2}' is not allowed."
            else:
                self.denied_reason = "The query attempted an operation that is not allowed."
        return sqlite3.SQLITE_DENY
