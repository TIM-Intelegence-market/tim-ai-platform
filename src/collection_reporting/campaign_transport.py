"""Bounded single-connection pump; callers supply durable journal callbacks.

No default network connector or live entrypoint. Journal integration must prove
that record() commits receipt before returning, and rotation binds closed hashes.
"""
import asyncio
import time

from .campaign import CampaignLimits
from .verified_runtime import PUBLIC_ENDPOINT


async def pump(limits: CampaignLimits, *, connector, record, rotate, health,
               segment_events=10000, clock=time.monotonic):
    if type(segment_events) is not int or not 1 <= segment_events <= 10000:
        raise ValueError('invalid segment event limit')
    if not await health():
        return {'status':'SAFE_STOP','reason':'HEALTH','received':0}
    received = segment_count = 0
    start = clock()
    boundary = start
    status, reason = 'SAFE_STOP', 'INTERRUPTED'
    try:
        async with connector(PUBLIC_ENDPOINT, proxy=None, max_queue=1, max_size=16384,
                             open_timeout=15, close_timeout=5) as socket:
            while received < limits.max_events:
                now = clock()
                if now-start >= limits.max_seconds:
                    status, reason = 'BOUNDED_STOP', 'DURATION'
                    break
                if not await health():
                    reason = 'HEALTH'
                    break
                # Awaited callbacks consume the same budget as receives.
                now = clock()
                if now-start >= limits.max_seconds:
                    status, reason = 'BOUNDED_STOP', 'DURATION'
                    break
                if segment_count == segment_events or now-boundary >= 300:
                    await rotate(received, now-start)
                    boundary, segment_count = now, 0
                    now = clock()
                    if now-start >= limits.max_seconds:
                        status, reason = 'BOUNDED_STOP', 'DURATION'
                        break
                    if now-boundary >= 300:
                        reason = 'ROTATION_AFTER_BOUNDARY'
                        break
                remaining = min(limits.max_seconds-(now-start), 300-(now-boundary), 30)
                try:
                    raw = await asyncio.wait_for(socket.recv(), remaining)
                except TimeoutError:
                    now = clock()
                    if now-start >= limits.max_seconds:
                        status, reason = 'BOUNDED_STOP', 'DURATION'
                    elif now-boundary >= 300:
                        continue
                    else:
                        reason = 'SOURCE_IDLE'
                    if now-boundary >= 300 and now-start < limits.max_seconds:
                        continue
                    break
                received += 1
                # Callback sees every returned frame including rejected payloads.
                # Crossing a deadline during recv cannot silently discard a frame.
                receipt_time = clock()
                accepted = await record(raw, received, receipt_time-start)
                segment_count += 1
                if receipt_time-start > limits.max_seconds or receipt_time-boundary > 300:
                    reason = 'RECEIPT_AFTER_BOUNDARY'
                    break
                if not accepted:
                    reason = 'RECEIPT_REJECTED'
                    break
            else:
                status, reason = 'BOUNDED_STOP', 'MAX_EVENTS'
    except asyncio.CancelledError:
        raise
    except Exception:
        reason = 'TRANSPORT_OR_JOURNAL_FAILURE'
    return {'status':status,'reason':reason,'received':received,'reconnections':0,
            'live_trading':False,'journal_acceptance_proven':False}
