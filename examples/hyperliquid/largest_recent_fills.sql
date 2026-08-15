-- OnchainDivers indexer example: https://onchaindivers.com
SELECT
    utc_fill_dttm,
    fill_id,
    wallet_address,
    coin,
    side,
    price,
    size,
    price * size AS notional,
    closed_pnl,
    fee,
    liquidation_user
FROM hyperliquid.raw_node_fills_by_block
PREWHERE utc_fill_dt >= today() - 1
ORDER BY notional DESC
LIMIT 100
