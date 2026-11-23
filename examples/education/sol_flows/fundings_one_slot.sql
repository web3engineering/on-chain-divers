-- Every funding row of the slot that holds the transaction above (tx_idx 292).
SELECT
    tx_idx,
    src_wallet,
    dst_wallet,
    src_decrease,
    dst_increase,
    src_pre_balance,
    dst_pre_balance
FROM indexer3_sol_fundings
WHERE slot = 470716085
ORDER BY tx_idx
