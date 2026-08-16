# OnchainDivers indexer examples

This repository is a self-contained, executable guide to the
[OnchainDivers indexers](https://onchaindivers.com). It contains working examples for:

- structured ClickHouse data for Solana DEX activity and helper tables;
- structured ClickHouse data for Polymarket fills and metadata;
- structured ClickHouse data for HyperLiquid fills, orders, wallets and positions;
- structured ClickHouse data for Robinhood Chain tokens and Uniswap v3/v4 activity;
- the aggregate fees API;
- raw Polymarket and HyperLiquid order-book archive discovery, download and replay;
- a synchronized Bitcoin five-minute Polymarket/HyperLiquid market reconstruction
  with a publication-sized diagnostic plot;
- a four-panel microprice study relating one- and two-level imbalance to
  Polymarket and HyperLiquid midpoint movement 300 milliseconds later;
- a live ranking of Pump.fun creators with at least five launches by the
  first-100-slot trade count of their weakest launch, plus migration-aware p95
  market-cap distributions valued with a Meteora DLMM SOL/USDC rate; and
- a comparison of early Pump.fun parent-program composition for migrated and
  non-migrated launches.

The examples under [`examples/`](examples/) are the source programs. The docs
explain the same programs, and `scripts/verify_examples.py` executes them during
every strict documentation build. A schema change, undocumented table, broken
query, invalid API response or incorrect order-book reconstruction fails the
build.

## Published ClickHouse datasets

| Network | DEX or domain tables | Helper tables |
| --- | --- | --- |
| Solana | Pump.fun, PumpSwap, Raydium AMM/CPMM/Launchpad, Meteora DLMM/Dynamic Bonding, Jito | token transfers, SOL top-ups, blocks, transaction timestamps, token creation, migrations, creator fees, caps |
| Polymarket | order fills | event and market metadata |
| HyperLiquid | raw fills and fulfilled orders | perpetual wallets and wallet positions |
| Robinhood Chain | Uniswap v3 and v4 pools and swaps | token metadata and EVM transaction context |

The exact live schemas and row counts are generated into the table-reference
pages. The generator intentionally uses a whitelist: a newly appearing table or
an undescribed published column stops the build until the documentation is
updated.

## Configuration

Copy `.env.example` to `.env` and insert read-only credentials and private
service URLs. `.env` is ignored by Git. Examples and docs refer only to variable
names, so deployment addresses and credentials are never committed or rendered.

## Run the checks in Docker

Docker is the authoritative execution environment; no host Python or Node setup
is required. To run the full checker without producing the final site image:

```sh
docker build \
  --target checker \
  --secret id=docs_env,src=.env \
  .
```

This includes the intentionally heavy 24-hour cross-venue example. It finds a
recent Bitcoin Up/Down five-minute interval, resolves its CLOB IDs from
Polymarket metadata, downloads the dedicated market capture and the matching
HyperLiquid checkpoint/diffs, rebuilds both books, and renders the chart used by
the docs.

## Build the static site

The Dockerfile is deliberately multi-stage:

1. The Python `checker` stage queries all four ClickHouse databases, generates
   schema pages, downloads the configured raw samples, and executes every
   published example, including the 24-hour historical cross-venue chart.
2. Node.js builds the static Vocs site from that verified content.
3. The final `scratch` image contains only the static files.

Pass configuration as a BuildKit secret. It exists only for the Python command
and is not stored in an image layer:

```sh
docker build \
  --secret id=docs_env,src=.env \
  --output type=local,dest=./site \
  .
```

The exported `site/` directory is ready for any static web server.
