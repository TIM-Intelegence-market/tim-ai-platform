"""One finite public WebSocket session. No retry loop, catch-up or trading."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Callable

import websockets

from .verified import CollectionStop, VerifiedJournal, utc

PUBLIC_ENDPOINT = "wss://stream.binance.com:443/ws/btcusdt@aggTrade"


async def consume_bounded(journal: VerifiedJournal, *, connector=websockets.connect,
                          health_probe: Callable | None = None) -> dict:
    application_received = 0
    start = time.monotonic()
    deadline = start + journal.contract["max_duration_seconds"]
    last_probe = start
    maximum_lag = 0.0
    journal.begin()
    try:
        async with connector(PUBLIC_ENDPOINT, proxy=None, open_timeout=15, close_timeout=5,
                             ping_interval=20, ping_timeout=20, max_queue=1, max_size=16384) as socket:
            while application_received < journal.contract["max_events"]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    journal.stop("DURATION")
                    break
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=min(remaining, 30))
                except TimeoutError:
                    journal.stop("DURATION" if time.monotonic() >= deadline else "SOURCE_IDLE_TIMEOUT",
                                 safe=time.monotonic() < deadline)
                    break
                application_received += 1
                at = utc()
                seq = journal.receive(raw, at)
                disposition = journal.classify(seq)
                receipt = journal.db.execute("SELECT source_timestamp FROM receipts WHERE seq=?", (seq,)).fetchone()
                if receipt[0] is not None:
                    lag = max(0.0, (datetime.fromisoformat(at) - datetime.fromisoformat(receipt[0])).total_seconds())
                    maximum_lag = max(maximum_lag, lag)
                    if lag > 30:
                        journal.stop("SOURCE_LAG_EXCEEDED", safe=True)
                journal.drain()
                if disposition == "REJECTED":
                    # Account the rejected frame, then stop; no silent skipping.
                    journal.stop("REJECTED_FRAME", safe=True)
                if journal.get("state") == "SAFE_STOP":
                    break
                elapsed = max(0.001, time.monotonic() - start)
                if time.monotonic() - last_probe >= 10:
                    c = journal.counts()
                    values = {**c, "queue": sum(c["statuses"][s] for s in c["statuses"] if s != "COMPLETED"),
                              "max_source_lag_seconds": maximum_lag,
                              "input_rate_per_second": application_received / elapsed,
                              "processing_rate_per_second": c["statuses"]["COMPLETED"] / elapsed,
                              "cursor": journal.db.execute("SELECT max(event_id) FROM events").fetchone()[0],
                              "gaps": journal.get("gaps"), "trading_actions": 0, "live_trading": False}
                    journal.record_telemetry(values)
                    print({"received": application_received, "completed": c["statuses"]["COMPLETED"],
                           "queue": values["queue"], "max_lag_s": round(maximum_lag, 3)}, flush=True)
                    if health_probe is not None and not await health_probe():
                        journal.stop("RUNTIME_SAFETY_CHANGED", safe=True)
                        break
                    last_probe = time.monotonic()
            if application_received == journal.contract["max_events"] and journal.get("state") == "OPEN":
                journal.stop("MAX_EVENTS")
            # Explicitly close before final drain/acceptance. No further recv.
            await socket.close()
    except (Exception, asyncio.CancelledError) as exc:
        journal.stop(f"SOURCE_OR_JOURNAL_ERROR:{type(exc).__name__}", safe=True)
    finally:
        if journal.get("state") == "OPEN":
            journal.stop("UNEXPECTED_SESSION_END", safe=True)
        journal.finish(application_received)
        elapsed = max(0.001, time.monotonic() - start)
        summary = {**journal.counts(), "max_source_lag_seconds": maximum_lag,
            "elapsed_seconds": elapsed, "input_rate_per_second": application_received / elapsed,
            "processing_rate_per_second": journal.counts()["statuses"]["COMPLETED"] / elapsed,
            "source_connection_closed": True, "reconnections": 0,
            "application_received": application_received, "trading_actions": 0, "live_trading": False}
        journal.record_telemetry(summary)
    return summary
