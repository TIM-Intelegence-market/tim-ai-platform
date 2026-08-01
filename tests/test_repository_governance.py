from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest

from src.database.repository import _validate_candle_for_persistence,_validate_observation_for_persistence,_validate_observation_input_hash
from src.observation.engine import candle_input_hash
from src.models.market_data import Candle,Observation,ObservationKind


NOW=datetime(2026,7,20,12,tzinfo=timezone.utc)


def candle(*,timeframe="1m",future=False):
    opened=NOW+(timedelta(days=1) if future else -timedelta(minutes=1))
    return Candle("BTCUSDT",timeframe,opened,opened+timedelta(minutes=1),100,101,99,100,1,1)


def observation(**changes):
    values={"kind":ObservationKind.REJECTION,"symbol":"BTCUSDT","timeframe":"1m","observed_at":NOW-timedelta(minutes=1),"summary":"context","confidence":50,"evidence":{},"provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC","rule_id":"bronxc","rule_version":"1.0.0","input_hash":"a"*64,"observation_id":uuid4(),"created_at":NOW-timedelta(seconds=1)}
    values.update(changes);return Observation(**values)


@pytest.mark.parametrize("item",[candle(timeframe="99x"),candle(future=True)])
def test_candle_governance_rejects_invalid_timeframe_and_future(item):
    with pytest.raises(ValueError):_validate_candle_for_persistence(item,NOW)


@pytest.mark.parametrize("changes",[
    {"timeframe":"99x"},
    {"observed_at":NOW+timedelta(seconds=1)},
    {"provenance":"UNKNOWN_PROVENANCE"},
    {"rule_version":"999.999.999"},
    {"input_hash":"MANIPULATED_HASH"},
])
def test_observation_governance_rejects_original_audit_payloads(changes):
    with pytest.raises(ValueError):_validate_observation_for_persistence(observation(**changes),NOW)


def test_observation_hash_is_recomputed_from_persisted_candles():
    candles=[candle()];valid=observation(input_hash=candle_input_hash(candles))
    _validate_observation_input_hash(valid,candles)
    with pytest.raises(ValueError,match="does not match"):_validate_observation_input_hash(observation(input_hash="f"*64),candles)


def test_candle_close_boundary_allows_one_second_clock_skew_only():
    opened=NOW-timedelta(minutes=1)
    boundary=Candle("BTCUSDT","1m",opened,NOW+timedelta(milliseconds=15),100,101,99,100,1,1)
    _validate_candle_for_persistence(boundary,NOW)
    too_early=Candle("BTCUSDT","1m",opened,NOW+timedelta(seconds=2),100,101,99,100,1,1)
    with pytest.raises(ValueError,match="Future candle"):
        _validate_candle_for_persistence(too_early,NOW)
