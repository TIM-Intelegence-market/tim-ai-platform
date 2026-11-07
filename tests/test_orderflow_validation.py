from datetime import datetime,timedelta,timezone

from src.models.market_data import Trade
from src.orderflow.validation import OrderflowValidationEngine
from src.research.case_engine import ResearchCase


AT=datetime(2026,7,22,12,tzinfo=timezone.utc)
OBS={"observation_id":"ofobs_test","symbol":"BTCUSDT","observed_at":AT.isoformat(),"input_hash":"a"*64}


def trade(i,minutes,price,qty=1,maker=False):return Trade("BTCUSDT",price,qty,AT+timedelta(minutes=minutes),i,maker)


def test_partial_then_complete_validation_and_case_closure():
    trades=[trade(0,0,100),trade(1,5,101,2,False),trade(2,15,99,1,True),trade(3,30,99.5,3,True)]
    engine=OrderflowValidationEngine();partial=engine.validate(OBS,trades,AT+timedelta(minutes=15))
    assert partial and [item.minutes for item in partial.horizons]==[5,15] and not partial.complete and partial.outcome is None
    complete=engine.validate(OBS,trades,AT+timedelta(minutes=30))
    assert complete and complete.complete and complete.outcome=="PRICE_DECREASED"
    case=ResearchCase("ofcase_test","BTCUSDT","60s",AT,AT,missing_evidence=["subsequent_orderflow_context"])
    engine.apply_to_case(complete,case)
    assert case.status=="CLOSED" and case.outcome=="PRICE_DECREASED" and case.missing_evidence==[]


def test_sideways_threshold_is_explicit_and_replay_stable():
    trades=[trade(0,0,100),trade(1,5,100),trade(2,15,100),trade(3,30,100.1)]
    engine=OrderflowValidationEngine();first=engine.validate(OBS,trades,AT+timedelta(minutes=30));second=engine.validate(OBS,list(reversed(trades)),AT+timedelta(minutes=30))
    assert first==second and first.outcome=="PRICE_SIDEWAYS"


def test_validation_never_marks_incomplete_horizons_or_source_gap_complete():
    engine=OrderflowValidationEngine()
    missing_horizons=engine.validate(
        OBS,
        [trade(0,0,100),trade(1,30,101)],
        AT+timedelta(minutes=30),
    )
    assert missing_horizons and not missing_horizons.complete and missing_horizons.outcome is None
    source_gap=engine.validate(
        OBS,
        [trade(0,0,100),trade(1,5,100),trade(3,15,100),trade(4,30,101)],
        AT+timedelta(minutes=30),
    )
    assert source_gap and not source_gap.complete and source_gap.outcome is None


def test_no_future_horizon_or_missing_baseline_is_invented():
    engine=OrderflowValidationEngine()
    assert engine.validate(OBS,[trade(1,5,101)],AT+timedelta(minutes=5)) is None
    value=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,30,90)],AT+timedelta(minutes=5))
    assert value and [item.minutes for item in value.horizons]==[5]


def test_future_rows_cannot_change_a_validation_at_the_cutoff():
    engine=OrderflowValidationEngine()
    at_cut=[trade(0,0,100),trade(1,5,101)]
    first=engine.validate(OBS,at_cut,AT+timedelta(minutes=5))
    replay=engine.validate(OBS,at_cut+[trade(999,30,1)],AT+timedelta(minutes=5))
    assert first==replay


def test_validation_has_no_prediction_probability_or_confidence():
    value=OrderflowValidationEngine().validate(OBS,[trade(0,0,100),trade(1,30,101)],AT+timedelta(minutes=30)).to_dict()
    assert not ({"prediction","probability","confidence"}&value.keys())


def test_gap_after_the_last_loaded_trade_keeps_the_validation_incomplete():
    # Prüfung 06.11.2026: trades end before the 30-minute target (outage), nothing after it is loaded.
    # The pairwise ID check sees no gap, so the sequence must reach a trade at or after the target.
    engine=OrderflowValidationEngine()
    cut=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,20,110)],AT+timedelta(minutes=31))
    assert cut and [item.minutes for item in cut.horizons]==[5,15,30] and not cut.complete and cut.outcome is None
    # A later trade with contiguous ID proves the stream continued past the target: complete.
    proven=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,20,110),trade(4,31,111)],AT+timedelta(minutes=31))
    assert proven and proven.complete and proven.outcome=="PRICE_INCREASED" and proven.horizons[-1].price==110
    # A later trade with a missing ID in between shows the gap: still incomplete.
    gap=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,20,110),trade(6,31,111)],AT+timedelta(minutes=31))
    assert gap and not gap.complete


def test_gap_behind_the_target_does_not_block_a_complete_window():
    # Only trades up to the first one at or after the target count; a later gap is not a window gap.
    engine=OrderflowValidationEngine()
    value=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,20,110),trade(4,31,111),trade(9,40,120)],AT+timedelta(minutes=40))
    assert value and value.complete and value.outcome=="PRICE_INCREASED" and value.horizons[-1].price==110
    assert value.validated_through==AT+timedelta(minutes=30)


def test_unproven_target_keeps_the_observation_pending():
    # validated_through stays before the target, so the pending query returns the observation again.
    engine=OrderflowValidationEngine()
    cut=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,20,110)],AT+timedelta(minutes=30))
    assert cut and not cut.complete and cut.validated_through==AT+timedelta(minutes=20)
    exact=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,30,110)],AT+timedelta(minutes=30))
    assert exact and exact.complete and exact.validated_through==AT+timedelta(minutes=30)


def test_all_trades_in_the_target_millisecond_belong_to_the_window():
    # The cut happens after the first trade past the target; trades exactly at the target stay.
    engine=OrderflowValidationEngine()
    value=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,30,110),trade(4,30,120),trade(5,30,130),trade(6,31,99)],AT+timedelta(minutes=31))
    assert value and value.complete and value.horizons[-1].trade_count==5 and value.horizons[-1].price==130


def test_gap_proven_by_a_late_trade_closes_the_validation():
    # Outage after the target: the first later trade (ID 9) proves the gap; validated_through = target ends the retries.
    engine=OrderflowValidationEngine()
    value=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,15,102),trade(3,20,110),trade(9,45,120)],AT+timedelta(minutes=45))
    assert value and not value.complete and value.outcome is None and value.validated_through==AT+timedelta(minutes=30)
