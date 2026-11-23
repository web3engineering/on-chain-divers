-- Pump.fun creators of the last 24 hours whose wallets were topped up
-- by different senders, yet with the same transaction settings, amounts
-- within 5% of each other, and inside the same hour.
WITH
    creators AS
    (
        SELECT DISTINCT trim(BOTH '\0' FROM toString(creator)) AS wallet
        FROM pumpfun_token_creation
        WHERE block_time >= now() - INTERVAL 1 DAY
    )
SELECT
    toTimeZone(toStartOfHour(block_time), 'UTC') AS hour_utc,
    provided_gas_limit,
    provided_gas_fee,
    cu_limit_ix_index,
    cu_price_ix_index,
    round(min(amount) / 1e9, 4) AS min_sol,
    round(max(amount) / 1e9, 4) AS max_sol,
    uniqExact(dst_wallet) AS creators,
    uniqExact(src_wallet) AS senders,
    groupUniqArray(3)(dst_wallet) AS sample_creators
FROM sol_top_ups
WHERE block_date_utc >= today() - 1
  AND num_signatures = 1
  AND provided_gas_limit > 0
  AND dst_wallet IN (SELECT wallet FROM creators)
GROUP BY
    hour_utc,
    provided_gas_limit,
    provided_gas_fee,
    cu_limit_ix_index,
    cu_price_ix_index,
    floor(log(amount) / log(1.05)) -- one bucket = amounts within 5%
HAVING creators >= 4 AND senders = creators
ORDER BY creators DESC
LIMIT 10
