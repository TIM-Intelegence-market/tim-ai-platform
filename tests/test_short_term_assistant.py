from datetime import datetime, timezone

from src.assistant.short_term import ShortTermAssistant
from src.models.market_data import Observation, ObservationKind


def test_empty_short_term_report_explains_missing_data() -> None:
    report = ShortTermAssistant().explain([])
    assert report.mode == "OBSERVE"
    assert report.missing_evidence == ("market_observations",)


def test_conflicting_structure_is_visible() -> None:
    at = datetime.now(timezone.utc)
    items = [Observation(kind, "BTCUSDT", "1m", at, kind.value, 60, {}) for kind in (ObservationKind.BOS_BULLISH, ObservationKind.BOS_BEARISH)]
    report = ShortTermAssistant().explain(items)
    assert report.conflicts == ("bullish_and_bearish_structure_present",)
    assert "no signal" in report.limitation
