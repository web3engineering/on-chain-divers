-- OnchainDivers indexer example: https://onchaindivers.com
WITH
    (SELECT max(block_time) FROM pumpfun_token_creation) + INTERVAL 1 SECOND AS end_time,
    end_time - INTERVAL 30 DAY AS start_time,
    created AS
    (
        SELECT
            replaceAll(mint, '\0', '') AS mint,
            argMin(replaceAll(creator, '\0', ''), tuple(block_time, slot, tx_idx)) AS creator,
            min(block_time) AS created_at
        FROM pumpfun_token_creation
        PREWHERE block_time >= start_time AND block_time < end_time
        GROUP BY mint
    ),
    migrated AS
    (
        SELECT
            replaceAll(mint, '\0', '') AS mint,
            min(block_time) AS migrated_at
        FROM pfamm_migrations
        PREWHERE block_date_utc >= toDate(start_time) AND block_date_utc <= toDate(end_time)
        WHERE block_time >= start_time AND block_time < end_time
        GROUP BY mint
    )
SELECT
    creator,
    count() AS tokens_created,
    countIf(migrated_at IS NOT NULL) AS tokens_migrated,
    round(100 * tokens_migrated / tokens_created, 2) AS migration_rate_pct,
    min(created_at) AS first_creation,
    max(created_at) AS last_creation
FROM created
LEFT JOIN migrated USING (mint)
WHERE creator != ''
GROUP BY creator
HAVING tokens_created >= 2
ORDER BY tokens_migrated DESC, tokens_created DESC
LIMIT 100
