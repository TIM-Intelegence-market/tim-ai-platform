from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from config.secrets import (
    DatabaseEndpoint,
    DatabaseSecretResolver,
    SecretProviderError,
    SecretValue,
    redact_database_url,
)
from scripts.admin import prepare_tim_credential
from scripts.admin import verify_postgres_hardening


ROOT = Path(__file__).resolve().parents[1]


def test_secret_value_cannot_be_printed_or_represented() -> None:
    value = SecretValue("not-a-real-test-secret")
    assert "not-a-real-test-secret" not in str(value)
    assert "not-a-real-test-secret" not in repr(value)
    assert "REDACTED" in repr(value)


def test_default_keychain_provider_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 44, "", "not found"),
    )
    resolver = DatabaseSecretResolver({})
    with pytest.raises(SecretProviderError, match="unavailable"):
        resolver.database_url(DatabaseEndpoint())


def test_keychain_provider_encodes_password_without_exposing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    supplied = "test-only value:@/with spaces"

    def fake_run(command, **kwargs):
        assert supplied not in command
        return subprocess.CompletedProcess(command, 0, f"{supplied}\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    url = DatabaseSecretResolver({"TIM_DATABASE_SECRET_PROVIDER": "keychain"}).database_url(DatabaseEndpoint())
    assert supplied not in url
    assert "test-only%20value%3A%40%2Fwith%20spaces" in url
    assert redact_database_url(url) == "postgresql://@REDACTED_USER@@127.0.0.1:5432/tim"


def test_pgpass_requires_private_permissions_and_supports_escaping(tmp_path: Path) -> None:
    path = tmp_path / "pgpass"
    path.write_text(r"127.0.0.1:5432:tim:tim:test\:only" + "\n", encoding="utf-8")
    path.chmod(0o644)
    env = {"TIM_DATABASE_SECRET_PROVIDER": "pgpass", "TIM_DATABASE_PGPASS_FILE": str(path)}
    with pytest.raises(SecretProviderError, match="0600"):
        DatabaseSecretResolver(env).database_url(DatabaseEndpoint())
    path.chmod(0o600)
    url = DatabaseSecretResolver(env).database_url(DatabaseEndpoint())
    assert "test%3Aonly" in url


def test_file_provider_requires_private_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "database-password"
    path.write_text("isolated-test-password\n", encoding="utf-8")
    path.chmod(0o600)
    env = {"TIM_DATABASE_SECRET_PROVIDER": "file", "TIM_DATABASE_SECRET_FILE": str(path)}
    assert "isolated-test-password" in DatabaseSecretResolver(env).database_url(DatabaseEndpoint())
    path.chmod(0o640)
    with pytest.raises(SecretProviderError, match="0600"):
        DatabaseSecretResolver(env).database_url(DatabaseEndpoint())


def test_url_environment_provider_is_limited_to_explicit_isolated_tests() -> None:
    test_url = "postgresql://role:fixture-only@127.0.0.1:5432/tim_test"
    base = {"TIM_DATABASE_SECRET_PROVIDER": "url-env", "TIM_DURABLE_TEST_DATABASE_URL": test_url}
    with pytest.raises(SecretProviderError, match="isolated tests"):
        DatabaseSecretResolver(base).database_url(DatabaseEndpoint())
    allowed = {
        **base,
        "TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS": "true",
        "TIM_RUNTIME_ENV": "test",
    }
    assert DatabaseSecretResolver(allowed).database_url(DatabaseEndpoint()) == test_url
    allowed["TIM_DURABLE_TEST_DATABASE_URL"] = "postgresql://role:fixture-only@192.0.2.5:5432/tim_test"
    with pytest.raises(SecretProviderError, match="loopback"):
        DatabaseSecretResolver(allowed).database_url(DatabaseEndpoint())
    allowed["TIM_DURABLE_TEST_DATABASE_URL"] = "postgresql://role:fixture-only@127.0.0.1:not-a-port/tim_test"
    with pytest.raises(SecretProviderError, match="invalid"):
        DatabaseSecretResolver(allowed).database_url(DatabaseEndpoint())


def test_scram_handoff_matches_password_without_storing_plaintext() -> None:
    password = "isolated-test-password"
    verifier = prepare_tim_credential.scram_verifier(password)
    assert password not in verifier
    assert re.fullmatch(
        r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+",
        verifier,
    )
    assert prepare_tim_credential.scram_verifier_for_existing_password(password, verifier) == verifier


def test_keychain_write_passes_secret_only_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(prepare_tim_credential.subprocess, "run", fake_run)
    prepare_tim_credential.store_keychain("fixture-only", "com.tim.database", "tim")
    assert "fixture-only" not in captured["command"]
    assert captured["command"][-1] == "-w"
    assert captured["input"] == "fixture-only\n"


def test_prepared_handoff_is_private_and_contains_no_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    handoff = tmp_path / "handoff.json"
    monkeypatch.setattr(prepare_tim_credential, "store_keychain", lambda *args: None)
    args = argparse.Namespace(
        handoff=handoff,
        replace=False,
        service="com.tim.database",
        account="tim",
    )
    assert prepare_tim_credential.prepare(args) == 0
    assert stat.S_IMODE(handoff.stat().st_mode) == 0o600
    payload = handoff.read_text(encoding="utf-8")
    assert "PENDING_POSTGRES_ADMIN_APPLY" in payload
    assert "password\"" not in payload.lower()
    output = capsys.readouterr().out
    assert "secret_printed" in output and "scram_verifier" not in output


def test_handoff_finalization_requires_bundle_matched_complete_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = tmp_path / "handoff.json"
    verification = tmp_path / "verification.json"
    monkeypatch.setattr(prepare_tim_credential, "store_keychain", lambda *args: None)
    monkeypatch.setattr(prepare_tim_credential, "read_keychain", lambda *args: "fixture-only")
    prepare_args = argparse.Namespace(
        handoff=handoff,
        replace=False,
        service="com.tim.database",
        account="tim",
    )
    assert prepare_tim_credential.prepare(prepare_args) == 0
    bundle_id = json.loads(handoff.read_text(encoding="utf-8"))["bundle_id"]
    prepare_tim_credential.atomic_private_json(
        verification,
        {
            "status": "PASS",
            "finalization_eligible": True,
            "bundle_id": "different-bundle",
            "previous_credential": {"old_credential_rejected": True},
        },
    )
    finalize_args = argparse.Namespace(
        handoff=handoff,
        verification=verification,
        confirm="FINALIZE",
    )
    with pytest.raises(RuntimeError, match="matching complete"):
        prepare_tim_credential.finalize(finalize_args)
    prepare_tim_credential.atomic_private_json(
        verification,
        {
            "status": "PASS",
            "finalization_eligible": True,
            "bundle_id": bundle_id,
            "previous_credential": {"old_credential_rejected": True},
        },
    )
    assert prepare_tim_credential.finalize(finalize_args) == 0
    assert not handoff.exists()


def test_postgres_verifier_rejects_specific_lan_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    output = "tcp4 0 0 192.168.10.177.5432 *.* LISTEN\n"
    monkeypatch.setattr(
        verify_postgres_hardening.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, output, ""),
    )
    assert verify_postgres_hardening.listener_check(5432)["status"] == "FAIL"


def test_current_security_sources_have_no_fixed_database_credential_or_sudo() -> None:
    paths = [
        ROOT / "config/settings.py",
        ROOT / "docker-compose.yml",
        ROOT / "scripts/setup_postgres.sh",
        ROOT / "scripts/reset_postgres_password.sh",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "tim_" + "local_only" not in combined
    assert not re.search(r"POSTGRES_PASSWORD:\s*[^$<{\s]", combined)
    assert not re.search(r"\bsudo\b", combined)


def test_admin_apply_refuses_unconfirmed_instance_classification() -> None:
    result = subprocess.run(
        [
            str(ROOT / "scripts/admin/apply_postgres_hardening.sh"),
            "--config-file",
            "/not/used",
            "--hba-file",
            "/not/used",
            "--data-directory",
            "/not/used",
            "--classification",
            "UNKNOWN",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "TIM_DEDICATED" in result.stderr


@pytest.mark.parametrize(
    "script",
    [
        "scripts/admin/inspect_postgres.sh",
        "scripts/admin/apply_postgres_hardening.sh",
        "scripts/admin/rollback_postgres_hardening.sh",
        "scripts/setup_postgres.sh",
        "scripts/reset_postgres_password.sh",
    ],
)
def test_security_shell_scripts_parse(script: str) -> None:
    result = subprocess.run(["/bin/bash", "-n", str(ROOT / script)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
