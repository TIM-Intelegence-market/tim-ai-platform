#!/usr/bin/env python3
"""Read-only functional checks for the deployed Mac-coordinator/server-compute topology.

Data readiness and patched source provenance remain separately visible; this
check never activates the legacy server writer or changes a service/database.
"""
from datetime import datetime, timezone
import json
import shutil
import subprocess
from urllib.request import urlopen

OLLAMA_URL = "http://127.0.0.2:11434"
MODEL = "qwen3-coder:30b"


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10, check=False).stdout.strip()


def fetch(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)


def collect(*, run=command, get=fetch, disk=shutil.disk_usage, now=None):
    fixed_now = now
    now = now or datetime.now(timezone.utc)
    checks = {}
    def check(name, function):
        try:
            checks[name] = function() is True
        except Exception:
            checks[name] = False

    for service in ("tim-runtime", "timec", "caddy", "ollama"):
        check(service + ".service", lambda service=service: run("systemctl", "is-active", service) == "active")
    check("server_writer_disabled", lambda: run("systemctl", "is-active", "tim-qwen-worker") != "active"
          and run("systemctl", "is-enabled", "tim-qwen-worker") in {"disabled", "masked"})
    check("ollama.model", lambda: any(row.get("name", row.get("model")) == MODEL
                                     for row in get(OLLAMA_URL + "/api/tags")["models"]))
    check("portal.http", lambda: get("http://127.0.0.1:8090/healthz").get("status") == "ok")
    readiness = {}
    try:
        snapshot = get("http://127.0.0.1:8765/api/operations")
        timestamp = datetime.fromisoformat(snapshot["generated_at_utc"].replace("Z", "+00:00"))
        # The response is generated after this probe starts. Compare against
        # receipt time so a fresh snapshot does not look a few milliseconds future.
        received_at = fixed_now or datetime.now(timezone.utc)
        checks["operations.fresh"] = 0 <= (received_at - timestamp).total_seconds() <= 300
        checks["execution.disabled"] = snapshot.get("execution_disabled") is True
        current = snapshot["current_status"]
        for name in ("runtime", "data", "maintenance"):
            checks["operations." + name] = current[name]["status"] == "PASS"
        horizon = snapshot.get("horizon_evidence", {}).get("report", {}).get("horizons", {})
        readiness = {"watchdog": current.get("watchdog", {}).get("status", "UNAVAILABLE"),
                     "long_missing_minutes": horizon.get("LONG", {}).get("missing_minutes")}
    except Exception:
        checks["operations.fresh"] = False
    for path in ("/", "/var", "/srv"):
        check("disk." + path, lambda path=path: disk(path).free / disk(path).total > 0.1)
    check("time.synchronized", lambda: run("timedatectl", "show", "-p", "NTPSynchronized", "--value") == "yes")
    provenance = {}
    try:
        prefix = ("git", "-c", "safe.directory=/opt/tim", "-C", "/opt/tim")
        provenance = {"commit": run(*prefix, "rev-parse", "HEAD"),
                      "changes": run(*prefix, "status", "--short").splitlines()}
        checks["source.identified"] = len(provenance["commit"]) == 40
    except Exception:
        checks["source.identified"] = False
    return {"checked_at": now.isoformat(), "scope": "FUNCTIONAL_SERVICES_NOT_RESEARCH_QUALIFICATION",
            "topology": "MAC_COORDINATOR_SERVER_COMPUTE", "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL", "readiness": readiness,
            "provenance": provenance, "source_reconciliation_required": bool(provenance.get("changes")),
            "trading_actions": 0}


if __name__ == "__main__":
    result = collect()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
