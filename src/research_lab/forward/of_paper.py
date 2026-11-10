"""Paper journal of the orderflow engine on current data (Uzi 10.11.2026, "go"; plan: OF-Papier-Pfad Stufe A).

Every step (the research workshop calls it on each wake-up on the Mac; it does real work once per new day):

1. Fetch the finished UTC days up to yesterday from the public Binance archive into the journal's own S8 store
   (``PAPER_RELEASE``: only days from 2026-10-01 on; the research store keeps its holdout lock).
2. Run the backtest's own engine (OF2 with the orderflow gate, the OFX base) over the lead days and every day since
   the start. Same code as the backtest, so recomputing gives the same trades. Signals count from the first full
   UTC day after the journal was started (prospective, no back-dating); the lead days only feed the levels.
3. Write ``journal.json`` (trades, funnel, summary) and ``status.json``, and append each newly seen closed trade
   to ``events.jsonl`` with the real clock.

Signals appear with up to a day of delay (the archive of a day is published after it ends). Nothing here sends an
order, touches the live trader or the plan journal, or counts in any net R outside this journal.
"""
from __future__ import annotations

import dataclasses
import fcntl
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.research_lab.of2.backtest import Trade, summarize
from src.research_lab.of2.config import DEFAULT_CONFIG, Config
from src.research_lab.of2.engine import Engine, _ms, funnel
from src.research_lab.orderflow_ml.store import PAPER_RELEASE, MinuteBarStore

FOLDER = Path("data/research/forward/OF")
LEAD_DAYS = 25           # as the backtest CLI: levels, naked POCs and the IB history need them
RETRY_SECONDS = 3600     # a missing archive is asked for at most once an hour
MIN_TRADES = 100
# OFX base at the journal's start: OF2 1.0 with the orderflow gate. Frozen in start.json (digest); a later code
# change of the engine parameters makes the step refuse instead of silently mixing two rule sets.
PAPER_CONFIG = dataclasses.replace(DEFAULT_CONFIG, of_gate=True)


class PaperError(RuntimeError):
    pass


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


class PaperJournal:
    def __init__(self, folder: Path | str = FOLDER, *, cfg: Config = PAPER_CONFIG, store: MinuteBarStore | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.folder = Path(folder)
        self.cfg = cfg
        self.store = store or MinuteBarStore(self.folder / "store", release=PAPER_RELEASE)
        self.clock = clock

    def _read(self, name: str) -> dict | None:
        path = self.folder / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def status(self) -> dict | None:
        return self._read("status.json")

    def start(self) -> dict:
        """First call fixes the start: signals count from the first full UTC day after it."""
        start = self._read("start.json")
        if start is None:
            now = self.clock()
            start = {"started_at": _iso(now), "first_day": (now.date() + timedelta(days=1)).isoformat(),
                     "config_digest": self.cfg.digest(), "config": self.cfg.as_dict()}
            self.folder.mkdir(parents=True, exist_ok=True)
            _write(self.folder / "start.json", start)
            start = self._read("start.json") or start
        if start["config_digest"] != self.cfg.digest():
            raise PaperError("engine parameters changed since the journal started; start a new journal folder")
        return start

    def step(self) -> dict[str, Any]:
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / "step.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._step()

    def _fetch(self, days: list[date], previous: dict) -> tuple[date | None, str | None]:
        """Fetch in order; stop at the first day that cannot be loaded (the engine needs consecutive days)."""
        last, waiting = None, None
        for day in days:
            if self.store.cached(day) is None:
                tried = previous.get("waiting_for") == day.isoformat() and previous.get("last_attempt")
                if tried and (self.clock() - datetime.fromisoformat(tried.replace("Z", "+00:00"))).total_seconds() < RETRY_SECONDS:
                    return last, f"{day.isoformat()}|{tried}|{previous.get('waiting_error', '')}"
                try:
                    self.store.fetch(day)
                except Exception as exc:  # noqa: BLE001 - not published yet, network, or a broken archive: shown, retried later
                    return last, f"{day.isoformat()}|{_iso(self.clock())}|{type(exc).__name__}: {exc}"[:400]
            last = day
        return last, waiting

    def _step(self) -> dict[str, Any]:
        start = self.start()
        first = date.fromisoformat(start["first_day"])
        now = self.clock()
        yesterday = now.date() - timedelta(days=1)
        previous = self.status() or {}
        lead = first - timedelta(days=LEAD_DAYS)
        days = [lead + timedelta(days=i) for i in range((yesterday - lead).days + 1)]
        last, waiting = self._fetch(days, previous)
        status: dict[str, Any] = {"start": start["started_at"], "first_day": start["first_day"], "checked_at": _iso(now),
                                  "config_digest": start["config_digest"], "min_trades": MIN_TRADES, "new_events": 0,
                                  "last_day": last.isoformat() if last else None, "waiting_for": None}
        if waiting:
            status["waiting_for"], status["last_attempt"], status["waiting_error"] = waiting.split("|", 2)
        if last is None or last.isoformat() == previous.get("last_day"):
            for key in ("trades", "net_r", "mean_r", "max_drawdown_r", "recent", "open", "trichter"):
                if key in previous:
                    status[key] = previous[key]
            _write(self.folder / "status.json", status)
            return status
        engine = Engine(self.cfg)
        trades: list[Trade] = []
        before: dict[str, int] = {}
        for day in days:
            if day > last:
                break
            if day == first:
                before = dict(engine.stats.trichter)
            trades.extend(engine.run_day(self.store.load(day), self.store.load_profile(day)))
        if last < first:
            before = dict(engine.stats.trichter)
        counted = [t for t in trades if t.signal.signal_ms >= _ms(first)]
        steps = {k: v - before.get(k, 0) for k, v in engine.stats.trichter.items() if v - before.get(k, 0)}
        rows = [t.as_dict() for t in counted]
        seen = {(e["signal_ms"], e["model"], e["direction"]) for e in self._events()}
        fresh = [r for r in rows if (r["signal_ms"], r["model"], r["direction"]) not in seen]
        with (self.folder / "events.jsonl").open("a", encoding="utf-8") as handle:
            for r in fresh:
                handle.write(json.dumps({**r, "seen_at": _iso(now)}, sort_keys=True) + "\n")
        eq = peak = dd = 0.0
        for t in counted:
            eq += t.net_r
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        open_now = [{"model": o.signal.model, "direction": o.signal.direction, "entry": o.entry, "stop": o.signal.stop,
                     "target": o.signal.target, "fill_ms": o.fill_ms}
                    for o in engine.tracker.open if o.signal.signal_ms >= _ms(first)]
        status.update({
            "trades": len(counted), "net_r": round(sum(t.net_r for t in counted), 3),
            "mean_r": round(sum(t.net_r for t in counted) / len(counted), 4) if counted else None,
            "max_drawdown_r": round(dd, 3), "new_events": len(fresh), "open": open_now,
            "trichter": funnel(steps, counted),
            "recent": [{k: r[k] for k in ("model", "direction", "session", "reason", "net_r", "exit_ms")} for r in rows[-5:]],
        })
        _write(self.folder / "journal.json", {"status": status, "zusammenfassung": summarize(counted, self.cfg), "trades": rows})
        _write(self.folder / "status.json", status)
        return status

    def _events(self) -> list[dict]:
        path = self.folder / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def step(root: Path | str = ".") -> dict[str, Any]:
    """Entry for the research workshop: one step of the journal under ``root``."""
    return PaperJournal(Path(root) / FOLDER).step()
