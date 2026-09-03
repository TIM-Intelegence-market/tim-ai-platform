#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.secrets import DatabaseSecretResolver  # noqa: E402
from config.settings import settings  # noqa: E402
from scripts.admin.prepare_tim_credential import atomic_private_json, load_handoff  # noqa: E402


def listener_check(port: int) -> dict[str, object]:
    result = subprocess.run(
        ["/usr/sbin/netstat", "-an", "-p", "tcp"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    addresses: list[str] = []
    for line in result.stdout.splitlines():
        if "LISTEN" not in line:
            continue
        for value in line.split():
            if value.endswith(f".{port}") or value.endswith(f":{port}"):
                addresses.append(value)
                break
    unsafe = any(
        value.startswith(("*.", "0.0.0.0.", "0.0.0.0:", "::.", ":::"))
        or not any(token in value for token in ("127.0.0.1", "::1", "localhost"))
        for value in addresses
    )
    return {"status": "PASS" if addresses and not unsafe else "FAIL", "addresses": sorted(set(addresses))}


def lan_negative_test(port: int) -> dict[str, object]:
    route = subprocess.run(
        ["/sbin/route", "-n", "get", "default"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    interface = next((line.split()[-1] for line in route.stdout.splitlines() if "interface:" in line), None)
    if not interface:
        return {"status": "UNKNOWN", "reason": "LAN interface unavailable"}
    address = subprocess.run(
        ["/usr/sbin/ipconfig", "getifaddr", interface],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    if not address:
        return {"status": "UNKNOWN", "reason": "LAN address unavailable"}
    try:
        connection = socket.create_connection((address, port), timeout=2)
    except OSError:
        return {"status": "PASS", "lan_address_redacted": True}
    connection.close()
    return {"status": "FAIL", "lan_address_redacted": True}


async def database_check() -> dict[str, object]:
    try:
        import asyncpg

        url = DatabaseSecretResolver().database_url(settings.database_endpoint)
        connection = await asyncpg.connect(url, timeout=5)
        try:
            row = await connection.fetchrow(
                "SELECT current_user AS role, current_setting('listen_addresses') AS listeners, "
                "current_setting('password_encryption') AS encryption"
            )
        finally:
            await connection.close()
    except Exception as exc:
        return {"status": "FAIL", "reason": type(exc).__name__}
    passed = row["role"] == "tim" and row["listeners"] in {"127.0.0.1,::1", "::1,127.0.0.1"} and row["encryption"] == "scram-sha-256"
    return {"status": "PASS" if passed else "FAIL", "role": row["role"], "password_encryption": row["encryption"]}


async def legacy_negative_test() -> dict[str, object]:
    old_password = getpass.getpass("Previous TIM database password (used only for a negative test): ")
    try:
        import asyncpg

        connection = await asyncpg.connect(
            host=settings.database_host,
            port=settings.database_port,
            database=settings.database_name,
            user=settings.database_user,
            password=old_password,
            timeout=3,
        )
        await connection.close()
    except Exception:
        old_password = ""
        return {"status": "PASS", "old_credential_rejected": True}
    old_password = ""
    return {"status": "FAIL", "old_credential_rejected": False}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify TIM PostgreSQL hardening without printing secrets")
    parser.add_argument("--test-previous-credential", action="store_true")
    parser.add_argument(
        "--handoff",
        type=Path,
        default=Path("~/Library/Application Support/TIM/postgres-admin-handoff.json"),
    )
    parser.add_argument(
        "--verification-output",
        type=Path,
        default=Path("~/Library/Application Support/TIM/postgres-hardening-verification.json"),
    )
    args = parser.parse_args()
    try:
        handoff = load_handoff(args.handoff.expanduser())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "secret_printed": False}))
        return 2
    payload = {
        "schema_version": "1.0.0",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "bundle_id": handoff["bundle_id"],
        "listener": listener_check(settings.database_port),
        "lan_negative": lan_negative_test(settings.database_port),
        "database": await database_check(),
        "previous_credential": await legacy_negative_test() if args.test_previous_credential else {"status": "NOT_RUN"},
        "secret_printed": False,
    }
    required = [payload["listener"]["status"], payload["lan_negative"]["status"], payload["database"]["status"]]
    if args.test_previous_credential:
        required.append(payload["previous_credential"]["status"])
    payload["status"] = "PASS" if args.test_previous_credential and all(value == "PASS" for value in required) else "FAIL"
    payload["finalization_eligible"] = payload["status"] == "PASS"
    if payload["finalization_eligible"]:
        atomic_private_json(args.verification_output.expanduser(), payload)
        payload["verification_output"] = str(args.verification_output.expanduser())
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
