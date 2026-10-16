from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.tim_server_healthcheck import MODEL, OLLAMA_URL, collect

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


def run(*args):
    if args[:2] == ("systemctl", "is-active"):
        return "inactive" if args[-1] == "tim-qwen-worker" else "active"
    if args[:2] == ("systemctl", "is-enabled"):
        return "disabled"
    if args[0] == "timedatectl":
        return "yes"
    if args[-1] == "HEAD":
        return "a" * 40
    return " M src/dashboard/operations.py"


def get(url):
    if url == OLLAMA_URL + "/api/tags":
        return {"models": [{"name": MODEL}]}
    if url.endswith("/healthz"):
        return {"status": "ok"}
    assert url.endswith("/api/operations")
    return {"generated_at_utc": NOW.isoformat(), "execution_disabled": True,
            "current_status": {name: {"status": "FAIL" if name == "watchdog" else "PASS"}
                               for name in ("runtime", "data", "maintenance", "watchdog")},
            "horizon_evidence": {"report": {"horizons": {"LONG": {"missing_minutes": 4251}}}}}


def collect_fake(**changes):
    return collect(**{"run": run, "get": get, "disk": lambda _: SimpleNamespace(free=50, total=100),
                      "now": NOW, **changes})


def test_compute_topology_and_real_model_endpoint_with_readiness_separate():
    urls = []
    result = collect_fake(get=lambda url: urls.append(url) or get(url))
    assert result["status"] == "PASS"
    assert OLLAMA_URL == "http://127.0.0.2:11434"
    assert OLLAMA_URL + "/api/tags" in urls
    assert result["readiness"] == {"watchdog": "FAIL", "long_missing_minutes": 4251}
    assert result["source_reconciliation_required"] is True
    assert result["trading_actions"] == 0


@pytest.mark.parametrize("service", ["tim-runtime", "timec", "caddy", "ollama"])
def test_required_service_failure_is_not_hidden(service):
    result = collect_fake(run=lambda *args: "inactive" if args == ("systemctl", "is-active", service) else run(*args))
    assert result["status"] == "FAIL" and result["checks"][service + ".service"] is False


def test_duplicate_server_writer_is_rejected():
    result = collect_fake(run=lambda *args: "active" if args == ("systemctl", "is-active", "tim-qwen-worker") else run(*args))
    assert result["status"] == "FAIL" and not result["checks"]["server_writer_disabled"]


@pytest.mark.parametrize("change", ["stale", "future", "enabled", "missing"])
def test_stale_or_incomplete_operations_and_enabled_execution_fail(change):
    def altered(url):
        value = get(url)
        if url.endswith("/api/operations"):
            if change == "stale":
                value["generated_at_utc"] = "2026-10-16T00:00:00Z"
            elif change == "future":
                value["generated_at_utc"] = "2026-10-18T00:00:00Z"
            elif change == "enabled":
                value["execution_disabled"] = False
            else:
                value.pop("current_status")
        return value
    assert collect_fake(get=altered)["status"] == "FAIL"


def test_transport_failure_and_missing_model_fail():
    def broken(url):
        if "/api/tags" in url:
            raise TimeoutError()
        return get(url)
    assert collect_fake(get=broken)["status"] == "FAIL"
    assert collect_fake(get=lambda url: {"models": []} if "/api/tags" in url else get(url))["status"] == "FAIL"


def test_low_disk_and_unsynchronized_clock_fail():
    assert collect_fake(disk=lambda _: SimpleNamespace(free=9, total=100))["status"] == "FAIL"
    assert collect_fake(run=lambda *args: "no" if args[0] == "timedatectl" else run(*args))["status"] == "FAIL"


def test_snapshot_generated_during_request_is_fresh():
    def current(url):
        value = get(url)
        if url.endswith("/api/operations"):
            value["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return value
    result = collect(run=run, get=current, disk=lambda _: SimpleNamespace(free=50, total=100))
    assert result["status"] == "PASS"
