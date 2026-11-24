-- OnchainDivers indexer example: https://onchaindivers.com
SELECT
    block_time,
    signature,
    direction,
    base_token,
    base_token_amount,
    quote_token_amount,
    pool_quote_amount,
    swap_quote_amount,
    user_quote_amount,
    fees_retained_in_pool,
    lp_fee,
    protocol_fee,
    virtual_quote_reserves,
    is_exact_quote,
    coin_creator,
    coin_creator_fees,
    cash_back_fees,
    buy_back_fees,
    pool_base_token_reserves_before,
    pool_quote_token_reserves_before,
    pool_base_token_reserves_after,
    pool_quote_token_reserves_after,
    if(
        direction = 'B',
        toInt128(pool_base_token_reserves_before) - toInt128(pool_base_token_reserves_after),
        toInt128(pool_base_token_reserves_after) - toInt128(pool_base_token_reserves_before)
    ) = toInt128(base_token_amount) AS base_reserves_match,
    if(
        direction = 'B',
        toInt128(pool_quote_token_reserves_after) - toInt128(pool_quote_token_reserves_before),
        toInt128(pool_quote_token_reserves_before) - toInt128(pool_quote_token_reserves_after)
    ) = toInt128(pool_quote_amount) AS quote_reserves_match,
    if(
        direction = 'B',
        toInt128(swap_quote_amount) + toInt128(lp_fee),
        toInt128(swap_quote_amount) - toInt128(lp_fee)
    ) = toInt128(pool_quote_amount) AS lp_fee_math_matches,
    if(
        direction = 'B',
        toInt128(swap_quote_amount) + toInt128(lp_fee) + toInt128(protocol_fee)
            + toInt128(coin_creator_fees) + toInt128(cash_back_fees),
        toInt128(swap_quote_amount) - toInt128(lp_fee) - toInt128(protocol_fee)
            - toInt128(coin_creator_fees) - toInt128(cash_back_fees)
    ) = toInt128(user_quote_amount) AS user_fee_math_matches
FROM pumpswap_all_swaps
PREWHERE block_date_utc >= today() - 1
ORDER BY slot DESC, tx_idx DESC
LIMIT 25
