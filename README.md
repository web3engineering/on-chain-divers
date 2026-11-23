# OnchainDivers indexer examples

This repository is a self-contained, executable guide to the
[OnchainDivers indexers](https://onchaindivers.com). It contains working examples for:

- structured ClickHouse data for Solana DEX activity and helper tables;
- structured ClickHouse data for Polymarket fills and metadata;
- structured ClickHouse data for HyperLiquid fills, orders, wallets and positions;
- structured ClickHouse data for Robinhood Chain tokens and Uniswap v3/v4 activity;
- the aggregate fees API;
- raw Polymarket and HyperLiquid order-book archive discovery, download and replay;
- a live ranking of Pump.fun creators with at least five launches by the
  first-100-slot trade count of their weakest launch, plus migration-aware p95
  market-cap distributions valued with a Meteora DLMM SOL/USDC rate; and
- a comparison of early Pump.fun parent-program composition for migrated and
  non-migrated launches; and
- a two-window wallet fingerprint monitor for transaction-builder changes that
  may warrant pausing a copytrading strategy.

The examples under [`examples/`](examples/) are the source programs. The docs
explain the same programs, and `scripts/verify_examples.py` executes them during
every strict documentation build. A schema change, undocumented table, broken
query, invalid API response or incorrect order-book reconstruction fails the
build.

## Published ClickHouse datasets

| Network | DEX or domain tables | Helper tables |
| --- | --- | --- |
| Solana | Pump.fun, PumpSwap, Raydium AMM/CPMM/CLMM/Launchpad, Meteora DLMM/DAMM v2/Dynamic Bonding, Jito | pools, liquidity events, limit orders, transfers, first funding, landing services, quote prices, enriched swaps, supply and token statistics |
| Polymarket | order fills | event and market metadata |
| HyperLiquid | raw fills and fulfilled orders | perpetual wallets, positions, DEX metadata and outcome market/question/deployer metadata |
| Robinhood Chain | Uniswap v3/v4 and launchpad creation/trading datasets, unified swaps | token metadata, launch parameters, quote prices, wallet funding relationships and transfer schema |

The exact live schemas and row counts are generated into the table-reference
pages. The generator intentionally uses a whitelist: a newly appearing table or
an undescribed published column stops the build until the documentation is
updated.

Column descriptions and per-table notes live in
`scripts/column_descriptions.yaml`; enriched views inherit their source-column
descriptions through YAML merges. Ordinary views are labeled as computed at
query time and do not report stored row counts. An empty published table
documents the schema without promising a historical backfill.

Generation includes storage engines and sorting keys so replacement and
aggregate-table behavior is visible. Optional first-non-default column dates
require historical scans and are disabled by default; set
`DOCS_INCLUDE_COLUMN_HISTORY=1` when running the generator to include them.
Query-time views omit optional record samples and their swap examples use a
date filter to bound the source scan.

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

## Build the static site

The Dockerfile is deliberately multi-stage:

1. The Python `checker` stage queries all four ClickHouse databases, generates
   schema pages, downloads the configured raw samples, and executes every
   published example.
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
