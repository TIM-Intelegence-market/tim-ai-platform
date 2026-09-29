"""scripts/openmarket_store_key.py: hidden input, shape check, 0600 write, no leak."""
from __future__ import annotations

import importlib.util
import stat

import pytest

KEY = "om_live_fixture_ABCDEFGHIJKLMNOPQRSTUV_0123456789"  # synthetic, not a real key


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


store = load("om_store_key", "scripts/openmarket_store_key.py")


def test_stores_clean_key_private_and_accepted_by_resolver(tmp_path, capsys) -> None:
    target = tmp_path / "TIM" / "openmarket-api-key"
    assert store.main(["--file", str(target)], prompt=lambda _: KEY + "\n") == 0
    assert target.read_text() == KEY
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    out = capsys.readouterr().out
    assert KEY not in out and "****6789" in out and "SECRET_CONFIGURED=YES" in out


@pytest.mark.parametrize(
    ("pasted", "reason"),
    [
        ("Name: TIM-SERVER-2\nKey: " + KEY + "\nCreated today", "spaces or line breaks"),
        (KEY + " copied", "spaces or line breaks"),
        ("TIM-SERVER", "key name"),
        (KEY[:-1] + "é", "non-ASCII"),
        ("", "key shape"),
    ],
    ids=["multi-line-text", "trailing-words", "key-name", "non-ascii", "empty"],
)
def test_rejects_anything_but_the_key_and_keeps_old_file(tmp_path, capsys, pasted, reason) -> None:
    target = tmp_path / "openmarket-api-key"
    target.write_text("previous")
    assert store.main(["--file", str(target)], prompt=lambda _: pasted) == 2
    assert target.read_text() == "previous", "a rejected input never overwrites the file"
    out = capsys.readouterr().out
    assert "NOT STORED" in out and reason in out
    assert KEY not in out and (not pasted or pasted not in out)


def test_overwrites_the_broken_multiline_file(tmp_path) -> None:
    target = tmp_path / "openmarket-api-key"
    target.write_text("line one\nline two with key " + KEY + "\n\n")
    target.chmod(0o600)
    assert store.main(["--file", str(target)], prompt=lambda _: KEY) == 0
    assert target.read_text() == KEY


def test_proof_names_the_secret_problem_without_the_value(tmp_path, monkeypatch, capsys) -> None:
    broken = "Name: TIM-SERVER-2\nKey: " + KEY + "\n"
    target = tmp_path / "openmarket-api-key"
    target.write_text(broken)
    target.chmod(0o600)
    monkeypatch.setenv("TIM_OPENMARKET_SECRET_PROVIDER", "file")
    monkeypatch.setenv("TIM_OPENMARKET_SECRET_FILE", str(target))
    monkeypatch.setattr("sys.argv", ["proof"])
    proof = load("om_proof_store", "scripts/openmarket_api_proof.py")
    assert proof.main() == 1
    out = capsys.readouterr().out
    assert "SECRET_CONFIGURED=NO" in out and "SECRET_ERROR=" in out and "invalid shape" in out
    assert KEY not in out and "TIM-SERVER-2" not in out
