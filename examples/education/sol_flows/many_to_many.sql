-- One transaction where three wallets lost SOL and two gained it.
-- The table pairs every sender with every receiver: 3 x 2 = 6 rows.
SELECT
    src_wallet,
    dst_wallet,
    src_decrease,
    dst_increase,
    n_src,
    n_dst
FROM indexer3_sol_fundings
WHERE slot = 470678384
  AND tx_idx = 709
ORDER BY dst_wallet, src_wallet
