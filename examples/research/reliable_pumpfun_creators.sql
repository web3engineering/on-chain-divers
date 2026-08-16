-- OnchainDivers indexer research: https://onchaindivers.com
-- Rank creators with at least five recent launches by the trade count of their
-- least-active launch, then estimate robust token highs from p95 swap prices.
WITH
    'So11111111111111111111111111111111111111112' AS wsol_mint,
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' AS usdc_mint,
    (SELECT max(block_time) FROM pumpfun_token_creation) AS end_time,
    end_time - INTERVAL 24 HOUR AS start_time,
    (
        SELECT max(slot)
        FROM pumpfun_all_swaps
        PREWHERE block_time >= start_time AND block_time < end_time + INTERVAL 1 MINUTE
    ) AS max_observed_slot,
    sol_usdc_samples AS
    (
        SELECT sol_usdc
        FROM
        (
            SELECT
                1000.0 * least(
                    toFloat64(quote_coin_amount) / base_coin_amount,
                    toFloat64(base_coin_amount) / quote_coin_amount
                ) AS sol_usdc,
                block_time,
                slot,
                tx_idx
            FROM meteora_swaps
            PREWHERE block_date >= toDate(start_time)
                AND block_date <= toDate(end_time)
            WHERE block_time >= start_time
                AND block_time < end_time
                AND base_coin_amount > 0
                AND quote_coin_amount > 0
                AND (
                    (
                        replaceAll(base_coin, '\0', '') = wsol_mint
                        AND replaceAll(quote_coin, '\0', '') = usdc_mint
                    )
                    OR
                    (
                        replaceAll(base_coin, '\0', '') = usdc_mint
                        AND replaceAll(quote_coin, '\0', '') = wsol_mint
                    )
                )
            ORDER BY block_time DESC, slot DESC, tx_idx DESC
            LIMIT 100
        )
        WHERE isFinite(sol_usdc) AND sol_usdc > 0
    ),
    sol_usdc_stats AS
    (
        SELECT
            quantileExact(0.5)(sol_usdc) AS sol_usdc_rate,
            count() AS sol_usdc_sample_count
        FROM sol_usdc_samples
    ),
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
    ),
    creator_stats AS
    (
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
    ),
    top_creators AS
    (
        SELECT *
        FROM creator_stats
        ORDER BY
            minimum_trades_first_100_slots DESC,
            average_trades_first_100_slots DESC,
            launches DESC,
            creator
        LIMIT 5
    ),
    selected_launches AS
    (
        SELECT launch.*
        FROM launches AS launch
        INNER JOIN top_creators USING (creator)
    ),
    migrations AS
    (
        SELECT
            replaceAll(mint, '\0', '') AS mint,
            min(block_time) AS migrated_at
        FROM pfamm_migrations
        PREWHERE block_date_utc >= toDate(start_time)
            AND block_date_utc <= toDate(end_time)
        WHERE block_time >= start_time AND block_time <= end_time
        GROUP BY mint
    ),
    selected_with_migration AS
    (
        SELECT
            launch.*,
            toUInt8(migration.mint != '') AS migrated,
            migration.migrated_at AS migrated_at
        FROM selected_launches AS launch
        LEFT JOIN migrations AS migration ON launch.mint = migration.mint
    ),
    pumpfun_prices AS
    (
        SELECT
            launch.mint AS mint,
            'pumpfun' AS source,
            1000000.0 * fx.sol_usdc_rate
                * toFloat64(swap.quote_coin_amount) / swap.base_coin_amount AS mcap_usd
        FROM pumpfun_all_swaps AS swap
        INNER JOIN selected_with_migration AS launch
            ON replaceAll(swap.base_coin, '\0', '') = launch.mint
        CROSS JOIN sol_usdc_stats AS fx
        PREWHERE swap.block_time >= start_time
            AND swap.block_time < end_time + INTERVAL 1 MINUTE
        WHERE swap.slot >= launch.launch_slot
            AND swap.base_coin_amount > 0
            AND swap.quote_coin_amount > 0
    ),
    pumpswap_prices AS
    (
        SELECT
            launch.mint AS mint,
            'pumpswap' AS source,
            1000000.0 * fx.sol_usdc_rate * swap.sol_per_token_raw AS mcap_usd
        FROM
        (
            SELECT
                block_time,
                if(
                    replaceAll(base_token, '\0', '') = wsol_mint,
                    replaceAll(quote_token, '\0', ''),
                    replaceAll(base_token, '\0', '')
                ) AS token_mint,
                if(
                    replaceAll(base_token, '\0', '') = wsol_mint,
                    toFloat64(base_token_amount) / quote_token_amount,
                    toFloat64(quote_token_amount) / base_token_amount
                ) AS sol_per_token_raw
            FROM pumpswap_all_swaps
            PREWHERE block_date_utc >= toDate(start_time)
                AND block_date_utc <= toDate(end_time)
            WHERE block_time < end_time + INTERVAL 1 MINUTE
                AND base_token_amount > 0
                AND quote_token_amount > 0
                AND (
                    replaceAll(base_token, '\0', '') = wsol_mint
                    OR replaceAll(quote_token, '\0', '') = wsol_mint
                )
        ) AS swap
        INNER JOIN selected_with_migration AS launch
            ON swap.token_mint = launch.mint AND launch.migrated = 1
        CROSS JOIN sol_usdc_stats AS fx
        WHERE swap.block_time >= launch.launched_at
    ),
    price_observations AS
    (
        SELECT * FROM pumpfun_prices
        UNION ALL
        SELECT * FROM pumpswap_prices
    ),
    token_mcaps AS
    (
        SELECT
            mint,
            quantileExact(0.95)(mcap_usd) AS p95_mcap_usd,
            count() AS price_observations,
            countIf(source = 'pumpfun') AS pumpfun_price_observations,
            countIf(source = 'pumpswap') AS pumpswap_price_observations
        FROM price_observations
        WHERE isFinite(mcap_usd) AND mcap_usd > 0
        GROUP BY mint
    )
SELECT
    creator.minimum_trades_first_100_slots,
    creator.average_trades_first_100_slots,
    creator.median_trades_first_100_slots,
    creator.maximum_trades_first_100_slots,
    creator.launches,
    creator.weakest_mint,
    creator.weakest_symbol,
    launch.creator AS creator_id,
    launch.mint AS mint,
    launch.name AS name,
    launch.symbol AS symbol,
    launch.launch_slot AS launch_slot,
    launch.launched_at AS launched_at,
    launch.trades AS trades,
    launch.migrated AS migrated,
    launch.migrated_at AS migrated_at,
    round(mcap.p95_mcap_usd, 2) AS p95_mcap_usd,
    mcap.price_observations,
    mcap.pumpfun_price_observations,
    mcap.pumpswap_price_observations,
    round(fx.sol_usdc_rate, 6) AS sol_usdc_rate,
    toUInt64(fx.sol_usdc_sample_count) AS sol_usdc_sample_count
FROM selected_with_migration AS launch
INNER JOIN top_creators AS creator USING (creator)
LEFT JOIN token_mcaps AS mcap USING (mint)
CROSS JOIN sol_usdc_stats AS fx
ORDER BY
    creator.minimum_trades_first_100_slots DESC,
    creator.average_trades_first_100_slots DESC,
    creator.launches DESC,
    launch.creator,
    launch.launched_at,
    launch.mint
