#!/usr/bin/env python3
"""Scan, download and reconstruct HyperLiquid recovery files.

Data and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import io
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import msgpack
import zstandard
from dotenv import dotenv_values

from archive import download, scan


def seek_key(unpacker: msgpack.Unpacker, wanted: str) -> None:
    for _ in range(unpacker.read_map_header()):
        key = unpacker.unpack()
        if key == wanted:
            return
        unpacker.skip()
    raise KeyError(wanted)


def seek_index(unpacker: msgpack.Unpacker, wanted: int) -> None:
    count = unpacker.read_array_header()
    if wanted < 0 or wanted >= count:
        raise IndexError(wanted)
    for _ in range(wanted):
        unpacker.skip()


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_snapshot_context(source) -> dict:
    unpacker = msgpack.Unpacker(source, raw=False, strict_map_key=False)
    seek_key(unpacker, "exchange")
    seek_key(unpacker, "locus")
    seek_key(unpacker, "ctx")
    return unpacker.unpack()


def snapshot_context(path: Path) -> dict:
    with path.open("rb") as source:
        return read_snapshot_context(source)


def remote_snapshot_context(source: str, relative_path: str) -> dict:
    encoded = "/".join(urllib.parse.quote(part) for part in relative_path.split("/"))
    url = urllib.parse.urljoin(source.rstrip("/") + "/", encoded)
    request = urllib.request.Request(url, headers={"User-Agent": "onchaindivers-examples/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return read_snapshot_context(response)


def asset_location(asset: int) -> tuple[str, int, int | None]:
    if 0 <= asset < 10_000:
        return "perp", asset, 0
    if 10_000 <= asset < 100_000:
        return "spot", asset - 10_000, None
    if 110_000 <= asset < 100_000_000:
        dex = (asset - 100_000) // 10_000
        return "perp", asset - (100_000 + dex * 10_000), dex
    raise ValueError("unsupported HyperLiquid action asset")


def load_raw_book(snapshot: Path, asset: int) -> dict:
    kind, book_index, dex_index = asset_location(asset)
    with snapshot.open("rb") as source:
        unpacker = msgpack.Unpacker(source, raw=False, strict_map_key=False)
        seek_key(unpacker, "exchange")
        if kind == "spot":
            seek_key(unpacker, "spot_books")
            seek_index(unpacker, book_index)
        else:
            seek_key(unpacker, "perp_dexs")
            assert dex_index is not None
            seek_index(unpacker, dex_index)
            seek_key(unpacker, "books")
            seek_index(unpacker, book_index)
        return unpacker.unpack()


def scaled(value: int, decimals: int) -> str:
    rendered = format(Decimal(value) / (Decimal(10) ** decimals), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def raw_snapshot_orders(snapshot: Path, asset: int, size_decimals: int) -> dict[int, dict]:
    book = load_raw_book(snapshot, asset)
    arena = book["bod"]["e"]
    price_decimals = 6 - size_decimals
    orders: dict[int, dict] = {}
    for raw_oid, raw_slot in book["oid_to_key"]:
        oid, slot = int(raw_oid), int(raw_slot)
        raw = arena[slot]["o"]
        command = raw["c"]
        orders[oid] = {
            "oid": oid,
            "side": command["s"],
            "px": scaled(int(command["l"]), price_decimals),
            "sz": scaled(int(raw["r"]), size_decimals),
        }
    return orders


def raw_diff_events(paths: list[Path], symbol: str):
    for path in paths:
        with path.open("rb") as raw:
            binary = zstandard.ZstdDecompressor().stream_reader(raw) if path.suffix == ".zst" else raw
            stream = io.TextIOWrapper(binary, encoding="utf-8")
            for line in stream:
                try:
                    envelope = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for event in envelope.get("events", []):
                    if isinstance(event, dict) and event.get("coin") == symbol:
                        yield envelope.get("block_time"), envelope.get("block_number"), event


def apply_raw_diff(orders: dict[int, dict], event: dict) -> None:
    oid = int(event["oid"])
    change = event["raw_book_diff"]
    if change == "remove":
        orders.pop(oid, None)
    elif isinstance(change, dict) and "new" in change:
        orders[oid] = {
            "oid": oid,
            "side": event["side"],
            "px": str(event["px"]),
            "sz": str(change["new"]["sz"]),
        }
    elif isinstance(change, dict) and "update" in change and oid in orders:
        orders[oid]["sz"] = str(change["update"]["newSz"])


def summarize(orders: dict[int, dict], symbol: str, timestamp: str | None) -> dict:
    levels: dict[str, dict[Decimal, Decimal]] = {"B": {}, "A": {}}
    for order in orders.values():
        side, price, size = order["side"], Decimal(order["px"]), Decimal(order["sz"])
        levels[side][price] = levels[side].get(price, Decimal(0)) + size
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "best_bid": str(max(levels["B"])) if levels["B"] else None,
        "best_ask": str(min(levels["A"])) if levels["A"] else None,
        "orders": len(orders),
    }


def reconstruct_raw(
    snapshot: Path,
    diffs: list[Path],
    symbol: str,
    asset: int,
    size_decimals: int,
) -> dict:
    orders = raw_snapshot_orders(snapshot, asset, size_decimals)
    timestamp = None
    for timestamp, _, event in raw_diff_events(diffs, symbol):
        apply_raw_diff(orders, event)
    return summarize(orders, symbol, timestamp)


def reconstruct_raw_at(
    snapshot: Path,
    diffs: list[Path],
    symbol: str,
    asset: int,
    size_decimals: int,
    target: datetime,
) -> dict:
    context = snapshot_context(snapshot)
    checkpoint_time = parse_datetime(str(context["time"]))
    checkpoint_height = int(context["height"])
    if checkpoint_time > target:
        raise ValueError("checkpoint is newer than target")
    orders = raw_snapshot_orders(snapshot, asset, size_decimals)
    last_time = checkpoint_time
    for raw_time, raw_height, event in raw_diff_events(diffs, symbol):
        event_time = parse_datetime(str(raw_time))
        if raw_height is not None and int(raw_height) <= checkpoint_height:
            continue
        if event_time > target:
            continue
        apply_raw_diff(orders, event)
        if event_time > last_time:
            last_time = event_time
    result = summarize(orders, symbol, last_time.isoformat().replace("+00:00", "Z"))
    result["checkpoint_time"] = checkpoint_time.isoformat().replace("+00:00", "Z")
    result["target_time"] = target.isoformat().replace("+00:00", "Z")
    return result


def configured_source() -> str | None:
    return os.environ.get("HYPERLIQUID_ORDER_BOOKS") or dotenv_values(".env").get(
        "HYPERLIQUID_ORDER_BOOKS"
    )


def reconstruct(path: Path, symbol: str) -> dict:
    orders: dict[int, dict] = {}
    timestamp = None
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        if row.get("symbol") not in {None, symbol}:
            continue
        if row.get("event_type") == "book_snapshot":
            orders = {int(order["oid"]): order for order in row.get("orders", [])}
            timestamp = row.get("time")
            continue
        if row.get("event_type") != "book_diff":
            continue
        event = row.get("event", row)
        oid = int(event["oid"])
        change = event["raw_book_diff"]
        if change == "remove":
            orders.pop(oid, None)
        elif "new" in change:
            orders[oid] = {
                "oid": oid,
                "side": event["side"],
                "px": str(event["px"]),
                "sz": str(change["new"]["sz"]),
            }
        elif "update" in change and oid in orders:
            orders[oid]["sz"] = str(change["update"]["newSz"])
        timestamp = row.get("block_time", timestamp)
    if not orders:
        raise ValueError("no order-level snapshot or remaining orders found")
    return summarize(orders, symbol, timestamp)


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
    replay.add_argument("symbol")
    raw_replay = commands.add_parser("reconstruct-raw")
    raw_replay.add_argument("snapshot", type=Path)
    raw_replay.add_argument("symbol")
    raw_replay.add_argument("asset", type=int)
    raw_replay.add_argument("size_decimals", type=int)
    raw_replay.add_argument("diffs", nargs="+", type=Path)
    raw_at = commands.add_parser("reconstruct-raw-at")
    raw_at.add_argument("snapshot", type=Path)
    raw_at.add_argument("symbol")
    raw_at.add_argument("asset", type=int)
    raw_at.add_argument("size_decimals", type=int)
    raw_at.add_argument("target")
    raw_at.add_argument("diffs", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "reconstruct":
        print(json.dumps(reconstruct(args.capture, args.symbol), indent=2))
        return
    if args.command == "reconstruct-raw":
        print(json.dumps(reconstruct_raw(
            args.snapshot, args.diffs, args.symbol, args.asset, args.size_decimals
        ), indent=2))
        return
    if args.command == "reconstruct-raw-at":
        print(json.dumps(reconstruct_raw_at(
            args.snapshot, args.diffs, args.symbol, args.asset, args.size_decimals,
            parse_datetime(args.target),
        ), indent=2))
        return
    source = args.source or configured_source()
    if not source:
        raise SystemExit("set HYPERLIQUID_ORDER_BOOKS or pass --source")
    if args.command == "scan":
        names = scan(source, (".zst", ".rmp", ".jsonl", ".log"))
        print(json.dumps({"capture_count": len(names), "latest": names[-10:]}, indent=2))
    else:
        download(source, args.name, args.output)
        print(json.dumps({"downloaded": args.name, "output": str(args.output)}))


if __name__ == "__main__":
    main()
