-- Wallets that collect SOL from the early traders of several launches.
-- "Early" = behind one of the first 10 trades of a token launched in the last day.
WITH
    launches AS
    (
        SELECT trim(BOTH '\0' FROM toString(mint)) AS mint
        FROM pumpfun_token_creation
        WHERE block_time >= now() - INTERVAL 1 DAY
    ),
    early AS
    (
        SELECT s.base_coin AS mint, s.signing_wallet AS wallet, s.block_time AS traded_at
        FROM pumpfun_v2_swaps AS s
        INNER JOIN launches AS l ON l.mint = s.base_coin
        WHERE s.block_date_utc >= today() - 1
          AND s.failed = 0
        ORDER BY s.slot, s.tx_idx, s.ix_idx
        LIMIT 10 BY mint
    ),
    payouts AS
    (
        SELECT src_wallet, dst_wallet, block_time, dst_increase
        FROM indexer3_sol_fundings
        WHERE block_date_utc >= today() - 1
          AND n_src = 1 AND n_dst = 1
          AND src_wallet GLOBAL IN (SELECT wallet FROM early)
    )
SELECT
    p.dst_wallet AS sink,
    uniqExact(e.mint) AS launches,
    uniqExact(e.wallet) AS early_wallets,
    round(sum(p.dst_increase) / 1e9, 1) AS sol_received,
    groupUniqArray(2)(e.mint) AS sample_tokens
FROM early AS e
INNER JOIN payouts AS p ON p.src_wallet = e.wallet
WHERE p.block_time >= e.traded_at
  AND p.dst_wallet NOT IN (SELECT wallet FROM early)
GROUP BY sink
HAVING launches >= 3 AND early_wallets >= 5
ORDER BY early_wallets DESC
LIMIT 10
