-- Potential SWQoS (stake-weighted quality-of-service) tip endpoints, inferred
-- from Pump.fun v2 swap transactions.
--
-- Every Pump.fun v2 swap carries the transaction's top-level SOL transfers in
-- `top_level_transfers_json` (an array of {from, to, lamports}). SWQoS relays
-- are paid through such a top-level transfer, so a destination that is tipped by
-- a very large number of distinct signers, with modest amounts, is a candidate
-- relay endpoint.
--
-- Screen:
--   * more than 3,000 distinct signers tipped the destination in the last 4 days
--   * the 95th percentile tip is at most 10,000,000 lamports (0.01 SOL)
--
-- For each surviving destination the query returns success/failed transfer
-- counts and a 7-bucket tip-size histogram, computed separately for landed
-- (failed = 0) and failed (failed = 1) transactions. Tip buckets, in lamports:
--   [0, 100k) [100k, 500k) [500k, 1M) [1M, 2M) [2M, 5M) [5M, 10M) [10M, +inf)
WITH
    (SELECT max(block_time) FROM default.pumpfun_v2_swaps) AS window_end,
    window_end - INTERVAL 4 DAY AS window_start
SELECT
    dest,
    uniqExact(signer)                       AS signers,
    count()                                 AS transfers,
    countIf(failed = 0)                     AS success_count,
    countIf(failed = 1)                     AS failed_count,
    quantileExact(0.95)(lamports)           AS p95_lamports,
    medianExact(lamports)                   AS median_lamports,
    [
        countIf(failed = 0 AND bucket = 0),
        countIf(failed = 0 AND bucket = 1),
        countIf(failed = 0 AND bucket = 2),
        countIf(failed = 0 AND bucket = 3),
        countIf(failed = 0 AND bucket = 4),
        countIf(failed = 0 AND bucket = 5),
        countIf(failed = 0 AND bucket = 6)
    ]                                       AS success_histogram,
    [
        countIf(failed = 1 AND bucket = 0),
        countIf(failed = 1 AND bucket = 1),
        countIf(failed = 1 AND bucket = 2),
        countIf(failed = 1 AND bucket = 3),
        countIf(failed = 1 AND bucket = 4),
        countIf(failed = 1 AND bucket = 5),
        countIf(failed = 1 AND bucket = 6)
    ]                                       AS failed_histogram
FROM
(
    SELECT
        signing_wallet                                        AS signer,
        failed,
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
    FROM default.pumpfun_v2_swaps
    ARRAY JOIN JSONExtractArrayRaw(top_level_transfers_json) AS transfer
    WHERE block_time >= window_start
      AND JSONExtractString(transfer, 'to') != ''
)
GROUP BY dest
HAVING signers > 3000 AND p95_lamports <= 10000000
ORDER BY signers DESC
