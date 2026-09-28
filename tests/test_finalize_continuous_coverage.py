from datetime import datetime, timezone

from scripts.continuous_coverage_campaign import parse_utc_minute


def test_sealed_campaign_time_parser_rejects_non_minute_boundaries() -> None:
    assert parse_utc_minute("2026-10-23T09:51:00Z") == datetime(2026, 10, 23, 9, 51, tzinfo=timezone.utc)
