"""Orderflow paper journal on live trades, stage B (plan of-live-ps5-2026-11-17, P2). Paper only.

Same engine, same frozen parameters (digest in ``start.json``) and same counting as stage A
(:mod:`.of_paper`), in its own folder ``data/research/forward/OF_LIVE``. The difference is the data:

* finished days come from the Binance archive when it is published, otherwise from the recorder's day
  (:mod:`.live_recorder`) if that day is complete; a blocked or missing day stops the run there, as in stage A;
* after the last finished day, the closed minutes of today run on a copy of the engine, so a signal shows up a few
  minutes after its candle closed instead of a day later.

The engine is causal, so a day computed from the recorder gives the trades the archive gives, and the closed minutes
of today give the trades the full day gives up to that minute. Nothing here sends an order or touches stage A.

    python -m src.research_lab.forward of-live-step  --folder data/research/forward/OF_LIVE --trades <recorder root>
    python -m src.research_lab.forward of-live-run   ... [--every 300]   # step loop, ends on <folder>/STOP
"""
from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.research_lab.forward.live_recorder import TradeRecorder
from src.research_lab.forward.of_paper import PAPER_CONFIG, PaperJournal, _iso, _write
from src.research_lab.of2.backtest import Trade
from src.research_lab.of2.config import Config
from src.research_lab.of2.engine import Engine
from src.research_lab.orderflow_ml.bars import DayProfile, MinuteBar
from src.research_lab.orderflow_ml.store import PAPER_FIRST_DAY, PAPER_RELEASE, MinuteBarStore, guard

FOLDER = Path("data/research/forward/OF_LIVE")
ARCHIVE_RETRY_SECONDS = 3600
STEP_EVERY = 300


class LiveStore:
    """Archive days first, then complete recorder days; today's closed minutes via :meth:`partial`."""

    def __init__(self, archive: MinuteBarStore, recorder: TradeRecorder, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.archive = archive
        self.recorder = recorder
        self.clock = clock
        self._recorded: dict[date, tuple[list[MinuteBar], DayProfile]] = {}
        self._archive_tried: dict[date, datetime] = {}
        self.sources: dict[date, str] = {}

    def cached(self, day: date) -> dict | None:
        if self.archive.cached(day) is not None:
            self.sources[day] = "archiv"
            return {"source": "archiv"}
        if day in self._recorded and self.recorder.day_state(day) != "complete":
            del self._recorded[day]   # blocked after it was read: never computed on
            self.sources.pop(day, None)
            return None
        if day in self._recorded:
            tried = self._archive_tried.get(day)
            if tried is None or (self.clock() - tried).total_seconds() >= ARCHIVE_RETRY_SECONDS:
                return None   # ask the archive again; the recorder day stays as fallback
            return {"source": "recorder"}
        return None

    def fetch(self, day: date) -> None:
        try:
            self.archive.fetch(day)
            self._recorded.pop(day, None)
            self.sources[day] = "archiv"
            return
        except Exception as exc:  # noqa: BLE001 - not published yet or network: the recorder may have the day
            archive_error = exc
        self._archive_tried[day] = self.clock()
        if day in self._recorded:
            return
        guard(day, PAPER_RELEASE, today=self.clock().date())
        if self.recorder.day_state(day) != "complete":
            raise FileNotFoundError(f"{day}: archive not available ({type(archive_error).__name__}) and "
                                    f"recorder day is {self.recorder.day_state(day)}")
        bars, quality, profile = self.recorder.reduce(day)
        if quality.id_gaps or quality.time_regressions:
            raise ValueError(f"{day}: recorder day has id gaps or time regressions")
        self._recorded[day] = (bars, profile)
        self.sources[day] = "recorder"

    def load(self, day: date) -> list[MinuteBar]:
        return self._recorded[day][0] if day in self._recorded else self.archive.load(day)

    def load_profile(self, day: date) -> DayProfile:
        return self._recorded[day][1] if day in self._recorded else self.archive.load_profile(day)

    def partial(self, day: date) -> tuple[list[MinuteBar], DayProfile, int] | None:
        """Closed minutes of ``day`` (today) from the recorder, or None if it has none or the day is broken."""
        if day < PAPER_FIRST_DAY or self.recorder.day_state(day) != "open":
            return None
        until = self.recorder.closed_until_ms(day)
        if until is None:
            return None
        bars, quality, profile = self.recorder.reduce(day, until)
        if not bars or quality.id_gaps or quality.time_regressions:
            return None
        return bars, profile, until


class LiveJournal(PaperJournal):
    recompute_each_step = True

    def __init__(self, folder: Path | str = FOLDER, *, trades_root: Path | str, cfg: Config = PAPER_CONFIG,
                 store: LiveStore | None = None, recorder: TradeRecorder | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        folder = Path(folder)
        store = store or LiveStore(MinuteBarStore(folder / "store", release=PAPER_RELEASE),
                                   recorder or TradeRecorder(trades_root), clock=clock)
        super().__init__(folder, cfg=cfg, store=store, clock=clock)  # type: ignore[arg-type]

    def _today(self, engine: Engine, last: date) -> tuple[list[Trade], Engine, int | None]:
        today = self.clock().date()
        if last != today - timedelta(days=1):
            return [], engine, None   # an earlier day is still missing: no jump over it
        part = self.store.partial(today)  # type: ignore[attr-defined]
        if part is None:
            return [], engine, None
        bars, profile, until = part
        if not bars:
            return [], engine, None
        live = copy.deepcopy(engine)
        return live.run_day(bars, profile), live, until

    def _step(self) -> dict[str, Any]:
        status = super()._step()
        sources = getattr(self.store, "sources", {})
        rec = getattr(self.store, "recorder", None)
        rec_status = rec.dir / "status.json" if rec is not None else None
        if rec_status is not None and rec_status.exists():
            updated = json.loads(rec_status.read_text(encoding="utf-8")).get("updated_ms")
            if updated:
                status["recorder_stand"] = _iso(datetime.fromtimestamp(updated / 1000, tz=timezone.utc))
        status["quellen"] = {"archiv": sum(1 for s in sources.values() if s == "archiv"),
                             "recorder": sorted(d.isoformat() for d, s in sources.items() if s == "recorder")}
        _write(self.folder / "status.json", status)
        return status


def run(journal: LiveJournal, *, every: float = STEP_EVERY, stop_after: float | None = None,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> int:
    """Step every ``every`` seconds until ``<folder>/STOP`` exists. Errors are logged and retried next round."""
    started, steps = clock(), 0
    while not (journal.folder / "STOP").exists() and (stop_after is None or clock() - started < stop_after):
        try:
            status = journal.step()
            print(json.dumps({"checked_at": status.get("checked_at"), "last_day": status.get("last_day"),
                              "live_until": status.get("live_until"), "trades": status.get("trades"),
                              "new_events": status.get("new_events")}), flush=True)
        except Exception as exc:  # noqa: BLE001 - shown in the log; the next round tries again
            print(f"of-live: {_iso(datetime.now(timezone.utc))} {type(exc).__name__}: {exc}", flush=True)
        steps += 1
        sleep(every)
    return steps
