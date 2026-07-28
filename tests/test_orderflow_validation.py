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
    trades=[trade(0,0,100),trade(1,30,100.1)]
    engine=OrderflowValidationEngine();first=engine.validate(OBS,trades,AT+timedelta(minutes=30));second=engine.validate(OBS,list(reversed(trades)),AT+timedelta(minutes=30))
    assert first==second and first.outcome=="PRICE_SIDEWAYS"


def test_no_future_horizon_or_missing_baseline_is_invented():
    engine=OrderflowValidationEngine()
    assert engine.validate(OBS,[trade(1,5,101)],AT+timedelta(minutes=5)) is None
    value=engine.validate(OBS,[trade(0,0,100),trade(1,5,101),trade(2,30,90)],AT+timedelta(minutes=5))
    assert value and [item.minutes for item in value.horizons]==[5]


def test_validation_has_no_prediction_probability_or_confidence():
    value=OrderflowValidationEngine().validate(OBS,[trade(0,0,100),trade(1,30,101)],AT+timedelta(minutes=30)).to_dict()
    assert not ({"prediction","probability","confidence"}&value.keys())
