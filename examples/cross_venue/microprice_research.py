#!/usr/bin/env python3
"""Research 300 ms microprice and imbalance signals across two BTC books.

The script fully reconstructs the Polymarket Bitcoin Up outcome and the
HyperLiquid BTC perpetual order book from raw OnchainDivers archives. It uses
the same downloaded market files as ``bitcoin_5m_updown.py`` during the Docker
build, then renders four imbalance-versus-future-move heatmaps.

Data, access, and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
CROSS_VENUE = ROOT / "examples" / "cross_venue"
sys.path.insert(0, str(CROSS_VENUE))

import bitcoin_5m_updown as bitcoin  # noqa: E402


UTC = timezone.utc
HORIZON_MS = 300


def event_ms(value: datetime) -> int:
    """Convert a timezone-aware event timestamp to Unix milliseconds."""
    return int(value.astimezone(UTC).timestamp() * 1000)


def imbalance(bid_size: Decimal, ask_size: Decimal) -> float:
    """Return normalized bid-versus-ask depth in the closed range [-1, 1]."""
    total = bid_size + ask_size
    return float((bid_size - ask_size) / total) if total > 0 else 0.0


def book_point(
    timestamp_ms: int,
    bids: dict[Decimal, Decimal],
    asks: dict[Decimal, Decimal],
) -> dict:
    """Calculate midpoint, microprice, and one/two-level imbalance.

    Microprice weights each best quote by the size resting on the opposite
    quote. More bid size therefore moves microprice toward the ask, while more
    ask size moves it toward the bid.
    """
    if not bids or not asks:
        raise ValueError("cannot sample an order book with an empty side")
    bid_prices = sorted(bids, reverse=True)
    ask_prices = sorted(asks)
    best_bid, best_ask = bid_prices[0], ask_prices[0]
    if best_bid >= best_ask:
        raise ValueError("cannot sample a crossed order book")
    bid_l1, ask_l1 = bids[best_bid], asks[best_ask]
    quoted = bid_l1 + ask_l1
    microprice = (
        (best_ask * bid_l1 + best_bid * ask_l1) / quoted
        if quoted > 0
        else (best_bid + best_ask) / 2
    )
    bid_l2 = sum((bids[price] for price in bid_prices[:2]), Decimal(0))
    ask_l2 = sum((asks[price] for price in ask_prices[:2]), Decimal(0))
    return {
        "timestamp_ms": timestamp_ms,
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "mid": float((best_bid + best_ask) / 2),
        "microprice": float(microprice),
        "imbalance_l1": imbalance(bid_l1, ask_l1),
        "imbalance_l2": imbalance(bid_l2, ask_l2),
    }


def append_state(points: list[dict], point: dict) -> None:
    """Keep the final complete state when several updates share a timestamp."""
    if points and points[-1]["timestamp_ms"] == point["timestamp_ms"]:
        points[-1] = point
    else:
        points.append(point)


def polymarket_series(
    capture: Path,
    asset_id: str,
    start_ms: int,
    end_ms: int,
) -> list[dict]:
    """Replay the complete Polymarket book and retain every changed state."""
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    points: list[dict] = []
    for capture_ms, event in bitcoin.poly.captured_records(capture):
        timestamp = bitcoin.poly.event_millis(event, capture_ms)
        if timestamp is None or timestamp > end_ms:
            continue
        changed = False
        if event.get("event_type") == "book" and str(event.get("asset_id")) == asset_id:
            bids = {
                Decimal(row["price"]): Decimal(row["size"])
                for row in event.get("bids", [])
            }
            asks = {
                Decimal(row["price"]): Decimal(row["size"])
                for row in event.get("asks", [])
            }
            changed = True
        elif event.get("event_type") == "price_change":
            for change in event.get("price_changes", []):
                if str(change.get("asset_id")) != asset_id:
                    continue
                side = bids if change.get("side") in {"BUY", "B"} else asks
                price, size = Decimal(change["price"]), Decimal(change["size"])
                if size == 0:
                    side.pop(price, None)
                else:
                    side[price] = size
                changed = True
        if changed and timestamp >= start_ms and bids and asks:
            append_state(points, book_point(timestamp, bids, asks))
    if len(points) < 100:
        raise ValueError("Polymarket replay produced too few microprice observations")
    return points


def hyperliquid_series(
    checkpoint: Path,
    diffs: list[Path],
    context: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Replay order-ID diffs and retain each completed HyperLiquid block state."""
    checkpoint_height = int(context["height"])
    book = bitcoin.IncrementalBook(
        bitcoin.hyper.raw_snapshot_orders(checkpoint, asset=0, size_decimals=5)
    )
    start_ms, end_ms = event_ms(start), event_ms(end)
    points: list[dict] = []
    started = False
    pending_timestamp_ms: int | None = None
    for raw_time, raw_height, event in bitcoin.hyper.raw_diff_events(diffs, "BTC"):
        timestamp = bitcoin.hyper.parse_datetime(str(raw_time))
        timestamp_ms = event_ms(timestamp)
        if raw_height is not None and int(raw_height) <= checkpoint_height:
            continue
        if timestamp_ms > end_ms:
            break
        # All order mutations in one HyperLiquid block share a timestamp. Do
        # not sample halfway through the block: removals can precede inserts and
        # create a transient state that was never externally observable.
        if (
            pending_timestamp_ms is not None
            and timestamp_ms != pending_timestamp_ms
            and pending_timestamp_ms >= start_ms
        ):
            append_state(
                points,
                book_point(pending_timestamp_ms, book.levels["B"], book.levels["A"]),
            )
        if timestamp_ms >= start_ms and not started:
            append_state(points, book_point(start_ms, book.levels["B"], book.levels["A"]))
            started = True
        book.apply(event)
        pending_timestamp_ms = timestamp_ms
    if pending_timestamp_ms is not None and pending_timestamp_ms >= start_ms:
        append_state(
            points,
            book_point(pending_timestamp_ms, book.levels["B"], book.levels["A"]),
        )
    if len(points) < 100:
        raise ValueError("HyperLiquid replay produced too few microprice observations")
    return points


def asof(points: list[dict], timestamps: list[int], target_ms: int) -> dict | None:
    """Return the last observable book state at or before a wall-clock time."""
    index = bisect.bisect_right(timestamps, target_ms) - 1
    return points[index] if index >= 0 else None


def forward_observations(
    predictors: list[dict],
    target: list[dict],
    imbalance_key: str,
    movement: str,
    end_ms: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Pair each imbalance with target-venue movement exactly 300 ms later.

    Both the initial and future prices use the most recent state observable at
    the requested wall-clock instant. If no message arrives during the horizon,
    the measured move is correctly zero rather than unknowable.
    """
    target_times = [int(point["timestamp_ms"]) for point in target]
    x: list[float] = []
    y: list[float] = []
    for predictor in predictors:
        timestamp = int(predictor["timestamp_ms"])
        if timestamp + HORIZON_MS > end_ms:
            continue
        initial = asof(target, target_times, timestamp)
        future = asof(target, target_times, timestamp + HORIZON_MS)
        if initial is None or future is None or initial["mid"] <= 0:
            continue
        x.append(float(predictor[imbalance_key]))
        if movement == "cents":
            y.append((float(future["mid"]) - float(initial["mid"])) * 100)
        elif movement == "bps":
            y.append((float(future["mid"]) / float(initial["mid"]) - 1) * 10_000)
        else:
            raise ValueError(f"unknown movement unit: {movement}")
    if len(x) < 100:
        raise ValueError("too few aligned observations for a heatmap")
    return np.asarray(x), np.asarray(y)


def movement_limit(values: np.ndarray, minimum: float) -> float:
    """Use a robust symmetric y range so a few outliers do not flatten detail."""
    finite = np.abs(values[np.isfinite(values)])
    return max(minimum, float(np.quantile(finite, 0.99))) if finite.size else minimum


def draw_heatmap(
    ax,
    x: np.ndarray,
    y: np.ndarray,
    title: str,
    x_label: str,
    y_label: str,
    minimum_y: float,
) -> dict:
    """Draw log-frequency cells and an imbalance-bin conditional mean overlay."""
    y_limit = movement_limit(y, minimum_y)
    x_edges = np.linspace(-1, 1, 25)
    y_edges = np.linspace(-y_limit, y_limit, 33)
    counts, _, _ = np.histogram2d(x, np.clip(y, -y_limit, y_limit), bins=(x_edges, y_edges))
    image = ax.pcolormesh(
        x_edges,
        y_edges,
        np.log1p(counts.T),
        shading="auto",
        cmap="magma",
    )
    centers = (x_edges[:-1] + x_edges[1:]) / 2
    assignments = np.clip(np.digitize(x, x_edges) - 1, 0, len(centers) - 1)
    means = [
        float(np.mean(y[assignments == index])) if np.any(assignments == index) else np.nan
        for index in range(len(centers))
    ]
    ax.plot(centers, means, color="#74e6c4", linewidth=2.0, marker="o", markersize=3)
    ax.axhline(0, color="white", alpha=0.55, linewidth=0.8)
    ax.axvline(0, color="white", alpha=0.3, linewidth=0.8)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-y_limit, y_limit)
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    correlation = float(np.corrcoef(x, y)[0, 1]) if np.std(x) and np.std(y) else 0.0
    ax.text(
        0.02,
        0.97,
        f"n={len(x):,}  corr={correlation:+.3f}",
        transform=ax.transAxes,
        va="top",
        color="white",
        fontsize=9,
    )
    colorbar = ax.figure.colorbar(image, ax=ax, pad=0.01)
    colorbar.set_label("log(1 + observations)")
    return {"observations": len(x), "correlation": correlation, "y_limit": y_limit}


def run_downloaded(downloaded: bitcoin.DownloadedMarket, output: Path) -> dict:
    """Run all four studies using raw files already present in the checker."""
    event = downloaded.event
    start_ms = event_ms(event["start"])
    end_ms = event_ms(event["end"] - timedelta(microseconds=1))
    up_asset = str(downloaded.outcomes["Up"]["clob_token_id"])
    polymarket = polymarket_series(
        downloaded.poly_capture, up_asset, start_ms, end_ms
    )
    hyperliquid = hyperliquid_series(
        downloaded.checkpoint,
        downloaded.diff_paths,
        downloaded.context,
        event["start"],
        event["end"] - timedelta(microseconds=1),
    )

    studies = [
        (
            "Polymarket L1 imbalance → Polymarket",
            polymarket,
            polymarket,
            "imbalance_l1",
            "cents",
            "Polymarket L1 imbalance",
            "Up midpoint move after 300 ms (¢)",
            0.1,
        ),
        (
            "Polymarket L2 imbalance → HyperLiquid",
            polymarket,
            hyperliquid,
            "imbalance_l2",
            "bps",
            "Polymarket top-2-level imbalance",
            "BTC midpoint move after 300 ms (bps)",
            0.05,
        ),
        (
            "HyperLiquid L2 imbalance → Polymarket",
            hyperliquid,
            polymarket,
            "imbalance_l2",
            "cents",
            "HyperLiquid top-2-level imbalance",
            "Up midpoint move after 300 ms (¢)",
            0.1,
        ),
        (
            "HyperLiquid L2 imbalance → HyperLiquid",
            hyperliquid,
            hyperliquid,
            "imbalance_l2",
            "bps",
            "HyperLiquid top-2-level imbalance",
            "BTC midpoint move after 300 ms (bps)",
            0.05,
        ),
    ]

    plt.style.use("dark_background")
    figure, axes = plt.subplots(2, 2, figsize=(20, 14), layout="constrained")
    figure.patch.set_facecolor("#081018")
    results: dict[str, dict] = {}
    for ax, study in zip(axes.flat, studies):
        title, predictors, target, key, unit, x_label, y_label, minimum = study
        x, y = forward_observations(predictors, target, key, unit, end_ms)
        results[title] = draw_heatmap(ax, x, y, title, x_label, y_label, minimum)
        ax.set_facecolor("#0d1722")
        ax.grid(False)

    figure.suptitle(
        "Simple microprice research — 300 ms cross-venue response",
        fontsize=22,
        fontweight="bold",
        x=0.01,
        ha="left",
    )
    figure.text(
        0.01,
        0.965,
        f"{event['title']}  •  {bitcoin.utc_text(event['start'])} to "
        f"{bitcoin.utc_text(event['end'])}  •  Up outcome vs BTC perpetual",
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
    figure.savefig(output, dpi=170, facecolor=figure.get_facecolor())
    plt.close(figure)

    summary = {
        "source": "https://onchaindivers.com",
        "market_slug": event["slug"],
        "interval_start": bitcoin.utc_text(event["start"]),
        "interval_end": bitcoin.utc_text(event["end"]),
        "horizon_ms": HORIZON_MS,
        "polymarket_states": len(polymarket),
        "hyperliquid_states": len(hyperliquid),
        "studies": results,
        "plot": str(output),
    }
    output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"rendered {output} from {len(polymarket):,} Polymarket and "
        f"{len(hyperliquid):,} HyperLiquid book states"
    )
    return summary


def run(env_path: Path, output: Path, hours_ago: float = 24) -> dict:
    """Standalone workflow; Docker verification reuses the shared context."""
    with bitcoin.downloaded_market(env_path, hours_ago=hours_ago) as downloaded:
        return run_downloaded(downloaded, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "public" / "examples" / "microprice-research.png",
    )
    parser.add_argument("--hours-ago", type=float, default=24)
    args = parser.parse_args()
    run(args.env_file, args.output, args.hours_ago)


if __name__ == "__main__":
    main()
