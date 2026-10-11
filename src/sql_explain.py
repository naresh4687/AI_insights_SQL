"""Plain-language explanations of SQL and of query errors, computed locally (no AI call).

``explain_sql`` describes what a validated query does from its parsed structure: tables,
joins, filters, grouping, calculations, sorting and row limit. ``explain_error`` turns a
user-safe error message into a hint about what to try next, using only the selected
dataset's table and column names.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from src.core.models import Dataset
from src.sql_guard import ALLOWED_FUNCTIONS

MAX_SHOWN = 6


def _arg(node: exp.Expression, name: str):
    """An AST argument; newer sqlglot versions add a trailing underscore to some names."""
    value = node.args.get(name)
    return value if value is not None else node.args.get(f"{name}_")


def _sql(node: exp.Expression) -> str:
    return node.sql(dialect="sqlite")


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_SHOWN])
    return shown + (f" and {len(items) - MAX_SHOWN} more" if len(items) > MAX_SHOWN else "")


def explain_sql(sql: str) -> list[str]:
    """Steps describing the query, in the order a reader would follow them."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except SqlglotError:
        statements = []
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        return ["This query could not be broken down automatically."]
    statement = statements[0]
    steps: list[str] = []
    with_clause = _arg(statement, "with")
    for cte in with_clause.expressions if with_clause is not None else []:
        steps.append(f"First builds an intermediate result named {cte.alias_or_name} "
                     f"from {_listed(_tables(cte.this)) or 'its own calculation'}.")
    if isinstance(statement, exp.SetOperation):
        kind = {exp.Union: "UNION", exp.Intersect: "INTERSECT", exp.Except: "EXCEPT"}.get(type(statement), "")
        selects = list(_set_parts(statement))
        distinct = statement.args.get("distinct", True)
        how = "keeping duplicates" if kind == "UNION" and not distinct else "without duplicates"
        steps.append(f"Combines {len(selects)} queries with {kind} ({how}).")
        for part in selects:
            steps += [f"Part: {s[0].lower()}{s[1:]}" for s in _select_steps(part)[:1]]
        steps += _order_limit(statement)
        return steps
    return steps + _select_steps(statement)


def _set_parts(node: exp.Expression):
    if isinstance(node, exp.SetOperation):
        yield from _set_parts(node.left)
        yield from _set_parts(node.right)
    else:
        yield node


def _tables(node: exp.Expression) -> list[str]:
    seen = []
    for table in node.find_all(exp.Table):
        name = table.name + (f" (as {table.alias})" if table.alias and table.alias != table.name else "")
        if name not in seen:
            seen.append(name)
    return seen


def _select_steps(select: exp.Expression) -> list[str]:
    if not isinstance(select, exp.Select):
        return [f"Reads {_sql(select)}."]
    steps = []
    source = _arg(select, "from")
    if source is not None:
        steps.append(f"Reads from {_listed(_tables(source))}.")
    for join in _arg(select, "joins") or []:
        on = join.args.get("on")
        steps.append(f"Joins {_listed(_tables(join))}" + (f" where {_sql(on)}." if on is not None else "."))
    if _arg(select, "where") is not None:
        steps.append(f"Keeps only rows where {_sql(_arg(select, "where").this)}.")
    if _arg(select, "group") is not None:
        steps.append(f"Groups the rows by {_listed([_sql(g) for g in _arg(select, "group").expressions])}.")
    calculated = [p for p in select.expressions if not isinstance(p, (exp.Column, exp.Star))
                  and not (isinstance(p, exp.Alias) and isinstance(p.this, exp.Column))]
    plain = ["all columns" if isinstance(p, exp.Star) else p.alias_or_name
             for p in select.expressions if p not in calculated]
    if plain:
        steps.append(f"Shows {_listed(plain)}.")
    for projection in calculated[:MAX_SHOWN]:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        name = projection.alias_or_name
        steps.append(f"Calculates {name} as {_sql(inner)}." if name and name != _sql(inner)
                     else f"Calculates {_sql(inner)}.")
    if _arg(select, "having") is not None:
        steps.append(f"Keeps only groups where {_sql(_arg(select, "having").this)}.")
    if _arg(select, "distinct") is not None:
        steps.append("Removes duplicate rows.")
    return steps + _order_limit(select)


def _order_limit(node: exp.Expression) -> list[str]:
    steps = []
    order = _arg(node, "order")
    if order is not None:
        keys = [f"{_sql(o.this)} ({'descending' if o.args.get('desc') else 'ascending'})"
                for o in order.expressions]
        steps.append(f"Sorts by {_listed(keys)}.")
    limit = _arg(node, "limit")
    if limit is not None and limit.expression is not None:
        steps.append(f"Returns at most {_sql(limit.expression)} rows.")
    return steps


# --- Errors -----------------------------------------------------------------------------

def _columns(dataset: Dataset) -> list[str]:
    return [f"{t.name}.{c.name}" if len(dataset.tables) > 1 else c.name for t in dataset.tables for c in t.columns]


def explain_error(message: str, dataset: Dataset | None) -> str | None:
    """A hint for a user-safe error message, or None when the message says it all."""
    text = message.lower()
    tables = sorted(dataset.table_names) if dataset else []
    if "is not available" in text and "table" in text or "reading from" in text:
        return (f"Questions about this dataset can only use {_listed(tables)}. To use other data, choose its "
                "dataset in the sidebar." if tables else None)
    if match := re.search(r"no such column: ([\w.]+)", message):
        columns = _columns(dataset) if dataset else []
        return (f"There is no column named {match.group(1).rstrip('.')}." +
                (f" Available columns: {_listed(columns)}." if columns else ""))
    if "took too long" in text:
        return "Try a narrower question: add a filter (for example one region or one year) or ask for fewer rows."
    if "could not be parsed" in text:
        return "Check the SQL for typos, unbalanced brackets or quotes. Only standard SQLite SELECT syntax is accepted."
    if "exactly one sql statement" in text:
        return "Run one statement at a time; remove the extra statements after the first semicolon."
    if "only read-only select" in text or "operation that is not allowed" in text:
        return "InsightSQL only reads data. It never changes, adds or deletes data or tables."
    if match := re.search(r"function '(\w+)' is not allowed", message):
        return f"{match.group(1)} is not supported. Supported functions: {_listed(sorted(ALLOWED_FUNCTIONS))}."
    if "recursive" in text:
        return "Recursive queries are not supported; rewrite the query without WITH RECURSIVE."
    return None
