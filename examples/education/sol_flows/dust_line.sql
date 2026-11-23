-- The smallest balance changes recorded yesterday.
-- Both sit just above the line of 90,000,000 lamports.
SELECT
    min(src_decrease) AS smallest_loss,
    min(dst_increase) AS smallest_gain,
    count() AS funding_rows
FROM indexer3_sol_fundings
WHERE block_date_utc = today() - 1
