#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


def scram_verifier(password: str, *, iterations: int = 4096) -> str:
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_stored = base64.b64encode(stored_key).decode("ascii")
    encoded_server = base64.b64encode(server_key).decode("ascii")
    return f"SCRAM-SHA-256${iterations}:{encoded_salt}${encoded_stored}:{encoded_server}"


def safe_name(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", value):
        raise ValueError(f"invalid {label}")
    return value


def atomic_private_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def store_keychain(password: str, service: str, account: str) -> None:
    command = [
        "/usr/bin/security",
        "add-generic-password",
        "-U",
        "-s",
        service,
        "-a",
        account,
        "-w",
        password,
    ]
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("macOS Keychain update failed") from exc
    if result.returncode != 0:
        raise RuntimeError("macOS Keychain update failed")


def read_keychain(service: str, account: str) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("macOS Keychain verification failed") from exc
    if result.returncode != 0 or not result.stdout.rstrip("\n"):
        raise RuntimeError("macOS Keychain verification failed")
    return result.stdout.rstrip("\n")


def load_handoff(path: Path) -> dict[str, str]:
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise RuntimeError("credential handoff permissions are unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "PENDING_POSTGRES_ADMIN_APPLY":
        raise RuntimeError("credential handoff is not pending")
    return value


def prepare(args: argparse.Namespace) -> int:
    handoff = args.handoff.expanduser()
    if handoff.exists() and not args.replace:
        print(json.dumps({"status": "BLOCKED", "reason": "pending handoff already exists", "handoff": str(handoff)}))
        return 2
    service = safe_name(args.service, "Keychain service")
    account = safe_name(args.account, "Keychain account")
    password = secrets.token_urlsafe(48)
    verifier = scram_verifier(password)
    store_keychain(password, service, account)
    payload = {
        "schema_version": "1.0.0",
        "bundle_id": f"tim-credential-{uuid.uuid4().hex}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_role": account,
        "keychain_service": service,
        "keychain_account": account,
        "password_encryption": "scram-sha-256",
        "scram_verifier": verifier,
        "status": "PENDING_POSTGRES_ADMIN_APPLY",
    }
    atomic_private_json(handoff, payload)
    password = ""
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "handoff": str(handoff),
                "keychain_service": service,
                "keychain_account": account,
                "secret_printed": False,
                "next": "POSTGRES_ADMIN_APPLY_REQUIRED",
            },
            sort_keys=True,
        )
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    handoff = load_handoff(args.handoff.expanduser())
    password = read_keychain(handoff["keychain_service"], handoff["keychain_account"])
    expected = scram_verifier_for_existing_password(password, handoff["scram_verifier"])
    matches = hmac.compare_digest(expected, handoff["scram_verifier"])
    password = ""
    print(json.dumps({"status": "PASS" if matches else "FAIL", "provider": "keychain", "secret_printed": False}))
    return 0 if matches else 2


def scram_verifier_for_existing_password(password: str, template: str) -> str:
    match = re.fullmatch(r"SCRAM-SHA-256\$(\d+):([^$]+)\$([^:]+):(.+)", template)
    if not match:
        raise RuntimeError("credential handoff verifier is invalid")
    iterations = int(match.group(1))
    salt = base64.b64decode(match.group(2), validate=True)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return (
        f"SCRAM-SHA-256${iterations}:{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(stored_key).decode('ascii')}:"
        f"{base64.b64encode(server_key).decode('ascii')}"
    )


def finalize(args: argparse.Namespace) -> int:
    path = args.handoff.expanduser()
    handoff = load_handoff(path)
    read_keychain(handoff["keychain_service"], handoff["keychain_account"])
    verification_path = args.verification.expanduser()
    verification_metadata = verification_path.lstat()
    if (
        verification_path.is_symlink()
        or not verification_path.is_file()
        or verification_metadata.st_uid != os.getuid()
        or verification_metadata.st_mode & 0o077
    ):
        raise RuntimeError("hardening verification permissions are unsafe")
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if (
        verification.get("status") != "PASS"
        or verification.get("finalization_eligible") is not True
        or verification.get("bundle_id") != handoff.get("bundle_id")
        or verification.get("previous_credential", {}).get("old_credential_rejected") is not True
    ):
        raise RuntimeError("matching complete hardening verification is required")
    confirmation = args.confirm or getpass.getpass("Type FINALIZE to remove the applied verifier handoff: ")
    if confirmation != "FINALIZE":
        print(json.dumps({"status": "BLOCKED", "reason": "confirmation failed"}))
        return 2
    path.unlink()
    print(json.dumps({"status": "FINALIZED", "handoff_removed": True, "secret_printed": False}))
    return 0


def parser() -> argparse.ArgumentParser:
    default = Path("~/Library/Application Support/TIM/postgres-admin-handoff.json")
    value = argparse.ArgumentParser(description="Prepare TIM database credential without printing it")
    subcommands = value.add_subparsers(dest="command", required=True)
    prepare_parser = subcommands.add_parser("prepare")
    prepare_parser.add_argument("--handoff", type=Path, default=default)
    prepare_parser.add_argument("--service", default="com.tim.database")
    prepare_parser.add_argument("--account", default="tim")
    prepare_parser.add_argument("--replace", action="store_true")
    prepare_parser.set_defaults(handler=prepare)
    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--handoff", type=Path, default=default)
    verify_parser.set_defaults(handler=verify)
    finalize_parser = subcommands.add_parser("finalize")
    finalize_parser.add_argument("--handoff", type=Path, default=default)
    finalize_parser.add_argument(
        "--verification",
        type=Path,
        default=Path("~/Library/Application Support/TIM/postgres-hardening-verification.json"),
    )
    finalize_parser.add_argument("--confirm")
    finalize_parser.set_defaults(handler=finalize)
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return int(args.handler(args))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "secret_printed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
