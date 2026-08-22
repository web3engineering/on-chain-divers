#!/usr/bin/env python3
"""Execute every published example in the Docker documentation gate.

Project and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import msgpack
from dotenv import dotenv_values

from clickhouse_accessors import (
    ClickHouseAccessor,
    HyperLiquidAccessor,
    PolymarketAccessor,
    RobinhoodAccessor,
)


ROOT = Path(__file__).resolve().parents[1]
ORDERBOOKS = ROOT / "examples" / "orderbooks"
sys.path.insert(0, str(ORDERBOOKS))


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


poly = module("poly_example", ORDERBOOKS / "polymarket.py")
hyper = module("hyper_example", ORDERBOOKS / "hyperliquid.py")
archive = module("archive_example", ORDERBOOKS / "archive.py")
fees = module("fees_example", ROOT / "examples" / "fees" / "global_fees.py")
bitcoin = module(
    "bitcoin_5m_updown", ROOT / "examples" / "cross_venue" / "bitcoin_5m_updown.py"
)
microprice = module(
    "microprice_research",
    ROOT / "examples" / "cross_venue" / "microprice_research.py",
)
research = module(
    "pumpfun_creator_and_migration_research",
    ROOT / "examples" / "research" / "generate_pumpfun_research.py",
)
wallet_fingerprints = module(
    "wallet_fingerprint_research",
    ROOT / "examples" / "research" / "generate_wallet_fingerprint_research.py",
)
swqos_research = module(
    "swqos_research",
    ROOT / "examples" / "research" / "generate_swqos_research.py",
)


def env_value(key: str) -> str | None:
    return os.environ.get(key) or dotenv_values(ROOT / ".env").get(key)


def valid_book(book: dict) -> bool:
    bid, ask = book.get("best_bid"), book.get("best_ask")
    return bid is not None and ask is not None and Decimal(str(bid)) < Decimal(str(ask))


def hyper_fixture_snapshot() -> dict:
    return {
        "exchange": {
            "locus": {"ctx": {"height": 100, "time": "2026-08-15T00:00:00Z"}},
            "perp_dexs": [
                {
                    "books": [
                        {
                            "bod": {
                                "e": [
                                    {"o": {"c": {"s": "B", "l": 12000000000}, "r": 4}},
                                    {"o": {"c": {"s": "A", "l": 12000100000}, "r": 5}},
                                ]
                            },
                            "oid_to_key": [[1, 0], [3, 1]],
                        }
                    ]
                }
            ],
        }
    }


def select_polymarket_capture(names: list[str], target_ms: int) -> str:
    pattern = re.compile(r"capture\.(\d+)\.log(?:\.zst)?$")
    candidates: list[tuple[int, int, str]] = []
    for name in names:
        match = pattern.fullmatch(name)
        if match and int(match.group(1)) <= target_ms:
            candidates.append((int(match.group(1)), name.endswith(".zst"), name))
    if not candidates:
        raise AssertionError("no Polymarket capture starts at or before the 24-hour target")
    return max(candidates)[2]


def select_hyperliquid_checkpoint(
    source: str, names: list[str], target: datetime
) -> tuple[str, dict]:
    checkpoints = sorted(name for name in names if name.startswith("abci/") and name.endswith(".rmp"))
    if not checkpoints:
        raise AssertionError("HyperLiquid archive contains no ABCI checkpoints")
    selected: tuple[str, dict] | None = None
    low, high = 0, len(checkpoints) - 1
    while low <= high:
        middle = (low + high) // 2
        context = hyper.remote_snapshot_context(source, checkpoints[middle])
        checkpoint_time = hyper.parse_datetime(str(context["time"]))
        if checkpoint_time <= target:
            selected = checkpoints[middle], context
            low = middle + 1
        else:
            high = middle - 1
    if selected is None:
        raise AssertionError("no HyperLiquid checkpoint exists before the 24-hour target")
    return selected


def hyperliquid_diff_paths(
    names: list[str], checkpoint_time: datetime, target: datetime
) -> list[str]:
    available = set(names)
    cursor = checkpoint_time.replace(minute=0, second=0, microsecond=0)
    final = target.replace(minute=0, second=0, microsecond=0)
    paths: list[str] = []
    while cursor <= final:
        base = f"book_diffs/{cursor:%Y%m%d}/{cursor.hour}"
        path = base + ".zst" if base + ".zst" in available else base
        if path not in available:
            raise AssertionError(f"HyperLiquid archive gap at {cursor.isoformat()}")
        paths.append(path)
        cursor += timedelta(hours=1)
    return paths


def verify_live_books_24h(
    poly_source: str,
    poly_names: list[str],
    hyper_source: str,
    hyper_names: list[str],
) -> None:
    target = datetime.now(timezone.utc) - timedelta(hours=24)
    target_ms = int(target.timestamp() * 1000)
    poly_name = select_polymarket_capture(poly_names, target_ms)
    poly_size = archive.content_length(poly_source, poly_name)
    print(f"downloading 24h Polymarket capture: {poly_name} ({poly_size} bytes)")
    with tempfile.TemporaryDirectory() as temporary:
        capture = Path(temporary) / "polymarket.log.zst"
        archive.download(poly_source, poly_name, capture, max_bytes=512 * 1024 * 1024)
        poly_book = poly.reconstruct_at(capture, target_ms)
    if not valid_book(poly_book):
        raise AssertionError("24h Polymarket replay produced an invalid or crossed book")
    print(
        "verified 24h order book: Polymarket "
        f"({poly_book['bid_levels']} bids, {poly_book['ask_levels']} asks)"
    )

    checkpoint_name, context = select_hyperliquid_checkpoint(hyper_source, hyper_names, target)
    checkpoint_time = hyper.parse_datetime(str(context["time"]))
    diff_names = hyperliquid_diff_paths(hyper_names, checkpoint_time, target)
    input_names = [checkpoint_name, *diff_names]
    sizes = [archive.content_length(hyper_source, name) for name in input_names]
    print(
        "downloading 24h HyperLiquid inputs: "
        f"{checkpoint_name} plus {len(diff_names)} diff file(s) ({sum(sizes)} bytes)"
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        checkpoint = root / "checkpoint.rmp"
        archive.download(
            hyper_source, checkpoint_name, checkpoint, max_bytes=3 * 1024 * 1024 * 1024
        )
        diffs: list[Path] = []
        for index, name in enumerate(diff_names):
            destination = root / f"diff-{index}.zst"
            archive.download(
                hyper_source, name, destination, max_bytes=3 * 1024 * 1024 * 1024
            )
            diffs.append(destination)
        hyper_book = hyper.reconstruct_raw_at(checkpoint, diffs, "BTC", 0, 5, target)
    if hyper_book.get("orders", 0) <= 0 or not valid_book(hyper_book):
        raise AssertionError("24h HyperLiquid replay produced an invalid or crossed BTC book")
    print(f"verified 24h order book: HyperLiquid BTC ({hyper_book['orders']} live orders)")


def verify_sql() -> None:
    examples = [
        (ClickHouseAccessor, "solana/transfer_activity.sql"),
        (ClickHouseAccessor, "solana/pumpswap_reserve_checks.sql"),
        (ClickHouseAccessor, "solana/creator_migration_rates.sql"),
        (PolymarketAccessor, "polymarket/recent_fills.sql"),
        (HyperLiquidAccessor, "hyperliquid/largest_recent_fills.sql"),
        (RobinhoodAccessor, "robinhood/recent_uniswap_trades.sql"),
        (RobinhoodAccessor, "robinhood/most_active_pools.sql"),
    ]
    for accessor_type, relative in examples:
        client = accessor_type(str(ROOT / ".env"))
        try:
            try:
                rows = client.query(
                    (ROOT / "examples" / relative).read_text(),
                    settings={"max_execution_time": 90, "readonly": 1},
                )
            except Exception as error:
                raise RuntimeError(
                    f"{relative}: query failed ({type(error).__name__})"
                ) from None
        finally:
            client.disconnect()
        if not rows:
            raise AssertionError(f"{relative}: query returned no rows")
        if relative.endswith("pumpswap_reserve_checks.sql"):
            checks = ("base_reserves_match", "quote_reserves_match", "lp_fee_math_matches")
            if any(not bool(row[key]) for row in rows for key in checks):
                raise AssertionError(f"{relative}: reserve or fee invariant failed")
        print(f"verified SQL: {relative} ({len(rows)} rows)")


def verify_orderbooks(strict_live: bool) -> None:
    poly_root = ORDERBOOKS / "fixtures" / "polymarket"
    names = archive.scan(str(poly_root), (".log", ".log.zst"))
    if names != ["capture.1000.log"]:
        raise AssertionError("Polymarket fixture scan returned unexpected files")
    with tempfile.TemporaryDirectory() as temporary:
        copied = Path(temporary) / names[0]
        archive.download(str(poly_root), names[0], copied)
        book = poly.reconstruct(copied, "asset-yes")
    if book["best_bid"] != "0.50" or book["best_ask"] != "0.52":
        raise AssertionError("Polymarket replay produced the wrong top of book")
    print("verified order book: Polymarket scan, download and replay")

    # Dedicated capture size and position within an hour are not validity
    # signals. A quiet but replayable :55 market must remain selectable; the
    # live path performs the substantive two-outcome replay checks afterward.
    class CaptureMetadataFixture:
        def query(self, _sql: str, **_kwargs) -> list[dict]:
            return [{
                "event_id": "fixture-event",
                "slug": "btc-updown-5m-1786751700",
                "title": "Bitcoin Up or Down",
                "interval_start": 1786751700,
            }]

    with tempfile.TemporaryDirectory() as temporary:
        capture_root = Path(temporary)
        capture_name = "btc-updown-5m-1786751700.log.zst"
        (capture_root / capture_name).write_bytes(b"small fixture")
        selected = bitcoin.choose_market(
            CaptureMetadataFixture(),
            datetime.fromtimestamp(1786751700, tz=timezone.utc),
            {capture_name},
            str(capture_root),
        )
    if selected["capture_name"] != capture_name or selected["capture_bytes"] != 13:
        raise AssertionError("quiet or hour-boundary Polymarket capture was rejected")
    print("verified capture selection: activity-independent BTC 5m candidate")

    hyper_root = ORDERBOOKS / "fixtures" / "hyperliquid"
    names = archive.scan(str(hyper_root), (".jsonl", ".log"))
    with tempfile.TemporaryDirectory() as temporary:
        copied = Path(temporary) / names[0]
        archive.download(str(hyper_root), names[0], copied)
        book = hyper.reconstruct(copied, "BTC")
    if book["best_bid"] != "120000" or book["best_ask"] != "120002":
        raise AssertionError("HyperLiquid replay produced the wrong top of book")
    print("verified order book: HyperLiquid scan, download and replay")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        snapshot = root / "checkpoint.rmp"
        diff = root / "0"
        snapshot.write_bytes(msgpack.packb(hyper_fixture_snapshot()))
        diff.write_text(json.dumps({
            "block_time": "2026-08-15T00:00:03Z",
            "events": [{
                "coin": "BTC", "oid": 3, "side": "A", "px": "120001",
                "raw_book_diff": "remove",
            }, {
                "coin": "BTC", "oid": 4, "side": "A", "px": "120002",
                "raw_book_diff": {"new": {"sz": "0.7"}},
            }],
        }) + "\n")
        book = hyper.reconstruct_raw(snapshot, [diff], "BTC", 0, 1)
    if book["best_bid"] != "120000" or book["best_ask"] != "120002":
        raise AssertionError("HyperLiquid raw checkpoint replay produced the wrong book")
    print("verified raw order book: HyperLiquid MessagePack checkpoint and hourly diffs")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        snapshot = root / "checkpoint.rmp"
        diff = root / "0"
        snapshot.write_bytes(msgpack.packb(hyper_fixture_snapshot()))
        diff.write_text(json.dumps({
            "block_time": "2026-08-15T00:00:01Z",
            "block_number": 101,
            "events": [{
                "coin": "BTC", "oid": 3, "side": "A", "px": "120001",
                "raw_book_diff": "remove",
            }, {
                "coin": "BTC", "oid": 4, "side": "A", "px": "120002",
                "raw_book_diff": {"new": {"sz": "0.7"}},
            }],
        }) + "\n")
        at = datetime(2026, 8, 15, 0, 0, 2, tzinfo=timezone.utc)
        book = hyper.reconstruct_raw_at(snapshot, [diff], "BTC", 0, 1, at)
    if book["best_bid"] != "120000" or book["best_ask"] != "120002":
        raise AssertionError("HyperLiquid timestamp-bounded raw replay produced the wrong book")
    print("verified historical replay: HyperLiquid target-time bound")

    poly_source = env_value("POLYMARKET_ORDERBOOKS")
    poly_live_names: list[str] = []
    if poly_source:
        poly_live_names = archive.scan(poly_source, (".log", ".log.zst"))
        if not poly_live_names:
            raise AssertionError("live Polymarket archive contains no capture files")
        print(f"verified live archive: Polymarket ({len(poly_live_names)} captures discoverable)")
    elif strict_live:
        raise ValueError("POLYMARKET_ORDERBOOKS is required for strict verification")

    hyper_source = env_value("HYPERLIQUID_ORDER_BOOKS")
    hyper_live_names: list[str] = []
    if hyper_source:
        hyper_live_names = archive.scan(hyper_source, (".zst", ".rmp", ".jsonl", ".log"))
        if not hyper_live_names:
            raise AssertionError("live HyperLiquid archive contains no capture files")
        print(f"verified live archive: HyperLiquid ({len(hyper_live_names)} captures discoverable)")
    elif strict_live:
        raise ValueError("HYPERLIQUID_ORDER_BOOKS is required for strict verification")

    if strict_live:
        assert poly_source is not None and hyper_source is not None
        output = ROOT / "docs" / "public" / "examples" / "bitcoin-5m-updown.png"
        microprice_output = (
            ROOT / "docs" / "public" / "examples" / "microprice-research.png"
        )
        with bitcoin.downloaded_market(
            ROOT / ".env",
            poly_names=poly_live_names,
            hyper_names=hyper_live_names,
        ) as downloaded:
            result = bitcoin.run_downloaded(downloaded, output)
            microprice_result = microprice.run_downloaded(
                downloaded, microprice_output
            )
        if (
            not output.is_file()
            or output.stat().st_size < 250_000
            or output.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
        ):
            raise AssertionError("cross-venue example did not produce a substantial PNG")
        if result["hyperliquid"]["samples"] < 290 or set(result["outcomes"]) != {"Up", "Down"}:
            raise AssertionError("cross-venue example did not cover both books and five minutes")
        print("verified feature example: Bitcoin 5m cross-venue plot")
        if (
            not microprice_output.is_file()
            or microprice_output.stat().st_size < 200_000
            or microprice_output.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
        ):
            raise AssertionError("microprice example did not produce a substantial PNG")
        if (
            microprice_result["horizon_ms"] != 300
            or len(microprice_result["studies"]) != 4
            or min(
                study["observations"]
                for study in microprice_result["studies"].values()
            ) < 100
        ):
            raise AssertionError("microprice example did not produce four aligned studies")
        print("verified feature example: 300 ms microprice heatmaps")


def verify_fees(strict_live: bool) -> None:
    if not env_value("FEES_URL"):
        if strict_live:
            raise ValueError("FEES_URL is required for strict verification")
        print("skipped live fees API: FEES_URL is not configured")
        return
    mint = "So11111111111111111111111111111111111111112"
    payload = fees.fetch(mint)
    if payload["total"] < 0 or payload["tx_count"] < payload["success_count"]:
        raise AssertionError("fees API returned invalid aggregate values")
    print("verified live API: global fees response and invariants")


def verify_research() -> None:
    pages = ROOT / "docs" / "pages" / "research"
    public = ROOT / "docs" / "public" / "research"
    summary = research.run(ROOT / ".env", pages, public)
    if (
        len(summary["reliable_creators"]) != 5
        or summary["eligible_profile_tokens"] < 100
    ):
        raise AssertionError("Pump.fun research output is incomplete")
    creator_floors = [
        int(row["minimum_trades_first_100_slots"])
        for row in summary["reliable_creators"]
    ]
    if (
        any(int(row["launches"]) < 5 for row in summary["reliable_creators"])
        or creator_floors != sorted(creator_floors, reverse=True)
        or not 10 < float(summary["sol_usdc_rate"]) < 1_000
        or int(summary["sol_usdc_sample_count"]) != 100
    ):
        raise AssertionError("reliable-creator ranking violates its launch/trade rules")
    for creator in summary["reliable_creators"]:
        if (
            len(creator["tokens"]) != int(creator["launches"])
            or sum(creator["mcap_bin_counts"]) != int(creator["launches"])
            or creator["migrated_launches"]
            != sum(token["migrated"] for token in creator["tokens"])
        ):
            raise AssertionError("creator token/mcap distribution is inconsistent")
        for token in creator["tokens"]:
            if (
                token["p95_mcap_usd"] <= 0
                or token["price_observations"] < 1
                or (
                    token["pumpswap_price_observations"] > 0
                    and not token["migrated"]
                )
            ):
                raise AssertionError("creator token price research is incomplete")
    groups = summary["migration_comparison"]
    for label in ("migrated", "not_migrated"):
        if (
            groups[label]["token_count"] < 1
            or len(groups[label]["parent_program_distribution"]) < 2
        ):
            raise AssertionError(f"Pump.fun {label} comparison cohort is incomplete")
    reliable_page = (pages / "reliable-pumpfun-creators.mdx").read_text()
    migration_page = (pages / "pumpfun-migration-parent-programs.mdx").read_text()
    if "github.com/web3engineering/on-chain-divers" not in reliable_page:
        raise AssertionError("reliable-creator page is missing its GitHub source link")
    if "Mcap distribution" not in reliable_page or "PumpSwap" not in reliable_page:
        raise AssertionError("reliable-creator page is missing market-cap details")
    if (
        "github.com/web3engineering/on-chain-divers" not in migration_page
        or "Migrated" not in migration_page
        or "Not migrated" not in migration_page
    ):
        raise AssertionError("migration comparison page is incomplete")
    wallet_summary = wallet_fingerprints.run(ROOT / ".env", pages, public)
    # The changed tier can legitimately be empty in a quiet window; only the
    # stable control group is required to be fully populated.
    changed_examples = wallet_summary["changed_examples"]
    if (
        wallet_summary["eligible_wallets"] < 10
        or len(wallet_summary["stable_examples"]) != 5
        or len(changed_examples) > 5
        or wallet_summary["tier_counts"]["stable"]
        < wallet_summary["eligible_wallets"] * 0.70
        or wallet_summary["tier_counts"]["changed"]
        >= wallet_summary["eligible_wallets"] / 4
        or any(
            row["tier"] != "stable"
            for row in wallet_summary["stable_examples"]
        )
        or any(row["tier"] != "changed" for row in changed_examples)
        or (
            changed_examples
            and changed_examples[0]["change_score"]
            < wallet_summary["stable_examples"][-1]["change_score"]
        )
    ):
        raise AssertionError("wallet-fingerprint research output is incomplete")
    fingerprint_page = (pages / "wallet-fingerprint-changes.mdx").read_text()
    if (
        "not claims of a wallet sale" not in fingerprint_page
        or "github.com/web3engineering/on-chain-divers" not in fingerprint_page
    ):
        raise AssertionError("wallet-fingerprint page is missing methodology safeguards")
    swqos_sources = swqos_research.run(ROOT / ".env", pages, public)["sources"]
    if set(swqos_sources) != {"pumpfun-v2", "pumpswap", "dlmm"}:
        raise AssertionError("SWQoS research is missing a source DEX page")
    for key, summary in swqos_sources.items():
        if (
            summary["screened_count"] < 1
            or len(summary["screened"]) != summary["screened_count"]
            or summary["labeled_provider_count"] < 1
            or summary["new_provider_count"] > summary["screened_count"]
            or any(
                row["signers"] <= summary["min_signers"]
                or row["median_lamports"] > summary["max_median_lamports"]
                or sum(row["landed_tip_buckets"]) != row["landed_count"]
                or sum(row["failed_tip_buckets"]) != row["failed_count"]
                for row in summary["screened"]
            )
        ):
            raise AssertionError(f"SWQoS research output for {key} is incomplete")
    for page_name in (
        "swqos-providers.mdx",
        "swqos-providers-pumpswap.mdx",
        "swqos-providers-dlmm.mdx",
    ):
        page_text = (pages / page_name).read_text()
        if (
            "github.com/web3engineering/on-chain-divers" not in page_text
            or "SWQoS" not in page_text
        ):
            raise AssertionError(f"SWQoS page {page_name} is missing its source link or heading")
    # OnchainDivers TPU must always be surfaced somewhere in the Pump.fun page.
    if "tpu.onchaindivers.com" not in (pages / "swqos-providers.mdx").read_text():
        raise AssertionError("SWQoS Pump.fun page is missing the OnchainDivers TPU reference")
    print(
        "verified research: creators, migrations, wallet fingerprint changes, "
        "and SWQoS endpoints (Pump.fun v2, PumpSwap, Meteora DLMM)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-live", action="store_true")
    args = parser.parse_args()
    verify_sql()
    verify_research()
    verify_orderbooks(args.strict_live)
    verify_fees(args.strict_live)
    print("all examples verified")


if __name__ == "__main__":
    main()
