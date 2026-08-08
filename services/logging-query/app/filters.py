from __future__ import annotations

from datetime import datetime
from typing import Any

from app.pagination import decode_cursor


def build_log_query(
    tenant_id: str,
    *,
    level: str | None = None,
    service: str | None = None,
    environment: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> tuple[str, list[Any]]:
    clauses = ["tenant_id = $1"]
    values: list[Any] = [tenant_id]

    def add(column: str, value: Any, operator: str = "=") -> None:
        if value is not None:
            values.append(value)
            clauses.append(f"{column} {operator} ${len(values)}")

    add("level", level)
    add("service", service)
    add("environment", environment)
    add("trace_id", trace_id)
    add("request_id", request_id)
    add("timestamp", from_time, ">=")
    add("timestamp", to_time, "<=")
    if search:
        values.append(f"%{search}%")
        clauses.append(f"message ILIKE ${len(values)}")
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        values.extend([cursor_time, cursor_id])
        clauses.append(f"(timestamp, event_id) < (${len(values)-1}, ${len(values)}::uuid)")
    values.append(max(1, min(limit, 500)))
    sql = f"""
        SELECT event_id, timestamp, ingested_at, level, message, service,
               environment, tenant_id, user_id, request_id, trace_id,
               tags, metadata, schema_version, event_fingerprint
        FROM logs
        WHERE {' AND '.join(clauses)}
        ORDER BY timestamp DESC, event_id DESC
        LIMIT ${len(values)}
    """
    return sql, values
