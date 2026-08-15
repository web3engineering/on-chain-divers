#!/usr/bin/env python3
"""Scan, download and reconstruct Polymarket CLOB capture files.

Data and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import io
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import zstandard
from dotenv import dotenv_values

from archive import download, scan


def configured_source() -> str | None:
    return os.environ.get("POLYMARKET_ORDERBOOKS") or dotenv_values(".env").get(
        "POLYMARKET_ORDERBOOKS"
    )


def captured_records(path: Path) -> Iterator[tuple[int | None, dict]]:
    with path.open("rb") as raw:
        binary = zstandard.ZstdDecompressor().stream_reader(raw) if path.suffix == ".zst" else raw
        stream = io.TextIOWrapper(binary, encoding="utf-8")
        for text_line in stream:
            line = text_line.strip()
            if not line or line.startswith("#"):
                continue
            pieces = line.split("\t", 1)
            try:
                capture_ms = int(pieces[0]) if len(pieces) == 2 else None
            except ValueError:
                capture_ms = None
            payload = pieces[-1]
            decoded = json.loads(payload)
            for event in decoded if isinstance(decoded, list) else [decoded]:
                if isinstance(event, dict):
                    yield capture_ms, event


def records(path: Path) -> Iterator[dict]:
    for _, event in captured_records(path):
        yield event


def event_millis(event: dict, capture_ms: int | None) -> int | None:
    try:
        return int(event.get("timestamp") or capture_ms)
    except (TypeError, ValueError):
        return None


def best_quote_series(
    path: Path,
    asset_ids: set[str],
    start_ms: int,
    end_ms: int,
) -> dict[str, list[dict]]:
    """Read the recorder's explicit best-bid/ask stream for selected assets.

    Dedicated market captures contain full ``book`` and ``price_change`` data,
    but also emit ``best_bid_ask`` whenever top of book moves.  Those records
    are the lossless and inexpensive input for charts; ``reconstruct_at`` is
    still used separately by the example to validate the underlying replay.
    """
    series: dict[str, list[dict]] = {asset_id: [] for asset_id in asset_ids}
    for capture_ms, event in captured_records(path):
        if event.get("event_type") != "best_bid_ask":
            continue
        asset_id = str(event.get("asset_id") or "")
        timestamp = event_millis(event, capture_ms)
        if asset_id not in series or timestamp is None or not start_ms <= timestamp <= end_ms:
            continue
        try:
            bid = Decimal(str(event["best_bid"]))
            ask = Decimal(str(event["best_ask"]))
        except (KeyError, TypeError, ValueError):
            continue
        # Prediction books legitimately use 0 and 1 as boundary quotes near
        # resolution. They remain valid so long as the book is not crossed.
        if bid < 0 or ask <= bid or ask > 1:
            continue
        point = {
            "timestamp_ms": timestamp,
            "best_bid": float(bid),
            "best_ask": float(ask),
            "mid": float((bid + ask) / 2),
            "spread": float(ask - bid),
        }
        # Several recorder messages can share a millisecond. Keep only the
        # final state at that timestamp so plot lines remain deterministic.
        if series[asset_id] and series[asset_id][-1]["timestamp_ms"] == timestamp:
            series[asset_id][-1] = point
        else:
            series[asset_id].append(point)
    missing = [asset_id for asset_id, points in series.items() if not points]
    if missing:
        raise ValueError(f"no best-bid/ask records for {len(missing)} requested asset(s)")
    return series


def reconstruct_at(path: Path, target_ms: int, asset_id: str | None = None) -> dict:
    """Build one complete CLOB asset book at a historical millisecond."""
    selected: tuple[int, str] | None = None
    for capture_ms, event in captured_records(path):
        if event.get("event_type") != "book":
            continue
        event_asset = str(event.get("asset_id") or "")
        timestamp = event_millis(event, capture_ms)
        if (
            not event_asset
            or timestamp is None
            or timestamp > target_ms
            or (asset_id is not None and event_asset != asset_id)
            or not event.get("bids")
            or not event.get("asks")
        ):
            continue
        if selected is None or timestamp > selected[0]:
            selected = (timestamp, event_asset)
    if selected is None:
        raise ValueError("capture contains no complete book snapshot at or before target")

    snapshot_ms, selected_asset = selected
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    last_event_ms = snapshot_ms
    anchored = False
    for capture_ms, event in captured_records(path):
        timestamp = event_millis(event, capture_ms)
        if timestamp is None or timestamp < snapshot_ms or timestamp > target_ms:
            continue
        if event.get("event_type") == "book" and event.get("asset_id") == selected_asset:
            bids = {Decimal(x["price"]): Decimal(x["size"]) for x in event.get("bids", [])}
            asks = {Decimal(x["price"]): Decimal(x["size"]) for x in event.get("asks", [])}
            anchored = True
            last_event_ms = timestamp
            continue
        if event.get("event_type") != "price_change" or not anchored:
            continue
        for change in event.get("price_changes", []):
            if change.get("asset_id") != selected_asset:
                continue
            levels = bids if change.get("side") in {"BUY", "B"} else asks
            price, size = Decimal(change["price"]), Decimal(change["size"])
            if size == 0:
                levels.pop(price, None)
            else:
                levels[price] = size
            last_event_ms = timestamp
    if not bids or not asks:
        raise ValueError("historical replay produced an empty side")
    return {
        "asset_id": selected_asset,
        "target_ms": target_ms,
        "snapshot_ms": snapshot_ms,
        "last_event_ms": last_event_ms,
        "best_bid": str(max(bids)),
        "best_ask": str(min(asks)),
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def reconstruct(path: Path, asset_id: str) -> dict:
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    timestamp: str | None = None
    seen_snapshot = False
    for event in records(path):
        if event.get("asset_id") == asset_id and event.get("event_type") == "book":
            bids = {Decimal(x["price"]): Decimal(x["size"]) for x in event.get("bids", [])}
            asks = {Decimal(x["price"]): Decimal(x["size"]) for x in event.get("asks", [])}
            timestamp = str(event.get("timestamp"))
            seen_snapshot = True
        if event.get("event_type") != "price_change":
            continue
        for change in event.get("price_changes", []):
            if change.get("asset_id") != asset_id:
                continue
            levels = bids if change.get("side") in {"BUY", "B"} else asks
            price, size = Decimal(change["price"]), Decimal(change["size"])
            if size == 0:
                levels.pop(price, None)
            else:
                levels[price] = size
            timestamp = str(event.get("timestamp") or timestamp)
    if not seen_snapshot:
        raise ValueError("no book snapshot found for requested asset")
    return {
        "asset_id": asset_id,
        "timestamp": timestamp,
        "best_bid": str(max(bids)) if bids else None,
        "best_ask": str(min(asks)) if asks else None,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan_parser = commands.add_parser("scan")
    scan_parser.add_argument("--source")
    get_parser = commands.add_parser("download")
    get_parser.add_argument("name")
    get_parser.add_argument("output", type=Path)
    get_parser.add_argument("--source")
    replay = commands.add_parser("reconstruct")
    replay.add_argument("capture", type=Path)
    replay.add_argument("asset_id")
    historical = commands.add_parser("reconstruct-at")
    historical.add_argument("capture", type=Path)
    historical.add_argument("target_ms", type=int)
    historical.add_argument("--asset-id")
    args = parser.parse_args()
    if args.command == "reconstruct":
        print(json.dumps(reconstruct(args.capture, args.asset_id), indent=2))
        return
    if args.command == "reconstruct-at":
        print(json.dumps(reconstruct_at(args.capture, args.target_ms, args.asset_id), indent=2))
        return
    source = args.source or configured_source()
    if not source:
        raise SystemExit("set POLYMARKET_ORDERBOOKS or pass --source")
    if args.command == "scan":
        names = scan(source, (".log", ".log.zst"))
        print(json.dumps({"capture_count": len(names), "latest": names[-10:]}, indent=2))
    else:
        download(source, args.name, args.output)
        print(json.dumps({"downloaded": args.name, "output": str(args.output)}))


if __name__ == "__main__":
    main()
