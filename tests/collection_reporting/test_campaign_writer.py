import asyncio
import sqlite3
import pytest
from src.collection_reporting.campaign_writer import CampaignWriter
from tests.test_verified_collection import raw


def test_sealed_segment_and_mapping_survive_close(tmp_path):
    directory=tmp_path/'campaign';w=CampaignWriter(directory,segment_events=2)
    async def write():
        assert await w.record(raw(100),1,0)
        assert await w.record(raw(101),2,1)
        await w.rotate(2,1)
    asyncio.run(write());w.close()
    with sqlite3.connect(directory/'manifest.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM mapping').fetchone()[0]==2
        assert db.execute('SELECT first_receipt,last_receipt FROM segments').fetchone()==(1,2)
        assert db.execute('SELECT value FROM state').fetchone()[0]=='OPEN'
    with pytest.raises(FileExistsError):CampaignWriter(directory)


def test_out_of_sequence_receipt_cannot_be_mapped(tmp_path):
    w=CampaignWriter(tmp_path/'campaign')
    try:
        with pytest.raises(ValueError):asyncio.run(w.record(raw(100),2,0))
        assert w.db.execute('SELECT count(*) FROM mapping').fetchone()[0]==0
    finally:w.close()


def test_finalization_validates_cross_segment_ids_and_persists_failure(tmp_path):
    from src.collection_reporting.campaign import CampaignLimits
    for suffix,next_id in [('good',102),('gap',103)]:
        w=CampaignWriter(tmp_path/suffix,segment_events=2)
        async def write():
            await w.record(raw(100),1,0);await w.record(raw(101),2,1)
            await w.rotate(2,1);await w.record(raw(next_id),3,2)
        asyncio.run(write())
        result=dict(status='BOUNDED_STOP',received=3,reconnections=0,live_trading=False,reason='MAX_EVENTS')
        if suffix=='good':
            assert w.finalize(result,CampaignLimits(600,3))['continuity_proven'] is False
        else:
            with pytest.raises(ValueError):w.finalize(result,CampaignLimits(600,3))
            assert w.db.execute('SELECT value FROM state').fetchone()[0]=='SAFE_STOP'
        w.close()


def test_transport_failure_cannot_seal(tmp_path):
    from src.collection_reporting.campaign import CampaignLimits
    w=CampaignWriter(tmp_path/'failed')
    with pytest.raises(ValueError):w.finalize({'status':'SAFE_STOP'},CampaignLimits(600,3))
    assert w.db.execute('SELECT value FROM state').fetchone()[0]=='SAFE_STOP'
    w.close()


@pytest.mark.parametrize('missing_segment', [0, 1])
def test_finalization_rejects_missing_segment_evidence(tmp_path, missing_segment):
    from src.collection_reporting.campaign import CampaignLimits
    w=CampaignWriter(tmp_path/'incomplete',segment_events=2)
    try:
        async def write():
            for receipt in range(1,5):
                assert await w.record(raw(99+receipt),receipt,receipt-1)
                if receipt%2==0:
                    await w.rotate(receipt,receipt-1)
        asyncio.run(write())
        with w.db:
            w.db.execute('DELETE FROM segments WHERE idx=?',(missing_segment,))
        result=dict(status='BOUNDED_STOP',received=4,reconnections=0,
                    live_trading=False,reason='MAX_EVENTS')

        with pytest.raises(ValueError,match='segment (chain|coverage) gap'):
            w.finalize(result,CampaignLimits(600,4))
        assert w.db.execute('SELECT value FROM state').fetchone()[0]=='SAFE_STOP'
    finally:
        w.close()


@pytest.mark.parametrize('span', [300, 300.001])
def test_finalization_enforces_segment_receipt_span(tmp_path, span):
    from src.collection_reporting.campaign import CampaignLimits
    w=CampaignWriter(tmp_path/'timed',segment_events=2)
    try:
        async def write():
            assert await w.record(raw(100),1,0)
            assert await w.record(raw(101),2,span)
        asyncio.run(write())
        result=dict(status='BOUNDED_STOP',received=2,reconnections=0,
                    live_trading=False,reason='MAX_EVENTS')

        if span==300:
            assert w.finalize(result,CampaignLimits(600,2))['continuity_proven'] is False
        else:
            with pytest.raises(ValueError,match='segment receipt span outside contract'):
                w.finalize(result,CampaignLimits(600,2))
            assert w.db.execute('SELECT value FROM state').fetchone()[0]=='SAFE_STOP'
    finally:
        w.close()


def test_stale_receipt_is_persisted_and_stops_campaign(tmp_path,monkeypatch):
    monkeypatch.setattr('src.collection_reporting.campaign_writer.utc',lambda:'2026-09-06T12:00:31+00:00')
    w=CampaignWriter(tmp_path/'stale')
    try:
        assert asyncio.run(w.record(raw(100),1,0)) is False
        assert w.db.execute('SELECT count(*) FROM mapping').fetchone()[0]==1
        assert w.journal.db.execute('SELECT count(*) FROM receipts').fetchone()[0]==1
        assert w.db.execute('SELECT value FROM state').fetchone()[0]=='SAFE_STOP'
    finally:w.close()
