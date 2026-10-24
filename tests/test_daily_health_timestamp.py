"""Keep the real Health snapshot timestamp when building qualification metrics."""
import copy
from datetime import UTC, date, datetime

import pytest

from src.v2_completion.campaign import daily_metrics


@pytest.mark.parametrize('health,expected', [
    ({'timestamp': '2026-10-21T00:31:00+00:00'}, '2026-10-21T00:31:00+00:00'),
    ({'generated_at_utc': '2026-10-21T00:30:00Z'}, '2026-10-21T00:30:00Z'),
    ({'generated_at_utc': '2026-10-21T00:30:00Z', 'timestamp': '2026-10-21T00:31:00Z'}, '2026-10-21T00:30:00Z'),
    ({'generated_at_utc': None, 'timestamp': '2026-10-21T00:31:00Z'}, '2026-10-21T00:31:00Z'),
    ({'status': 'RED', 'mode': 'OBSERVE', 'trading_actions': 0}, None),
    (None, None),
])
def test_daily_metrics_preserve_snapshot_time_without_mutating_health(health, expected):
    original = copy.deepcopy(health)
    result = daily_metrics(
        day=date(2026, 10, 20),
        window=(datetime(2026, 10, 20, 20, 34, tzinfo=UTC), datetime(2026, 10, 21, tzinfo=UTC)),
        coverage={'dimensions': {'date_partitions': [{'utc_date': '2026-10-20',
                  'coverage': 1.0, 'expected': 206, 'observed': 206, 'missing': 0}]},
                  'product_calculation': {'coverage': 1.0, 'missing_observations': 0},
                  'audit_agreement': True, 'data_manifest_hash': 'a' * 64, 'database_snapshot': 'test'},
        gaps=[], cases={'raw_complete_validation_rows': 417, 'quality_eligible_labels': 417,
                        'strict_independent_30m_windows': 6, 'required_independent_cases': 1000},
        health=health, security={'status': 'PASS'}, open_gap_incidents=0)
    assert result['runtime_status']['generated_at_utc'] == expected
    # Snapshot time is preserved even when it is on the next day, never replaced by window time.
    assert result['window_end_utc'] == '2026-10-21T00:00:00Z'
    assert health == original
    if health is not None:
        for key in ('status', 'mode', 'trading_actions'):
            assert result['runtime_status'][key] == health.get(key)
