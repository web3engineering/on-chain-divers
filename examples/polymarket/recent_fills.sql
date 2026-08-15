-- OnchainDivers indexer example: https://onchaindivers.com
SELECT
    block_timestamp,
    transaction_hash,
    wallet,
    asset,
    side,
    amount_token,
    amount_usdc,
    fee,
    is_maker
FROM polymarket.polymarket_order_filled_v3
PREWHERE block_timestamp >= now() - INTERVAL 1 DAY
ORDER BY block_timestamp DESC, block_number DESC, log_index DESC
LIMIT 100
