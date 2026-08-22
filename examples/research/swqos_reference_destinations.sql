-- Which candidate SWQoS destinations were already receiving top-level transfers
-- roughly 30 days ago. Used to flag "new" providers: a candidate that qualifies
-- in the recent 4-day window but is absent here had no top-level transfer
-- activity 30 days ago.
--
-- The reference window is the 4-day span ending 30 days before the latest data,
-- and the candidate list is bound as a query parameter so the scan only has to
-- resolve the handful of addresses under test.
WITH
    (SELECT max(block_time) FROM default.pumpfun_v2_swaps) AS window_end,
    window_end - INTERVAL 34 DAY AS ref_start,
    window_end - INTERVAL 30 DAY AS ref_end
SELECT DISTINCT JSONExtractString(transfer, 'to') AS dest
FROM default.pumpfun_v2_swaps
ARRAY JOIN JSONExtractArrayRaw(top_level_transfers_json) AS transfer
WHERE block_time >= ref_start
  AND block_time < ref_end
  AND JSONExtractString(transfer, 'to') IN {destinations:Array(String)}
