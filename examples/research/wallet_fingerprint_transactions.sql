-- OnchainDivers indexer research: https://onchaindivers.com
-- Return a bounded, deterministic sample of transaction-construction features
-- for active Pump.fun wallets in two adjacent 24-hour windows.
WITH
    (SELECT max(block_time) FROM pumpfun_v2_swaps WHERE failed = 0) AS end_time,
    end_time - INTERVAL 24 HOUR AS recent_start,
    end_time - INTERVAL 48 HOUR AS start_time,
    transactions AS
    (
        SELECT
            if(block_time >= recent_start, 'recent', 'previous') AS period,
            replaceAll(signing_wallet, '\0', '') AS wallet,
            replaceAll(signature, '\0', '') AS signature,
            min(block_time) AS transaction_time,
            argMin(replaceAll(base_coin, '\0', ''), tuple(ix_idx, tx_idx)) AS mint,
            argMin(direction, tuple(ix_idx, tx_idx)) AS direction,
            argMin(instruction_type, tuple(ix_idx, tx_idx)) AS instruction_type,
            argMin(
                if(empty(parent_program), '<direct>', parent_program),
                tuple(ix_idx, tx_idx)
            ) AS parent_program,
            min(ix_idx) AS swap_ix_index,
            argMin(cu_price_ix_index, tuple(ix_idx, tx_idx)) AS cu_price_ix_index,
            argMin(cu_limit_ix_index, tuple(ix_idx, tx_idx)) AS cu_limit_ix_index,
            argMin(tip_index, tuple(ix_idx, tx_idx)) AS tip_index,
            max(provided_gas_fee) AS provided_gas_fee,
            max(provided_gas_limit) AS provided_gas_limit,
            max(consumed_gas) AS consumed_gas,
            argMin(replaceAll(fee_payer, '\0', ''), tuple(ix_idx, tx_idx)) AS fee_payer
        FROM pumpfun_v2_swaps
        PREWHERE block_date_utc >= toDate(start_time)
            AND block_date_utc <= toDate(end_time)
            AND failed = 0
        WHERE block_time >= start_time
            AND block_time < end_time
            AND signing_wallet != ''
            AND signature != ''
        GROUP BY period, wallet, signature
    ),
    eligible_wallets AS
    (
        SELECT
            wallet,
            countIf(period = 'previous') AS previous_transactions,
            countIf(period = 'recent') AS recent_transactions
        FROM transactions
        GROUP BY wallet
        HAVING previous_transactions >= 20 AND recent_transactions >= 20
        ORDER BY least(previous_transactions, recent_transactions) DESC, wallet
        LIMIT 250
    ),
    sampled AS
    (
        SELECT *
        FROM
        (
            SELECT
                transaction.*,
                eligible.previous_transactions,
                eligible.recent_transactions,
                row_number() OVER (
                    PARTITION BY transaction.wallet, transaction.period
                    ORDER BY sipHash64(transaction.signature)
                ) AS sample_rank
            FROM transactions AS transaction
            INNER JOIN eligible_wallets AS eligible USING (wallet)
        )
        WHERE sample_rank <= 500
    ),
    tips AS
    (
        SELECT
            replaceAll(signature, '\0', '') AS signature,
            sum(amount) AS tip_lamports,
            argMax(replaceAll(tip_account, '\0', ''), amount) AS tip_account
        FROM jito_tips
        PREWHERE block_date_utc >= toDate(start_time)
            AND block_date_utc <= toDate(end_time)
        WHERE block_time >= start_time AND block_time < end_time
        GROUP BY signature
    )
SELECT
    sample.period,
    sample.wallet,
    sample.previous_transactions,
    sample.recent_transactions,
    sample.transaction_time,
    sample.mint,
    sample.direction,
    sample.instruction_type,
    sample.parent_program,
    sample.swap_ix_index,
    sample.cu_price_ix_index,
    sample.cu_limit_ix_index,
    sample.tip_index,
    sample.provided_gas_fee,
    sample.provided_gas_limit,
    sample.consumed_gas,
    toUInt8(sample.fee_payer = sample.wallet) AS self_paid,
    if(
        tip.signature != '',
        'jito',
        if(sample.tip_index >= 0, 'other-indexed-tip', 'none')
    ) AS tip_route,
    toUInt64(if(tip.signature != '', tip.tip_lamports, 0)) AS tip_lamports,
    if(tip.signature != '', tip.tip_account, '') AS tip_account
FROM sampled AS sample
LEFT JOIN tips AS tip USING (signature)
ORDER BY sample.wallet, sample.period, sample.transaction_time, sample.signature
