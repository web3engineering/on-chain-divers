-- OnchainDivers indexer research: https://onchaindivers.com
-- Rank creators whose recent launches sustain >5 distinct buy transactions in
-- every slot of an eight-consecutive-slot streak within 128 slots of launch.
WITH
    (SELECT max(block_time) FROM pumpfun_token_creation) AS end_time,
    end_time - INTERVAL 24 HOUR AS start_time,
    (
        SELECT max(slot)
        FROM pumpfun_all_swaps
        PREWHERE block_time >= start_time AND block_time < end_time + INTERVAL 1 MINUTE
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
    slot_buys AS
    (
        SELECT
            creation.mint AS mint,
            creation.creator AS creator,
            creation.name AS name,
            creation.symbol AS symbol,
            creation.launch_slot AS launch_slot,
            creation.launched_at AS launched_at,
            swap.slot AS buy_slot,
            uniqExact(replaceAll(swap.signature, '\0', '')) AS buys
        FROM pumpfun_all_swaps AS swap
        INNER JOIN creations AS creation
            ON replaceAll(swap.base_coin, '\0', '') = creation.mint
        PREWHERE swap.block_time >= start_time
            AND swap.block_time < end_time + INTERVAL 1 MINUTE
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
            swap.slot
        HAVING buys > 5
    ),
    qualifying_launches AS
    (
        SELECT
            mint,
            creator,
            any(name) AS name,
            any(symbol) AS symbol,
            launch_slot,
            any(launched_at) AS launched_at,
            arraySort(groupArray(toUInt32(buy_slot - launch_slot))) AS hot_slot_offsets,
            arrayFirst(
                start -> arrayAll(
                    offset -> has(hot_slot_offsets, start + offset),
                    range(8)
                ),
                hot_slot_offsets
            ) AS streak_start_offset,
            min(buys) AS minimum_buys_per_slot,
            sum(buys) AS buys_in_hot_slots
        FROM slot_buys
        GROUP BY mint, creator, launch_slot
        HAVING arrayExists(
            start -> arrayAll(
                offset -> has(hot_slot_offsets, start + offset),
                range(8)
            ),
            hot_slot_offsets
        )
    ),
    creator_totals AS
    (
        SELECT creator, uniqExact(mint) AS launches
        FROM creations
        WHERE creator != '' AND launch_slot + 128 <= max_observed_slot
        GROUP BY creator
    )
SELECT
    qualified.creator AS creator,
    count() AS qualifying_launches,
    any(total.launches) AS total_launches,
    round(100 * qualifying_launches / total_launches, 2) AS qualification_rate_pct,
    min(qualified.minimum_buys_per_slot) AS minimum_buys_in_any_required_slot,
    sum(qualified.buys_in_hot_slots) AS qualifying_launch_buys,
    min(qualified.streak_start_offset) AS earliest_streak_start_offset,
    argMax(qualified.mint, qualified.buys_in_hot_slots) AS example_mint,
    argMax(qualified.symbol, qualified.buys_in_hot_slots) AS example_symbol
FROM qualifying_launches AS qualified
INNER JOIN creator_totals AS total USING (creator)
GROUP BY qualified.creator
ORDER BY
    qualifying_launches DESC,
    qualification_rate_pct DESC,
    qualifying_launch_buys DESC,
    qualified.creator
LIMIT 5
