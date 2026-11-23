"""Exercise the published SQL against real transaction accounting fixtures.

SQLite runs the portable arithmetic and conditionals without a live service.
ClickHouse-specific syntax, Int128 conversion and live rows are additionally
checked by verify_examples.py during the Docker build.
"""

import json
import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / "examples/solana/fixtures/pumpswap_quote_flows.json").read_text()
)["cases"]
CHECKS = (
    "base_reserves_match", "quote_reserves_match",
    "lp_fee_math_matches", "user_fee_math_matches",
)


def query_row(row):
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.create_function("toInt128", 1, int)
        connection.create_function("if", 3, lambda condition, yes, no: yes if condition else no)
        connection.create_function("today", 0, lambda: 1)
        columns = ", ".join(f'"{column}"' for column in row)
        connection.execute(f"CREATE TABLE pumpswap_all_swaps ({columns})")
        placeholders = ", ".join("?" for _ in row)
        connection.execute(
            f"INSERT INTO pumpswap_all_swaps VALUES ({placeholders})", tuple(row.values())
        )
        sql = (ROOT / "examples/solana/pumpswap_reserve_checks.sql").read_text()
        return dict(connection.execute(sql.replace("PREWHERE", "WHERE")).fetchone())


class PumpSwapReserveChecksTests(unittest.TestCase):
    def test_real_transactions_cover_all_quote_flow_variants(self):
        for case in CASES:
            with self.subTest(case=case["case"]):
                result = query_row(case["row"])
                self.assertTrue(all(result[check] for check in CHECKS), result)

    def test_corrupted_values_fail_each_invariant(self):
        for direction in ("B", "S"):
            original = next(case["row"] for case in CASES if case["row"]["direction"] == direction)
            for column, check in (
                ("pool_base_token_reserves_after", "base_reserves_match"),
                ("pool_quote_token_reserves_after", "quote_reserves_match"),
                ("lp_fee", "lp_fee_math_matches"),
                ("user_quote_amount", "user_fee_math_matches"),
            ):
                with self.subTest(direction=direction, column=column):
                    row = dict(original)
                    row[column] += 1
                    self.assertFalse(query_row(row)[check])

    def test_raw_event_quote_amount_is_not_used_as_pool_flow(self):
        case = next(case for case in CASES if case["case"] == "ps_buy_exact_quote_in_v2")
        row = dict(case["row"])
        self.assertNotEqual(row["quote_token_amount"], row["pool_quote_amount"])
        row["pool_quote_amount"] = row["quote_token_amount"]
        result = query_row(row)
        self.assertFalse(result["quote_reserves_match"])
        self.assertFalse(result["lp_fee_math_matches"])


if __name__ == "__main__":
    unittest.main()
