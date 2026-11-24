"""Small helpers shared by the education examples.

Keeps connection, retry and printing code out of the examples so that each
example file shows only the query and the logic that matters.

    PYTHONPATH=examples/education python3 examples/education/sol_flows/funding_pipe.py

Credentials are read from the `.env` file at the repository root
(CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USERNAME, CLICKHOUSE_PASSWORD).
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import clickhouse_connect
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOL = 1_000_000_000  # lamports in one SOL

_client = None


def _connect():
    env = dotenv_values(ROOT / ".env")
    return clickhouse_connect.get_client(
        host=env["CLICKHOUSE_HOST"],
        port=int(env.get("CLICKHOUSE_PORT") or 8123),
        username=env["CLICKHOUSE_USERNAME"],
        password=env["CLICKHOUSE_PASSWORD"],
        compress=False,
    )


def query(sql: str, parameters: dict[str, Any] | None = None, wait_s: int = 1800) -> list[dict]:
    """Run one read-only query and return rows as dictionaries.

    Read-only users may run one query at a time, so a busy slot (ClickHouse
    code 202) is retried until it frees up or `wait_s` seconds pass.
    """
    global _client
    deadline = time.time() + wait_s
    while True:
        try:
            if _client is None:
                _client = _connect()
            result = _client.query(
                sql,
                parameters=parameters,
                settings={"readonly": 1, "max_execution_time": 300},
            )
            return [dict(zip(result.column_names, row)) for row in result.result_rows]
        except Exception as error:  # noqa: BLE001 - retry only the busy-slot case
            busy = "TOO_MANY_SIMULTANEOUS_QUERIES" in str(error) or "Code: 202" in str(error)
            if not busy or time.time() > deadline:
                raise
            _client = None
            time.sleep(1)


def short(address: str) -> str:
    """Shorten a wallet or signature for printing: 9xQe…Vp3k."""
    return f"{address[:4]}…{address[-4:]}" if len(address) > 12 else address


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:  # print every time in UTC
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def show(rows: list[dict]) -> None:
    """Print rows as a text table.

    The documentation build sets OCD_RESULT_JSON; the same rows are then also
    written there, and that file is what the published page displays.
    """
    rows = [{key: _plain(value) for key, value in row.items()} for row in rows]
    target = os.environ.get("OCD_RESULT_JSON")
    if target:
        Path(target).write_text(json.dumps(rows))
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0])
    cells = [[short(str(row[c])) if isinstance(row[c], str) else str(row[c]) for c in columns] for row in rows]
    widths = [max(len(c), *(len(line[i]) for line in cells)) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    for line in cells:
        print("  ".join(v.ljust(w) for v, w in zip(line, widths)))
