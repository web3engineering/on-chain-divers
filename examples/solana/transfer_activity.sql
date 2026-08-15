-- OnchainDivers indexer example: https://onchaindivers.com
WITH
    toStartOfHour(now()) AS end_hour,
    end_hour - INTERVAL 24 HOUR AS start_hour
SELECT
    hour,
    sum(token_transfers) AS token_transfers,
    sum(sol_top_ups) AS sol_top_ups
FROM
(
    SELECT
        toStartOfHour(block_time) AS hour,
        count() AS token_transfers,
        0 AS sol_top_ups
    FROM token_transfers
    PREWHERE block_time >= start_hour AND block_time < end_hour
    GROUP BY hour

    UNION ALL

    SELECT
        toStartOfHour(block_time) AS hour,
        0 AS token_transfers,
        count() AS sol_top_ups
    FROM sol_top_ups
    PREWHERE block_time >= start_hour AND block_time < end_hour
    GROUP BY hour
)
GROUP BY hour
ORDER BY hour
