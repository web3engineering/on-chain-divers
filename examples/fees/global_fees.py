#!/usr/bin/env python3
"""Fetch aggregate indexer fees for one Solana mint.

API and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request

from dotenv import dotenv_values


FIELDS = (
    "total",
    "transaction_fees",
    "base_fees",
    "priority_fees",
    "tips",
    "trading_fees",
    "tx_count",
    "success_count",
)


def endpoint() -> str:
    value = os.environ.get("FEES_URL") or dotenv_values(".env").get("FEES_URL")
    if not value:
        raise ValueError("set FEES_URL in the environment or .env")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("FEES_URL must be an HTTP(S) URL")
    return value


def fetch(mint: str) -> dict:
    base = endpoint()
    parsed = urllib.parse.urlsplit(base)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "mint"] + [("mint", mint)]
    url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except Exception as error:
        raise RuntimeError(f"fees request failed ({type(error).__name__})") from None
    if payload.get("mint") != mint or any(not isinstance(payload.get(key), int) for key in FIELDS):
        raise ValueError("fees API returned an unexpected response shape")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mint", help="Solana mint address")
    args = parser.parse_args()
    print(json.dumps(fetch(args.mint), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
