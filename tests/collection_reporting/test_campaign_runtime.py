import asyncio
import sqlite3
import pytest
from src.collection_reporting.campaign import CampaignLimits
from src.collection_reporting.campaign_runtime import collect_campaign
from tests.test_verified_collection import raw


def test_integrated_writer_single_socket_and_persistent_transport(tmp_path):
    calls=[]
    class Socket:
        index=99
        async def __aenter__(self):calls.append('open');return self
        async def __aexit__(self,*args):calls.append('close')
        async def recv(self):self.index+=1;return raw(self.index)
    async def health():return True
    path=tmp_path/'campaign'
    result=asyncio.run(collect_campaign(path,CampaignLimits(600,3),connector=lambda *a,**k:Socket(),health=health,segment_events=2))
    assert calls==['open','close'] and result['events']==3 and result['coverage_ready'] is False
    with sqlite3.connect(path/'manifest.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM segments').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM transport').fetchone()[0]==2


def test_cancel_persists_safe_stop_and_closes_socket(tmp_path):
    closed=[]
    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):closed.append(True)
        async def recv(self):raise asyncio.CancelledError()
    async def health():return True
    path=tmp_path/'cancelled'
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect_campaign(path,CampaignLimits(600,3),connector=lambda *a,**k:Socket(),health=health))
    assert closed==[True]
    with sqlite3.connect(path/'manifest.sqlite3') as db:
        assert db.execute('SELECT value FROM state').fetchone()[0]=='SAFE_STOP'


@pytest.mark.parametrize('tamper',['segment','reason','elapsed'])
def test_independent_proof_rejects_changed_mapping(tmp_path,tamper):
    from src.collection_reporting.campaign_proof import inspect_campaign
    class Socket:
        i=99
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def recv(self):self.i+=1;return raw(self.i)
    async def health():return True
    path=tmp_path/'proof'
    asyncio.run(collect_campaign(path,CampaignLimits(600,3),connector=lambda *a,**k:Socket(),health=health,segment_events=2))
    assert inspect_campaign(path)['events']==3
    with sqlite3.connect(path/'manifest.sqlite3') as db:
        if tamper=='segment':db.execute('DELETE FROM segments WHERE idx=1')
        else:
            import json
            value=json.loads(db.execute("SELECT value FROM transport WHERE key='result'").fetchone()[0])
            value['reason' if tamper=='reason' else 'elapsed_seconds']='INVENTED' if tamper=='reason' else -1
            db.execute("UPDATE transport SET value=? WHERE key='result'",(json.dumps(value),))
    with pytest.raises(ValueError):inspect_campaign(path)
