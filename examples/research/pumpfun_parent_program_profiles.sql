-- OnchainDivers indexer research: https://onchaindivers.com
-- Return per-token parent-program buy counts for complete 128-slot windows.
-- The Python companion normalizes each token and computes Jensen-Shannon distance.
WITH
    (SELECT max(block_time) FROM pumpfun_token_creation) AS end_time,
    end_time - INTERVAL 24 HOUR AS start_time,
    (
        SELECT max(slot)
        FROM pumpfun_all_swaps
        PREWHERE block_time >= start_time AND block_time < end_time + INTERVAL 2 MINUTE
    ) AS max_observed_slot,
    creations AS
    (
        SELECT
            replaceAll(mint, '\0', '') AS mint,
            argMin(replaceAll(creator, '\0', ''), tuple(slot, tx_idx)) AS creator,
            argMin(trim(replaceAll(name, '\0', '')), tuple(slot, tx_idx)) AS name,
            argMin(trim(replaceAll(symbol, '\0', '')), tuple(slot, tx_idx)) AS symbol,
            min(slot) AS launch_slot,
            min(block_time) AS launched_at
        FROM pumpfun_token_creation
        PREWHERE block_time >= start_time AND block_time < end_time
        GROUP BY mint
    ),
    program_counts AS
    (
        SELECT
            creation.mint AS mint,
            creation.creator AS creator,
            creation.name AS name,
            creation.symbol AS symbol,
            creation.launch_slot AS launch_slot,
            creation.launched_at AS launched_at,
            if(empty(swap.parent_program), '<direct>', swap.parent_program) AS parent_program,
            uniqExact(replaceAll(swap.signature, '\0', '')) AS buys
        FROM pumpfun_all_swaps AS swap
        INNER JOIN creations AS creation
            ON replaceAll(swap.base_coin, '\0', '') = creation.mint
        PREWHERE swap.block_time >= start_time
            AND swap.block_time < end_time + INTERVAL 2 MINUTE
        WHERE swap.direction = 'buy'
            AND creation.launch_slot + 128 <= max_observed_slot
            AND swap.slot > creation.launch_slot
            AND swap.slot <= creation.launch_slot + 128
        GROUP BY
            creation.mint,
            creation.creator,
            creation.name,
            creation.symbol,
            creation.launch_slot,
            creation.launched_at,
            parent_program
    )
SELECT
    mint,
    creator,
    name,
    symbol,
    launch_slot,
    launched_at,
    parent_program,
    buys,
    sum(buys) OVER (PARTITION BY mint) AS total_buys
FROM program_counts
QUALIFY total_buys >= 48
ORDER BY mint, parent_program
