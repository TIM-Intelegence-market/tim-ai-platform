"""Isolated positive and negative tests for the INFRA-09 §11 identity guard.

No real mount, no root: findmnt/blkid are replaced by a fake runner; the image check runs on a
real ext4 image file built with mkfs.ext4 (nothing mounted).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from src.archive_sync import mount_guard as g

PARENT = "/var/lib/warpgate"
MNT = "/srv/tim-archive-tmp"
GOOD = "0f1e2d3c-4b5a-4697-8877-665544332211"  # fixed: xdist needs identical test ids
OTHER = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


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
    first_effect = min(_first(lines, x) for x in ("adduser --system", "install -d -m 0711", "fallocate -l", "mkfs.ext4 -q", ">> /etc/fstab"))
    assert _first(lines, "$GUARD parent") < first_effect
    assert _first(lines, "$GUARD reserve --parent /var/lib/warpgate") < first_effect
    assert _first(lines, "test ! -e \"$IMG_DIR\"") < first_effect
    mkfs = _first(lines, "mkfs.ext4 -q")
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

def _run_ownership(root):
    lines = _section_11()
    start = _first(lines, "test -d /opt/tim")
    end = _first(lines, 'test -z "$unsafe_entry"')
    script = "\n".join(lines[start:end + 1]).replace("/opt/tim", str(root))
    return subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], capture_output=True).returncode


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


# The documented plan is executable test input. All its paths are rebased into
# tmp_path and every external command is replaced before running Bash.
_SETUP_STEPS = (
    "find", "guard:parent", "guard:reserve", "df", "tail",
    "getent:passwd", "getent:group", "awk", "adduser",
    "install", "fallocate", "chmod", "stat:%b", "stat:%B", "stat:%s",
    "guard:parent", "cat:kernel", "chmod", "cat:archive", "mkfs.ext4",
    "guard:image", "install", "chattr", "systemctl", "guard:parent", "mount",
    "guard:archive", "guard:parent", "guard:reserve", "chown", "chmod",
    "install", "sudo", "cat:script", "chmod",
)
_RUNTIME_STEPS = ("find", "guard:parent", "guard:image", "guard:archive", "guard:reserve")
_PLAN_STEPS = _SETUP_STEPS + _RUNTIME_STEPS
_POST_MOUNT_CHECKS = range(27, 30)
_FIRST_EFFECT = 9  # adduser
_STUBS = r"""
record() {
    printf '%s\n' "$1" >> "$TRACE"
    local count=0
    while IFS= read -r line; do ((count += 1)); done < "$TRACE"
    test "$count" -ne "$FAIL_STEP" || return 73
    test "$1" != umount || test "$FAIL_UNMOUNT" != 1 || return 74
}
getent() {
    record "getent:$1" || return
    case "$1" in
        passwd) return "$GETENT_PASSWD_RC" ;;
        group) return "$GETENT_GROUP_RC" ;;
        *) return 75 ;;
    esac
}
awk() {
    record awk || return
    "$REAL_AWK" "$@"
}
find() {
    record find || return
    if [[ $FIND_RESULT == unsafe ]]; then printf '%s\n' 'unsafe entry'; fi
}
df() {
    # A partial result can contain a usable-looking number even on error.
    printf 'Avail\n%s\n' "$AVAILABLE_BYTES"
    record df
}
tail() {
    local line last=''
    while IFS= read -r line; do last=$line; done
    printf '%s\n' "$last"
    record tail
}
stat() {
    case "$2" in
        %b) printf '%s\n' "$ALLOCATED_BLOCKS" ;;
        %B) printf '512\n' ;;
        %s) printf '34359738368\n' ;;
        *) return 75 ;;
    esac
    record "stat:$2"
}
cat() {
    case "${1-}" in
        */proc/sys/kernel/random/uuid) printf '%s\n' "$TEST_UUID"; record cat:kernel ;;
        */archive-volume.uuid) printf '%s\n' "$TEST_UUID"; record cat:archive ;;
        '')
            record cat:script || return
            local line
            while IFS= read -r line; do printf '%s\n' "$line"; done
            ;;
        *) return 75 ;;
    esac
}
findmnt() { return 75; }
blkid() { return 75; }
adduser() { record adduser; }
install() { record install; }
fallocate() { record fallocate; }
chmod() { record chmod; }
mkfs.ext4() { record mkfs.ext4; }
chattr() { record chattr; }
systemctl() { record systemctl; }
mount() { record mount; }
umount() { record umount; }
chown() { record chown; }
sudo() { record sudo; }
"""


def _run_section_11(tmp_path, *, fail_step=0, fail_unmount=False, before_run=None, **overrides):
    bash = shutil.which("bash")
    assert bash is not None
    for directory in ("opt/tim/.venv/bin", "etc/tim", "usr/local/sbin", "srv"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "etc/fstab").write_text("# leer\nUUID=x / ext4 defaults 0 1\n")
    trace = tmp_path / "trace"
    trace.touch()
    stubs = tmp_path / "stubs"
    stubs.write_text(_STUBS)
    python = tmp_path / "opt/tim/.venv/bin/python"
    python.write_text(f'#!{bash}\nsource "$STUBS"\nrecord "guard:$3"\n')
    python.chmod(0o700)

    lines = _section_11()
    replacements = ("/opt/tim", "/var/lib/warpgate", "/srv/tim-archive-tmp", "/etc/",
                    "/proc/sys/kernel/random/uuid", "/usr/local/sbin/tim-archive-guard",
                    "/usr/local/sbin")
    # Rebase the fixed paths before executing any of the documented steps.
    paths = re.compile("|".join(re.escape(path) for path in replacements))
    script = paths.sub(lambda match: f"{tmp_path}{match[0]}", "\n".join(lines))
    guard = tmp_path / "usr/local/sbin/tim-archive-guard"
    script = script.replace(f"\n{guard}", f'\n"{bash}" "{guard}"')
    # $EUID is read-only in Bash; the tests run the root check against a stand-in.
    assert script.count('test "$EUID" -eq 0') == 1
    script = script.replace('test "$EUID" -eq 0', 'test "$TEST_EUID" -eq 0')
    env = {
        "PATH": str(tmp_path / "empty-path"),
        "BASH_ENV": str(stubs),
        "STUBS": str(stubs),
        "TRACE": str(trace),
        "FAIL_STEP": str(fail_step),
        "FAIL_UNMOUNT": str(int(fail_unmount)),
        "FIND_RESULT": "safe",
        "AVAILABLE_BYTES": "325000000000",
        "ALLOCATED_BLOCKS": "67108864",
        "TEST_UUID": GOOD,
        "TEST_EUID": "0",
        "GETENT_PASSWD_RC": "2",
        "GETENT_GROUP_RC": "2",
        "REAL_AWK": shutil.which("awk") or "/usr/bin/awk",
        **overrides,
    }
    if before_run is not None:
        before_run(tmp_path)
    result = subprocess.run([bash, "-c", script], cwd=tmp_path, env=env, capture_output=True, timeout=10)
    return result, trace.read_text().splitlines()


def test_section_11_accepts_successful_setup_and_runtime_checks(tmp_path):
    result, steps = _run_section_11(tmp_path)
    assert result.returncode == 0, result.stderr
    assert steps == list(_PLAN_STEPS)


@pytest.mark.parametrize("step", range(1, len(_PLAN_STEPS) + 1),
                         ids=[f"{index}-{name}" for index, name in enumerate(_PLAN_STEPS, 1)])
def test_section_11_stops_after_a_failed_command(tmp_path, step):
    result, steps = _run_section_11(tmp_path, fail_step=step)
    expected = list(_PLAN_STEPS[:step])
    if step in _POST_MOUNT_CHECKS:
        expected.append("umount")
    assert result.returncode != 0
    # Both pipeline stages start even when one exits nonzero.
    if step == 4:
        expected.append("tail")
    assert steps == expected


def test_section_11_stops_even_if_post_mount_cleanup_fails(tmp_path):
    result, steps = _run_section_11(tmp_path, fail_step=27, fail_unmount=True)
    assert result.returncode != 0
    assert steps == [*_PLAN_STEPS[:27], "umount"]


@pytest.mark.parametrize(("overrides", "last_step"), [
    ({"FIND_RESULT": "unsafe"}, 1),
    ({"AVAILABLE_BYTES": "299999999999"}, 5),
    ({"ALLOCATED_BLOCKS": "67108863"}, 15),
    ({"TEST_UUID": "invalid"}, 19),
    ({"TEST_EUID": "1000"}, 0),
    ({"GETENT_PASSWD_RC": "0"}, 6),   # account exists already
    ({"GETENT_PASSWD_RC": "1"}, 6),   # lookup error is not "absent"
    ({"GETENT_PASSWD_RC": "3"}, 6),
    ({"GETENT_GROUP_RC": "0"}, 7),
    ({"GETENT_GROUP_RC": "1"}, 7),
])
def test_section_11_rejects_unsuitable_inputs(tmp_path, overrides, last_step):
    result, steps = _run_section_11(tmp_path, **overrides)
    assert result.returncode != 0
    assert steps == list(_PLAN_STEPS[:last_step])


@pytest.mark.parametrize(("path", "last_step"), [
    ("var/lib/warpgate/tim-archive-img", 5),
    ("srv/tim-archive-tmp", 5),
    ("etc/tim/archive-volume.uuid", 5),
    ("etc/fstab", 7),  # Directory in place of the fstab file.
    ("usr/local/sbin/tim-archive-guard", 5),
])
def test_section_11_rejects_blocked_paths(tmp_path, path, last_step):
    def block_path(root):
        if (root / path).is_file():
            (root / path).unlink()
        (root / path).mkdir(parents=True)

    result, steps = _run_section_11(tmp_path, before_run=block_path)
    assert result.returncode != 0
    assert steps == list(_PLAN_STEPS[:last_step])


def test_section_11_rejects_missing_required_command(tmp_path):
    def remove_command(root):
        stubs = root / "stubs"
        with stubs.open("a") as script:
            script.write("\nunset -f blkid\n")

    result, steps = _run_section_11(tmp_path, before_run=remove_command)
    assert result.returncode != 0
    assert steps == ["find"]


def test_section_11_rejects_blocked_regular_files_and_links(tmp_path):
    """An existing regular file or a dangling link counts as an existing target."""
    def guard_file(root):
        (root / "usr/local/sbin/tim-archive-guard").write_text("#!/bin/bash\nexit 0\n")

    def dangling(name):
        def make(root):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).symlink_to(root / "nowhere")
        return make

    for before_run in (guard_file, dangling("usr/local/sbin/tim-archive-guard"),
                       dangling("srv/tim-archive-tmp"), dangling("etc/tim/archive-volume.uuid"),
                       dangling("var/lib/warpgate/tim-archive-img")):
        root = tmp_path / before_run.__name__ / str(id(before_run))
        root.mkdir(parents=True)
        result, steps = _run_section_11(root, before_run=before_run)
        assert result.returncode != 0
        assert steps == list(_PLAN_STEPS[:5])


@pytest.mark.parametrize("fstab", [
    "{img} {mnt} ext4 loop 0 2\n",
    "/other {mnt} ext4 defaults 0 2\n",
    "/other {mnt}/ ext4 defaults 0 2\n",
    "{img} /elsewhere ext4 loop 0 2\n",
    "   {img}\t{mnt}\text4 loop 0 2\n",
])
def test_section_11_rejects_existing_fstab_entry(tmp_path, fstab):
    def write(root):
        img = root / "var/lib/warpgate/tim-archive-img/archive.img"
        (root / "etc/fstab").write_text(fstab.format(img=img, mnt=root / "srv/tim-archive-tmp"))

    result, steps = _run_section_11(tmp_path, before_run=write)
    assert result.returncode != 0
    assert steps == list(_PLAN_STEPS[:8])


def test_section_11_accepts_commented_old_fstab_entry(tmp_path):
    def write(root):
        img = root / "var/lib/warpgate/tim-archive-img/archive.img"
        (root / "etc/fstab").write_text(f"# {img} {root / 'srv/tim-archive-tmp'} ext4 loop 0 2\n")

    result, steps = _run_section_11(tmp_path, before_run=write)
    assert result.returncode == 0, result.stderr
    assert steps == list(_PLAN_STEPS)


@pytest.mark.parametrize("change", ["missing_fstab", "fstab_link", "missing_srv", "srv_link", "missing_etc_tim"])
def test_section_11_rejects_unreliable_parents(tmp_path, change):
    def apply(root):
        if change == "missing_fstab":
            (root / "etc/fstab").unlink()
        elif change == "fstab_link":
            real = root / "fstab.real"
            (root / "etc/fstab").rename(real)
            (root / "etc/fstab").symlink_to(real)
        elif change == "missing_srv":
            (root / "srv").rmdir()
        elif change == "srv_link":
            (root / "srv").rmdir()
            (root / "srv-real").mkdir()
            (root / "srv").symlink_to(root / "srv-real")
        else:
            shutil.rmtree(root / "etc/tim")

    result, steps = _run_section_11(tmp_path, before_run=apply)
    assert result.returncode != 0
    assert len(steps) < _FIRST_EFFECT
    assert "adduser" not in steps


def test_section_11_every_target_check_precedes_first_side_effect():
    lines = _section_11()
    first_effect = _first(lines, "adduser --system")
    for needle in ('test ! -e "$IMG_DIR"', 'test ! -e "$MNT"', 'test ! -e "$ARCH_UUID_FILE"',
                   "test ! -e /usr/local/sbin/tim-archive-guard", "getent passwd tim-archive",
                   "getent group tim-archive", "test -f /etc/fstab", 'test -z "$fstab_hits"',
                   'test "$EUID" -eq 0'):
        assert _first(lines, needle) < first_effect, needle
    # No negated command as a precondition: "! cmd" is exempt from errexit.
    assert not any(line.startswith("! ") for line in lines[:first_effect])


def test_section_11_rollback_note_does_not_expect_empty_fuser():
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath("docs/ARCHIV_WARPGATE_UEBERGANG.md").read_text("utf-8")
    assert "fuser -vm /srv/tim-archive-tmp      # darf nichts zeigen" not in text
    assert "root kernel mount" in text
