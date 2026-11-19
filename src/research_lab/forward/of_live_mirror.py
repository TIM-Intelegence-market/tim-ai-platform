"""Mac side of the live orderflow journal (plan of-live-ps5-2026-11-17, P4). Read only towards the PS5.

The PS5 writes the live journal (:mod:`.of_live`); the Mac copies its ``status.json`` and ``journal.json`` into
``data/research/forward/OF_LIVE_PS5`` over the same Warpgate access the job runner uses, and compares the live trades
with stage A (:mod:`.of_paper`, archive of the previous day) on the days both have finished. The engine is the same,
so the trades must be the same; any difference is a data error and shows as an alarm on the Forschung screen.

The connection is described in ``OF_LIVE_PS5/pull.json`` on the Mac (target, port, key path, remote folder; never a
key). Without that file nothing is pulled.

    python -m src.research_lab.forward of-live-pull    # copy from the PS5 and compare (the workshop does this)
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.research_lab.forward.of_paper import FOLDER as STAGE_A_FOLDER
from src.research_lab.forward.of_paper import _iso, _write

FOLDER = Path("data/research/forward/OF_LIVE_PS5")
FILES = ("status.json", "journal.json")
Run = Callable[[Sequence[str]], subprocess.CompletedProcess]


SAFE_PATH = re.compile(r"[A-Za-z0-9_./~-]+")


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=60)


def scp_argv(cfg: dict[str, Any], name: str, dest: Path) -> list[str]:
    target = str(cfg["ssh"])
    if target.startswith("-") or not target:
        raise ValueError("ssh target must not start with '-'")
    options = ["-o", "BatchMode=yes"]
    if "@" in target:   # the Warpgate user has a colon ("uzi:ps5-research"); scp would take "uzi" as the host
        user, target = target.rsplit("@", 1)
        options += ["-o", f"User={user}"]
    if cfg.get("port"):
        options += ["-P", str(int(cfg["port"]))]
    if cfg.get("identity"):
        options += ["-i", str(cfg["identity"])]
    remote = str(cfg["remote_folder"]).rstrip("/")
    if not SAFE_PATH.fullmatch(remote) or ".." in remote:
        raise ValueError("remote_folder may only hold letters, digits and _ . / ~ -")   # no quoting in SFTP mode
    remote = remote.removeprefix("~/")   # scp paths without "/" start in the home folder
    return ["scp", *options, f"{target}:{remote}/{name}", str(dest)]


def pull(root: Path | str = ".", *, run: Run = _run, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
         ) -> dict[str, Any]:
    folder = Path(root) / FOLDER
    cfg_path = folder / "pull.json"
    if not cfg_path.exists():
        return {"pulled": False, "reason": "kein pull.json"}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        cfg = {}
        result = {"pulled": False, "pulled_at": _iso(clock()), "errors": [f"pull.json: {type(exc).__name__}"],
                  "last_ok": (_read(folder / "mirror.json") or {}).get("last_ok"),
                  "abgleich": {"ok": None, "grund": "pull.json unlesbar"}}
        _write(folder / "mirror.json", result)
        return result
    errors = []
    for name in FILES:
        tmp = folder / (name + ".pull")
        try:
            done = run(scp_argv(cfg, name, tmp))
        except Exception as exc:  # noqa: BLE001 - timeout, missing scp, bad config: recorded, the old copy stays
            errors.append(f"{name}: {type(exc).__name__}: {exc}"[:200])
            continue
        if done.returncode != 0:
            errors.append(f"{name}: {(done.stderr or '').strip()[:200]}")
            continue
        try:
            json.loads(tmp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: unlesbar ({type(exc).__name__})")
            continue
        tmp.replace(folder / name)
    result: dict[str, Any] = {"pulled": not errors, "pulled_at": _iso(clock()), "errors": errors}
    previous = _read(folder / "mirror.json") or {}
    result["last_ok"] = result["pulled_at"] if not errors else previous.get("last_ok")
    result["abgleich"] = (compare(_read(folder / "journal.json"), _read(Path(root) / STAGE_A_FOLDER / "journal.json"))
                          if not errors else {"ok": None, "grund": "Spiegel veraltet (Abholen fehlgeschlagen)"})
    _write(folder / "mirror.json", result)
    return result


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except ValueError:
        return None


def _key(t: dict) -> tuple:
    return (t["signal_ms"], t["model"], t["direction"], t["fill_ms"], t["exit_ms"], t["reason"], round(t["net_r"], 6))


def _end_ms(day: str) -> int:
    d = date.fromisoformat(day) + timedelta(days=1)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _start_ms(day: str) -> int:
    d = date.fromisoformat(day)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def compare(live: dict | None, stage_a: dict | None) -> dict[str, Any]:
    """Trades both journals must have: signal from the live start on, closed before the end of stage A's last day."""
    if not live or not stage_a:
        return {"ok": None, "grund": "Journal fehlt"}
    live_status, a_status = live.get("status") or {}, stage_a.get("status") or {}
    first = live_status.get("first_day")
    # only days both have finished: a stale copy of the live journal must not look like a data error
    last = min((d for d in (a_status.get("last_day"), live_status.get("last_day")) if d), default=None) \
        if a_status.get("last_day") and live_status.get("last_day") else None
    if not first or not last or last < first:
        return {"ok": None, "grund": "noch kein gemeinsamer Tag", "ab": first, "bis": last}
    lo, hi = _start_ms(first), _end_ms(last)

    def inside(trades: list[dict]) -> set[tuple]:
        return {_key(t) for t in trades if lo <= t["signal_ms"] and t["exit_ms"] < hi}

    a, b = inside(stage_a.get("trades") or []), inside(live.get("trades") or [])
    return {"ok": a == b, "ab": first, "bis": last, "gleich": len(a & b),
            "nur_archiv": sorted(a - b)[:5], "nur_live": sorted(b - a)[:5]}
