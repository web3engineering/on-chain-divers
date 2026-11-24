-- How far back each table goes today.
SELECT *
FROM
(
    SELECT 'sol_top_ups' AS table_name, min(block_date_utc) AS first_day,
           toTimeZone(max(block_time), 'UTC') AS last_row_utc
    FROM sol_top_ups
    UNION ALL
    SELECT 'token_transfers', min(block_date_utc), toTimeZone(max(block_time), 'UTC')
    FROM token_transfers
    UNION ALL
    SELECT 'indexer3_sol_top_ups', min(block_date_utc), toTimeZone(max(block_time), 'UTC')
    FROM indexer3_sol_top_ups
    UNION ALL
    SELECT 'indexer3_sol_fundings', min(block_date_utc), toTimeZone(max(block_time), 'UTC')
    FROM indexer3_sol_fundings
    UNION ALL
    SELECT 'indexer3_token_transfers', min(block_date_utc), toTimeZone(max(block_time), 'UTC')
    FROM indexer3_token_transfers
)
ORDER BY first_day DESC, table_name
