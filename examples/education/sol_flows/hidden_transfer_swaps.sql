-- The same transaction in the PumpSwap table. Slot and tx_idx identify it,
-- and this table has the signature. In this pool wSOL is the base token.
SELECT
    signing_wallet,
    if(direction = 'S', 'pays SOL into the pool', 'takes SOL out of the pool') AS what_it_does,
    base_token_amount / 1e9 AS sol,
    signature
FROM pumpswap_all_swaps
WHERE slot = 470716000
  AND tx_idx = 241
  AND base_token = 'So11111111111111111111111111111111111111112'
ORDER BY direction DESC
