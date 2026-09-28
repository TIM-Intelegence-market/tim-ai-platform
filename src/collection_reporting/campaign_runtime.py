"""Opt-in integration seam; connector and safety probe are mandatory.

No live command/default connector. Sealing is journal integrity evidence only;
independent coverage/transport proof is required before research readiness.
"""
import json
import time
import uuid
from datetime import datetime, timezone

from .campaign_transport import pump
from .campaign_writer import CampaignWriter


async def collect_campaign(directory, limits, *, connector, health, segment_events=10000):
    writer = CampaignWriter(directory, segment_events=segment_events)
    connection_id = str(uuid.uuid4())
    start = time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    with writer.db:
        writer.db.execute('CREATE TABLE transport(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        writer.db.execute('INSERT INTO transport VALUES(?,?)',('session',json.dumps({
            'connection_id':connection_id,'started_at':started,'max_seconds':limits.max_seconds,
            'max_events':limits.max_events,'status':'OPEN'})))
    try:
        result = await pump(limits,connector=connector,record=writer.record,
                            rotate=writer.rotate,health=health,segment_events=segment_events)
        result.update(connection_id=connection_id,started_at=started,
                      ended_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-start)
        with writer.db:
            writer.db.execute('INSERT INTO transport VALUES(?,?)',('result',json.dumps(result,sort_keys=True)))
        sealed = writer.finalize(result,limits)
        return {**result,**sealed,'coverage_ready':False}
    except BaseException:
        writer.fail()
        raise
    finally:
        writer.close()
