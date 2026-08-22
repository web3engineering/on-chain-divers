-- Potential SWQoS (stake-weighted quality-of-service) tip endpoints, inferred
-- from a single DEX's swap transactions.
--
-- This is a TEMPLATE. The generator (generate_swqos_research.py) substitutes the
-- __TOKENS__ per source before executing it, because ClickHouse cannot bind a
-- table name as a query parameter:
--   __TABLE__        swap table, e.g. pumpfun_v2_swaps / pumpswap_all_swaps / meteora_swaps
--   __LANDED__       landed-flag expression: (failed = 0) when the table has a
--                    `failed` column, otherwise the literal 1
--   __MIN_SIGNERS__  distinct-signer floor for the screen
--   __MAX_MEDIAN__   maximum median (p50) tip, in lamports
--   __ONCHAINDIVERS__ OnchainDivers TPU tip account (force-included when active)
--
-- Every swap carries the transaction's top-level SOL transfers in
-- `top_level_transfers_json` (an array of {from, to, lamports}). SWQoS relays are
-- paid through such a top-level transfer, so a destination tipped by many
-- distinct signers with a modest median tip is a candidate relay endpoint.
--
-- Screen: more than __MIN_SIGNERS__ distinct signers in the last 4 days and a
-- median tip of at most __MAX_MEDIAN__ lamports. Additionally, known-provider
-- vanity accounts (NextBlock, LandX, Corvus) and the OnchainDivers TPU account are
-- force-included even when below the screen, so the page never looks like it
-- silently dropped a well-known provider; the generator flags those rows.
--
-- Per destination the query returns landed/failed transfer counts and a 7-bucket
-- tip-size histogram, computed separately for landed (__LANDED__ = 1) and failed
-- transactions. Tip buckets, in lamports:
--   [0,100k) [100k,500k) [500k,1M) [1M,2M) [2M,5M) [5M,10M) [10M,+inf)
WITH
    (SELECT max(block_time) FROM default.__TABLE__) AS window_end,
    window_end - INTERVAL 4 DAY AS window_start
SELECT
    dest,
    uniqExact(signer)                       AS signers,
    count()                                 AS transfers,
    countIf(landed = 1)                     AS success_count,
    countIf(landed = 0)                     AS failed_count,
    medianExact(lamports)                   AS median_lamports,
    quantileExact(0.95)(lamports)           AS p95_lamports,
    [
        countIf(landed = 1 AND bucket = 0),
        countIf(landed = 1 AND bucket = 1),
        countIf(landed = 1 AND bucket = 2),
        countIf(landed = 1 AND bucket = 3),
        countIf(landed = 1 AND bucket = 4),
        countIf(landed = 1 AND bucket = 5),
        countIf(landed = 1 AND bucket = 6)
    ]                                       AS success_histogram,
    [
        countIf(landed = 0 AND bucket = 0),
        countIf(landed = 0 AND bucket = 1),
        countIf(landed = 0 AND bucket = 2),
        countIf(landed = 0 AND bucket = 3),
        countIf(landed = 0 AND bucket = 4),
        countIf(landed = 0 AND bucket = 5),
        countIf(landed = 0 AND bucket = 6)
    ]                                       AS failed_histogram
FROM
(
    SELECT
        signing_wallet                                        AS signer,
        __LANDED__                                            AS landed,
        JSONExtractString(transfer, 'to')                     AS dest,
        toUInt64OrZero(JSONExtractString(transfer, 'lamports')) AS lamports,
        multiIf(
            lamports <   100000, 0,
            lamports <   500000, 1,
            lamports <  1000000, 2,
            lamports <  2000000, 3,
            lamports <  5000000, 4,
            lamports < 10000000, 5,
            6
        )                                                     AS bucket
    FROM default.__TABLE__
    ARRAY JOIN JSONExtractArrayRaw(top_level_transfers_json) AS transfer
    WHERE block_time >= window_start
      AND JSONExtractString(transfer, 'to') != ''
)
GROUP BY dest
HAVING (signers > __MIN_SIGNERS__ AND median_lamports <= __MAX_MEDIAN__)
    OR lower(dest) LIKE 'nextblock%'
    OR lower(dest) LIKE 'corvu%'
    OR lower(dest) LIKE 'landx%'
    OR dest = '__ONCHAINDIVERS__'
ORDER BY signers DESC
