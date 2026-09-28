import asyncio
import pytest
from src.collection_reporting.campaign import CampaignLimits
from src.collection_reporting.campaign_transport import pump


def run_case(fail=False):
    calls=[]
    class Socket:
        async def __aenter__(self):calls.append('connect');return self
        async def __aexit__(self,*args):calls.append('close')
        async def recv(self):
            calls.append('recv')
            if fail:raise OSError('synthetic')
            return 'raw'
    async def health():return True
    async def record(raw,seq,elapsed):calls.append(('commit',seq));return True
    async def rotate(n,elapsed):calls.append(('rotate',n))
    result=asyncio.run(pump(CampaignLimits(600,3),connector=lambda *a,**k:Socket(),record=record,rotate=rotate,health=health,segment_events=2))
    return result,calls


def test_one_socket_rotates_without_extra_receive():
    result,calls=run_case()
    assert result['reason']=='MAX_EVENTS'
    assert calls==['connect','recv',('commit',1),'recv',('commit',2),('rotate',2),'recv',('commit',3),'close']
    assert result['journal_acceptance_proven'] is False


def test_disconnect_closes_without_reconnect():
    result,calls=run_case(True)
    assert result['status']=='SAFE_STOP'
    assert calls==['connect','recv','close']


@pytest.mark.parametrize('slow_callback', ['health', 'rotate'])
def test_callback_exhausting_campaign_budget_prevents_another_receive(slow_callback):
    calls=[]
    now=0
    health_calls=0

    class Socket:
        async def __aenter__(self):calls.append('connect');return self
        async def __aexit__(self,*args):calls.append('close')
        async def recv(self):calls.append('recv');return 'raw'

    async def health():
        nonlocal now,health_calls
        health_calls+=1
        if slow_callback=='health' and health_calls==2:
            now=10
        return True

    async def record(raw,seq,elapsed):calls.append(('commit',seq));return True

    async def rotate(total,elapsed):
        nonlocal now
        calls.append(('rotate',total))
        if slow_callback=='rotate':
            now=10

    result=asyncio.run(pump(CampaignLimits(10,2),connector=lambda *a,**k:Socket(),
        record=record,rotate=rotate,health=health,segment_events=1,clock=lambda:now))

    assert result['status']=='BOUNDED_STOP' and result['reason']=='DURATION'
    expected_received=0 if slow_callback=='health' else 1
    assert result['received']==expected_received
    assert calls.count('recv')==expected_received
    assert calls[-1]=='close'


def test_health_crossing_segment_boundary_rotates_before_receive():
    calls=[]
    now=0
    health_calls=0

    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def recv(self):calls.append('recv');return 'raw'

    async def health():
        nonlocal now,health_calls
        health_calls+=1
        if health_calls==3:
            now=300
        return True

    async def record(raw,seq,elapsed):return True
    async def rotate(total,elapsed):calls.append(('rotate',total,elapsed))

    result=asyncio.run(pump(CampaignLimits(600,2),connector=lambda *a,**k:Socket(),
        record=record,rotate=rotate,health=health,clock=lambda:now))

    assert result['reason']=='MAX_EVENTS'
    assert calls==['recv',('rotate',1,300),'recv']


def test_rotation_exhausting_segment_budget_stops_before_receive():
    calls=[]
    now=0

    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):calls.append('close')
        async def recv(self):calls.append('recv');return 'raw'

    async def health():return True
    async def record(raw,seq,elapsed):return True

    async def rotate(total,elapsed):
        nonlocal now
        now=300

    result=asyncio.run(pump(CampaignLimits(600,2),connector=lambda *a,**k:Socket(),
        record=record,rotate=rotate,health=health,segment_events=1,clock=lambda:now))

    assert result['status']=='SAFE_STOP'
    assert result['reason']=='ROTATION_AFTER_BOUNDARY'
    assert result['received']==1 and calls==['recv','close']
