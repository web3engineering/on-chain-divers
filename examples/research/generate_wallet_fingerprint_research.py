#!/usr/bin/env python3
"""Generate a reproducible wallet-fingerprint change study.

Data, access, and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from clickhouse_accessors import ClickHouseAccessor  # noqa: E402


GITHUB_ROOT = "https://github.com/web3engineering/on-chain-divers/blob/master"
SQL_URL = f"{GITHUB_ROOT}/examples/research/wallet_fingerprint_transactions.sql"
CODE_URL = (
    f"{GITHUB_ROOT}/examples/research/generate_wallet_fingerprint_research.py"
)


def md(value: object) -> str:
    return html.escape(str(value), quote=True).replace("|", "&#124;").replace("\n", " ")


def code(value: object) -> str:
    return f"`{md(value).replace('`', '&#96;')}`"


def short(value: str) -> str:
    return f"{value[:6]}…{value[-6:]}" if len(value) > 16 else value


def utc_text(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def distribution(values: list[str]) -> dict[str, float]:
    counts = Counter(values)
    total = sum(counts.values())
    return {key: count / total for key, count in counts.items()}


def dominant(values: list[str]) -> tuple[str, float]:
    counts = Counter(values)
    value, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    return value, count / len(values)


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def numeric_stability(values: list[float], floor: float = 1.0) -> float:
    center = median(values)
    deviations = [abs(value - center) for value in values]
    relative_mad = median(deviations) / max(abs(center), floor)
    return 1 / (1 + relative_mad)


def fingerprint(profile: dict) -> str:
    """Hash a coarse signature; detailed comparison remains continuous."""
    payload = {
        "tip_route": profile["preferred_tip_route"],
        "parent_program": profile["preferred_parent_program"],
        "instruction_order": profile["preferred_instruction_order"],
        "instruction_type": profile["preferred_instruction_type"],
        "cu_limit_10k": round(profile["median_cu_limit"] / 10_000),
        "cu_used_10k": round(profile["median_cu_used"] / 10_000),
        "priority_log": round(math.log10(profile["average_priority_fee"] + 1), 1),
        "tip_log": round(math.log10(profile["average_tip_lamports"] + 1), 1),
        "self_paid_10pct": round(profile["self_paid_rate"] * 10),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def make_profile(rows: list[dict]) -> dict:
    orders = [
        f"{int(row['cu_price_ix_index'])}/{int(row['cu_limit_ix_index'])}/"
        f"{int(row['tip_index'])}/{int(row['swap_ix_index'])}"
        for row in rows
    ]
    tip_routes = [str(row["tip_route"]) for row in rows]
    parents = [str(row["parent_program"]) for row in rows]
    instruction_types = [str(row["instruction_type"]) for row in rows]
    cu_limits = [float(row["provided_gas_limit"]) for row in rows]
    cu_used = [float(row["consumed_gas"]) for row in rows]
    priority_fees = [float(row["provided_gas_fee"]) for row in rows]
    tips = [float(row["tip_lamports"]) for row in rows]
    preferred_tip_route, tip_route_share = dominant(tip_routes)
    preferred_parent, parent_share = dominant(parents)
    preferred_order, order_share = dominant(orders)
    preferred_instruction, instruction_share = dominant(instruction_types)
    profile = {
        "sampled_transactions": len(rows),
        "distinct_tokens": len({str(row["mint"]) for row in rows}),
        "median_cu_limit": median(cu_limits),
        "median_cu_used": median(cu_used),
        "average_priority_fee": statistics.fmean(priority_fees),
        "average_tip_lamports": statistics.fmean(tips),
        "tip_rate": sum(value > 0 for value in tips) / len(tips),
        "self_paid_rate": statistics.fmean(float(row["self_paid"]) for row in rows),
        "buy_rate": sum(str(row["direction"]).lower() == "buy" for row in rows)
        / len(rows),
        "preferred_tip_route": preferred_tip_route,
        "preferred_parent_program": preferred_parent,
        "preferred_instruction_order": preferred_order,
        "preferred_instruction_type": preferred_instruction,
        "tip_route_distribution": distribution(tip_routes),
        "parent_program_distribution": distribution(parents),
        "instruction_order_distribution": distribution(orders),
        "instruction_type_distribution": distribution(instruction_types),
    }
    categorical_stability = statistics.fmean(
        [tip_route_share, parent_share, order_share, instruction_share]
    )
    numerical_stability = statistics.fmean(
        [
            numeric_stability(cu_limits, 10_000),
            numeric_stability(cu_used, 10_000),
            numeric_stability(priority_fees, 1_000),
            numeric_stability(tips, 1_000),
        ]
    )
    profile["internal_stability"] = 100 * (
        0.65 * categorical_stability + 0.35 * numerical_stability
    )
    profile["fingerprint"] = fingerprint(profile)
    return profile


def total_variation(left: dict[str, float], right: dict[str, float]) -> float:
    return 0.5 * sum(
        abs(left.get(key, 0.0) - right.get(key, 0.0))
        for key in set(left) | set(right)
    )


def log_change(left: float, right: float, floor: float) -> float:
    ratio = abs(math.log((right + floor) / (left + floor)))
    return min(1.0, ratio / math.log(4))


def compare(previous: dict, recent: dict) -> tuple[float, list[str], dict[str, float]]:
    components = {
        "preferred tip route": total_variation(
            previous["tip_route_distribution"], recent["tip_route_distribution"]
        ),
        "average tip": log_change(
            previous["average_tip_lamports"], recent["average_tip_lamports"], 1_000
        ),
        "CU usage": log_change(previous["median_cu_used"], recent["median_cu_used"], 10_000),
        "CU limit": log_change(previous["median_cu_limit"], recent["median_cu_limit"], 10_000),
        "priority fee": log_change(
            previous["average_priority_fee"], recent["average_priority_fee"], 1_000
        ),
        "instruction order": total_variation(
            previous["instruction_order_distribution"],
            recent["instruction_order_distribution"],
        ),
        "parent program": total_variation(
            previous["parent_program_distribution"],
            recent["parent_program_distribution"],
        ),
        "fee-payer pattern": abs(previous["self_paid_rate"] - recent["self_paid_rate"]),
        "instruction type": total_variation(
            previous["instruction_type_distribution"],
            recent["instruction_type_distribution"],
        ),
        "buy/sell mix": abs(previous["buy_rate"] - recent["buy_rate"]),
    }
    weights = {
        "preferred tip route": 0.15,
        "average tip": 0.10,
        "CU usage": 0.12,
        "CU limit": 0.10,
        "priority fee": 0.10,
        "instruction order": 0.18,
        "parent program": 0.18,
        "fee-payer pattern": 0.04,
        "instruction type": 0.02,
        "buy/sell mix": 0.01,
    }
    contributions = {key: components[key] * weights[key] for key in components}
    score = 100 * sum(contributions.values())
    drivers = sorted(contributions, key=lambda key: (-contributions[key], key))[:3]
    return score, drivers, components


def analyze(rows: list[dict]) -> list[dict]:
    grouped: defaultdict[str, defaultdict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    totals: dict[str, tuple[int, int]] = {}
    for row in rows:
        wallet = str(row["wallet"])
        grouped[wallet][str(row["period"])].append(row)
        totals[wallet] = (
            int(row["previous_transactions"]), int(row["recent_transactions"])
        )
    comparisons: list[dict] = []
    for wallet, periods in grouped.items():
        if set(periods) != {"previous", "recent"}:
            continue
        previous, recent = make_profile(periods["previous"]), make_profile(periods["recent"])
        score, drivers, components = compare(previous, recent)
        comparisons.append(
            {
                "wallet": wallet,
                "previous_transactions": totals[wallet][0],
                "recent_transactions": totals[wallet][1],
                "change_score": score,
                "minimum_internal_stability": min(
                    previous["internal_stability"], recent["internal_stability"]
                ),
                "change_drivers": drivers,
                "components": components,
                "previous": previous,
                "recent": recent,
            }
        )
    if len(comparisons) < 10:
        raise ValueError("wallet-fingerprint query returned fewer than ten comparable wallets")
    return comparisons


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def assign_tiers(comparisons: list[dict]) -> tuple[dict[str, int], dict[str, float]]:
    """Keep routine variation stable and reserve alerts for the extreme tail."""
    scores = [row["change_score"] for row in comparisons]
    stable_cutoff = max(15.0, percentile(scores, 0.80))
    changed_cutoff = max(30.0, percentile(scores, 0.95))
    stable_cutoff = min(stable_cutoff, changed_cutoff - 1)
    counts = {"stable": 0, "review": 0, "changed": 0}
    for row in comparisons:
        if row["minimum_internal_stability"] < 45:
            tier = "review"
        elif row["change_score"] >= changed_cutoff:
            tier = "changed"
        elif row["change_score"] <= stable_cutoff:
            tier = "stable"
        else:
            tier = "review"
        row["tier"] = tier
        counts[tier] += 1
    return counts, {
        "stable_max_score": stable_cutoff,
        "changed_min_score": changed_cutoff,
        "minimum_internal_stability": 45.0,
    }


def research_page(
    stable: list[dict],
    changed: list[dict],
    window_end: object,
    eligible_count: int,
    tier_counts: dict[str, int],
) -> str:
    lines = [
        "# Detecting wallet operator changes",
        "",
        "A profitable public wallet can attract copytraders. If control of that wallet",
        "changes, the address stays the same while the transaction builder often does not.",
        "The indexer makes those construction details queryable, so monitoring can look",
        "beyond PnL and token selection.",
        "",
        "This experiment compares two adjacent 24-hour windows for active Pump.fun",
        "wallets. Its fingerprint uses tip routing and size, compute-unit behavior,",
        "priority fees, instruction ordering, fee-payer behavior, instruction variants,",
        "and parent-program mix. Each wallet needs at least 20 transactions per window.",
        "The examples float with live data and are regenerated by the documentation build.",
        "",
        f"*Window end: {md(utc_text(window_end))} · Comparable wallets: {eligible_count:,}*",
        "",
        "## Current tiers",
        "",
        "Thresholds are calibrated conservatively across the current population. Routine",
        "variation stays stable, ambiguous or internally noisy profiles go to review, and",
        "only the extreme high-change tail enters the changed tier.",
        "",
        "| Stable | Review | Changed |",
        "| ---: | ---: | ---: |",
        f"| {tier_counts['stable']:,} ({tier_counts['stable'] / eligible_count * 100:.1f}%) | "
        f"{tier_counts['review']:,} ({tier_counts['review'] / eligible_count * 100:.1f}%) | "
        f"{tier_counts['changed']:,} ({tier_counts['changed'] / eligible_count * 100:.1f}%) |",
        "",
        "## High-change tier examples",
        "",
        "These wallets are investigation candidates, not claims of a wallet sale or bad",
        "behavior. A bot upgrade, routing change, RPC change, or strategy change can create",
        "the same signal.",
        "",
        "| Wallet | Transactions, old → recent | Fingerprint, old → recent | Change score | Within-window stability | Main changes |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for row in changed:
        lines.append(
            "| "
            + " | ".join(
                [
                    code(short(row["wallet"])),
                    f"{row['previous_transactions']:,} → {row['recent_transactions']:,}",
                    f"{code(row['previous']['fingerprint'])} → {code(row['recent']['fingerprint'])}",
                    f"{row['change_score']:.1f}",
                    f"{row['minimum_internal_stability']:.1f}%",
                    md(", ".join(row["change_drivers"])),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Stable controls",
            "",
            "Low-change wallets provide a control group: the same feature set can remain",
            "recognizably stable across windows despite different trades and tokens.",
            "",
            "| Wallet | Transactions, old → recent | Fingerprint, old → recent | Change score | Within-window stability |",
            "| --- | ---: | --- | ---: | ---: |",
        ]
    )
    for row in stable:
        lines.append(
            "| "
            + " | ".join(
                [
                    code(short(row["wallet"])),
                    f"{row['previous_transactions']:,} → {row['recent_transactions']:,}",
                    f"{code(row['previous']['fingerprint'])} → {code(row['recent']['fingerprint'])}",
                    f"{row['change_score']:.1f}",
                    f"{row['minimum_internal_stability']:.1f}%",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## How to use the signal",
            "",
            "Treat a change as a circuit breaker for copytrading: pause, compare the new",
            "transaction fingerprint with the wallet's prior baseline, and require fresh",
            "performance evidence before following it again. Combining this signal with",
            "funding flows, token outcomes, and position sizing is stronger than any single",
            "fingerprint component.",
            "",
            f"[View the bounded SQL sample]({SQL_URL}) and",
            f"[the fingerprint calculation]({CODE_URL}).",
        ]
    )
    return "\n".join(lines) + "\n"


def run(env_path: Path, pages_dir: Path, public_dir: Path) -> dict:
    client = ClickHouseAccessor(str(env_path))
    try:
        try:
            rows = client.query(
                (SCRIPT_DIR / "wallet_fingerprint_transactions.sql").read_text(),
                settings={"max_execution_time": 240, "readonly": 1},
            )
            window_end = client.query(
                "SELECT max(block_time) AS window_end FROM pumpfun_v2_swaps WHERE failed = 0",
                settings={"max_execution_time": 60, "readonly": 1},
            )[0]["window_end"]
        except Exception as error:
            code_value = getattr(error, "code", None)
            suffix = f" code={code_value}" if code_value is not None else ""
            raise RuntimeError(
                f"wallet fingerprint query failed: {type(error).__name__}{suffix}"
            ) from None
    finally:
        client.disconnect()
    comparisons = analyze(rows)
    tier_counts, thresholds = assign_tiers(comparisons)
    stable_tier = [row for row in comparisons if row["tier"] == "stable"]
    changed_tier = [row for row in comparisons if row["tier"] == "changed"]
    if len(stable_tier) < len(comparisons) * 0.70:
        raise ValueError("wallet fingerprint calibration left fewer than 70% stable")
    if len(changed_tier) < 5:
        raise ValueError("wallet fingerprint calibration produced fewer than five changes")
    changed = sorted(
        changed_tier,
        key=lambda row: (-row["change_score"], -row["minimum_internal_stability"], row["wallet"]),
    )[:5]
    stable = sorted(
        stable_tier,
        key=lambda row: (row["change_score"], -row["minimum_internal_stability"], row["wallet"]),
    )[:5]

    pages_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "wallet-fingerprint-changes.mdx").write_text(
        research_page(
            stable, changed, window_end, len(comparisons), tier_counts
        )
    )
    summary = {
        "source": "https://onchaindivers.com",
        "window_end": utc_text(window_end),
        "eligible_wallets": len(comparisons),
        "tier_counts": tier_counts,
        "tier_thresholds": thresholds,
        "stable_examples": stable,
        "changed_examples": changed,
    }
    (public_dir / "wallet-fingerprint-research.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(
        f"generated wallet fingerprint research: {len(comparisons):,} wallets, "
        f"{tier_counts['stable']:,} stable, {tier_counts['review']:,} review, "
        f"{tier_counts['changed']:,} changed"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--pages-dir", type=Path, default=ROOT / "docs" / "pages" / "research")
    parser.add_argument("--public-dir", type=Path, default=ROOT / "docs" / "public" / "research")
    args = parser.parse_args()
    run(args.env_file, args.pages_dir, args.public_dir)


if __name__ == "__main__":
    main()
