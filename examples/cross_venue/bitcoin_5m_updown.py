#!/usr/bin/env python3
"""Rebuild and plot one Bitcoin five-minute market across two venues.

This intentionally substantial example joins three independent indexer
surfaces:

* Polymarket event and market metadata in ClickHouse;
* the dedicated Polymarket CLOB capture named after the market slug; and
* HyperLiquid's raw MessagePack checkpoint plus hourly order-level diffs.

It chooses the nearest replayable Bitcoin Up/Down interval around UTC now minus 24 hours, obtains
the outcome CLOB token IDs from metadata (never hard-codes them), replays both
venues over the same five minutes, and writes a publication-sized PNG plus a
machine-readable JSON summary.

Data, access, and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from dotenv import dotenv_values


# Keep the file directly executable from the repository without packaging the
# examples. Docker uses the exact same entry point during its checker stage.
ROOT = Path(__file__).resolve().parents[2]
ORDERBOOKS = ROOT / "examples" / "orderbooks"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ORDERBOOKS))

import archive  # noqa: E402
import hyperliquid as hyper  # noqa: E402
import polymarket as poly  # noqa: E402
from clickhouse_accessors import PolymarketAccessor  # noqa: E402


UTC = timezone.utc
GIB = 1024 * 1024 * 1024
ARCHIVE_FINALIZATION_LAG = timedelta(minutes=15)
MIN_DEDICATED_CAPTURE_BYTES = 8 * 1024 * 1024


def env_value(key: str, env_path: Path) -> str:
    """Read a required value without ever printing the secret or endpoint."""
    value = os.environ.get(key) or dotenv_values(env_path).get(key)
    if not value:
        raise ValueError(f"{key} is required")
    return str(value)


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def choose_market(
    client: PolymarketAccessor,
    target: datetime,
    available_captures: set[str],
    capture_source: str,
    excluded_captures: set[str] | None = None,
) -> dict:
    """Find a captured BTC 5m event near the requested historical instant.

    The epoch suffix in ``btc-updown-5m-<epoch>`` is the authoritative interval
    start. Metadata creation timestamps can precede the actual market window,
    which is why the query derives the time from the slug itself.
    """
    excluded_captures = excluded_captures or set()
    target_epoch = int(target.timestamp())
    sql = f"""
        WITH toInt64OrZero(substring(slug, 15)) AS interval_start
        SELECT
            toString(event_id) AS event_id,
            slug,
            title,
            interval_start
        FROM polymarket.raw_event_meta
        WHERE startsWith(slug, 'btc-updown-5m-')
          AND interval_start BETWEEN {target_epoch - 7200} AND {target_epoch + 7200}
          AND modulo(interval_start, 3600) BETWEEN 300 AND 3000
        ORDER BY abs(interval_start - {target_epoch}), end_dttm DESC
        LIMIT 200
    """
    rows = client.query(sql, settings={"max_execution_time": 60, "readonly": 1})
    checked_slugs: set[str] = set()
    for row in rows:
        slug = str(row["slug"])
        if slug in checked_slugs:
            continue
        checked_slugs.add(slug)
        dedicated = next(
            (
                name
                for name in (f"{slug}.log.zst", f"{slug}.log")
                if name in available_captures
            ),
            None,
        )
        if dedicated and dedicated not in excluded_captures:
            # The newest archive entry can appear while its recorder is still
            # finalizing. A complete liquid BTC five-minute capture is normally
            # several MiB; rejecting tiny edge files avoids selecting a handful
            # of post-settlement messages merely because the filename exists.
            capture_bytes = archive.content_length(capture_source, dedicated)
            if capture_bytes < MIN_DEDICATED_CAPTURE_BYTES:
                continue
            start = datetime.fromtimestamp(int(row["interval_start"]), tz=UTC)
            return {
                "event_id": str(row["event_id"]),
                "slug": slug,
                "title": str(row["title"]),
                "start": start,
                "end": start + timedelta(minutes=5),
                "capture_name": dedicated,
                "capture_bytes": capture_bytes,
            }
    raise ValueError("no captured Bitcoin five-minute event was found near the 24-hour target")


def market_outcomes(client: PolymarketAccessor, event: dict) -> dict[str, dict]:
    """Resolve Up/Down CLOB IDs from the market table and cross-check event ID."""
    sql = """
        SELECT DISTINCT
            outcome,
            clob_token_id,
            toString(market_id) AS market_id,
            condition_id
        FROM polymarket.raw_market_meta
        WHERE slug = {slug:String}
          AND JSONExtractString(event, 'id') = {event_id:String}
          AND outcome IN ('Up', 'Down')
    """
    rows = client.query(
        sql,
        parameters={"slug": event["slug"], "event_id": event["event_id"]},
        settings={"max_execution_time": 60, "readonly": 1},
    )
    outcomes = {str(row["outcome"]): dict(row) for row in rows}
    if set(outcomes) != {"Up", "Down"}:
        raise ValueError("market metadata did not resolve exactly one Up and one Down token")
    if any(not str(row.get("clob_token_id") or "") for row in outcomes.values()):
        raise ValueError("market metadata contains an empty CLOB token ID")
    return outcomes


def select_checkpoint(source: str, names: list[str], target: datetime) -> tuple[str, dict]:
    """Binary-search remote checkpoint headers for the last snapshot before start."""
    checkpoints = sorted(
        name for name in names if name.startswith("abci/") and name.endswith(".rmp")
    )
    if not checkpoints:
        raise ValueError("HyperLiquid archive contains no ABCI checkpoints")
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
        raise ValueError("no HyperLiquid checkpoint predates the selected market")
    return selected


def required_diffs(names: list[str], start: datetime, end: datetime) -> list[str]:
    """Select every hourly diff shard between a checkpoint and market end."""
    available = set(names)
    cursor = start.replace(minute=0, second=0, microsecond=0)
    final = end.replace(minute=0, second=0, microsecond=0)
    selected: list[str] = []
    while cursor <= final:
        stem = f"book_diffs/{cursor:%Y%m%d}/{cursor.hour}"
        name = stem + ".zst" if stem + ".zst" in available else stem
        if name not in available:
            raise ValueError(f"HyperLiquid diff archive has a gap at {utc_text(cursor)}")
        selected.append(name)
        cursor += timedelta(hours=1)
    return selected


@dataclass
class IncrementalBook:
    """Order-ID state plus aggregated levels for efficient historical sampling."""

    orders: dict[int, dict]

    def __post_init__(self) -> None:
        self.levels: dict[str, dict[Decimal, Decimal]] = {"B": {}, "A": {}}
        for order in self.orders.values():
            self._add(order)

    def _add(self, order: dict) -> None:
        side = str(order["side"])
        price, size = Decimal(str(order["px"])), Decimal(str(order["sz"]))
        self.levels[side][price] = self.levels[side].get(price, Decimal(0)) + size

    def _remove(self, order: dict) -> None:
        side = str(order["side"])
        price, size = Decimal(str(order["px"])), Decimal(str(order["sz"]))
        remaining = self.levels[side].get(price, Decimal(0)) - size
        if remaining <= 0:
            self.levels[side].pop(price, None)
        else:
            self.levels[side][price] = remaining

    def apply(self, event: dict) -> None:
        """Apply remove/new/update while preserving per-price aggregate size."""
        oid = int(event["oid"])
        old = self.orders.get(oid)
        if old is not None:
            self._remove(old)
        change = event["raw_book_diff"]
        if change == "remove":
            self.orders.pop(oid, None)
            return
        if isinstance(change, dict) and "new" in change:
            current = {
                "oid": oid,
                "side": str(event["side"]),
                "px": str(event["px"]),
                "sz": str(change["new"]["sz"]),
            }
            self.orders[oid] = current
            self._add(current)
            return
        if isinstance(change, dict) and "update" in change and old is not None:
            old["sz"] = str(change["update"]["newSz"])
            self.orders[oid] = old
            self._add(old)
            return
        # Unknown updates are not silently accepted: a malformed diff must fail
        # the documentation build instead of yielding a plausible-looking plot.
        if old is not None:
            self._add(old)
        raise ValueError("unsupported or unanchored HyperLiquid raw book diff")

    def sample(self, timestamp: datetime) -> dict:
        bids, asks = self.levels["B"], self.levels["A"]
        if not bids or not asks:
            raise ValueError("HyperLiquid replay produced an empty book side")
        bid, ask = max(bids), min(asks)
        if bid >= ask:
            raise ValueError("HyperLiquid replay produced a crossed book")
        mid = (bid + ask) / 2
        band = mid * Decimal("0.001")  # depth available within ten basis points
        return {
            "time": timestamp,
            "best_bid": float(bid),
            "best_ask": float(ask),
            "mid": float(mid),
            "spread_bps": float((ask - bid) / mid * 10_000),
            "bid_depth_10bps": float(sum(size for px, size in bids.items() if px >= mid - band)),
            "ask_depth_10bps": float(sum(size for px, size in asks.items() if px <= mid + band)),
            "orders": len(self.orders),
        }


def hyper_series(
    checkpoint: Path,
    diffs: list[Path],
    context: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Replay BTC order diffs and sample the complete book once per second."""
    checkpoint_height = int(context["height"])
    book = IncrementalBook(hyper.raw_snapshot_orders(checkpoint, asset=0, size_decimals=5))
    next_sample = start
    points: list[dict] = []
    for raw_time, raw_height, event in hyper.raw_diff_events(diffs, "BTC"):
        event_time = hyper.parse_datetime(str(raw_time))
        if raw_height is not None and int(raw_height) <= checkpoint_height:
            continue
        if event_time > end:
            break
        # A sample represents all events strictly before that UTC second. All
        # messages sharing a block timestamp are applied before the next sample.
        while next_sample < event_time and next_sample <= end:
            points.append(book.sample(next_sample))
            next_sample += timedelta(seconds=1)
        book.apply(event)
    while next_sample <= end:
        points.append(book.sample(next_sample))
        next_sample += timedelta(seconds=1)
    if len(points) < 290:
        raise ValueError("HyperLiquid replay did not cover the full five-minute interval")
    return points


def point_times(points: list[dict], key: str = "time") -> list[datetime]:
    values: list[datetime] = []
    for point in points:
        value = point[key]
        values.append(
            datetime.fromtimestamp(value / 1000, tz=UTC) if isinstance(value, int) else value
        )
    return values


def render_plot(
    output: Path,
    event: dict,
    outcomes: dict[str, dict],
    poly_points: dict[str, list[dict]],
    hyper_points: list[dict],
) -> None:
    """Render complementary probability, underlying price, spread and depth views."""
    plt.style.use("dark_background")
    figure, axes = plt.subplots(4, 1, figsize=(22, 15), sharex=True, layout="constrained")
    figure.patch.set_facecolor("#081018")
    colors = {"Up": "#41d69c", "Down": "#ff6b81"}

    hx = point_times(hyper_points)
    hbid = [point["best_bid"] for point in hyper_points]
    hask = [point["best_ask"] for point in hyper_points]
    hmid = [point["mid"] for point in hyper_points]

    ax = axes[0]
    ax.fill_between(hx, hbid, hask, color="#5aa9ff", alpha=0.25, label="bid/ask spread")
    ax.plot(hx, hmid, color="#8bc4ff", linewidth=2.2, label="BTC perpetual midpoint")
    ax.plot(hx, hbid, color="#41d69c", linewidth=0.8, alpha=0.85, label="best bid")
    ax.plot(hx, hask, color="#ff8da1", linewidth=0.8, alpha=0.85, label="best ask")
    ax.set_ylabel("HyperLiquid BTC price (USD)")
    ax.legend(ncols=4, loc="upper left", frameon=False)

    ax = axes[1]
    outcome_series: dict[str, list[dict]] = {}
    for outcome in ("Up", "Down"):
        asset = str(outcomes[outcome]["clob_token_id"])
        points = poly_points[asset]
        outcome_series[outcome] = points
        times = point_times(points, "timestamp_ms")
        bid = [point["best_bid"] * 100 for point in points]
        ask = [point["best_ask"] * 100 for point in points]
        mid = [point["mid"] * 100 for point in points]
        ax.fill_between(times, bid, ask, color=colors[outcome], alpha=0.16)
        ax.step(times, mid, where="post", color=colors[outcome], linewidth=2.0, label=outcome)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Polymarket price (¢ / implied %)")
    ax.legend(ncols=2, loc="upper left", frameon=False)

    ax = axes[2]
    btc_return = [(value / hmid[0] - 1) * 10_000 for value in hmid]
    ax.plot(hx, btc_return, color="#8bc4ff", linewidth=2, label="BTC return from open")
    ax.axhline(0, color="#8b98a5", linewidth=0.8, alpha=0.7)
    ax.set_ylabel("BTC move (basis points)")
    probability_axis = ax.twinx()
    up = outcome_series["Up"]
    probability_axis.step(
        point_times(up, "timestamp_ms"),
        [point["mid"] * 100 for point in up],
        where="post",
        color=colors["Up"],
        linewidth=1.5,
        alpha=0.9,
        label="Up midpoint",
    )
    probability_axis.set_ylabel("Up midpoint (%)", color=colors["Up"])
    handles, labels = ax.get_legend_handles_labels()
    right_handles, right_labels = probability_axis.get_legend_handles_labels()
    ax.legend(handles + right_handles, labels + right_labels, ncols=2, loc="upper left", frameon=False)

    ax = axes[3]
    ax.plot(hx, [point["bid_depth_10bps"] for point in hyper_points], color="#41d69c", label="bid depth ≤10 bps")
    ax.plot(hx, [point["ask_depth_10bps"] for point in hyper_points], color="#ff6b81", label="ask depth ≤10 bps")
    ax.set_ylabel("HyperLiquid BTC depth")
    spread_axis = ax.twinx()
    spread_axis.plot(
        hx,
        [point["spread_bps"] for point in hyper_points],
        color="#f4c95d",
        linewidth=1.1,
        alpha=0.85,
        label="spread",
    )
    spread_axis.set_ylabel("Spread (basis points)", color="#f4c95d")
    handles, labels = ax.get_legend_handles_labels()
    right_handles, right_labels = spread_axis.get_legend_handles_labels()
    ax.legend(handles + right_handles, labels + right_labels, ncols=3, loc="upper left", frameon=False)

    for panel in axes:
        panel.set_facecolor("#0d1722")
        panel.grid(True, color="#8492a6", alpha=0.13, linewidth=0.7)
        panel.spines[["top", "right"]].set_visible(False)
    axes[-1].xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M UTC", tz=UTC))
    axes[-1].set_xlabel(f"Five-minute interval on {event['start']:%Y-%m-%d}")

    figure.suptitle(
        "Bitcoin 5-minute Up/Down — Polymarket probability vs HyperLiquid BTC book",
        fontsize=22,
        fontweight="bold",
        x=0.01,
        ha="left",
    )
    figure.text(
        0.01,
        0.965,
        f"{event['title']}  •  {utc_text(event['start'])} to {utc_text(event['end'])}  •  raw historical reconstruction",
        fontsize=11,
        color="#aebdca",
        ha="left",
    )
    figure.text(
        0.99,
        0.008,
        "Reproducible indexer example • https://onchaindivers.com",
        fontsize=10,
        color="#8fa1b2",
        ha="right",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=160, facecolor=figure.get_facecolor())
    plt.close(figure)


@dataclass
class DownloadedMarket:
    """One selected market and its locally downloaded raw replay inputs."""

    event: dict
    outcomes: dict[str, dict]
    poly_capture: Path
    checkpoint: Path
    diff_paths: list[Path]
    context: dict
    input_names: list[str]
    input_sizes: list[int]


@contextmanager
def downloaded_market(
    env_path: Path,
    hours_ago: float = 24,
    now: datetime | None = None,
    poly_names: list[str] | None = None,
    hyper_names: list[str] | None = None,
):
    """Select and download one market, then share its files with analyses.

    The strict Docker checker enters this context once and runs both the main
    cross-venue chart and the microprice study before the temporary files are
    removed. This keeps the 1-3 GiB HyperLiquid checkpoint from being fetched
    twice while preserving a standalone, reproducible API for each analysis.
    """
    reference_now = (now or datetime.now(UTC)).astimezone(UTC)
    # Stay near the requested 24-hour age while giving both asynchronous raw
    # archives a small finalization buffer. This also avoids choosing a file
    # that has only just appeared in an HTTP listing.
    target = reference_now - timedelta(hours=hours_ago) - ARCHIVE_FINALIZATION_LAG
    poly_source = env_value("POLYMARKET_ORDERBOOKS", env_path)
    hyper_source = env_value("HYPERLIQUID_ORDER_BOOKS", env_path)
    poly_names = poly_names or archive.scan(poly_source, (".log", ".log.zst"))
    hyper_names = hyper_names or archive.scan(
        hyper_source, (".zst", ".rmp", ".jsonl", ".log")
    )

    with tempfile.TemporaryDirectory(prefix="bitcoin-5m-") as temporary:
        work = Path(temporary)
        rejected_captures: set[str] = set()
        client = PolymarketAccessor(str(env_path))
        try:
            while len(rejected_captures) < 8:
                event = choose_market(
                    client,
                    target,
                    set(poly_names),
                    poly_source,
                    rejected_captures,
                )
                outcomes = market_outcomes(client, event)
                poly_capture = archive.download(
                    poly_source,
                    event["capture_name"],
                    work / "polymarket.log.zst",
                    max_bytes=512 * 1024 * 1024,
                )
                start_ms = int(event["start"].timestamp() * 1000)
                end_ms = int(event["end"].timestamp() * 1000)
                asset_ids = {str(row["clob_token_id"]) for row in outcomes.values()}
                try:
                    # Market windows are half-open: the quote at exactly ``end``
                    # belongs to resolution, not to the tradable plot window.
                    poly.best_quote_series(
                        poly_capture, asset_ids, start_ms, end_ms - 1
                    )

                    # Validate the chart stream against two independent full
                    # snapshot/delta reconstructions. A recorder can produce a
                    # correctly named, substantial capture that is nevertheless
                    # missing one side; skip it before downloading the GiB-scale
                    # HyperLiquid input and try the next-nearest interval.
                    validation_ms = start_ms + 4 * 60 * 1000
                    close_books = {
                        outcome: poly.reconstruct_at(
                            poly_capture,
                            validation_ms,
                            str(metadata["clob_token_id"]),
                        )
                        for outcome, metadata in outcomes.items()
                    }
                    if any(
                        Decimal(book["best_bid"]) >= Decimal(book["best_ask"])
                        for book in close_books.values()
                    ):
                        raise ValueError("Polymarket full replay produced a crossed book")
                    break
                except ValueError:
                    rejected_captures.add(str(event["capture_name"]))
                    print(
                        "skipped one unusable dedicated Polymarket capture; "
                        "trying the next-nearest interval"
                    )
            else:
                raise ValueError("no replayable Bitcoin five-minute capture was found")
        finally:
            client.disconnect()

        checkpoint_name, context = select_checkpoint(
            hyper_source, hyper_names, event["start"]
        )
        checkpoint_time = hyper.parse_datetime(str(context["time"]))
        diff_names = required_diffs(
            hyper_names, checkpoint_time, event["end"] - timedelta(microseconds=1)
        )
        input_names = [event["capture_name"], checkpoint_name, *diff_names]
        poly_size = int(event["capture_bytes"])
        checkpoint_size = archive.content_length(hyper_source, checkpoint_name)
        diff_sizes = [archive.content_length(hyper_source, name) for name in diff_names]
        input_sizes = [poly_size, checkpoint_size, *diff_sizes]
        print(
            f"selected dedicated Polymarket capture {event['capture_name']} and "
            f"{len(outcomes)} CLOB outcomes ({poly_size:,} bytes)"
        )
        print(
            "HyperLiquid raw anchor: "
            f"checkpoint {checkpoint_size:,} bytes + {len(diff_names)} hourly diff(s) "
            f"{sum(diff_sizes):,} bytes"
        )

        # Only start the much larger futures download after the dedicated
        # Polymarket capture has passed both stream and full-replay checks.
        checkpoint = archive.download(
            hyper_source,
            checkpoint_name,
            work / "checkpoint.rmp",
            max_bytes=3 * GIB,
        )
        diff_paths: list[Path] = []
        for index, name in enumerate(diff_names):
            diff_paths.append(
                archive.download(
                    hyper_source,
                    name,
                    work / f"diff-{index}.zst",
                    max_bytes=3 * GIB,
                )
            )

        yield DownloadedMarket(
            event=event,
            outcomes=outcomes,
            poly_capture=poly_capture,
            checkpoint=checkpoint,
            diff_paths=diff_paths,
            context=context,
            input_names=input_names,
            input_sizes=input_sizes,
        )


def run_downloaded(downloaded: DownloadedMarket, output: Path) -> dict:
    """Render the original cross-venue chart from already downloaded inputs."""
    event = downloaded.event
    outcomes = downloaded.outcomes
    start_ms = int(event["start"].timestamp() * 1000)
    end_ms = int(event["end"].timestamp() * 1000)
    asset_ids = {str(row["clob_token_id"]) for row in outcomes.values()}
    poly_points = poly.best_quote_series(
        downloaded.poly_capture, asset_ids, start_ms, end_ms - 1
    )
    hyper_points = hyper_series(
        downloaded.checkpoint,
        downloaded.diff_paths,
        downloaded.context,
        event["start"],
        event["end"] - timedelta(microseconds=1),
    )
    render_plot(output, event, outcomes, poly_points, hyper_points)

    summary = {
        "source": "https://onchaindivers.com",
        "event_id": event["event_id"],
        "market_slug": event["slug"],
        "title": event["title"],
        "interval_start": utc_text(event["start"]),
        "interval_end": utc_text(event["end"]),
        "outcomes": {
            outcome: {
                "clob_token_id": str(metadata["clob_token_id"]),
                "quote_points": len(poly_points[str(metadata["clob_token_id"])]),
            }
            for outcome, metadata in outcomes.items()
        },
        "hyperliquid": {
            "symbol": "BTC",
            "samples": len(hyper_points),
            "open_mid": hyper_points[0]["mid"],
            "close_mid": hyper_points[-1]["mid"],
            "close_orders": hyper_points[-1]["orders"],
        },
        "raw_files": len(downloaded.input_names),
        "raw_bytes": sum(downloaded.input_sizes),
        "plot": str(output),
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"rendered {output} with {len(hyper_points)} BTC samples and "
        f"{sum(item['quote_points'] for item in summary['outcomes'].values())} Polymarket quote changes"
    )
    return summary


def run(
    env_path: Path,
    output: Path,
    hours_ago: float = 24,
    now: datetime | None = None,
    poly_names: list[str] | None = None,
    hyper_names: list[str] | None = None,
) -> dict:
    """Download one market and render the original cross-venue analysis."""
    with downloaded_market(
        env_path,
        hours_ago=hours_ago,
        now=now,
        poly_names=poly_names,
        hyper_names=hyper_names,
    ) as downloaded:
        return run_downloaded(downloaded, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "public" / "examples" / "bitcoin-5m-updown.png",
    )
    parser.add_argument("--hours-ago", type=float, default=24)
    args = parser.parse_args()
    run(args.env_file, args.output, args.hours_ago)


if __name__ == "__main__":
    main()
