"""Bounded telemetry must not delay or replace authoritative worker decisions."""
from __future__ import annotations

import asyncio
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main


def sample_metrics(depth=12):
    return {
        'queue_depth': depth, 'queue_high_water': 30, 'queue_oldest_age': 100.0,
        'cursor_age': 2.0, 'recovery_state': 'CATCHING_UP',
        'duplicate_total': 4, 'out_of_order_total': 0,
    }


def application(monkeypatch, clock):
    # No credentials, database, dashboard listener, stream or extra worker.
    app = main.TIMApplication.__new__(main.TIMApplication)
    app.durable_store = SimpleNamespace(metrics_snapshot=AsyncMock(return_value=sample_metrics()), record_metric=AsyncMock())
    app.dashboard_state = SimpleNamespace(lock=Lock(), system_health={})
    app._ingestion_health_lock = asyncio.Lock()
    app._ingestion_health_snapshot = None
    app._ingestion_health_sample_started = 0.0
    app._ingestion_health_observed_at = None
    app.worker_stop = asyncio.Event()
    app.queue_events = []
    app.queue_log = SimpleNamespace(write=lambda event, **kwargs: app.queue_events.append({'event': event, **kwargs}))
    monkeypatch.setattr(main, 'monotonic', lambda: clock[0])
    return app


def test_many_worker_completions_use_one_explicitly_cached_telemetry_sample(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        calls = 0
        async def run_once():
            nonlocal calls
            calls += 1
            if calls == 100:
                app.worker_stop.set()
            return {'claimed': 1, 'completed': 1, 'retried': 0, 'quarantined': 0}
        app.enrichment_worker = SimpleNamespace(run_once=run_once)
        await app._worker_loop()
        assert calls == 100
        assert app.durable_store.metrics_snapshot.await_count == 1
        assert len(app.queue_events) == 100
        assert sum(row['result']['completed'] for row in app.queue_events) == 100
        assert app.queue_events[0]['health_snapshot_cached'] is False
        assert all(row['health_snapshot_cached'] and row['health_snapshot_stale'] for row in app.queue_events[1:])
        assert all(row['health_snapshot_scope'] == 'telemetry_only' for row in app.queue_events)
        assert all(row['mode'] == 'OBSERVE' and row['trading_actions'] == 0 for row in app.queue_events)
    asyncio.run(exercise())


def test_refresh_at_exact_interval_and_cache_age_is_explicit(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        first = await app._refresh_ingestion_health()
        first['queue_depth'] = 999
        clock[0] = 104.999
        cached = await app._refresh_ingestion_health()
        assert cached['queue_depth'] == 12
        assert cached['health_snapshot_age_seconds'] == pytest.approx(4.999)
        assert cached['health_snapshot_stale'] is True
        assert cached['health_snapshot_observed_at'] == first['health_snapshot_observed_at']
        app.durable_store.metrics_snapshot.return_value = sample_metrics(depth=8)
        clock[0] = 105.0
        current = await app._refresh_ingestion_health()
        assert app.durable_store.metrics_snapshot.await_count == 2
        assert current['queue_depth'] == 8
        assert current['health_snapshot_cached'] is False
        assert current['health_snapshot_stale'] is False
        assert app.dashboard_state.system_health['health_snapshot_age_seconds'] == 0.0
    asyncio.run(exercise())


def test_simultaneous_refresh_requests_coalesce_without_overlapping_queries(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_snapshot(_symbol):
            started.set()
            await release.wait()
            return sample_metrics()
        app.durable_store.metrics_snapshot.side_effect = slow_snapshot
        first = asyncio.create_task(app._refresh_ingestion_health())
        await started.wait()
        second = asyncio.create_task(app._refresh_ingestion_health())
        await asyncio.sleep(0)
        assert app.durable_store.metrics_snapshot.await_count == 1
        release.set()
        a, b = await asyncio.gather(first, second)
        assert app.durable_store.metrics_snapshot.await_count == 1
        assert a['health_snapshot_cached'] is False
        assert b['health_snapshot_cached'] is True
    asyncio.run(exercise())


def test_failed_refresh_never_relabels_old_snapshot_as_current_and_retries(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        old = await app._refresh_ingestion_health()
        clock[0] = 105.0
        app.durable_store.metrics_snapshot.side_effect = TimeoutError('bounded probe expired')
        with pytest.raises(TimeoutError):
            await app._refresh_ingestion_health()
        assert app._ingestion_health_observed_at == old['health_snapshot_observed_at']
        assert app._ingestion_health_sample_started == 100.0
        assert app.dashboard_state.system_health['health_snapshot_stale'] is True
        assert app.dashboard_state.system_health['health_snapshot_age_seconds'] == 5.0
        app.durable_store.metrics_snapshot.side_effect = None
        app.durable_store.metrics_snapshot.return_value = sample_metrics(depth=7)
        current = await app._refresh_ingestion_health()
        assert app.durable_store.metrics_snapshot.await_count == 3
        assert current['queue_depth'] == 7 and current['health_snapshot_cached'] is False
    asyncio.run(exercise())


def test_query_duration_is_included_in_observation_age(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        async def delayed_snapshot(_symbol):
            clock[0] += 6.0
            return sample_metrics()
        app.durable_store.metrics_snapshot.side_effect = delayed_snapshot
        current = await app._refresh_ingestion_health()
        assert current['health_snapshot_age_seconds'] == 6.0
        assert current['health_snapshot_stale'] is True
    asyncio.run(exercise())


def test_terminal_strict_order_blocker_is_logged_without_any_telemetry_dependency(monkeypatch):
    async def exercise():
        clock = [100.0]
        app = application(monkeypatch, clock)
        app.durable_store.metrics_snapshot.side_effect = AssertionError('must not delay blocker')
        blocker = {'outbox_id': 'a' * 64, 'status': 'QUARANTINED', 'attempts': 5}
        async def blocked():
            app.worker_stop.set()
            return {'status': 'TERMINAL_BLOCKED', 'claimed': 0, 'completed': 0,
                    'retried': 0, 'quarantined': 0, 'terminal_blocker': blocker}
        app.enrichment_worker = SimpleNamespace(run_once=blocked)
        await app._worker_loop()
        app.durable_store.metrics_snapshot.assert_not_awaited()
        assert app.dashboard_state.system_health['worker'] == 'TERMINAL_BLOCKED'
        assert app.dashboard_state.system_health['terminal_blocker'] == blocker
        assert len(app.queue_events) == 1
        evidence = app.queue_events[0]
        assert evidence['severity'] == 'ERROR'
        assert evidence['result']['terminal_blocker'] == blocker
        assert evidence['health_snapshot_stale'] is True
        assert evidence['queue_depth'] is None
        assert evidence['health_snapshot_observed_at'] is None
        assert evidence['result']['claimed'] == 0
    asyncio.run(exercise())
