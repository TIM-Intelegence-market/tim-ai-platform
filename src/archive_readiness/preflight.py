"""Lesende Vorab-Prüfung für das INFRA-09-Übergangsarchiv (32 GiB Image, 26 GiB Grenze).

Dieses Modul richtet nichts ein. Es misst nur (``os.statvfs``, ``os.path.lexists``,
``/proc/self/mounts``) und rechnet die Bedingungen aus Uzis bedingter Freigabe vom 24.11.2026
nach (``docs/ARCHIV_WARPGATE_UEBERGANG.md`` §9 bis §11):

- Image fest belegt 32 GiB, Store-Grenze 26 GiB,
- mindestens 15 % frei auf der übergeordneten Platte, auch während des Restore-Tests,
- Ziele (Image-Ordner, Einhängepunkt) existieren noch nicht,
- Warpgate-Platte eingehängt.

Urteil: PASS nur, wenn jede Bedingung gemessen und erfüllt ist. Fehlt ein Messwert, ist das
Urteil INCONCLUSIVE (fail-closed, nie PASS). Ein PASS ist keine Freigabe zur Einrichtung.
``TRADING_AUTHORIZED=NO``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

GIB = 1024**3
IMAGE_BYTES = 32 * GIB
STORE_LIMIT_GIB = 26
MIN_FREE_SHARE = 0.15
# Restore-Bedarf des letzten belegten Laufs (22.11.2026, PASS): 2 x DB + 8 GiB.
LAST_RESTORE_NEED_BYTES = 208_662_998_398
# Puffer auf den Restore-Bedarf, weil die Datenbank zwischen zwei Messungen wachsen kann.
RESTORE_GROWTH_MARGIN = 0.05

DEFAULT_PARENT = "/var/lib/warpgate"
DEFAULT_IMG_DIR = "/var/lib/warpgate/tim-archive-img"
DEFAULT_MOUNT = "/srv/tim-archive-tmp"


@dataclass
class Measurement:
    """Messwerte in Byte. ``None`` heißt: nicht gemessen."""

    parent_size: Optional[int] = None
    parent_avail: Optional[int] = None
    parent_mounted: Optional[bool] = None
    img_dir_exists: Optional[bool] = None
    mount_exists: Optional[bool] = None
    restore_need: Optional[int] = LAST_RESTORE_NEED_BYTES


@dataclass
class Result:
    urteil: str
    checks: list = field(default_factory=list)
    zahlen: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "schema": "tim-archiv-preflight/1",
            "urteil": self.urteil,
            "checks": self.checks,
            "zahlen": self.zahlen,
            "hinweis": "Nur Messung. Kein PASS ist eine Freigabe zur Einrichtung.",
            "trading_authorized": "NO",
        }


def _check(checks: list, name: str, ok: Optional[bool], detail: str) -> None:
    status = "INCONCLUSIVE" if ok is None else ("PASS" if ok else "FAIL")
    checks.append({"name": name, "status": status, "detail": detail})


def _valid_bytes(value: Optional[int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def evaluate(m: Measurement, image_bytes: int = IMAGE_BYTES) -> Result:
    """Rechnet alle Bedingungen nach. Reine Funktion, keine Seiteneffekte."""
    checks: list = []
    zahlen: dict = {"image_bytes": image_bytes, "store_limit_gib": STORE_LIMIT_GIB}

    _check(checks, "parent_mounted", m.parent_mounted, "Warpgate-Platte eingehängt")
    _check(
        checks,
        "img_dir_absent",
        None if m.img_dir_exists is None else not m.img_dir_exists,
        "Image-Ordner existiert noch nicht",
    )
    _check(
        checks,
        "mount_absent",
        None if m.mount_exists is None else not m.mount_exists,
        "Einhängepunkt existiert noch nicht",
    )

    sizes_ok = (
        _valid_bytes(m.parent_size)
        and _valid_bytes(m.parent_avail)
        and m.parent_size > 0
        and m.parent_avail <= m.parent_size
    )
    if not sizes_ok:
        for name in ("free_after_image", "free_during_restore", "store_limit_fits"):
            _check(checks, name, None, "Plattengröße oder freier Platz nicht gemessen oder unplausibel")
    else:
        size, avail = m.parent_size, m.parent_avail
        reserve = int(size * MIN_FREE_SHARE)
        after = avail - image_bytes
        zahlen.update({"parent_size": size, "parent_avail": avail, "reserve_15pct": reserve, "frei_nach_image": after})
        _check(checks, "free_after_image", after >= reserve, f"frei nach Image {after} B, Reserve {reserve} B")

        if not _valid_bytes(m.restore_need) or m.restore_need == 0:
            _check(checks, "free_during_restore", None, "Restore-Bedarf unbekannt")
        else:
            need = int(m.restore_need * (1 + RESTORE_GROWTH_MARGIN))
            during = after - need
            zahlen.update({"restore_bedarf_mit_puffer": need, "frei_waehrend_restore": during,
                           "anteil_waehrend_restore": round(during / size, 4)})
            _check(checks, "free_during_restore", during >= reserve,
                   f"frei während Restore {during} B ({during / size:.1%}), Reserve {reserve} B")

        # Grenze im Store: 26 GiB müssen unter 85 % des nutzbaren Image-Platzes liegen.
        usable = int(image_bytes * 0.984)  # ext4-Verwaltung, -m 0, Schätzung wie in §10 (~31,5 GiB)
        _check(checks, "store_limit_fits", STORE_LIMIT_GIB * GIB <= int(usable * (1 - MIN_FREE_SHARE)),
               f"Grenze {STORE_LIMIT_GIB} GiB, nutzbar ca. {usable / GIB:.1f} GiB")

    statuses = {c["status"] for c in checks}
    if "FAIL" in statuses:
        urteil = "FAIL"
    elif "INCONCLUSIVE" in statuses:
        urteil = "INCONCLUSIVE"
    else:
        urteil = "PASS"
    return Result(urteil=urteil, checks=checks, zahlen=zahlen)


def _is_mountpoint(path: str, mounts_file: str = "/proc/self/mounts") -> Optional[bool]:
    try:
        with open(mounts_file, encoding="utf-8") as handle:
            targets = {line.split()[1].replace("\\040", " ") for line in handle if len(line.split()) > 1}
    except OSError:
        return None
    return os.path.normpath(path) in targets


def measure(parent: str = DEFAULT_PARENT, img_dir: str = DEFAULT_IMG_DIR, mount: str = DEFAULT_MOUNT,
            restore_need: Optional[int] = LAST_RESTORE_NEED_BYTES) -> Measurement:
    """Misst nur lesend. Schreibt nichts, startet nichts."""
    m = Measurement(restore_need=restore_need)
    try:
        st = os.statvfs(parent)
        m.parent_size = st.f_blocks * st.f_frsize
        m.parent_avail = st.f_bavail * st.f_frsize  # frei für Nicht-root, wie df "avail"
    except OSError:
        pass
    m.parent_mounted = _is_mountpoint(parent)
    m.img_dir_exists = os.path.lexists(img_dir)
    m.mount_exists = os.path.lexists(mount)
    return m


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="INFRA-09 Vorab-Prüfung, nur lesend")
    parser.add_argument("--parent", default=DEFAULT_PARENT)
    parser.add_argument("--img-dir", default=DEFAULT_IMG_DIR)
    parser.add_argument("--mount", default=DEFAULT_MOUNT)
    parser.add_argument("--restore-need-bytes", type=int, default=LAST_RESTORE_NEED_BYTES)
    args = parser.parse_args(argv)
    result = evaluate(measure(args.parent, args.img_dir, args.mount, args.restore_need_bytes))
    json.dump(result.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return {"PASS": 0, "FAIL": 1}.get(result.urteil, 2)


if __name__ == "__main__":
    raise SystemExit(main())
