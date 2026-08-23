#!/usr/bin/env python3
"""Generate reproducible research pages on potential SWQoS tip endpoints.

Stake-weighted quality-of-service (SWQoS) relays are paid with a plain SOL
transfer at the top level of a transaction, in the same shape as a Jito tip. This
script screens the top-level transfers recorded on a DEX's swaps to surface
candidate relay endpoints, labels the ones that map to a known landing provider,
and force-includes a few well-known providers that never clear the screen so the
page never looks like it silently dropped them.

One page is produced per source DEX (Pump.fun v2, PumpSwap, Meteora DLMM), each
with its own thresholds. Data, access, and indexer docs: https://onchaindivers.com
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

RECENT_WINDOW_DAYS = 4
REFERENCE_LAG_DAYS = 30
LAMPORTS_PER_SOL = 1_000_000_000
MAX_MEDIAN_LAMPORTS = 10_000_000  # 0.01 SOL median-tip cap, shared by all sources

# Tip-size histogram buckets (upper bounds, in lamports). Seven buckets total.
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

# One page per DEX. Thresholds scale with each DEX's traffic; Meteora DLMM is
# ~20x smaller than the Pump.fun venues, so it uses a lower signer floor.
SOURCES = (
    {
        "key": "pumpfun-v2",
        "table": "pumpfun_v2_swaps",
        "landed_expr": "(failed = 0)",
        "has_failed": True,
        "dex": "Pump.fun v2",
        "dex_seo": "Pump.fun",
        "page": "swqos-providers.mdx",
        "json": "swqos-research.json",
        "sidebar": "Best SWQoS for Pump.fun",
        "min_signers": 1000,
    },
    {
        "key": "pumpswap",
        "table": "pumpswap_all_swaps",
        "landed_expr": "1",
        "has_failed": False,
        "dex": "PumpSwap",
        "dex_seo": "PumpSwap",
        "page": "swqos-providers-pumpswap.mdx",
        "json": "swqos-research-pumpswap.json",
        "sidebar": "Best SWQoS for PumpSwap",
        "min_signers": 1000,
    },
    {
        "key": "dlmm",
        "table": "meteora_swaps",
        "landed_expr": "1",
        "has_failed": False,
        "dex": "Meteora DLMM",
        "dex_seo": "Meteora DLMM",
        "page": "swqos-providers-dlmm.mdx",
        "json": "swqos-research-dlmm.json",
        "sidebar": "Best SWQoS for Meteora DLMM",
        "min_signers": 200,
    },
)

# --- Known-provider registry -------------------------------------------------
# A single source of truth, reused across every page:
#   PROVIDERS         provider name -> extra info (endpoint URL, ...)
#   ACCOUNT_PROVIDER  tip account address -> provider name (explicit, non-vanity)
#   PREFIX_PROVIDER   lowercased vanity prefix -> provider name
# provider_for(address) resolves an address to {"name", "url"} via these maps.

ONCHAINDIVERS_TPU_ADDRESS = "GxkB4oYYLsoeAoxAdXjDEBSrP7JGCy3re7mqozFYyiYW"
CORVUS_ADDRESS = "CorvuSSoLxPKLoXWXSfn8pFSMhCRHhe7Uwqe874cmwvg"

PROVIDERS: dict[str, dict[str, Any]] = {
    "Jito": {"url": "https://docs.jito.wtf/"},
    "BlockSprint": {"url": "https://blocksprint.io/"},
    "0slot": {"url": "https://0slot.trade/"},
    "BlockRazor": {"url": "https://blockrazor.io/"},
    "Astralane": {"url": "https://astralane.io/"},
    "Nozomi": {"url": "https://temporal.xyz/"},
    "NextBlock": {"url": "https://nextblock.io/"},
    "Hello Moon": {"url": "https://www.hellomoon.io/"},
    "Falcon": {"url": "https://docs.corvus-labs.io/falcon/"},
    "LandX": {"url": None},
    "Corvus": {"url": None},
    "OnchainDivers TPU": {"url": "https://tpu.onchaindivers.com/"},
}

# Some high-fan-out, modest-tip destinations are trading-terminal fee vaults, not
# SWQoS relays (e.g. GMGN). Drop any address with these vanity prefixes from every
# page. Compare EXCLUDED_ACCOUNTS for one-off addresses (e.g. Padre's fee vault).
EXCLUDED_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gmgn", "GMGN terminal fee account (not a SWQoS relay)"),
)

# Explicit (non-vanity) tip accounts -> provider name.
ACCOUNT_PROVIDER: dict[str, str] = {}


def _register_accounts(provider: str, addresses: tuple[str, ...]) -> None:
    for address in addresses:
        ACCOUNT_PROVIDER[address] = provider


_register_accounts(
    "Jito",
    (
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
        "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
        "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
        "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
        "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
        "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    ),
)
_register_accounts(
    "BlockSprint",
    (
        "Sp1x2AqpQckPLaWnWCJUNg8k6qQexfaEWcSRKf5JcDV",
        "SpWrza9E63MQuHeGnnfzmtLVCs3pBdjyKPXUABPo9nq",
        "SpagSJmnh8E9cGT5Y431xPPaS2c1xLREGGCWN9yDeUf",
        "Sp4JHSh9cksfzXbgK7Pq2ovtn8LirLQydaJKTsiNT77",
        "Sp1xMS2cbw83SZDNr4AGqkBYYLjb3LvVnmDSrTMaHkr",
    ),
)
_register_accounts(
    "0slot",
    (
        "6fQaVhYZA4w3MBSXjJ81Vf6W1EDYeUPXpgVQ6UQyU1Av",
        "DiTmWENJsHQdawVUUKnUXkconcpW4Jv52TnMWhkncF6t",
        "HRyRhQ86t3H4aAtgvHVpUJmw64BDrb61gRiKcdKUXs5c",
        "Eb2KpSC8uMt9GmzyAEm5Eb1AAAgTjRaXWFjKyFXHZxF3",
        "FCjUJZ1qozm1e8romw216qyfQMaaWKxWsuySnumVCCNe",
        "7y4whZmw388w1ggjToDLSBLv47drw5SUXcLk6jtmwixd",
        "J9BMEWFbCBEjtQ1fG5Lo9kouX1HfrKQxeUxetwXrifBw",
        "8U1JPQh3mVQ4F5jwRdFTBzvNRQaYFQppHQYoH38DJGSQ",
        "ENxTEjSQ1YabmUpXAdCgevnHQ9MHdLv8tzFiuiYJqa13",
        "6rYLG55Q9RpsPGvqdPNJs4z5WTxJVatMB8zV3WJhs5EK",
        "Cix2bHfqPcKcM233mzxbLk14kSggUUiz2A87fJtGivXr",
        "4HiwLEP2Bzqj3hM2ENxJuzhcPCdsafwiet3oGkMkuQY4",
        "7toBU3inhmrARGngC7z6SjyP85HgGMmCTEwGNRAcYnEK",
        "8mR3wB1nh4D6J9RUCugxUpc6ya8w38LPxZ3ZjcBhgzws",
        "6SiVU5WEwqfFapRuYCndomztEwDjvS5xgtEof3PLEGm9",
        "TpdxgNJBWZRL8UXF5mrEsyWxDWx9HQexA9P1eTWQ42p",
        "D8f3WkQu6dCF33cZxuAsrKHrGsqGP2yvAHf8mX6RXnwf",
        "GQPFicsy3P3NXxB5piJohoxACqTvWE9fKpLgdsMduoHE",
        "Ey2JEr8hDkgN8qKJGrLf2yFjRhW7rab99HVxwi5rcvJE",
        "4iUgjMT8q2hNZnLuhpqZ1QtiV8deFPy2ajvvjEpKKgsS",
        "3Rz8uD83QsU8wKvZbgWAPvCNDU6Fy8TSZTMcPm3RB6zt",
    ),
)
_register_accounts(
    "BlockRazor",
    (
        "Gywj98ophM7GmkDdaWs4isqZnDdFCW7B46TXmKfvyqSm",
        "FjmZZrFvhnqqb9ThCuMVnENaM3JGVuGWNyCAxRJcFpg9",
        "6No2i3aawzHsjtThw81iq1EXPJN6rh8eSJCLaYZfKDTG",
        "A9cWowVAiHe9pJfKAj3TJiN9VpbzMUq6E4kEvf5mUT22",
        "68Pwb4jS7eZATjDfhmTXgRJjCiZmw1L7Huy4HNpnxJ3o",
        "4ABhJh5rZPjv63RBJBuyWzBK3g9gWMUQdTZP2kiW31V9",
        "B2M4NG5eyZp5SBQrSdtemzk5TqVuaWGQnowGaCBt8GyM",
        "5jA59cXMKQqZAVdtopv8q3yyw9SYfiE3vUCbt7p8MfVf",
        "5YktoWygr1Bp9wiS1xtMtUki1PeYuuzuCF98tqwYxf61",
        "295Avbam4qGShBYK7E9H5Ldew4B3WyJGmgmXfiWdeeyV",
        "EDi4rSy2LZgKJX74mbLTFk4mxoTgT6F7HxxzG2HBAFyK",
        "BnGKHAC386n4Qmv9xtpBVbRaUTKixjBe3oagkPFKtoy6",
        "Dd7K2Fp7AtoN8xCghKDRmyqr5U169t48Tw5fEd3wT9mq",
        "AP6qExwrbRgBAVaehg4b5xHENX815sMabtBzUzVB4v8S",
    ),
)
_register_accounts("OnchainDivers TPU", (ONCHAINDIVERS_TPU_ADDRESS,))

# Distinctive lowercased vanity prefixes that identify a provider across all of
# its rotating accounts.
PREFIX_PROVIDER: tuple[tuple[str, str], ...] = (
    ("nextblock", "NextBlock"),
    ("landx", "LandX"),
    ("moon", "Hello Moon"),
    ("fa1con", "Falcon"),
    ("astra", "Astralane"),
    ("noz", "Nozomi"),
    ("corvu", "Corvus"),
)

# Providers we guarantee a row for even when they never clear the screen. Corvus
# and OnchainDivers TPU often have no activity at all on a given DEX, so a synthetic
# placeholder row is injected when the query returns nothing for them.
PLACEHOLDER_PROVIDERS = (
    {"name": "Falcon", "address": "Fa1con11xLjPddfzRwRUB16sbFZggp2JeJkCeWREyR8X"},
    {"name": "Corvus", "address": CORVUS_ADDRESS},
    {"name": "OnchainDivers TPU", "address": ONCHAINDIVERS_TPU_ADDRESS},
)

# Addresses that match the screen's shape (high fan-out, modest tips) but are
# known NOT to be SWQoS relays — e.g. trading-terminal fee vaults. Dropped from
# every page.
EXCLUDED_ACCOUNTS: dict[str, str] = {
    "J5XGHmzrRmnYWbmw45DbYkdZAU2bwERFZ11qCDXPvFB5": "Padre terminal fee account",
}


def provider_for(address: str) -> Optional[dict[str, Any]]:
    """Return {"name", "url"} for a known provider, or None when unlabeled."""
    name = ACCOUNT_PROVIDER.get(address)
    if name is None:
        lowered = address.lower()
        for prefix, prefix_name in PREFIX_PROVIDER:
            if lowered.startswith(prefix):
                name = prefix_name
                break
    if name is None:
        return None
    return {"name": name, "url": PROVIDERS[name]["url"]}


# --- formatting helpers ------------------------------------------------------
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


def sol(lamports: object) -> str:
    return f"{int(lamports) / LAMPORTS_PER_SOL:.6f}"


def sparkline(counts: list[int]) -> str:
    tallest = max(counts, default=0)
    levels = "▁▂▃▄▅▆▇█"
    if tallest == 0:
        return "·" * len(counts)
    return "".join(
        "·" if count == 0 else levels[max(0, round(count / tallest * 7))]
        for count in counts
    )


def histogram_cell(counts: list[int]) -> str:
    if sum(counts) == 0:
        return "—"
    return f"{code(sparkline(counts))} ({'/'.join(str(c) for c in counts)})"


def provider_cell(record: dict) -> str:
    if not record["provider"]:
        return "—"
    name = record["provider"]
    text = f"[{md(name)}]({record['provider_url']})" if record["provider_url"] else md(name)
    if record["below_screen"]:
        text += "†"
    return text


# --- query plumbing ----------------------------------------------------------
def query_sql(
    client: ClickHouseAccessor,
    template_name: str,
    replacements: dict[str, str],
    parameters: Optional[dict[str, Any]] = None,
) -> list[dict]:
    """Execute a checked-in SQL template after substituting __TOKENS__."""
    sql = (SCRIPT_DIR / template_name).read_text()
    for token, value in replacements.items():
        sql = sql.replace(token, value)
    try:
        return client.query(
            sql,
            parameters=parameters,
            settings={"max_execution_time": 300, "readonly": 1},
        )
    except Exception as error:
        code_value = getattr(error, "code", None)
        suffix = f" code={code_value}" if code_value is not None else ""
        raise RuntimeError(
            f"{template_name} failed: {type(error).__name__}{suffix}"
        ) from None


def build_records(
    candidate_rows: list[dict],
    seen_30d: set[str],
    source: dict,
    reference_available: bool,
) -> list[dict]:
    """Turn raw query rows into screened records plus below-screen representatives."""
    records: list[dict] = []
    for row in candidate_rows:
        dest = str(row["dest"])
        lowered_dest = dest.lower()
        if dest in EXCLUDED_ACCOUNTS or any(
            lowered_dest.startswith(prefix) for prefix, _ in EXCLUDED_PREFIXES
        ):
            continue
        success_hist = [int(x) for x in row["success_histogram"]]
        failed_hist = [int(x) for x in row["failed_histogram"]]
        success_count = int(row["success_count"])
        failed_count = int(row["failed_count"])
        if sum(success_hist) != success_count or sum(failed_hist) != failed_count:
            raise ValueError(f"histogram totals do not reconcile for {dest}")
        signers = int(row["signers"])
        median = int(row["median_lamports"])
        provider = provider_for(dest)
        below = not (signers > source["min_signers"] and median <= MAX_MEDIAN_LAMPORTS)
        records.append(
            {
                "address": dest,
                "provider": provider["name"] if provider else None,
                "provider_url": provider["url"] if provider else None,
                "signers": signers,
                "transfers": int(row["transfers"]),
                "landed_count": success_count,
                "failed_count": failed_count,
                "median_lamports": median,
                "p95_lamports": int(row["p95_lamports"]),
                "landed_tip_buckets": success_hist,
                "failed_tip_buckets": failed_hist,
                "is_new": (dest not in seen_30d) if reference_available else None,
                "below_screen": below,
                "placeholder": False,
            }
        )

    screened = sorted(
        (r for r in records if not r["below_screen"]),
        key=lambda r: (-r["signers"], r["address"]),
    )
    if not screened:
        raise ValueError(f"{source['key']} screen returned no candidate destinations")

    # Below-screen rows arrive because they are force-included known providers.
    # Collapse each such provider to a single representative (its busiest account),
    # and only for providers that have no screened row already.
    labeled_in_screen = {r["provider"] for r in screened if r["provider"]}
    representatives: dict[str, dict] = {}
    for row in records:
        if not row["below_screen"] or not row["provider"]:
            continue
        if row["provider"] in labeled_in_screen:
            continue
        current = representatives.get(row["provider"])
        if current is None or row["signers"] > current["signers"]:
            representatives[row["provider"]] = row
    below = sorted(representatives.values(), key=lambda r: (-r["signers"], r["address"]))

    # Synthesize a placeholder for guaranteed providers with no row at all.
    present = labeled_in_screen | set(representatives)
    for provider in PLACEHOLDER_PROVIDERS:
        if provider["name"] in present:
            continue
        below.append(
            {
                "address": provider["address"],
                "provider": provider["name"],
                "provider_url": PROVIDERS[provider["name"]]["url"],
                "signers": None,
                "transfers": None,
                "landed_count": None,
                "failed_count": None,
                "median_lamports": None,
                "p95_lamports": None,
                "landed_tip_buckets": [0] * 7,
                "failed_tip_buckets": [0] * 7,
                "is_new": None,
                "below_screen": True,
                "placeholder": True,
            }
        )
    return screened, below


def num(value: object, fmt: str = "{:,}") -> str:
    return "—" if value is None else fmt.format(value)


def render_row(rank: str, record: dict, has_failed: bool) -> str:
    signers = num(record["signers"])
    median_p95 = (
        [sol(record["median_lamports"]), sol(record["p95_lamports"])]
        if record["median_lamports"] is not None
        else ["—", "—"]
    )
    new_flag = "!" if record["is_new"] else ""
    if has_failed:
        cells = [
            rank,
            code(record["address"]),
            provider_cell(record),
            new_flag,
            signers,
            num(record["landed_count"]),
            num(record["failed_count"]),
            "—" if record["placeholder"] else histogram_cell(record["landed_tip_buckets"]),
            "—" if record["placeholder"] else histogram_cell(record["failed_tip_buckets"]),
            *median_p95,
        ]
    else:
        cells = [
            rank,
            code(record["address"]),
            provider_cell(record),
            new_flag,
            signers,
            num(record["transfers"]),
            "—" if record["placeholder"] else histogram_cell(record["landed_tip_buckets"]),
            *median_p95,
        ]
    return "| " + " | ".join(cells) + " |"


def known_providers_section(screened: list[dict], below: list[dict]) -> list[str]:
    counts: dict[str, dict[str, object]] = {}
    for record in screened:
        if record["provider"]:
            entry = counts.setdefault(record["provider"], {"url": record["provider_url"], "rows": 0})
            entry["rows"] = int(entry["rows"]) + 1
    lines = [
        "",
        "## Known providers",
        "",
        "Destinations that map to a publicly identifiable transaction-landing",
        "service. Everything else in the table is an unlabeled lead.",
        "",
        "| Provider | Endpoint | Screened rows |",
        "| --- | --- | ---: |",
    ]
    for name in sorted(counts, key=lambda item: (-int(counts[item]["rows"]), item)):
        url = counts[name]["url"]
        label = f"[{md(name)}]({url})" if url else md(name)
        endpoint = md(url) if url else "—"
        lines.append(f"| {label} | {endpoint} | {int(counts[name]['rows'])} |")
    for record in below:
        url = record["provider_url"]
        label = f"[{md(record['provider'])}]({url})" if url else md(record["provider"])
        endpoint = md(url) if url else "—"
        note = "no activity in window" if record["placeholder"] else "below screen"
        lines.append(f"| {label}† | {endpoint} | {note} |")
    return lines


def research_page(
    source: dict,
    screened: list[dict],
    below: list[dict],
    window_end: object,
    reference_available: bool,
) -> str:
    dex = source["dex"]
    dex_seo = source["dex_seo"]
    has_failed = source["has_failed"]
    cap_sol = f"{MAX_MEDIAN_LAMPORTS / LAMPORTS_PER_SOL:g}"
    new_count = sum(1 for r in screened if r["is_new"])
    if has_failed:
        header = (
            "| Rank | Address | Provider | New | Signers | Landed | Failed | "
            "Landed tip sizes | Failed tip sizes | Median tip (SOL) | P95 tip (SOL) |"
        )
        divider = "| ---: | --- | --- | :---: | ---: | ---: | ---: | --- | --- | ---: | ---: |"
    else:
        header = (
            "| Rank | Address | Provider | New | Signers | Transfers | "
            "Tip sizes | Median tip (SOL) | P95 tip (SOL) |"
        )
        divider = "| ---: | --- | --- | :---: | ---: | ---: | --- | ---: | ---: |"

    if reference_available:
        new_legend = (
            ", and a **!** marks an address absent from top-level transfers "
            f"{REFERENCE_LAG_DAYS} days earlier"
        )
        new_stat = f" · New in {REFERENCE_LAG_DAYS} days: {new_count}"
    else:
        new_legend = (
            f" (the {REFERENCE_LAG_DAYS}-day new-provider check is not available for "
            f"{dex}, which did not record top-level transfers that far back)"
        )
        new_stat = ""

    lines = [
        f"# What is the best SWQoS landing provider for {dex_seo}?",
        "",
        "Short answer: there is no single winner — it depends on the tip you are",
        "willing to pay and how much you value landed-vs-failed reliability. This page",
        "is a **data-driven shortlist** of the transaction-landing (SWQoS) relays that",
        f"{dex_seo} traders actually pay, rebuilt from on-chain data on every",
        "documentation build so you can compare them yourself.",
        "",
        "Stake-weighted quality-of-service (SWQoS) relays let a transaction reach a",
        "validator through staked bandwidth, and are paid with a plain SOL transfer at",
        "the top level of the transaction — the same shape as a Jito tip. We infer",
        f"candidate relays from the top-level transfers recorded on {dex} swaps.",
        "",
        f"A destination is screened in when, in the latest {RECENT_WINDOW_DAYS}-day data",
        f"window, more than {source['min_signers']:,} distinct signers tipped it and its",
        f"**median** tip is at most {cap_sol} SOL ({MAX_MEDIAN_LAMPORTS:,} lamports). The",
        "median cap keeps the screen on low-fee, high-fan-out relays while still",
        "admitting providers whose occasional tips run large.",
        "",
        "Rows labeled in the *Provider* column map to a known service; the rest are",
        "unlabeled leads whose endpoint we have not resolved — published as-is to make",
        "that lookup easier. A **†** marks a well-known provider force-included for",
        f"completeness even though it did not clear the screen{new_legend}.",
        "",
        f"*Window end: {md(utc_text(window_end))} · Screened relays: {len(screened)}{new_stat}*",
        "",
        "Tip-size buckets, left to right, in SOL: "
        + ", ".join(f"`{label}`" for label in BUCKET_LABELS)
        + ". The numbers in parentheses are the transfer counts in those buckets."
        + ("" if has_failed else f" {dex} swaps are recorded only when they land, so"
           " there is no failed breakdown for this venue."),
        "",
        header,
        divider,
    ]
    for rank, record in enumerate(screened, 1):
        lines.append(render_row(str(rank), record, has_failed))
    for record in below:
        lines.append(render_row("—", record, has_failed))

    lines.append("")
    lines.append(
        f"† Known provider force-included though it did not clear the screen "
        f"(fewer than {source['min_signers']:,} distinct signers, or a median tip "
        f"above {cap_sol} SOL). Placeholder rows had no observed top-level-transfer "
        f"activity on {dex} in this window."
    )
    lines.extend(known_providers_section(screened, below))
    lines.extend(
        [
            "",
            f"[View the candidate SQL on GitHub]({CANDIDATES_SQL_URL}), "
            f"[the 30-day reference SQL]({REFERENCE_SQL_URL}), and "
            f"[the page generator]({SOURCE_URL}).",
            "",
            "This is a mechanical activity screen over one DEX's traffic, not a latency",
            "benchmark or an endorsement. A high distinct-signer count is consistent",
            "with, but does not prove, a SWQoS relay: shared tip vaults, aggregators,",
            "and fee accounts can present the same shape. \"Best\" for your bot depends on",
            "your endpoint, region, and tip budget — measure landed rate yourself.",
        ]
    )
    return "\n".join(lines) + "\n"


def fetch_source(client: ClickHouseAccessor, source: dict) -> dict:
    """Run the two live queries for one DEX and return the raw rows.

    Separated from rendering so the expensive scans can be cached and the pages
    re-rendered offline when only the provider registry or exclusions change.
    """
    table = source["table"]
    replacements = {
        "__TABLE__": table,
        "__LANDED__": source["landed_expr"],
        "__MIN_SIGNERS__": str(source["min_signers"]),
        "__MAX_MEDIAN__": str(MAX_MEDIAN_LAMPORTS),
        "__ONCHAINDIVERS__": ONCHAINDIVERS_TPU_ADDRESS,
    }
    window_end = client.query(
        f"SELECT max(block_time) AS window_end FROM default.{table}",
        settings={"max_execution_time": 60, "readonly": 1},
    )[0]["window_end"]
    candidate_rows = query_sql(client, "swqos_candidates.sql", replacements)
    destinations = [str(row["dest"]) for row in candidate_rows]
    reference_rows = query_sql(
        client,
        "swqos_reference_destinations.sql",
        {"__TABLE__": table},
        parameters={"destinations": destinations},
    )
    return {
        "window_end": window_end,
        "candidate_rows": candidate_rows,
        "seen_30d": sorted({str(row["dest"]) for row in reference_rows}),
    }


def render_source(source: dict, fetched: dict, pages_dir: Path, public_dir: Path) -> dict:
    """Build the page and JSON for one DEX from fetched rows and the registry."""
    window_end = fetched["window_end"]
    seen_30d = set(fetched["seen_30d"])
    # If nothing was seen 30 days ago the reference is unusable — most often the
    # DEX did not record top-level transfers back then — so suppress the flag
    # rather than marking every relay "new".
    reference_available = bool(seen_30d)
    screened, below = build_records(
        fetched["candidate_rows"], seen_30d, source, reference_available
    )

    pages_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / source["page"]).write_text(
        research_page(source, screened, below, window_end, reference_available)
    )
    table = source["table"]

    summary = {
        "source": "https://onchaindivers.com",
        "dex": source["dex"],
        "table": table,
        "window_end": utc_text(window_end),
        "recent_window_days": RECENT_WINDOW_DAYS,
        "reference_lag_days": REFERENCE_LAG_DAYS,
        "min_signers": source["min_signers"],
        "max_median_lamports": MAX_MEDIAN_LAMPORTS,
        "reference_available": reference_available,
        "tip_bucket_edges_lamports": list(BUCKET_EDGES),
        "tip_bucket_labels_sol": list(BUCKET_LABELS),
        "screened_count": len(screened),
        "labeled_provider_count": sum(1 for r in screened if r["provider"]),
        "force_included_count": len(below),
        "new_provider_count": sum(1 for r in screened if r["is_new"]),
        "screened": screened,
        "force_included": below,
    }
    (public_dir / source["json"]).write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(
        f"generated SWQoS research [{source['key']}]: {len(screened)} screened, "
        f"{summary['labeled_provider_count']} labeled, {len(below)} force-included"
    )
    return summary


def run(env_path: Path, pages_dir: Path, public_dir: Path) -> dict:
    client = ClickHouseAccessor(str(env_path))
    summaries: dict[str, dict] = {}
    try:
        for source in SOURCES:
            fetched = fetch_source(client, source)
            summaries[source["key"]] = render_source(source, fetched, pages_dir, public_dir)
    finally:
        client.disconnect()
    return {"sources": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--pages-dir", type=Path, default=ROOT / "docs" / "pages" / "research")
    parser.add_argument("--public-dir", type=Path, default=ROOT / "docs" / "public" / "research")
    args = parser.parse_args()
    run(args.env_file, args.pages_dir, args.public_dir)


if __name__ == "__main__":
    main()
