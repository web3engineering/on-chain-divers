-- Which candidate SWQoS destinations were already receiving top-level transfers
-- roughly 30 days ago on the same DEX. Used to flag "new" providers: a candidate
-- that qualifies in the recent 4-day window but is absent here had no top-level
-- transfer activity 30 days ago.
--
-- This is a TEMPLATE: the generator substitutes __TABLE__ with the swap table,
-- because ClickHouse cannot bind a table name as a query parameter. The candidate
-- list is bound as the {destinations:Array(String)} parameter so the scan only
-- has to resolve the handful of addresses under test.
--
-- The reference window is the 4-day span ending 30 days before the latest data.
WITH
    (SELECT max(block_time) FROM default.__TABLE__) AS window_end,
    window_end - INTERVAL 34 DAY AS ref_start,
    window_end - INTERVAL 30 DAY AS ref_end
SELECT DISTINCT JSONExtractString(transfer, 'to') AS dest
FROM default.__TABLE__
ARRAY JOIN JSONExtractArrayRaw(top_level_transfers_json) AS transfer
WHERE block_time >= ref_start
  AND block_time < ref_end
  AND JSONExtractString(transfer, 'to') IN {destinations:Array(String)}
