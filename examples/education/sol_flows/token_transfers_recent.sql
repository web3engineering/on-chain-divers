-- The five largest USDC transfers of the last hour.
SELECT
    toTimeZone(block_time, 'UTC') AS block_time_utc,
    src_wallet,
    dst_wallet,
    amount / 1e6 AS usdc,
    flavour,
    signature
FROM token_transfers
WHERE block_date_utc >= today() - 1
  AND block_time >= now() - INTERVAL 1 HOUR
  AND mint = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' -- USDC
  AND src_wallet != dst_wallet
ORDER BY amount DESC
LIMIT 5
