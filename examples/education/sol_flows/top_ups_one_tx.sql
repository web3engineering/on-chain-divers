-- One transaction that pays five wallets with five System Program transfers.
-- sol_top_ups keeps only the wallets whose balance was zero before.
SELECT
    dst_wallet,
    amount,
    src_wallet,
    JSONLength(top_level_transfers_json) AS transfers_in_tx,
    signature
FROM sol_top_ups
WHERE block_date_utc = '2026-11-17'
  AND signature = 'KfjE2rhYq66UuMjZhbgwB7rxXkwnbfH8dvPmNY1dxjv3Ngw2bgC4mHrLXdeX6BBoz82mcQtK9NyeXWKLwPRmACb'
