#!/usr/bin/env python3
"""Generate two reproducible Pump.fun research pages from live ClickHouse data.

The outputs rank frequently active token creators by their weakest recent launch
and compare early parent-program composition between migrated and other launches.

Data, access, and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from clickhouse_accessors import ClickHouseAccessor  # noqa: E402


GITHUB_ROOT = "https://github.com/web3engineering/on-chain-divers/blob/master"
SOURCE_URL = f"{GITHUB_ROOT}/examples/research/generate_pumpfun_research.py"
RELIABLE_SQL_URL = f"{GITHUB_ROOT}/examples/research/reliable_pumpfun_creators.sql"
PROFILES_SQL_URL = f"{GITHUB_ROOT}/examples/research/pumpfun_parent_program_profiles.sql"


def md(value: object) -> str:
    """Escape database-controlled text before inserting it into MDX tables."""
    return html.escape(str(value), quote=True).replace("|", "&#124;").replace("\n", " ")


def code(value: object) -> str:
    return f"`{md(value).replace('`', '&#96;')}`"


def short(value: str) -> str:
    return f"{value[:6]}…{value[-6:]}" if len(value) > 16 else value


MCAP_BINS = (10_000, 25_000, 50_000, 100_000, 250_000)


def usd(value: float) -> str:
    """Format a USD value compactly for a generated table."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}m"
    return f"${value:,.0f}"


def mcap_histogram(values: list[float]) -> tuple[str, list[int]]:
    """Return a compact fixed-bin histogram and its auditable bin counts."""
    counts = [0] * (len(MCAP_BINS) + 1)
    for value in values:
        index = next(
            (index for index, upper in enumerate(MCAP_BINS) if value < upper),
            len(MCAP_BINS),
        )
        counts[index] += 1
    tallest = max(counts, default=0)
    levels = "▁▂▃▄▅▆▇█"
    bars = "".join(
        "·" if count == 0 else levels[max(0, round(count / tallest * 7))]
        for count in counts
    )
    return bars, counts


def creator_research(rows: list[dict]) -> tuple[list[dict], float, int]:
    """Group the token-level query into creator summaries and distributions."""
    creators: dict[str, dict] = {}
    for row in rows:
        creator_id = str(row["creator_id"])
        creator = creators.setdefault(
            creator_id,
            {
                "creator": creator_id,
                "launches": int(row["launches"]),
                "minimum_trades_first_100_slots": int(
                    row["minimum_trades_first_100_slots"]
                ),
                "average_trades_first_100_slots": float(
                    row["average_trades_first_100_slots"]
                ),
                "median_trades_first_100_slots": float(
                    row["median_trades_first_100_slots"]
                ),
                "maximum_trades_first_100_slots": int(
                    row["maximum_trades_first_100_slots"]
                ),
                "weakest_mint": str(row["weakest_mint"]),
                "weakest_symbol": str(row["weakest_symbol"]),
                "tokens": [],
            },
        )
        p95_mcap = float(row["p95_mcap_usd"] or 0)
        if p95_mcap <= 0 or int(row["price_observations"] or 0) < 1:
            raise ValueError(f"token {row['mint']} has no valid market-cap observations")
        creator["tokens"].append(
            {
                "mint": str(row["mint"]),
                "name": str(row["name"]),
                "symbol": str(row["symbol"]),
                "launched_at": utc_text(row["launched_at"]),
                "trades_first_100_slots": int(row["trades"]),
                "migrated": bool(int(row["migrated"])),
                "migrated_at": (
                    utc_text(row["migrated_at"]) if int(row["migrated"]) else None
                ),
                "p95_mcap_usd": p95_mcap,
                "price_observations": int(row["price_observations"] or 0),
                "pumpfun_price_observations": int(
                    row["pumpfun_price_observations"] or 0
                ),
                "pumpswap_price_observations": int(
                    row["pumpswap_price_observations"] or 0
                ),
            }
        )
    if len(creators) != 5:
        raise ValueError(f"expected five reliable creators, received {len(creators)}")

    ordered = list(creators.values())
    for creator in ordered:
        values = [token["p95_mcap_usd"] for token in creator["tokens"]]
        histogram, counts = mcap_histogram(values)
        creator["migrated_launches"] = sum(
            token["migrated"] for token in creator["tokens"]
        )
        creator["mcap_histogram"] = histogram
        creator["mcap_bin_counts"] = counts
    sol_usdc_rates = {float(row["sol_usdc_rate"]) for row in rows}
    sample_counts = {int(row["sol_usdc_sample_count"]) for row in rows}
    if len(sol_usdc_rates) != 1 or len(sample_counts) != 1:
        raise ValueError("SOL/USDC calculation was not constant across creator rows")
    return ordered, sol_usdc_rates.pop(), sample_counts.pop()


def utc_text(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def query_file(client: ClickHouseAccessor, name: str) -> list[dict]:
    """Execute a checked-in query without leaking connection details on error."""
    try:
        return client.query(
            (SCRIPT_DIR / name).read_text(),
            settings={"max_execution_time": 240, "readonly": 1},
        )
    except Exception as error:
        code_value = getattr(error, "code", None)
        suffix = f" code={code_value}" if code_value is not None else ""
        raise RuntimeError(f"{name} failed: {type(error).__name__}{suffix}") from None


def migration_profiles(rows: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build equal-token parent-program distributions for both migration groups."""
    tokens: dict[str, dict] = {}
    for row in rows:
        mint = str(row["mint"])
        token = tokens.setdefault(
            mint,
            {
                "mint": mint,
                "creator": str(row["creator"]),
                "name": str(row["name"]),
                "symbol": str(row["symbol"]),
                "launch_slot": int(row["launch_slot"]),
                "launched_at": utc_text(row["launched_at"]),
                "total_buys": int(row["total_buys"]),
                "migrated": bool(int(row["migrated"])),
                "counts": {},
            },
        )
        token["counts"][str(row["parent_program"])] = int(row["buys"])
    if not tokens:
        raise ValueError("parent-program query returned no eligible tokens")

    groups: dict[str, dict] = {}
    for token in tokens.values():
        total = sum(token["counts"].values())
        token["profile"] = {
            program: count / total for program, count in token["counts"].items()
        }
    for migrated, label in ((True, "migrated"), (False, "not_migrated")):
        members = [token for token in tokens.values() if token["migrated"] is migrated]
        if not members:
            raise ValueError(f"parent-program query returned no {label} tokens")
        distribution: defaultdict[str, float] = defaultdict(float)
        for token in members:
            for program, share in token["profile"].items():
                distribution[program] += share / len(members)
        groups[label] = {
            "token_count": len(members),
            "cohort_share": len(members) / len(tokens),
            "mean_buys": sum(token["total_buys"] for token in members) / len(members),
            "parent_program_distribution": dict(distribution),
        }
    return tokens, groups


def reliable_page(
    creators: list[dict], window_end: object, sol_usdc_rate: float, sample_count: int
) -> str:
    lines = [
        "# Most reliable Pump.fun token creators",
        "",
        "This ranking starts with creators that launched at least five tokens in the",
        "latest 24-hour data window. For every launch it counts distinct trades during",
        "slots `launch_slot + 1` through `launch_slot + 100`, then ranks creators by",
        "the minimum count across their launches. In other words, the leading creator",
        "has the strongest worst-performing launch. Both buys and sells count as trades.",
        "Only launches with a complete 100-slot observation horizon are included.",
        "",
        "For every token, robust peak market cap is its p95 swap-implied valuation.",
        "Pump.fun observations are combined with PumpSwap observations after migration.",
        "The calculation assumes one billion tokens with six decimals. SOL/USD is the",
        "median of the 100 most recent WSOL/USDC Meteora DLMM swaps in the window; a",
        "single rate is used for the day.",
        "",
        f"*Window end: {md(utc_text(window_end))} · SOL/USD: ${sol_usdc_rate:,.4f} "
        f"from {sample_count} DLMM swaps*",
        "",
        "Mcap histogram bins, left to right: `<$10k`, `$10–25k`, `$25–50k`,",
        "`$50–100k`, `$100–250k`, `≥$250k`. The numbers in parentheses are the",
        "token counts in those bins.",
        "",
        "| Rank | Creator | Launches | Minimum trades | Average | Median | Maximum | Migrated | Mcap distribution | Weakest launch |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for rank, row in enumerate(creators, 1):
        creator = str(row["creator"])
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    code(creator),
                    f"{int(row['launches']):,}",
                    f"{int(row['minimum_trades_first_100_slots']):,}",
                    f"{float(row['average_trades_first_100_slots']):,.2f}",
                    f"{float(row['median_trades_first_100_slots']):,.1f}",
                    f"{int(row['maximum_trades_first_100_slots']):,}",
                    f"{int(row['migrated_launches']):,}/{int(row['launches']):,}",
                    f"{code(row['mcap_histogram'])} ({'/'.join(map(str, row['mcap_bin_counts']))})",
                    f"{code(row['weakest_symbol'])} {code(short(str(row['weakest_mint'])))}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Token details",
            "",
            "| Creator rank | Token | Symbol / name | First-100-slot trades | Migrated | P95 market cap | Price observations | Sources |",
            "| ---: | --- | --- | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for rank, creator in enumerate(creators, 1):
        for token in sorted(
            creator["tokens"], key=lambda item: (-item["p95_mcap_usd"], item["mint"])
        ):
            sources = f"Pump.fun {token['pumpfun_price_observations']:,}"
            if token["pumpswap_price_observations"]:
                sources += f" + PumpSwap {token['pumpswap_price_observations']:,}"
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(rank),
                        code(token["mint"]),
                        f"{code(token['symbol'])} / {md(token['name'])}",
                        f"{token['trades_first_100_slots']:,}",
                        "Yes" if token["migrated"] else "No",
                        usd(token["p95_mcap_usd"]),
                        f"{token['price_observations']:,}",
                        sources,
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            f"[View the SQL on GitHub]({RELIABLE_SQL_URL}).",
            "",
            "P95 market cap is a robust descriptive high, not an all-time high or a",
            "guarantee that the displayed valuation was executable at meaningful size.",
            "This is a mechanical activity screen, not an endorsement of a creator or token.",
        ]
    )
    return "\n".join(lines) + "\n"


def migration_page(
    groups: dict[str, dict],
    eligible_count: int,
    window_end: object,
) -> str:
    migrated = groups["migrated"]
    not_migrated = groups["not_migrated"]
    migrated_mix = migrated["parent_program_distribution"]
    not_migrated_mix = not_migrated["parent_program_distribution"]
    all_programs = set(migrated_mix) | set(not_migrated_mix)
    top_programs = sorted(
        all_programs,
        key=lambda program: (
            -max(migrated_mix.get(program, 0.0), not_migrated_mix.get(program, 0.0)),
            program,
        ),
    )[:12]
    migrated_other = max(0.0, 1.0 - sum(migrated_mix.get(p, 0.0) for p in top_programs))
    not_migrated_other = max(
        0.0, 1.0 - sum(not_migrated_mix.get(p, 0.0) for p in top_programs)
    )
    lines = [
        "# Pump.fun parent programs: migrated vs not migrated",
        "",
        "This study compares Pump.fun launches from the latest 24-hour data window.",
        "For each token it counts distinct buys by `parent_program` during slots",
        "`launch_slot + 1` through `launch_slot + 128`, keeps tokens with at least 48",
        "buys, and labels it migrated when the mint appears in `pfamm_migrations` by",
        "the cohort cutoff. Launches without a complete 128-slot horizon are excluded.",
        "",
        f"*Window end: {md(utc_text(window_end))} · Eligible tokens: {eligible_count:,}*",
        "",
        "## Cohorts",
        "",
        "| Cohort | Tokens | Share of eligible launches | Mean buys in first 128 slots |",
        "| --- | ---: | ---: | ---: |",
        f"| Migrated | {migrated['token_count']:,} | {migrated['cohort_share'] * 100:.2f}% | {migrated['mean_buys']:,.1f} |",
        f"| Not migrated | {not_migrated['token_count']:,} | {not_migrated['cohort_share'] * 100:.2f}% | {not_migrated['mean_buys']:,.1f} |",
        "",
        "## Parent-program composition",
        "",
        "Every token is normalized to a distribution before cohort averaging, so a",
        "high-volume token cannot dominate the result. The difference is migrated minus",
        "not migrated, in percentage points.",
        "",
        "| Parent program | Migrated | Not migrated | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for program in top_programs:
        migrated_share = migrated_mix.get(program, 0.0)
        not_migrated_share = not_migrated_mix.get(program, 0.0)
        lines.append(
            f"| {code(program)} | {migrated_share * 100:.3f}% | "
            f"{not_migrated_share * 100:.3f}% | "
            f"{(migrated_share - not_migrated_share) * 100:+.3f} pp |"
        )
    lines.append(
        f"| Other ({max(0, len(all_programs) - len(top_programs))} programs) | "
        f"{migrated_other * 100:.3f}% | {not_migrated_other * 100:.3f}% | "
        f"{(migrated_other - not_migrated_other) * 100:+.3f} pp |"
    )
    lines.extend(
        [
            "",
            f"[View the profile SQL on GitHub]({PROFILES_SQL_URL}) and",
            f"[the cohort calculation]({SOURCE_URL}).",
            "",
            "Migration is observed only through the displayed cutoff. Tokens launched near",
            "that cutoff have less time to migrate, so the not-migrated cohort is",
            "right-censored. This descriptive comparison does not establish causality or",
            "predict future migration.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(env_path: Path, pages_dir: Path, public_dir: Path) -> dict:
    client = ClickHouseAccessor(str(env_path))
    try:
        try:
            window = client.query(
                "SELECT max(block_time) AS window_end FROM pumpfun_token_creation",
                settings={"max_execution_time": 60, "readonly": 1},
            )[0]["window_end"]
            creator_rows = query_file(client, "reliable_pumpfun_creators.sql")
            profile_rows = query_file(client, "pumpfun_parent_program_profiles.sql")
        except RuntimeError:
            raise
        except Exception as error:
            code_value = getattr(error, "code", None)
            suffix = f" code={code_value}" if code_value is not None else ""
            raise RuntimeError(
                f"Pump.fun research query failed: {type(error).__name__}{suffix}"
            ) from None
    finally:
        client.disconnect()
    creators, sol_usdc_rate, sol_usdc_sample_count = creator_research(creator_rows)
    tokens, groups = migration_profiles(profile_rows)

    pages_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "reliable-pumpfun-creators.mdx").write_text(
        reliable_page(
            creators, window, sol_usdc_rate, sol_usdc_sample_count
        )
    )
    (pages_dir / "pumpfun-migration-parent-programs.mdx").write_text(
        migration_page(groups, len(tokens), window)
    )
    summary = {
        "source": "https://onchaindivers.com",
        "window_end": utc_text(window),
        "sol_usdc_rate": sol_usdc_rate,
        "sol_usdc_sample_count": sol_usdc_sample_count,
        "reliable_creators": creators,
        "eligible_profile_tokens": len(tokens),
        "migration_comparison": groups,
    }
    (public_dir / "pumpfun-research.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(
        f"generated Pump.fun research: {len(creators)} creators, "
        f"{len(tokens):,} eligible profiles, "
        f"{groups['migrated']['token_count']:,} migrated"
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
