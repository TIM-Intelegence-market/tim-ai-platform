from datetime import datetime,timedelta,timezone
import pytest
from src.tim_v2.observation import Observation,ObservationRegistry
N=datetime(2026,7,28,tzinfo=timezone.utc)
def item():return Observation("observation_one","btc@1",N,N+timedelta(seconds=1),N+timedelta(seconds=2),"manifest:ref","dataset","a"*64)
def test_immutable_deterministic_observation():
 r=ObservationRegistry();x=item();assert r.register(x).manifest_sha256()==x.manifest_sha256();assert r.register(x)==x
def test_time_order_rejected():
 with pytest.raises(ValueError,match="OBSERVATION_TIME_ORDER_INVALID"):ObservationRegistry().register(Observation("observation_two","btc@1",N+timedelta(seconds=2),N,N,"ref","dataset","a"*64))
