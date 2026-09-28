"""Cached telemetry must not overwrite live dashboard values or hide failures."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.test_ingestion_health_efficiency import application


def test_cached_sample_never_overwrites_live_values_published_by_ingest(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        await app._refresh_ingestion_health()
        # ingest_trade publishes live values between worker cycles.
        with app.dashboard_state.lock:
            app.dashboard_state.system_health.update({"queue_depth": 3, "recovery_state": "GAP_DETECTED"})
        clock[0] = 102.0
        cached = await app._refresh_ingestion_health()
        assert cached["queue_depth"] == 12 and cached["health_snapshot_cached"] is True
        health = app.dashboard_state.system_health
        assert health["queue_depth"] == 3 and health["recovery_state"] == "GAP_DETECTED"
        assert health["health_snapshot_cached"] is True and health["health_snapshot_age_seconds"] == 2.0
    asyncio.run(exercise())


def test_failing_telemetry_is_logged_without_stopping_the_worker(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        app.durable_store.metrics_snapshot.side_effect = TimeoutError("probe expired")
        calls = 0

        async def run_once():
            nonlocal calls
            calls += 1
            if calls == 3:
                app.worker_stop.set()
            return {"claimed": 1, "completed": 1, "retried": 0, "quarantined": 0}

        app.enrichment_worker = SimpleNamespace(run_once=run_once)
        await app._worker_loop()
        assert calls == 3
        warnings = [row for row in app.queue_events if row["event"] == "INGESTION_HEALTH_UNAVAILABLE"]
        assert len(warnings) == 3 and warnings[0]["error_type"] == "TimeoutError"
        assert warnings[0]["rate_limit_seconds"] == 60.0
        cycles = [row for row in app.queue_events if row["event"] == "OUTBOX_WORKER_CYCLE"]
        assert len(cycles) == 3 and all(row["health_snapshot_stale"] for row in cycles)
    asyncio.run(exercise())
