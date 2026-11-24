-- Last 1,000 Pump.fun launches quoted in SOL.
-- x: how long before the launch the creator wallet was last topped up from zero.
-- y: how many different wallets bought in the first minute.
WITH
    launches AS
    (
        SELECT
            trim(BOTH '\0' FROM toString(mint)) AS mint,
            trim(BOTH '\0' FROM toString(creator)) AS creator,
            block_time AS launched_at
        FROM pumpfun_token_creation
        WHERE quote_coin = '11111111111111111111111111111111' -- SOL
          AND block_time < now() - INTERVAL 2 MINUTE
        ORDER BY slot DESC, tx_idx DESC
        LIMIT 1000
    ),
    top_ups AS
    (
        SELECT dst_wallet, block_time
        FROM sol_top_ups
        WHERE dst_wallet IN (SELECT creator FROM launches)
    ),
    buys AS
    (
        SELECT base_coin, signing_wallet, block_time
        FROM pumpfun_v2_swaps
        WHERE block_date_utc >= (SELECT toDate(min(launched_at)) FROM launches)
          AND failed = 0
          AND direction = 'buy'
          AND base_coin IN (SELECT mint FROM launches)
    ),
    per_launch AS
    (
        SELECT
            l.mint AS mint,
            dateDiff(
                'second',
                maxIf(t.block_time, t.block_time <= l.launched_at),
                any(l.launched_at)
            ) AS top_up_age,
            uniqExactIf(
                b.signing_wallet,
                b.block_time < l.launched_at + INTERVAL 1 MINUTE
            ) AS buyers
        FROM launches AS l
        LEFT JOIN top_ups AS t ON t.dst_wallet = l.creator
        LEFT JOIN buys AS b ON b.base_coin = l.mint
        GROUP BY l.mint
    )
SELECT
    -- no top-up found means the last one is older than the table (31 days)
    multiIf(top_up_age < 60, 1, top_up_age < 600, 2, top_up_age < 3600, 3,
            top_up_age < 21600, 4, top_up_age < 86400, 5,
            top_up_age < 31 * 86400, 6, 7) AS age_bucket,
    ['<1 min', '1-10 min', '10-60 min', '1-6 h', '6-24 h', '1-31 d', 'older'][age_bucket]
        AS topped_up_before_launch,
    multiIf(buyers <= 1, 1, buyers <= 3, 2, buyers <= 7, 3,
            buyers <= 15, 4, buyers <= 31, 5, 6) AS buyers_bucket,
    ['0-1', '2-3', '4-7', '8-15', '16-31', '32+'][buyers_bucket]
        AS buyers_in_first_minute,
    count() AS launches
FROM per_launch
GROUP BY age_bucket, buyers_bucket
ORDER BY age_bucket, buyers_bucket
