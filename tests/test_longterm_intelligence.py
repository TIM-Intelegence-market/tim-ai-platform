from datetime import datetime, timezone

from src.longterm.intelligence import LongTermIntelligence, LongTermSnapshot


def test_longterm_context_is_deterministic_and_descriptive() -> None:
    snapshot = LongTermSnapshot(datetime.now(timezone.utc), 57, 8, {"defi": 4, "l1": 10, "gaming": -2}, "MIXED", ("source:a",))
    context = LongTermIntelligence().evaluate(snapshot)
    assert context.market_cycle_context == "EXPANDING"
    assert context.dominance_context == "BTC_HIGH"
    assert context.sector_leaders == ("l1", "defi", "gaming")
    assert "not portfolio or trading advice" in context.limitation


def test_missing_longterm_evidence_is_explicit() -> None:
    context = LongTermIntelligence().evaluate(LongTermSnapshot(datetime.now(timezone.utc), None, None, {}, "UNKNOWN", ()))
    assert set(context.missing_evidence) == {"btc_dominance", "total_market_change_30d", "sector_changes_30d"}
