-- OnchainDivers indexer example: https://onchaindivers.com
-- Compare the latest decoded Uniswap v3 and v4 swaps on Robinhood Chain.
SELECT
    protocol,
    block_timestamp,
    transaction_hash,
    pool,
    sender,
    recipient,
    amount0_raw,
    amount1_raw,
    tick,
    sqrt_price_x96
FROM
(
    SELECT
        'uniswap_v3' AS protocol,
        block_timestamp,
        transaction_hash,
        pool_address AS pool,
        sender,
        toNullable(recipient) AS recipient,
        toString(amount0) AS amount0_raw,
        toString(amount1) AS amount1_raw,
        tick,
        toString(sqrt_price_x96) AS sqrt_price_x96
    FROM robinhood.uniswap_v3_trades
    PREWHERE block_timestamp >= now() - INTERVAL 1 HOUR
    ORDER BY block_number DESC, transaction_index DESC, log_index DESC
    LIMIT 50

    UNION ALL

    SELECT
        'uniswap_v4' AS protocol,
        block_timestamp,
        transaction_hash,
        pool_id AS pool,
        sender,
        CAST(NULL, 'Nullable(String)') AS recipient,
        toString(amount0) AS amount0_raw,
        toString(amount1) AS amount1_raw,
        tick,
        toString(sqrt_price_x96) AS sqrt_price_x96
    FROM robinhood.uniswap_v4_trades
    PREWHERE block_timestamp >= now() - INTERVAL 1 HOUR
    ORDER BY block_number DESC, transaction_index DESC, log_index DESC
    LIMIT 50
)
ORDER BY block_timestamp DESC
LIMIT 100
