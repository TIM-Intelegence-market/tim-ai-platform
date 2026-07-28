from datetime import datetime,timezone
import pytest
from src.tim_v2.features import FeatureDefinition,FeatureRegistry,FeatureValidity
NOW=datetime(2026,7,28,tzinfo=timezone.utc)
def feature(deps=()):return FeatureDefinition("spread","1.0.0","ask-bid","btc@1",("ask","bid"),"event_time","pure",deps,"code","a"*64,True,"past_only","complete","low","owner",FeatureValidity(NOW,NOW))
def test_contract_is_deterministic_and_immutable():
    registry=FeatureRegistry();value=feature();assert registry.register(value).manifest_sha256()==value.manifest_sha256();assert registry.register(value)==value
def test_missing_dependency_and_lookahead_are_rejected():
    with pytest.raises(ValueError,match="FEATURE_DEPENDENCY_NOT_FOUND"):FeatureRegistry().register(feature(("missing@1",)))
    with pytest.raises(ValueError,match="FEATURE_LOOKAHEAD_REQUIRED"):FeatureRegistry().register(FeatureDefinition(**{**feature().__dict__,"lookahead_policy":""}))
