"""Isolated positive and negative tests for the INFRA-09 §11 identity guard.

No real mount, no root: findmnt/blkid are replaced by a fake runner; the image check runs on a
real ext4 image file built with mkfs.ext4 (nothing mounted).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from src.archive_sync import mount_guard as g

PARENT = "/var/lib/warpgate"
MNT = "/srv/tim-archive-tmp"
GOOD = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def runner_for(mounts: dict, uuids: dict):
    """mounts: target -> findmnt entry (or list for stacked); uuids: source -> blkid output."""
    calls = []

    def run(argv):
        calls.append(list(argv))
        if argv[0] == "findmnt":
            target = argv[argv.index("--mountpoint") + 1]
            if target not in mounts:
                raise g.GuardError("findmnt failed (exit 1)")
            value = mounts[target]
            return json.dumps({"filesystems": value if isinstance(value, list) else [value]})
        if argv[0] == "blkid":
            if argv[-1] not in uuids:
                raise g.GuardError("blkid failed (exit 2)")
            return uuids[argv[-1]] + "\n"
        raise AssertionError(argv)

    run.calls = calls
    return run


def parent_entry(**kw):
    entry = {"target": PARENT, "source": "/dev/mapper/warpgate_crypt", "fstype": "ext4", "options": "rw,relatime"}
    entry.update(kw)
    return entry


# --- parent -----------------------------------------------------------------------------------

def test_parent_pass_with_expected_identity():
    r = g.check_parent(PARENT, GOOD, "ext4", runner_for({PARENT: parent_entry()}, {"/dev/mapper/warpgate_crypt": GOOD}))
    assert r.ok, r.reasons


def test_parent_uses_exact_mountpoint_and_low_level_probe():
    run = runner_for({PARENT: parent_entry()}, {"/dev/mapper/warpgate_crypt": GOOD})
    g.check_parent(PARENT, GOOD, "ext4", run)
    assert run.calls[0][:4] == ["findmnt", "--json", "--mountpoint", PARENT]
    assert run.calls[1][:2] == ["blkid", "-p"]


@pytest.mark.parametrize("mounts,uuids,why", [
    ({}, {}, "not a mount point"),                                                          # missing mount
    ({PARENT: parent_entry()}, {"/dev/mapper/warpgate_crypt": OTHER}, "mismatch"),           # wrong disk
    ({PARENT: parent_entry()}, {}, "unreadable"),                                           # UUID unknown
    ({PARENT: parent_entry()}, {"/dev/mapper/warpgate_crypt": "not-a-uuid"}, "unreadable"),
    ({PARENT: parent_entry(fstype="tmpfs")}, {"/dev/mapper/warpgate_crypt": GOOD}, "type"),  # wrong fs
    ({PARENT: parent_entry(options="ro,relatime")}, {"/dev/mapper/warpgate_crypt": GOOD}, "read-write"),
    ({PARENT: parent_entry(target="/var/lib")}, {"/dev/mapper/warpgate_crypt": GOOD}, "exactly"),
    ({PARENT: [parent_entry(), parent_entry(source="/dev/sdz1")]}, {"/dev/mapper/warpgate_crypt": GOOD}, "exactly one"),
    ({PARENT: []}, {}, "exactly one"),
    ({PARENT: parent_entry(source="")}, {}, "source unknown"),
])
def test_parent_negative_cases_fail(mounts, uuids, why):
    r = g.check_parent(PARENT, GOOD, "ext4", runner_for(mounts, uuids))
    assert not r.ok
    assert why in " ".join(r.reasons)


def test_parent_garbage_findmnt_output_fails():
    r = g.check_parent(PARENT, GOOD, "ext4", lambda argv: "not json")
    assert not r.ok


def test_reasons_never_contain_a_uuid():
    r = g.check_parent(PARENT, GOOD, "ext4", runner_for({PARENT: parent_entry()}, {"/dev/mapper/warpgate_crypt": OTHER}))
    text = json.dumps(r.as_dict())
    assert GOOD not in text and OTHER not in text


# --- expected-UUID file -----------------------------------------------------------------------

def _uuid_file(tmp_path, content=GOOD, mode=0o600):
    path = tmp_path / "expected.uuid"
    path.write_text(content + "\n")
    os.chmod(path, mode)
    return path


def test_uuid_file_ok_without_root_requirement(tmp_path):
    assert g.load_expected_uuid(_uuid_file(tmp_path), require_root=False) == GOOD


@pytest.mark.parametrize("content,mode", [("", 0o600), ("garbage", 0o600), (GOOD + "\n" + OTHER, 0o600),
                                          (GOOD, 0o644), (GOOD, 0o660)])
def test_uuid_file_bad_content_or_mode_fails(tmp_path, content, mode):
    with pytest.raises(g.GuardError):
        g.load_expected_uuid(_uuid_file(tmp_path, content, mode), require_root=False)


def test_uuid_file_symlink_and_missing_fail(tmp_path):
    real = _uuid_file(tmp_path)
    link = tmp_path / "link.uuid"
    link.symlink_to(real)
    with pytest.raises(g.GuardError):
        g.load_expected_uuid(link, require_root=False)
    with pytest.raises(g.GuardError):
        g.load_expected_uuid(tmp_path / "absent", require_root=False)


@pytest.mark.skipif(os.geteuid() == 0, reason="needs a non-root owner")
def test_uuid_file_not_owned_by_root_fails_by_default(tmp_path):
    with pytest.raises(g.GuardError):
        g.load_expected_uuid(_uuid_file(tmp_path))


# --- image (real ext4 image file, nothing mounted) --------------------------------------------

needs_mkfs = pytest.mark.skipif(shutil.which("mkfs.ext4") is None, reason="mkfs.ext4 not installed")
SMALL = 8 * 1024 * 1024


def _image(tmp_path, fs_uuid=GOOD, allocated=True):
    img = tmp_path / "archive.img"
    with open(img, "wb") as handle:
        if allocated:
            os.posix_fallocate(handle.fileno(), 0, SMALL)
        else:
            handle.truncate(SMALL)
    subprocess.run(["mkfs.ext4", "-q", "-F", "-m", "0", "-E", "nodiscard", "-U", fs_uuid, str(img)], check=True)
    return img


@needs_mkfs
def test_image_pass_and_superblock_uuid(tmp_path):
    img = _image(tmp_path)
    assert g.read_ext4_uuid(img) == GOOD
    r = g.check_image(str(img), GOOD, expected_bytes=SMALL)
    assert r.ok, r.reasons


@needs_mkfs
def test_image_wrong_uuid_size_or_sparse_fails(tmp_path):
    img = _image(tmp_path)
    assert "mismatch" in " ".join(g.check_image(str(img), OTHER, expected_bytes=SMALL).reasons)
    assert not g.check_image(str(img), GOOD, expected_bytes=2 * SMALL).ok
    sparse_dir = tmp_path / "sparse"
    sparse_dir.mkdir()
    sparse = _image(sparse_dir, allocated=False)
    assert not g.check_image(str(sparse), GOOD, expected_bytes=SMALL).ok


def test_image_missing_symlink_or_not_ext4_fails(tmp_path):
    assert not g.check_image(str(tmp_path / "absent"), GOOD).ok
    plain = tmp_path / "plain.img"
    with open(plain, "wb") as handle:
        os.posix_fallocate(handle.fileno(), 0, SMALL)
    assert g.read_ext4_uuid(plain) is None
    assert not g.check_image(str(plain), GOOD, expected_bytes=SMALL).ok
    link = tmp_path / "link.img"
    link.symlink_to(plain)
    assert not g.check_image(str(link), GOOD, expected_bytes=SMALL).ok
    assert g.read_ext4_uuid(link) is None


# --- archive mount ----------------------------------------------------------------------------

IMG = "/var/lib/warpgate/tim-archive-img/archive.img"


def _sys_block(tmp_path, loop="loop7", backing=IMG):
    d = tmp_path / "sys" / loop / "loop"
    d.mkdir(parents=True)
    (d / "backing_file").write_text(backing + "\n")
    return str(tmp_path / "sys")


def archive_entry(**kw):
    entry = {"target": MNT, "source": "/dev/loop7", "fstype": "ext4",
             "options": "rw,nosuid,nodev,noexec,noatime"}
    entry.update(kw)
    return entry


def test_archive_pass(tmp_path):
    r = g.check_archive(MNT, IMG, GOOD, runner_for({MNT: archive_entry()}, {"/dev/loop7": GOOD}), _sys_block(tmp_path))
    assert r.ok, r.reasons


@pytest.mark.parametrize("entry,uuids,backing,why", [
    (None, {"/dev/loop7": GOOD}, IMG, "not a mount point"),                     # archive not mounted
    (archive_entry(), {"/dev/loop7": OTHER}, IMG, "mismatch"),                  # wrong file system
    (archive_entry(), {}, IMG, "unreadable"),
    (archive_entry(), {"/dev/loop7": GOOD}, "/tmp/other.img", "approved image"),  # other image
    (archive_entry(), {"/dev/loop7": GOOD}, IMG + " (deleted)", "approved image"),
    (archive_entry(source="/dev/sdb1"), {"/dev/sdb1": GOOD}, IMG, "approved image"),  # not a loop
    (archive_entry(fstype="xfs"), {"/dev/loop7": GOOD}, IMG, "not ext4"),
    (archive_entry(options="rw,nosuid,nodev"), {"/dev/loop7": GOOD}, IMG, "noexec"),
    (archive_entry(options="ro,nosuid,nodev,noexec"), {"/dev/loop7": GOOD}, IMG, "read-write"),
    (archive_entry(options="rw,ro,nosuid,nodev,noexec"), {"/dev/loop7": GOOD}, IMG, "read-write"),
    (archive_entry(), {"/dev/loop7": GOOD}, "/var/lib/warpgate/./tim-archive-img/archive.img", "approved image"),
    (archive_entry(source="/dev/loop7p1"), {"/dev/loop7p1": GOOD}, IMG, "approved image"),
    (archive_entry(children=[{"target": MNT}]), {"/dev/loop7": GOOD}, IMG, "exactly"),
])
def test_archive_negative_cases_fail(tmp_path, entry, uuids, backing, why):
    mounts = {} if entry is None else {MNT: entry}
    r = g.check_archive(MNT, IMG, GOOD, runner_for(mounts, uuids), _sys_block(tmp_path, backing=backing))
    assert not r.ok
    assert why in " ".join(r.reasons)


# --- reserve (§10 numbers) --------------------------------------------------------------------

SIZE = 391_999_193_088
AVAIL_26_11 = 324_995_493_888


def test_reserve_pass_before_and_after_allocation():
    assert g.check_reserve(SIZE, AVAIL_26_11, image_allocated=False).ok
    assert g.check_reserve(SIZE, AVAIL_26_11 - g.IMAGE_BYTES, image_allocated=True).ok


def test_reserve_fails_for_100_gib_or_restore_growth_or_low_disk():
    assert not g.check_reserve(SIZE, AVAIL_26_11, image_allocated=False, image_bytes=100 * g.GIB).ok
    assert not g.check_reserve(SIZE, AVAIL_26_11, image_allocated=False,
                               restore_need=int(g.RESTORE_NEED_BYTES * 1.12)).ok
    assert not g.check_reserve(SIZE, 200_000_000_000, image_allocated=False).ok


def test_reserve_store_limit_above_85_percent_fails():
    assert not g.check_reserve(SIZE, AVAIL_26_11, image_allocated=False, store_limit=28 * g.GIB).ok


@pytest.mark.parametrize("size,avail", [(None, 1), (1, None), (0, 0), (10, 11), (10, -1), (True, 1)])
def test_reserve_missing_or_implausible_fails(size, avail):
    assert not g.check_reserve(size, avail, image_allocated=False).ok


# --- CLI: exit code 0 only on PASS ------------------------------------------------------------

@pytest.fixture(autouse=True)
def _test_only_owner_relax(monkeypatch):
    monkeypatch.setenv(g.TEST_ENV, "1")


def test_cli_without_test_env_requires_root_owned_uuid_file(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(g.TEST_ENV)
    path = _uuid_file(tmp_path)
    code = g.main(["parent", "--target", str(tmp_path), "--expected-uuid-file", str(path)])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    if os.geteuid() != 0:
        assert "not owned by root" in " ".join(out["reasons"])


def test_cli_has_no_weakening_switches():
    with pytest.raises(SystemExit):
        g.main(["reserve", "--parent", "/", "--restore-need-bytes", "1"])
    with pytest.raises(SystemExit):
        g.main(["parent", "--target", "/", "--expected-uuid-file", "/x", "--allow-non-root-uuid-file"])


def test_runner_errors_become_guard_errors():
    with pytest.raises(g.GuardError):
        g._run(["/nonexistent/findmnt-xyz"])
    with pytest.raises(g.GuardError):
        g._run(["false"])


def test_reserve_exact_15_percent_boundary():
    size = 1_000_000_000_000
    need = int(g.RESTORE_NEED_BYTES * (1 + g.RESTORE_GROWTH_MARGIN))
    exact = int(size * g.MIN_FREE_SHARE) + g.IMAGE_BYTES + need
    assert g.check_reserve(size, exact, image_allocated=False).ok
    assert not g.check_reserve(size, exact - 1, image_allocated=False).ok


def test_cli_fails_closed_on_missing_uuid_file(tmp_path, capsys):
    code = g.main(["parent", "--target", str(tmp_path), "--expected-uuid-file", str(tmp_path / "absent"),
                   ])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["result"] == "FAIL"


def test_cli_parent_on_non_mountpoint_fails(tmp_path, capsys):
    if shutil.which("findmnt") is None:
        pytest.skip("findmnt not installed")
    path = _uuid_file(tmp_path)
    code = g.main(["parent", "--target", str(tmp_path), "--expected-uuid-file", str(path),
                   ])
    assert code == 1
    assert GOOD not in capsys.readouterr().out


@needs_mkfs
def test_cli_image_pass_and_fail(tmp_path, capsys, monkeypatch):
    img = _image(tmp_path)
    monkeypatch.setitem(g.check_image.__kwdefaults__, "expected_bytes", SMALL)
    good = _uuid_file(tmp_path)
    assert g.main(["image", "--image", str(img), "--expected-uuid-file", str(good)]) == 0
    other_dir = tmp_path / "o"
    other_dir.mkdir()
    bad = _uuid_file(other_dir, OTHER)
    assert g.main(["image", "--image", str(img), "--expected-uuid-file", str(bad)]) == 1
    assert GOOD not in capsys.readouterr().out


def test_cli_reserve_on_small_tmp_fails(tmp_path):
    # A small test file system cannot hold 32 GiB plus the restore need: must be FAIL, never PASS.
    size, avail = g._statvfs(str(tmp_path))
    if size and avail and avail > 300 * 10**9:
        pytest.skip("unusually large test disk")
    assert g.main(["reserve", "--parent", str(tmp_path)]) == 1


def test_guard_never_writes(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    g.check_reserve(*g._statvfs(str(tmp_path)), image_allocated=False)
    g.check_image(str(tmp_path / "absent"), GOOD)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# --- §11 shell plan: every guard before the side effect it protects ---------------------------

def _section_11():
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath("docs/ARCHIV_WARPGATE_UEBERGANG.md").read_text("utf-8")
    block = text.split("## 11 ", 1)[1].split("## 12 ", 1)[0]
    code = block.split("```", 2)[1]
    return [line.strip() for line in code.splitlines() if line.strip() and not line.strip().startswith("#")]


def _first(lines, needle):
    for index, line in enumerate(lines):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} missing in §11")


def test_section_11_order_guards_before_side_effects():
    lines = _section_11()
    first_effect = min(_first(lines, x) for x in ("adduser", "install -d -m 0711", "fallocate", "mkfs.ext4", ">> /etc/fstab"))
    assert _first(lines, "$GUARD parent") < first_effect
    assert _first(lines, "$GUARD reserve --parent /var/lib/warpgate") < first_effect
    assert _first(lines, "test ! -e \"$IMG_DIR\"") < first_effect
    mkfs = _first(lines, "mkfs.ext4")
    mount = _first(lines, 'mount "$MNT"')
    assert mkfs < _first(lines, "$GUARD image") < mount
    after_mount = [i for i, line in enumerate(lines) if "$GUARD archive" in line]
    assert after_mount and after_mount[0] > mount
    # The three post-mount checks sit in one block that unmounts on any failure.
    bail = next(i for i in range(mount, len(lines)) if 'umount "$MNT"; exit 1' in lines[i])
    block = " ".join(lines[after_mount[0]:bail + 1])
    assert lines[after_mount[0]].startswith("if ! {")
    for needle in ("$GUARD archive", "$GUARD parent", "$GUARD reserve --parent /var/lib/warpgate --image-allocated"):
        assert needle in block
    assert _first(lines, "find /opt/tim") < first_effect
    assert _first(lines, "cold-init") > after_mount[0]


def test_section_11_no_old_identity_check_and_no_uuid_in_doc():
    import re
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath("docs/ARCHIV_WARPGATE_UEBERGANG.md").read_text("utf-8")
    lines = _section_11()
    assert not any(line.startswith("findmnt -no TARGET /var/lib/warpgate") for line in lines)
    assert not any("> /etc/tim/archive-volume.uuid" in line and "findmnt" in line for line in lines)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
    assert "--restore-need-bytes" not in text and "--allow-non-root-uuid-file" not in text


# --- §11 ownership line for /opt/tim, run for real on a fresh venv ---------------------------

def _ownership_line():
    for line in _section_11():
        if "find /opt/tim" in line:
            return line
    raise AssertionError("ownership check missing in §11")


def _run_ownership(root):
    import subprocess as sp
    line = _ownership_line().replace("/opt/tim", str(root))
    return sp.run(["bash", "-c", "set -euo pipefail; " + line], capture_output=True).returncode


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to own the tree like /opt/tim")
def test_ownership_line_accepts_standard_venv_and_rejects_writable_or_foreign(tmp_path):
    import subprocess as sp
    import sys
    root = tmp_path / "opt-tim"
    (root / "src").mkdir(parents=True)
    (root / "src" / "m.py").write_text("x = 1\n")
    os.chmod(tmp_path, 0o755)
    sp.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True)
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
    assert any(p.is_symlink() for p in (root / ".venv" / "bin").iterdir())
    assert _run_ownership(root) == 0
    os.chmod(root / "src" / "m.py", 0o664)
    assert _run_ownership(root) != 0
    os.chmod(root / "src" / "m.py", 0o644)
    os.chown(root / "src" / "m.py", 65534, 65534)
    assert _run_ownership(root) != 0
    os.chown(root / "src" / "m.py", 0, 0)
    assert _run_ownership(tmp_path / "missing") != 0
    link = tmp_path / "linked"
    link.symlink_to(root)
    assert _run_ownership(link) != 0


def test_test_env_never_relaxes_for_root(tmp_path, monkeypatch, capsys):
    if os.geteuid() != 0:
        pytest.skip("root only")
    path = _uuid_file(tmp_path)
    os.chown(path, 65534, 65534)
    code = g.main(["parent", "--target", str(tmp_path), "--expected-uuid-file", str(path)])
    assert code == 1
    assert "not owned by root" in capsys.readouterr().out
