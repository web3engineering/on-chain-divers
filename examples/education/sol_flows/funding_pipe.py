"""Walk SOL backwards from a Pump.fun creator through pass-through wallets."""

from ocd import query, show

CREATOR = "2x7XsuzUzWPsTHeoUgEtSbFXNVcKiPTu3mfqX4Kqx3sZ"  # launched a token on 2026-11-18

# One hop back: who filled this wallet when it was empty,
# and sent nearly everything they had?
HOP = """
SELECT
    slot,
    toTimeZone(block_time, 'UTC') AS block_time_utc,
    src_wallet,
    dst_wallet,
    dst_increase / 1e9 AS sol
FROM indexer3_sol_fundings
WHERE dst_wallet = %(wallet)s
  AND slot < %(before_slot)s
  AND dst_pre_balance = 0                        -- receiver was empty
  AND src_pre_balance - src_decrease < 3000000   -- sender kept under 0.003 SOL
  AND n_src = 1 AND n_dst = 1                    -- one sender, one receiver
ORDER BY slot DESC
LIMIT 1
"""

wallet, before_slot, hops = CREATOR, 470_740_000, []
while len(hops) < 12:
    rows = query(HOP, {"wallet": wallet, "before_slot": before_slot})
    if not rows:
        break
    hops.append({"hop": len(hops) + 1, **rows[0]})
    wallet, before_slot = rows[0]["src_wallet"], rows[0]["slot"]

show(hops)
