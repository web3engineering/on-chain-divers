-- OnchainDivers indexer example: https://onchaindivers.com
-- Rank Robinhood Chain pools by decoded swaps in the latest complete hour.
WITH pool_activity AS
(
    SELECT
        'uniswap_v3' AS protocol,
        pool_address AS pool,
        count() AS trades,
        uniqExact(transaction_hash) AS transactions,
        min(block_timestamp) AS first_trade,
        max(block_timestamp) AS last_trade
    FROM robinhood.uniswap_v3_trades
    PREWHERE block_timestamp >= toStartOfHour(now()) - INTERVAL 1 HOUR
        AND block_timestamp < toStartOfHour(now())
    GROUP BY pool_address

    UNION ALL

    SELECT
        'uniswap_v4' AS protocol,
        pool_id AS pool,
        count() AS trades,
        uniqExact(transaction_hash) AS transactions,
        min(block_timestamp) AS first_trade,
        max(block_timestamp) AS last_trade
    FROM robinhood.uniswap_v4_trades
    PREWHERE block_timestamp >= toStartOfHour(now()) - INTERVAL 1 HOUR
        AND block_timestamp < toStartOfHour(now())
    GROUP BY pool_id
)
SELECT
    protocol,
    pool,
    trades,
    transactions,
    first_trade,
    last_trade
FROM pool_activity
ORDER BY trades DESC, protocol, pool
LIMIT 50
