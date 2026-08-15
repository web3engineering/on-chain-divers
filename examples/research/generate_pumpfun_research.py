#!/usr/bin/env python3
"""Generate two reproducible Pump.fun research pages from live ClickHouse data.

The outputs rank sustained-activity token creators and identify launches whose
early parent-program mix differs most from the equal-token population average.

Data, access, and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
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
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")


def md(value: object) -> str:
    """Escape database-controlled text before inserting it into MDX tables."""
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


def average_profiles(rows: list[dict]) -> tuple[dict[str, dict], dict[str, float]]:
    """Build per-token distributions and their equal-token population average."""
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
                "counts": {},
            },
        )
        token["counts"][str(row["parent_program"])] = int(row["buys"])
    if not tokens:
        raise ValueError("parent-program query returned no eligible tokens")

    average: defaultdict[str, float] = defaultdict(float)
    for token in tokens.values():
        total = sum(token["counts"].values())
        token["profile"] = {
            program: count / total for program, count in token["counts"].items()
        }
        for program, share in token["profile"].items():
            average[program] += share / len(tokens)
    return tokens, dict(average)


def jensen_shannon_distance(profile: dict[str, float], average: dict[str, float]) -> float:
    """Return base-2 Jensen-Shannon distance, bounded between zero and one."""
    programs = set(profile) | set(average)
    divergence = 0.0
    for program in programs:
        p = profile.get(program, 0.0)
        q = average.get(program, 0.0)
        midpoint = (p + q) / 2
        if p:
            divergence += 0.5 * p * math.log2(p / midpoint)
        if q:
            divergence += 0.5 * q * math.log2(q / midpoint)
    return math.sqrt(max(0.0, divergence))


def anomalous_tokens(
    tokens: dict[str, dict], average: dict[str, float], limit: int = 5
) -> list[dict]:
    """Select the deterministic farthest profiles and explain their largest delta."""
    ranked: list[dict] = []
    for token in tokens.values():
        profile = token["profile"]
        standout = max(
            set(profile) | set(average),
            key=lambda program: abs(profile.get(program, 0.0) - average.get(program, 0.0)),
        )
        dominant = max(profile, key=profile.get)
        ranked.append(
            {
                **token,
                "distance": jensen_shannon_distance(profile, average),
                "standout_program": standout,
                "token_share": profile.get(standout, 0.0),
                "average_share": average.get(standout, 0.0),
                "dominant_program": dominant,
                "dominant_share": profile[dominant],
                "dominant_average_share": average.get(dominant, 0.0),
            }
        )
    return sorted(ranked, key=lambda row: (-row["distance"], row["mint"]))[:limit]


def reliable_page(creators: list[dict], window_end: object) -> str:
    lines = [
        "# Most reliable Pump.fun token creators",
        "",
        "A launch qualifies when it has more than five distinct buy transactions in",
        "every slot of at least one eight-consecutive-slot streak within its first 128",
        "post-launch slots. The table ranks creators from the latest 24-hour",
        "data window by qualifying launches, qualification rate, and sustained buy activity.",
        "Only launches with the full 128-slot observation horizon available enter the",
        "table.",
        "",
        f"*Window end: {md(utc_text(window_end))}*",
        "",
        "| Rank | Creator | Qualifying launches | All launches | Rate | Lowest buys in a required slot | Earliest streak offset | Example token |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for rank, row in enumerate(creators, 1):
        creator = str(row["creator"])
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    code(creator),
                    f"{int(row['qualifying_launches']):,}",
                    f"{int(row['total_launches']):,}",
                    f"{float(row['qualification_rate_pct']):.2f}%",
                    f"{int(row['minimum_buys_in_any_required_slot']):,}",
                    f"+{int(row['earliest_streak_start_offset'])}",
                    f"{code(row['example_symbol'])} {code(short(str(row['example_mint'])))}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            f"[View the SQL on GitHub]({RELIABLE_SQL_URL}).",
            "",
            "This is a mechanical activity screen, not an endorsement of a creator or token.",
        ]
    )
    return "\n".join(lines) + "\n"


def weird_page(
    anomalies: list[dict],
    average: dict[str, float],
    eligible_count: int,
    window_end: object,
) -> str:
    top_programs = sorted(average.items(), key=lambda item: (-item[1], item[0]))[:10]
    other_share = max(0.0, 1.0 - sum(share for _, share in top_programs))
    lines = [
        "# Pump.fun tokens with unusual early activity",
        "",
        "This screen compares Pump.fun launches from the latest 24-hour data window.",
        "For each token it counts distinct buys by `parent_program` during slots",
        "`launch_slot + 1` through `launch_slot + 128`, keeps tokens with at least 48",
        "buys, normalizes each token to a distribution, and averages those distributions",
        "with equal weight per token. Launches without a complete 128-slot horizon are",
        "excluded.",
        "",
        f"*Window end: {md(utc_text(window_end))} · Eligible tokens: {eligible_count:,}*",
        "",
        "## Average parent-program distribution",
        "",
        "| Parent program | Average token share |",
        "| --- | ---: |",
    ]
    for program, share in top_programs:
        lines.append(f"| {code(program)} | {share * 100:.3f}% |")
    lines.append(f"| Other ({max(0, len(average) - len(top_programs))} programs) | {other_share * 100:.3f}% |")
    lines.extend(
        [
            "",
            "## Five farthest token profiles",
            "",
            "Distance is base-2 Jensen–Shannon distance from the average profile. It is",
            "bounded from 0 (identical) to 1 (disjoint). Ties are ordered by mint so the",
            "selection is reproducible.",
            "",
            "| Rank | Token | Symbol / name | Buys | Distance | Dominant parent-program mix |",
            "| ---: | --- | --- | ---: | ---: | --- |",
        ]
    )
    for rank, token in enumerate(anomalies, 1):
        mint = str(token["mint"])
        if not BASE58.fullmatch(mint):
            raise ValueError("invalid Solana mint in anomaly result")
        gmgn = f"https://gmgn.ai/sol/token/{mint}?chain=sol"
        dominant = (
            f"{code(token['dominant_program'])}: "
            f"token {token['dominant_share'] * 100:.2f}% vs average "
            f"{token['dominant_average_share'] * 100:.2f}%"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    f"[{code(short(mint))}]({gmgn})",
                    f"{code(token['symbol'])} / {md(token['name'])}",
                    f"{int(token['total_buys']):,}",
                    f"{float(token['distance']):.4f}",
                    dominant,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            f"[View the profile SQL on GitHub]({PROFILES_SQL_URL}) and",
            f"[the distance calculation]({SOURCE_URL}).",
            "",
            "Unusual means statistically different in this one feature window; it does not",
            "by itself imply manipulation, fraud, or future performance.",
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
            creators = query_file(client, "reliable_pumpfun_creators.sql")
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
    if len(creators) != 5:
        raise ValueError(f"expected five reliable creators, received {len(creators)}")
    tokens, average = average_profiles(profile_rows)
    anomalies = anomalous_tokens(tokens, average)
    if len(anomalies) != 5:
        raise ValueError(f"expected five anomalous tokens, received {len(anomalies)}")

    pages_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "reliable-pumpfun-creators.mdx").write_text(
        reliable_page(creators, window)
    )
    (pages_dir / "weird-pumpfun-activity.mdx").write_text(
        weird_page(anomalies, average, len(tokens), window)
    )
    summary = {
        "source": "https://onchaindivers.com",
        "window_end": utc_text(window),
        "reliable_creators": creators,
        "eligible_profile_tokens": len(tokens),
        "average_parent_program_distribution": average,
        "anomalous_tokens": [
            {key: value for key, value in token.items() if key not in {"counts", "profile"}}
            for token in anomalies
        ],
    }
    (public_dir / "pumpfun-research.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(
        f"generated Pump.fun research: {len(creators)} creators, "
        f"{len(tokens):,} eligible profiles, {len(average)} parent programs"
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
