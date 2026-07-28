from datetime import datetime, timedelta, timezone

from src.models.market_data import Candle, Trade
from src.quality.framework import DataQualityFramework, QualityPolicy


def trade(trade_id: int = 1, *, future: bool = False) -> Trade:
    at = datetime.now(timezone.utc) + (timedelta(hours=1) if future else timedelta(minutes=-30))
    return Trade("BTCUSDT", 68_420, 0.25, at, trade_id, False)


def test_valid_batch_has_provenance_and_stable_input_hash() -> None:
    records = [trade()]
    first = DataQualityFramework().validate(records)
    second = DataQualityFramework().validate(records)
    assert first.quality_score == 100
    assert first.provenance_counts == {"BINANCE_PUBLIC": 1}
    assert first.input_hash == second.input_hash


def test_duplicate_records_are_rejected() -> None:
    record = trade()
    report = DataQualityFramework().validate([record, record])
    assert report.duplicate_records == 1
    assert "DUPLICATE_RECORD" in {issue.code for issue in report.issues}
    assert report.valid_records == 1


def test_future_timestamp_is_reported() -> None:
    report = DataQualityFramework().validate([trade(future=True)])
    assert "FUTURE_TIMESTAMP" in {issue.code for issue in report.issues}
    assert report.valid_records == 0


def test_open_candle_is_quality_warning_not_silent_error() -> None:
    start = datetime.now(timezone.utc) - timedelta(minutes=2)
    candle = Candle("BTCUSDT", "1m", start, start + timedelta(minutes=1), 100, 102, 99, 101, 2, 3, False)
    report = DataQualityFramework().validate([candle])
    assert "UNFINISHED_CANDLE" in {issue.code for issue in report.issues}
    assert report.valid_records == 1


def test_report_is_reproducible_with_explicit_as_of() -> None:
    as_of = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    record = Trade("BTCUSDT", 100, 1, as_of - timedelta(minutes=1), 7, False)
    first = DataQualityFramework().validate([record], as_of=as_of).to_dict()
    second = DataQualityFramework().validate([record], as_of=as_of).to_dict()
    assert first == second


def test_stale_record_remains_visible() -> None:
    as_of = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    record = Trade("BTCUSDT", 100, 1, as_of - timedelta(minutes=2), 8, False)
    report = DataQualityFramework(QualityPolicy(freshness_seconds=60)).validate([record], as_of=as_of)
    assert "STALE_RECORD" in {issue.code for issue in report.issues}


def test_candle_gap_is_detected() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle("BTCUSDT", "1m", start, start + timedelta(minutes=1), 100, 101, 99, 100, 1, 1),
        Candle("BTCUSDT", "1m", start + timedelta(minutes=2), start + timedelta(minutes=3), 100, 101, 99, 100, 1, 1),
    ]
    report = DataQualityFramework(QualityPolicy(freshness_seconds=10**9)).validate(candles, as_of=start + timedelta(minutes=3))
    assert "CANDLE_GAP" in {issue.code for issue in report.issues}
