-- 9.65 SOL moves from one wallet to another, yet no instruction says
-- "transfer SOL to that wallet". The only top-level transfer goes elsewhere.
SELECT
    src_wallet,
    dst_wallet,
    src_decrease / 1e9 AS sol_lost,
    dst_increase / 1e9 AS sol_gained,
    JSONExtractString(top_level_transfers_json, 1, 'to') AS only_transfer_goes_to
FROM indexer3_sol_fundings
WHERE slot = 470716000
  AND tx_idx = 241
