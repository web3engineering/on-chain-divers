#!/usr/bin/env python3
"""Render education articles from templates, running every embedded example.

Project and indexer documentation: https://onchaindivers.com

A template lives in docs/articles/<path>.mdx and is rendered to
docs/pages/<path>.mdx. Prose is copied as is. A line of the form

    {sql example: examples/education/<dir>/<name>.sql}
    {python example: examples/education/<dir>/<name>.py | rows=10}

is replaced by: the example file copied 1:1 into a highlighted code block, a
link to the same file on GitHub, and the result the code returned when this
script ran it. An example that fails or returns no rows fails the build, so a
page can never show code that does not run or a result that code did not
produce.

Options, separated by `|`:
    pinned        the example reads a fixed, historical transaction. Its result
                  must not change between runs; once the rows age out of the
                  table the committed snapshot is shown instead.
    rows=N        show at most N rows (the rest is counted in the caption).
    view=NAME     table (default), heatmap, pipe or cross (a figure drawn from the rows).
    key=value     passed to the view component (for example x=, y=, value=).

Each result is also saved to examples/education/results/, together with the
hash of the code that produced it. `--offline` renders from those snapshots
and refuses any snapshot whose code has changed since it was taken.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "docs" / "articles"
PAGES = ROOT / "docs" / "pages"
EXAMPLES = ROOT / "examples" / "education"
RESULTS = EXAMPLES / "results"
GITHUB = "https://github.com/web3engineering/on-chain-divers/blob/master"

sys.path.insert(0, str(EXAMPLES))
import ocd  # noqa: E402

DIRECTIVE = re.compile(r"^\{(sql|python) example:\s*([^|}\s]+)\s*((?:\|[^}]*)?)\}\s*$")
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")
PLAIN_INT_COLUMNS = re.compile(r"(^|_)(slot|idx|index|version|hop|bucket)$")


VIEWS = {"heatmap": "Heatmap", "pipe": "PipeDiagram", "cross": "CrossDiagram"}


class ExampleError(RuntimeError):
    pass


def parse_options(raw: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition("=")
        options[key.strip()] = value.strip().strip('"') or "true"
    return options


def run_sql(path: Path) -> list[dict]:
    return ocd.query(path.read_text())


def run_python(path: Path) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "rows.json"
        env = dict(os.environ, OCD_RESULT_JSON=str(target), PYTHONPATH=str(EXAMPLES))
        done = subprocess.run(
            [sys.executable, str(path)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=3600
        )
        if done.returncode != 0:
            raise ExampleError(f"{path.name}: exited with {done.returncode}\n{done.stderr[-2000:]}")
        if not target.exists():
            raise ExampleError(f"{path.name}: did not call ocd.show(rows)")
        return json.loads(target.read_text())


def normalise(rows: list[dict]) -> tuple[list[str], list[list]]:
    columns = list(rows[0]) if rows else []
    plain = [[ocd._plain(row[c]) for c in columns] for row in rows]
    return columns, json.loads(json.dumps(plain, default=str))


def result_for(kind: str, relative: str, options: dict[str, str], offline: bool, reuse: bool) -> dict:
    source = ROOT / relative
    if not source.is_file() or EXAMPLES not in source.resolve().parents:
        raise ExampleError(f"{relative}: example must be a file under examples/education/")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    snapshot_path = RESULTS / source.relative_to(EXAMPLES).with_suffix(".json")
    snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else None
    fresh_snapshot = snapshot is not None and snapshot["sha256"] == digest
    pinned = "pinned" in options

    if offline or (reuse and fresh_snapshot):
        if not fresh_snapshot:
            raise ExampleError(f"{relative}: no snapshot for the current code; run without --offline")
        return dict(snapshot, from_snapshot=False)

    try:
        rows = run_sql(source) if kind == "sql" else run_python(source)
    except ExampleError:
        raise
    except Exception as error:  # noqa: BLE001 - any failure of an example fails the build
        raise ExampleError(f"{relative}: {type(error).__name__}: {str(error)[:600]}") from None
    columns, plain = normalise(rows)
    if not plain:
        if pinned and fresh_snapshot:
            print(f"  {relative}: data aged out, showing snapshot from {snapshot['ran_at']}")
            return dict(snapshot, from_snapshot=True)
        raise ExampleError(f"{relative}: returned no rows")
    if pinned and fresh_snapshot and (snapshot["columns"], snapshot["rows"]) != (columns, plain):
        raise ExampleError(f"{relative}: pinned result changed since {snapshot['ran_at']}")
    result = {
        "example": relative,
        "sha256": digest,
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "columns": columns,
        "rows": plain,
    }
    if not (pinned and fresh_snapshot):
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(result, indent=1) + "\n")
    else:
        result["ran_at"] = snapshot["ran_at"]
    return dict(result, from_snapshot=False)


def escape(text: str) -> str:
    return html.escape(text, quote=False).replace("|", "&#124;").replace("{", "&#123;").replace("}", "&#125;")


def cell(value, column: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value) if PLAIN_INT_COLUMNS.search(column) else f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return ", ".join(cell(item, column) for item in value)
    text = str(value).rstrip("\x00")
    if BASE58.match(text):
        if 32 <= len(text) <= 44:
            return f"[`{text[:4]}…{text[-4:]}`](https://solscan.io/account/{text})"
        if 80 <= len(text) <= 90:
            return f"[`{text[:6]}…{text[-4:]}`](https://solscan.io/tx/{text}#balance_change)"
    if len(text) > 72:
        text = text[:70] + "…"
    return escape(text)


def table(columns: list[str], rows: list[list]) -> str:
    numeric = [all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows) for i in range(len(columns))]
    lines = [
        "| " + " | ".join(f"`{c}`" for c in columns) + " |",
        "| " + " | ".join("--:" if n else ":--" for n in numeric) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(v, c) for v, c in zip(row, columns)) + " |")
    return "\n".join(lines)


def render_example(kind: str, relative: str, options: dict[str, str], result: dict) -> str:
    code = (ROOT / relative).read_text().rstrip("\n")
    columns, rows = result["columns"], result["rows"]
    limit = int(options.get("rows", 12))
    shown = rows[:limit]
    view = options.get("view", "table")
    meta = {
        "file": relative,
        "href": f"{GITHUB}/{relative}",
        "ranAt": result["ran_at"],
        "rowCount": len(rows),
        "shown": len(shown) if view == "table" else len(rows),
        "snapshot": bool(result["from_snapshot"]),
    }
    props = " ".join(f"{key}={{{json.dumps(value)}}}" for key, value in meta.items())
    fence = "````" if "```" in code else "```"
    parts = [f"<Example {props}>", "", f"{fence}{'sql' if kind == 'sql' else 'python'}", code, fence, "", "<ExampleResult>", ""]
    if view in VIEWS:
        records = [dict(zip(columns, row)) for row in rows]
        extra = " ".join(
            f"{key}={json.dumps(value)}" for key, value in options.items() if key not in ("view", "rows", "pinned")
        )
        component = VIEWS[view]
        parts += [f"<{component} data={{{json.dumps(records)}}} {extra} />", ""]
    if view != "heatmap":
        parts += [table(columns, shown), ""]
    parts += ["</ExampleResult>", "", "</Example>"]
    return "\n".join(parts)


def render(template: Path, offline: bool, reuse: bool) -> Path:
    relative = template.relative_to(TEMPLATES)
    out_lines = []
    count = 0
    for line in template.read_text().splitlines():
        match = DIRECTIVE.match(line)
        if not match:
            if line.lstrip().startswith(("{sql example", "{python example")):
                raise ExampleError(f"{relative}: malformed example directive: {line}")
            out_lines.append(line)
            continue
        kind, example, raw_options = match.groups()
        options = parse_options(raw_options)
        print(f"  running {example}", flush=True)
        result = result_for(kind, example, options, offline, reuse)
        out_lines.append(render_example(kind, example, options, result))
        count += 1
    text = "\n".join(out_lines) + "\n"
    marker = f"{{/* Generated by scripts/render_articles.py from docs/articles/{relative}. Do not edit. */}}\n\n"
    if text.startswith("---\n"):
        end = text.index("\n---\n", 4) + 5
        text = text[:end] + "\n" + marker + text[end:].lstrip("\n")
    else:
        text = marker + text
    target = PAGES / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    print(f"rendered {relative}: {count} examples")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--offline", action="store_true", help="render from committed snapshots, no database")
    parser.add_argument("--reuse", action="store_true", help="skip examples whose snapshot matches the current code")
    parser.add_argument("--only", help="render only templates whose path contains this text")
    args = parser.parse_args()
    templates = sorted(p for p in TEMPLATES.rglob("*.mdx") if not args.only or args.only in str(p))
    if not templates:
        raise SystemExit("no article templates found")
    try:
        for template in templates:
            render(template, args.offline, args.reuse)
    except ExampleError as error:
        raise SystemExit(f"article example failed: {error}") from None


if __name__ == "__main__":
    main()
