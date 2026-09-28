from copy import deepcopy
import pytest
from src.collection_reporting.campaign import CampaignLimits, verify_segments


def rows():
    return [dict(index=i,connection_id='synthetic',verified=True,first_receipt=i*2+1,last_receipt=i*2+2,first_trade=100+i*2,last_trade=101+i*2,events=2,start_elapsed=i*300,end_elapsed=(i+1)*300) for i in range(2)]


def test_contiguous_chain_and_whole_campaign_limit():
    assert verify_segments(rows(),CampaignLimits(600,4))['events']==4
    with pytest.raises(ValueError):verify_segments(rows(),CampaignLimits(600,3))


@pytest.mark.parametrize('key,value',[('connection_id','reconnected'),('first_receipt',4),('first_trade',104),('start_elapsed',301),('verified',False),('end_elapsed',float('nan'))])
def test_discontinuity_never_becomes_verified_history(key,value):
    data=deepcopy(rows());data[1][key]=value
    with pytest.raises(ValueError):verify_segments(data,CampaignLimits(600,4))


def test_invalid_limits_and_empty_chain():
    with pytest.raises(ValueError):CampaignLimits(float('inf'),4)
    with pytest.raises(ValueError):verify_segments([],CampaignLimits(600,4))


def test_journal_evidence_binds_content_and_rejects_tamper(tmp_path):
    from tests.test_verified_collection import create, complete, raw
    from src.collection_reporting.campaign import inspect_closed_journal
    j=create(tmp_path);complete(j,[raw(100),raw(101)]);path=j.path;j.close()
    first=inspect_closed_journal(path)
    assert first==inspect_closed_journal(path)
    assert first['events']==2 and first['continuity_proven'] is False
    import sqlite3
    with sqlite3.connect(path) as db:db.execute("UPDATE receipts SET raw_payload='tampered' WHERE seq=1")
    with pytest.raises(ValueError):inspect_closed_journal(path)


def test_open_journal_cannot_attest_campaign(tmp_path):
    from tests.test_verified_collection import create
    from src.collection_reporting.campaign import inspect_closed_journal
    j=create(tmp_path);path=j.path;j.close()
    with pytest.raises(ValueError):inspect_closed_journal(path)
