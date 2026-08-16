-- OnchainDivers indexer research: https://onchaindivers.com
-- Rank creators with at least five recent launches by the trade count of their
-- least-active launch during its first 100 post-launch slots.
WITH
    (SELECT max(block_time) FROM pumpfun_token_creation) AS end_time,
    end_time - INTERVAL 24 HOUR AS start_time,
    (
        SELECT max(slot)
        FROM pumpfun_all_swaps
        PREWHERE block_time >= start_time AND block_time < end_time + INTERVAL 1 MINUTE
    ) AS max_observed_slot,
    complete_creations AS
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
        HAVING creator != '' AND launch_slot + 100 <= max_observed_slot
    ),
    trade_counts AS
    (
        SELECT
            creation.mint AS mint,
            uniqExact(replaceAll(swap.signature, '\0', '')) AS trades
        FROM pumpfun_all_swaps AS swap
        INNER JOIN complete_creations AS creation
            ON replaceAll(swap.base_coin, '\0', '') = creation.mint
        PREWHERE swap.block_time >= start_time
            AND swap.block_time < end_time + INTERVAL 1 MINUTE
        WHERE swap.slot > creation.launch_slot
            AND swap.slot <= creation.launch_slot + 100
        GROUP BY creation.mint
    ),
    launches AS
    (
        SELECT
            creation.mint AS mint,
            creation.creator AS creator,
            creation.name AS name,
            creation.symbol AS symbol,
            creation.launch_slot AS launch_slot,
            creation.launched_at AS launched_at,
            toUInt64(ifNull(trade_counts.trades, 0)) AS trades
        FROM complete_creations AS creation
        LEFT JOIN trade_counts USING (mint)
    )
SELECT
    creator,
    count() AS launches,
    min(trades) AS minimum_trades_first_100_slots,
    round(avg(trades), 2) AS average_trades_first_100_slots,
    quantileExact(0.5)(trades) AS median_trades_first_100_slots,
    max(trades) AS maximum_trades_first_100_slots,
    argMin(mint, tuple(trades, mint)) AS weakest_mint,
    argMin(symbol, tuple(trades, mint)) AS weakest_symbol
FROM launches
GROUP BY creator
HAVING launches >= 5
ORDER BY
    minimum_trades_first_100_slots DESC,
    average_trades_first_100_slots DESC,
    launches DESC,
    creator
LIMIT 5
