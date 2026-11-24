-- A top-up is not a once-in-a-lifetime event. This wallet is emptied and
-- refilled all day, and every refill from zero is a new row.
SELECT
    toTimeZone(block_time, 'UTC') AS block_time_utc,
    amount / 1e9 AS sol,
    src_wallet,
    signature
FROM sol_top_ups
WHERE block_date_utc = '2026-11-17'
  AND dst_wallet = '6gnVbP38GXVgseLGRTN52rhzfHsyfKzzSK1Z5SuykuQZ'
ORDER BY slot, tx_idx
