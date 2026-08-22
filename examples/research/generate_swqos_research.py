#!/usr/bin/env python3
"""Generate a reproducible research page on potential SWQoS tip endpoints.

Pump.fun v2 swap transactions record their top-level SOL transfers. Stake-weighted
quality-of-service (SWQoS) relays are paid through such a top-level transfer, so a
destination tipped by a very large number of distinct signers, with modest
amounts, is a candidate relay endpoint. This script screens those destinations,
summarises landed/failed activity and tip-size distributions, and flags addresses
that were not receiving top-level transfers roughly a month earlier.

Data, access, and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from clickhouse_accessors import ClickHouseAccessor  # noqa: E402


GITHUB_ROOT = "https://github.com/web3engineering/on-chain-divers/blob/master"
SOURCE_URL = f"{GITHUB_ROOT}/examples/research/generate_swqos_research.py"
CANDIDATES_SQL_URL = f"{GITHUB_ROOT}/examples/research/swqos_candidates.sql"
REFERENCE_SQL_URL = f"{GITHUB_ROOT}/examples/research/swqos_reference_destinations.sql"

# Screen thresholds — kept in sync with swqos_candidates.sql for the page text.
MIN_SIGNERS = 3000
MAX_P95_LAMPORTS = 10_000_000
RECENT_WINDOW_DAYS = 4
REFERENCE_LAG_DAYS = 30

LAMPORTS_PER_SOL = 1_000_000_000

# Tip-size histogram buckets (upper bounds, in lamports). Seven buckets total:
# the seventh captures everything at or above the last edge.
BUCKET_EDGES = (100_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000)
BUCKET_LABELS = (
    "<0.0001",
    "0.0001–0.0005",
    "0.0005–0.001",
    "0.001–0.002",
    "0.002–0.005",
    "0.005–0.01",
    "≥0.01",
)

# Curated registry of publicly identifiable transaction-landing / SWQoS providers,
# keyed by their on-chain tip account. Anything not matched here is published as an
# unlabeled lead, so the table is a mix of known and unknown providers.
#
# EXPLICIT_PROVIDERS maps a specific tip account to a provider; PROVIDER_PREFIXES
# matches distinctive vanity prefixes (e.g. every `gmgn…` account is GMGN).
EXPLICIT_PROVIDERS: dict[str, dict[str, str]] = {
    # Jito tip payment accounts (canonical, publicly documented set of eight).
    **{
        address: {"name": "Jito", "url": "https://docs.jito.wtf/"}
        for address in (
            "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
            "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
            "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
            "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
            "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
            "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
            "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
            "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
        )
    },
    # BlockSprint tip-wallet rotation (Sp… vanity prefix).
    **{
        address: {"name": "BlockSprint", "url": "https://blocksprint.io/"}
        for address in (
            "Sp1x2AqpQckPLaWnWCJUNg8k6qQexfaEWcSRKf5JcDV",
            "SpWrza9E63MQuHeGnnfzmtLVCs3pBdjyKPXUABPo9nq",
            "SpagSJmnh8E9cGT5Y431xPPaS2c1xLREGGCWN9yDeUf",
            "Sp4JHSh9cksfzXbgK7Pq2ovtn8LirLQydaJKTsiNT77",
            "Sp1xMS2cbw83SZDNr4AGqkBYYLjb3LvVnmDSrTMaHkr",
        )
    },
}

# Distinctive vanity prefixes that identify a provider across all of its accounts.
PROVIDER_PREFIXES: tuple[tuple[str, dict[str, str]], ...] = (
    ("gmgn", {"name": "GMGN", "url": "https://gmgn.ai/"}),
)

# A known endpoint supplied out of band. It does not always clear the Pump.fun v2
# screen, so it is surfaced in the Known providers section rather than the table.
ONCHAINDIVERS_TPU = {
    "name": "OnchainDivers TPU",
    "url": "https://tpu.onchaindivers.com/",
    "address": "GxkB4oYYLsoeAoxAdXjDEBSrP7JGCy3re7mqozFYyiYW",
}


def provider_for(address: str) -> Optional[dict[str, str]]:
    """Return the known provider for an address, or None when it is unlabeled."""
    if address in EXPLICIT_PROVIDERS:
        return EXPLICIT_PROVIDERS[address]
    for prefix, provider in PROVIDER_PREFIXES:
        if address.startswith(prefix):
            return provider
    if address == ONCHAINDIVERS_TPU["address"]:
        return {"name": ONCHAINDIVERS_TPU["name"], "url": ONCHAINDIVERS_TPU["url"]}
    return None


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


def sol(lamports: object) -> str:
    """Render a lamport amount as SOL with lamport precision."""
    return f"{int(lamports) / LAMPORTS_PER_SOL:.6f}"


def sparkline(counts: list[int]) -> str:
    """Return a compact fixed-bin histogram bar for auditable bin counts."""
    tallest = max(counts, default=0)
    levels = "▁▂▃▄▅▆▇█"
    if tallest == 0:
        return "·" * len(counts)
    return "".join(
        "·" if count == 0 else levels[max(0, round(count / tallest * 7))]
        for count in counts
    )


def query_file(
    client: ClickHouseAccessor,
    name: str,
    parameters: Optional[dict[str, Any]] = None,
) -> list[dict]:
    """Execute a checked-in query without leaking connection details on error."""
    try:
        return client.query(
            (SCRIPT_DIR / name).read_text(),
            parameters=parameters,
            settings={"max_execution_time": 300, "readonly": 1},
        )
    except Exception as error:
        code_value = getattr(error, "code", None)
        suffix = f" code={code_value}" if code_value is not None else ""
        raise RuntimeError(f"{name} failed: {type(error).__name__}{suffix}") from None


def build_records(candidate_rows: list[dict], seen_30d: set[str]) -> list[dict]:
    """Validate the raw query rows and attach the new-provider flag."""
    records: list[dict] = []
    for row in candidate_rows:
        dest = str(row["dest"])
        success_hist = [int(x) for x in row["success_histogram"]]
        failed_hist = [int(x) for x in row["failed_histogram"]]
        success_count = int(row["success_count"])
        failed_count = int(row["failed_count"])
        # The per-bucket counts must reconcile with the landed/failed totals, or
        # the histogram and the headline numbers would disagree.
        if sum(success_hist) != success_count or sum(failed_hist) != failed_count:
            raise ValueError(f"histogram totals do not reconcile for {dest}")
        provider = provider_for(dest)
        records.append(
            {
                "address": dest,
                "provider": provider["name"] if provider else None,
                "provider_url": provider["url"] if provider else None,
                "signers": int(row["signers"]),
                "transfers": int(row["transfers"]),
                "landed_count": success_count,
                "failed_count": failed_count,
                "median_lamports": int(row["median_lamports"]),
                "p95_lamports": int(row["p95_lamports"]),
                "landed_tip_buckets": success_hist,
                "failed_tip_buckets": failed_hist,
                "is_new": dest not in seen_30d,
            }
        )
    if not records:
        raise ValueError("SWQoS screen returned no candidate destinations")
    return records


def histogram_cell(counts: list[int]) -> str:
    if sum(counts) == 0:
        return "—"
    return f"{code(sparkline(counts))} ({'/'.join(str(c) for c in counts)})"


def known_providers_section(records: list[dict]) -> list[str]:
    """A short reference of the labeled providers, plus curated known endpoints."""
    counts: dict[str, dict[str, object]] = {}
    for record in records:
        if record["provider"]:
            entry = counts.setdefault(
                record["provider"],
                {"url": record["provider_url"], "rows": 0},
            )
            entry["rows"] = int(entry["rows"]) + 1

    lines = [
        "",
        "## Known providers",
        "",
        "A subset of the destinations above map to publicly identifiable",
        "transaction-landing services; the remaining rows are unlabeled leads.",
        "",
        "| Provider | Endpoint | Labeled rows |",
        "| --- | --- | ---: |",
    ]
    for name in sorted(counts, key=lambda item: (-int(counts[item]["rows"]), item)):
        url = str(counts[name]["url"])
        lines.append(f"| [{md(name)}]({url}) | {md(url)} | {int(counts[name]['rows'])} |")

    # Always surface the OnchainDivers TPU endpoint, even when its tip account did
    # not clear the screen in the current window.
    if ONCHAINDIVERS_TPU["name"] not in counts:
        lines.extend(
            [
                "",
                f"[{md(ONCHAINDIVERS_TPU['name'])}]({ONCHAINDIVERS_TPU['url']}) "
                f"({code(short(ONCHAINDIVERS_TPU['address']))}) is a known low-latency "
                "endpoint that did not clear this window's screen and so is not listed "
                "in the table above; its tip account is published here as a labeled "
                "reference.",
            ]
        )
    return lines


def research_page(records: list[dict], window_end: object) -> str:
    new_count = sum(1 for record in records if record["is_new"])
    lines = [
        "# Potential SWQoS relay endpoints",
        "",
        "Stake-weighted quality-of-service (SWQoS) relays let a transaction reach a",
        "validator through staked bandwidth. They are paid with a plain SOL transfer",
        "at the top level of the transaction, in the same shape as a Jito tip. This",
        "study infers candidate relay endpoints from that payment pattern using the",
        "top-level transfers recorded on every Pump.fun v2 swap.",
        "",
        "A destination is treated as a candidate when, in the latest "
        f"{RECENT_WINDOW_DAYS}-day data window, more than {MIN_SIGNERS:,} distinct",
        "signers tipped it and its 95th-percentile tip is at most "
        f"{MAX_P95_LAMPORTS / LAMPORTS_PER_SOL:g} SOL "
        f"({MAX_P95_LAMPORTS:,} lamports). The percentile cap keeps the screen on",
        "low-fee, high-fan-out relays rather than a handful of large one-off",
        "transfers. Entries lower in the table — fewer signers, and the flagged new",
        "endpoints — are the less-popular relays this study is meant to surface.",
        "",
        "Some destinations map to a publicly identifiable landing service and are",
        "labeled in the *Provider* column; the rest are unlabeled leads. **For the",
        "unlabeled rows we do not resolve which RPC provider or endpoint the address",
        "belongs to** — the address is published as-is to make that lookup easier.",
        "Treat every unlabeled row as a lead to investigate, not a confirmed provider.",
        "",
        f"A **!** in the *New* column marks an address that qualifies now but received",
        f"no top-level transfers in the 4-day window ending {REFERENCE_LAG_DAYS} days",
        "earlier — a newly-active endpoint over the past month.",
        "",
        f"*Window end: {md(utc_text(window_end))} · Candidates: {len(records)} · "
        f"New in the last {REFERENCE_LAG_DAYS} days: {new_count}*",
        "",
        "Tip-size buckets, left to right, in SOL: "
        + ", ".join(f"`{label}`" for label in BUCKET_LABELS)
        + ". The numbers in parentheses are the transfer counts in those buckets.",
        "Landed and failed transactions are bucketed separately; a relay can have no",
        "failures, shown as `—`.",
        "",
        "| Rank | Address | Provider | New | Signers | Landed | Failed | Landed tip sizes | Failed tip sizes | Median tip (SOL) | P95 tip (SOL) |",
        "| ---: | --- | --- | :---: | ---: | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for rank, record in enumerate(records, 1):
        if record["provider"]:
            provider_cell = f"[{md(record['provider'])}]({record['provider_url']})"
        else:
            provider_cell = "—"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    code(record["address"]),
                    provider_cell,
                    "!" if record["is_new"] else "",
                    f"{record['signers']:,}",
                    f"{record['landed_count']:,}",
                    f"{record['failed_count']:,}",
                    histogram_cell(record["landed_tip_buckets"]),
                    histogram_cell(record["failed_tip_buckets"]),
                    sol(record["median_lamports"]),
                    sol(record["p95_lamports"]),
                ]
            )
            + " |"
        )
    lines.extend(known_providers_section(records))
    lines.extend(
        [
            "",
            f"[View the candidate SQL on GitHub]({CANDIDATES_SQL_URL}), "
            f"[the 30-day reference SQL]({REFERENCE_SQL_URL}), and "
            f"[the page generator]({SOURCE_URL}).",
            "",
            "This is a mechanical activity screen over Pump.fun v2 traffic only. A high",
            "distinct-signer count is consistent with, but does not prove, a SWQoS relay:",
            "shared tip vaults, aggregators, and fee accounts can present the same shape.",
            "Absence from the reference window means no observed top-level transfers 30",
            "days ago, not that the endpoint did not exist.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(env_path: Path, pages_dir: Path, public_dir: Path) -> dict:
    client = ClickHouseAccessor(str(env_path))
    try:
        try:
            window_end = client.query(
                "SELECT max(block_time) AS window_end FROM default.pumpfun_v2_swaps",
                settings={"max_execution_time": 60, "readonly": 1},
            )[0]["window_end"]
            candidate_rows = query_file(client, "swqos_candidates.sql")
            destinations = [str(row["dest"]) for row in candidate_rows]
            reference_rows = query_file(
                client,
                "swqos_reference_destinations.sql",
                parameters={"destinations": destinations},
            )
        except RuntimeError:
            raise
        except Exception as error:
            code_value = getattr(error, "code", None)
            suffix = f" code={code_value}" if code_value is not None else ""
            raise RuntimeError(
                f"SWQoS research query failed: {type(error).__name__}{suffix}"
            ) from None
    finally:
        client.disconnect()

    seen_30d = {str(row["dest"]) for row in reference_rows}
    records = build_records(candidate_rows, seen_30d)

    pages_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "swqos-providers.mdx").write_text(research_page(records, window_end))

    summary = {
        "source": "https://onchaindivers.com",
        "window_end": utc_text(window_end),
        "recent_window_days": RECENT_WINDOW_DAYS,
        "reference_lag_days": REFERENCE_LAG_DAYS,
        "min_signers": MIN_SIGNERS,
        "max_p95_lamports": MAX_P95_LAMPORTS,
        "tip_bucket_edges_lamports": list(BUCKET_EDGES),
        "tip_bucket_labels_sol": list(BUCKET_LABELS),
        "candidate_count": len(records),
        "new_provider_count": sum(1 for record in records if record["is_new"]),
        "labeled_provider_count": sum(1 for record in records if record["provider"]),
        "onchaindivers_tpu": ONCHAINDIVERS_TPU,
        "candidates": records,
    }
    (public_dir / "swqos-research.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(
        f"generated SWQoS research: {len(records)} candidates, "
        f"{summary['new_provider_count']} new in the last {REFERENCE_LAG_DAYS} days"
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
