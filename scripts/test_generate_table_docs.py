"""Regression checks for timestamp selection in live schema documentation."""

import unittest

from generate_table_docs import _is_temporal_type, find_time_column, get_date_range


class TimestampSelectionTests(unittest.TestCase):
    def test_scalar_dates_and_wrappers(self):
        for column_type in (
            "Date", "Date32", "DateTime('UTC')", "DateTime64(6, 'UTC')",
            "Nullable(DateTime64(3))", "LowCardinality(Nullable(Date))",
            "SimpleAggregateFunction(min, DateTime('UTC'))",
        ):
            with self.subTest(column_type=column_type):
                self.assertTrue(_is_temporal_type(column_type))

    def test_dates_inside_containers_are_not_timestamps(self):
        for column_type in (
            "Tuple(price_usd Float64, hour DateTime('UTC'))",
            "SimpleAggregateFunction(max, Tuple(price_usd Float64, hour DateTime('UTC')))",
            "Array(DateTime)", "Map(String, Date)", "AggregateFunction(min, DateTime)",
        ):
            with self.subTest(column_type=column_type):
                self.assertFalse(_is_temporal_type(column_type))

    def test_token_stats_uses_scalar_hour_instead_of_ath_tuple(self):
        self.assertEqual(find_time_column([
            {"name": "ath", "type": "SimpleAggregateFunction(max, Tuple(price_usd Float64, mcap_usd Float64, hour DateTime('UTC')))"},
            {"name": "first_hour", "type": "SimpleAggregateFunction(min, DateTime('UTC'))"},
            {"name": "last_hour", "type": "SimpleAggregateFunction(max, DateTime('UTC'))"},
        ]), ("first_hour", False))

    def test_container_only_schema_has_no_timestamp(self):
        self.assertIsNone(find_time_column([
            {"name": "observations", "type": "Array(DateTime)"},
        ]))

    def test_aggregate_coverage_uses_both_hour_bounds(self):
        class Accessor:
            def query(self, sql, settings=None):
                self.sql = sql
                return [{"first_record": "2026-10-01", "last_record": "2026-10-26"}]

        accessor = Accessor()
        result = get_date_range(accessor, "solana_token_stats", [
            {"name": "first_hour", "type": "SimpleAggregateFunction(min, DateTime('UTC'))"},
            {"name": "last_hour", "type": "SimpleAggregateFunction(max, DateTime('UTC'))"},
        ])
        self.assertIn("MIN(first_hour)", accessor.sql)
        self.assertIn("MAX(last_hour)", accessor.sql)
        self.assertEqual(result["last_record"], "2026-10-26")


if __name__ == "__main__":
    unittest.main()
