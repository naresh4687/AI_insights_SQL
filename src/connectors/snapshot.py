"""Turn data fetched from a connection into an import, so it goes through the same quality
checks, cleaning options, confirmation and all-or-nothing save as an uploaded file.

The fetched data becomes a ``RawTable`` of text; the original kept for the dataset is the data
as fetched (CSV for a database table, the raw JSON pages for an API). For database tables the
column types are preset from the server's own types, so values that do not fit are reported.
"""

import json
from dataclasses import dataclass

import pandas as pd

from src.connectors import databases, rest
from src.connectors.profiles import ConnectorError, Profile
from src.ingest.preprocess import ColumnOptions
from src.ingest.readers import RawTable


@dataclass
class Snapshot:
    raw: RawTable
    content: bytes  # stored unchanged as the dataset's original
    source: dict  # how to fetch it again (non-secret), stored with the dataset
    type_presets: dict[int, ColumnOptions]  # by column position


def from_database(profile: Profile, password: str, schema: str, table: str, column_names: list[str],
                  max_rows: int) -> Snapshot:
    described = {c.name: c for c in databases.columns(profile, password, schema, table)}
    frame, truncated = databases.fetch(profile, password, schema, table, column_names, max_rows)
    if truncated:
        raise ConnectorError(f"{schema}.{table} has more than {max_rows:,} rows, the import limit. Ask an "
                             "administrator to raise INSIGHTSQL_IMPORT_MAX_ROWS, or import a smaller view.")
    raw = RawTable(file_name=f"{schema}.{table}.csv", file_type=profile.kind, headers=list(frame.columns),
                   frame=frame.set_axis(range(frame.shape[1]), axis=1))
    presets = {i: ColumnOptions(type=described[name].kind) for i, name in enumerate(column_names)
               if described[name].kind in ("integer", "float", "boolean", "date", "datetime")}
    return Snapshot(
        raw=raw, content=frame.to_csv(index=False).encode("utf-8"), type_presets=presets,
        source={"connection_id": profile.connection_id, "kind": profile.kind, "schema": schema, "table": table,
                "columns": list(column_names),
                "source_types": {name: described[name].source_type for name in column_names}},
    )


def from_api(profile: Profile, secret: str | None, endpoint: rest.Endpoint, max_records: int,
             max_columns: int) -> Snapshot:
    result = rest.fetch(profile, secret, endpoint, max_records)
    if not result.records:
        raise ConnectorError("The API returned no records.")
    frame = rest.to_frame(result.records)
    if frame.shape[1] > max_columns:
        raise ConnectorError(f"The records have {frame.shape[1]} fields; the limit is {max_columns}.")
    name = endpoint.path.strip("/").replace("/", "_") or "records"
    raw = RawTable(file_name=f"{name}.json", file_type="rest", headers=[str(c) for c in frame.columns],
                   frame=frame.set_axis(range(frame.shape[1]), axis=1).reset_index(drop=True))
    content = b"[" + b",\n".join(result.pages) + b"]"  # the pages exactly as received
    return Snapshot(raw=raw, content=content, type_presets={},
                    source={"connection_id": profile.connection_id, "kind": "rest", "endpoint": endpoint.to_dict(),
                            "pages": len(result.pages)})


def describe_types(source: dict) -> pd.DataFrame | None:
    """Source column types next to the InsightSQL types they map to (database snapshots)."""
    if "source_types" not in source:
        return None
    return pd.DataFrame([{"Column": name, "Server type": kind} for name, kind in source["source_types"].items()])


def source_label(source: dict) -> str:
    if source.get("kind") == "rest":
        return f"{source['endpoint']['path']} ({source.get('pages', 1)} page(s))"
    return f"{source['schema']}.{source['table']}"


def to_json(source: dict) -> str:
    return json.dumps(source, sort_keys=True)
