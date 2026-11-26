"""Fail-closed identity guard for the INFRA-09 interim archive (§11 of ARCHIV_WARPGATE_UEBERGANG.md).

Fixes the §11 finding: ``findmnt -no TARGET /var/lib/warpgate`` only proves that *something* is
mounted there, not that it is the expected Warpgate file system. This guard proves identity:

* ``parent``  - the Warpgate mount point is a mount point *exactly* (``--mountpoint``), carries the
  expected file system type and the expected file system UUID (low-level probe of the device,
  ``blkid -p``, no cache), and is mounted read-write.
* ``image``   - the image file is a regular file (no symlink), fully allocated, and its ext4 superblock
  carries the expected UUID (read directly from the file, nothing mounted).
* ``archive`` - the archive mount point is mounted exactly, is ext4, is backed by a loop device whose
  backing file is the expected image, and the mounted file system has the expected UUID.
* ``reserve`` - 15 % of the parent file system stays free after the 32-GiB image and during the
  Sunday restore test; the store limit stays below 85 % of the usable image.

The expected UUIDs come from root-only files (0600, owner root, no symlink) filled from the
authorised read-only inventory. The guard never prints a UUID, only ``match``/``mismatch``.
Every unknown, unreadable or ambiguous state is a FAIL; exit code 0 means PASS and nothing else.
The guard only reads. ``TRADING_AUTHORIZED=NO``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

GIB = 1024**3
IMAGE_BYTES = 32 * GIB
STORE_LIMIT_BYTES = 26 * GIB
MIN_FREE_SHARE = 0.15
# Last measured restore need (22.11.2026, PASS): 2 x database + 8 GiB. Plus 5 % growth margin.
RESTORE_NEED_BYTES = 208_662_998_398
RESTORE_GROWTH_MARGIN = 0.05
# ext4 with -m 0 keeps roughly 98.4 % of the image usable (measured basis of §10: ~31.5 GiB).
EXT4_USABLE_SHARE = 0.984

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EXT4_MAGIC = 0xEF53
_SUPERBLOCK_OFFSET = 1024

TEST_ENV = "TIM_MOUNT_GUARD_TEST_ONLY"

Runner = Callable[[Sequence[str]], str]


@dataclass
class GuardResult:
    check: str
    ok: bool
    reasons: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"check": self.check, "result": "PASS" if self.ok else "FAIL", "reasons": self.reasons}


class GuardError(Exception):
    """A state that must stop everything. Messages never contain a UUID."""


def _run(argv: Sequence[str]) -> str:
    try:
        completed = subprocess.run(list(argv), check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise GuardError(f"{argv[0]} not runnable") from None
    if completed.returncode != 0:
        raise GuardError(f"{argv[0]} failed (exit {completed.returncode})")
    return completed.stdout


def normalise_uuid(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if _UUID.fullmatch(text) else None


def load_expected_uuid(path: str | Path, *, require_root: bool = True) -> str:
    """Read an expected UUID from a protected file. Refuses links, group/other access and bad content."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        raise GuardError("expected-UUID file missing, unreadable or a symlink") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise GuardError("expected-UUID file is not a regular file")
        if info.st_mode & 0o077:
            raise GuardError("expected-UUID file is accessible by group or others (needs 0600)")
        if require_root and info.st_uid != 0:
            raise GuardError("expected-UUID file is not owned by root")
        raw = os.read(fd, 128)
    finally:
        os.close(fd)
    found = normalise_uuid(raw.decode("ascii", errors="replace"))
    if found is None:
        raise GuardError("expected-UUID file does not hold exactly one UUID")
    return found


def read_ext4_uuid(image: str | Path) -> Optional[str]:
    """UUID from the ext4 superblock of an image file, without mounting. None if not ext4."""
    try:
        fd = os.open(str(image), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        block = os.pread(fd, 1024, _SUPERBLOCK_OFFSET)
    finally:
        os.close(fd)
    if len(block) < 0x78 or int.from_bytes(block[0x38:0x3A], "little") != _EXT4_MAGIC:
        return None
    raw = block[0x68:0x78].hex()
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def _exact_mount(target: str, runner: Runner) -> dict:
    """The single mount whose mount point is exactly ``target`` (no parent fallback)."""
    try:
        data = json.loads(runner(["findmnt", "--json", "--mountpoint", target,
                                  "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"]))
    except GuardError:
        raise GuardError(f"{target} is not a mount point") from None
    except (ValueError, TypeError):
        raise GuardError("findmnt output unreadable") from None
    systems = data.get("filesystems") if isinstance(data, dict) else None
    if not isinstance(systems, list) or len(systems) != 1 or not isinstance(systems[0], dict):
        raise GuardError(f"{target}: not exactly one mount (stacked or missing)")
    entry = systems[0]
    if entry.get("target") != target or entry.get("children"):
        raise GuardError(f"{target}: mount point does not match exactly")
    for key in ("source", "fstype", "options"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise GuardError(f"{target}: {key} unknown")
    return entry


def _device_uuid(source: str, runner: Runner) -> Optional[str]:
    try:
        return normalise_uuid(runner(["blkid", "-p", "-s", "UUID", "-o", "value", source]))
    except GuardError:
        return None


def check_parent(target: str, expected_uuid: str, fstype: str, runner: Runner = _run) -> GuardResult:
    result = GuardResult("parent", False)
    try:
        entry = _exact_mount(target, runner)
        if entry["fstype"] != fstype:
            raise GuardError(f"{target}: wrong file system type")
        options = entry["options"].split(",")
        if "rw" not in options or "ro" in options:
            raise GuardError(f"{target}: not mounted read-write")
        found = _device_uuid(entry["source"], runner)
        if found is None:
            raise GuardError(f"{target}: file system UUID unreadable")
        if found != expected_uuid:
            raise GuardError(f"{target}: file system UUID mismatch")
    except GuardError as exc:
        result.reasons.append(str(exc))
        return result
    result.ok = True
    result.reasons.append(f"{target}: mounted exactly, {fstype}, rw, UUID match")
    return result


def check_image(image: str, expected_uuid: str, *, expected_bytes: int = IMAGE_BYTES) -> GuardResult:
    result = GuardResult("image", False)
    try:
        info = os.lstat(image)
    except OSError:
        result.reasons.append("image missing")
        return result
    if not stat.S_ISREG(info.st_mode):
        result.reasons.append("image is not a regular file")
        return result
    if info.st_size != expected_bytes:
        result.reasons.append("image size differs from the approved size")
    if info.st_blocks * 512 < info.st_size:
        result.reasons.append("image is not fully allocated (sparse)")
    found = read_ext4_uuid(image)
    if found is None:
        result.reasons.append("image holds no readable ext4 superblock")
    elif found != expected_uuid:
        result.reasons.append("image file system UUID mismatch")
    if not result.reasons:
        result.ok = True
        result.reasons.append("image regular, approved size, fully allocated, UUID match")
    return result


def _loop_backing_file(source: str, sys_block: str) -> Optional[str]:
    name = os.path.basename(source)
    if not re.fullmatch(r"loop[0-9]+", name) or source != f"/dev/{name}":
        return None
    try:
        return Path(sys_block, name, "loop", "backing_file").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def check_archive(target: str, image: str, expected_uuid: str, runner: Runner = _run,
                  sys_block: str = "/sys/block") -> GuardResult:
    result = GuardResult("archive", False)
    try:
        entry = _exact_mount(target, runner)
        if entry["fstype"] != "ext4":
            raise GuardError(f"{target}: not ext4")
        options = set(entry["options"].split(","))
        if "rw" not in options or "ro" in options:
            raise GuardError(f"{target}: not mounted read-write")
        missing = {"nodev", "nosuid", "noexec"} - options
        if missing:
            raise GuardError(f"{target}: missing mount options {sorted(missing)}")
        backing = _loop_backing_file(entry["source"], sys_block)
        # Exact string match on purpose: the approved image path has no links (checked by the
        # image check with O_NOFOLLOW); any other spelling is refused.
        if backing is None or backing != image:
            raise GuardError(f"{target}: not backed by the approved image")
        found = _device_uuid(entry["source"], runner)
        if found is None:
            raise GuardError(f"{target}: file system UUID unreadable")
        if found != expected_uuid:
            raise GuardError(f"{target}: file system UUID mismatch")
    except GuardError as exc:
        result.reasons.append(str(exc))
        return result
    result.ok = True
    result.reasons.append(f"{target}: loop on approved image, ext4, rw,nodev,nosuid,noexec, UUID match")
    return result


def check_reserve(size: Optional[int], avail: Optional[int], *, image_allocated: bool,
                  image_bytes: int = IMAGE_BYTES, restore_need: int = RESTORE_NEED_BYTES,
                  store_limit: int = STORE_LIMIT_BYTES) -> GuardResult:
    """Byte arithmetic of §10. ``image_allocated``: the image already exists on the parent."""
    result = GuardResult("reserve", False)
    values = (size, avail, image_bytes, restore_need, store_limit)
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in values) or size <= 0 \
            or not 0 <= avail <= size or image_bytes <= 0 or restore_need <= 0 or store_limit <= 0:
        result.reasons.append("measurement missing or implausible")
        return result
    reserve = int(size * MIN_FREE_SHARE)
    after = avail if image_allocated else avail - image_bytes
    during = after - int(restore_need * (1 + RESTORE_GROWTH_MARGIN))
    if after < reserve:
        result.reasons.append("less than 15 % free after the image")
    if during < reserve:
        result.reasons.append("less than 15 % free during the restore test")
    if store_limit > int(image_bytes * EXT4_USABLE_SHARE * (1 - MIN_FREE_SHARE)):
        result.reasons.append("store limit above 85 % of the usable image")
    if not result.reasons:
        result.ok = True
        result.reasons.append(f"free during restore test {during / size:.1%} (needs 15 %)")
    return result


def _statvfs(path: str) -> tuple[Optional[int], Optional[int]]:
    try:
        st = os.statvfs(path)
    except OSError:
        return None, None
    return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.archive_sync.mount_guard",
                                     description="INFRA-09 identity guard, read-only, fail-closed")
    sub = parser.add_subparsers(dest="check", required=True)
    p = sub.add_parser("parent")
    p.add_argument("--target", required=True)
    p.add_argument("--expected-uuid-file", required=True)
    p.add_argument("--fstype", default="ext4")
    i = sub.add_parser("image")
    i.add_argument("--image", required=True)
    i.add_argument("--expected-uuid-file", required=True)
    a = sub.add_parser("archive")
    a.add_argument("--target", required=True)
    a.add_argument("--image", required=True)
    a.add_argument("--expected-uuid-file", required=True)
    r = sub.add_parser("reserve")
    r.add_argument("--parent", required=True)
    r.add_argument("--image-allocated", action="store_true")
    # No switch weakens a check. Only the test suite may accept a UUID file not owned by root,
    # and only through this environment variable (never set in §11).
    relax_owner = os.environ.get(TEST_ENV) == "1"
    args = parser.parse_args(argv)
    try:
        if args.check == "reserve":
            size, avail = _statvfs(args.parent)
            result = check_reserve(size, avail, image_allocated=args.image_allocated)
        else:
            expected = load_expected_uuid(args.expected_uuid_file, require_root=not relax_owner)
            if args.check == "parent":
                result = check_parent(args.target, expected, args.fstype)
            elif args.check == "image":
                result = check_image(args.image, expected)
            else:
                result = check_archive(args.target, args.image, expected)
    except GuardError as exc:
        result = GuardResult(args.check, False, [str(exc)])
    json.dump(result.as_dict(), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
