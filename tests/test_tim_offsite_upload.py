"""scripts/tim_offsite_upload.py: checksum-verified SSH upload, dumps only encrypted."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from scripts import tim_offsite_upload as off


def make_backup(d: Path, name: str, data: bytes = b"abc") -> Path:
    f = d / name
    f.write_bytes(data)
    (d / (name + ".sha256")).write_text(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    return f


class Fake:
    def __init__(self, remote_sum: str | None = None, fail_scp: bool = False):
        self.calls: list[list[str]] = []
        self.remote_sum, self.fail_scp = remote_sum, fail_scp

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        out = ""
        if cmd[0] == "scp" and self.fail_scp:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if cmd[0] == "ssh" and "sha256sum" in cmd[-1]:
            out = f"{self.remote_sum}  x\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")


def args(tmp: Path, cmd: str, *extra: str) -> list[str]:
    return [cmd, "--dir", str(tmp), "--target", "u@h", "--remote-dir", "tim-backup", *extra]


def test_files_upload_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(off, "REPORT_PATH", tmp_path / "r.json")
    make_backup(tmp_path, "tim_files_20261117T020000Z.tar.gz")
    fake = Fake(hashlib.sha256(b"abc").hexdigest())
    assert off.main(args(tmp_path, "files"), fake) == 0
    assert any("mv " in c[-1] for c in fake.calls if c[0] == "ssh")


def test_remote_mismatch_fails_and_removes_copy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(off, "REPORT_PATH", tmp_path / "r.json")
    make_backup(tmp_path, "tim_files_20261117T020000Z.tar.gz")
    fake = Fake("0" * 64)
    assert off.main(args(tmp_path, "files"), fake) == 2
    assert not any("mv " in c[-1] for c in fake.calls if c[0] == "ssh")
    assert any("rm -f" in c[-1] for c in fake.calls if c[0] == "ssh")


def test_corrupt_local_file_is_not_uploaded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(off, "REPORT_PATH", tmp_path / "r.json")
    f = make_backup(tmp_path, "tim_files_20261117T020000Z.tar.gz")
    f.write_bytes(b"changed")
    fake = Fake()
    assert off.main(args(tmp_path, "files"), fake) == 2
    assert fake.calls == []


def test_dump_refused_without_encryption(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(off, "REPORT_PATH", tmp_path / "r.json")
    make_backup(tmp_path, "tim_20261117T020000Z.dump")
    fake = Fake()
    assert off.main(args(tmp_path, "dump"), fake) == 2
    assert fake.calls == []


def test_unsafe_remote_dir_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(off, "REPORT_PATH", tmp_path / "r.json")
    make_backup(tmp_path, "tim_files_20261117T020000Z.tar.gz")
    fake = Fake()
    code = off.main(["files", "--dir", str(tmp_path), "--target", "u@h", "--remote-dir", "x; rm -rf /"], fake)
    assert code == 2 and fake.calls == []
