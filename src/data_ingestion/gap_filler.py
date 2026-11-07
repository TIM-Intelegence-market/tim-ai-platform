"""Background gap filler: closes OPEN aggTrade gaps while live ingestion keeps running (issue #82).

Before #82 the runtime accepted no live trade until a gap after an outage was
closed, and the inline catch-up (300 s, ~25 trades/s) lost against the growing
gap: every longer outage needed a manual live cutover. Now the ingress hands a
gap it cannot close quickly to this filler, and live data flows again at once.

The filler, one asyncio task inside the runtime:

- takes the OPEN gaps from the gap ledger, newest first (the current outage
  matters most for the chart), and fetches them from the same public Binance
  REST source as the inline catch-up (``CatchUpCoordinator.recover_open_gap``);
- writes each page behind the live cursor in one transaction
  (``DurableIngestionStore.ingest_historical_batch``): no cursor movement, and
  the outbox rows go to DEFERRED so they never queue in front of live work;
- resolves a gap only after the independent completeness check of its whole ID
  range (``resolve_gap``), as before;
- rebuilds the closed 1m candles of the filled minutes from the raw trades
  (``deferred_candles.rebuild_deferred_candles``), which skips any minute that an
  OPEN gap still touches, so a rebuilt candle is never a partial candle;
- backs off per gap when Binance returns nothing usable, and reports its state
  (open gaps, missing trades, last progress) for the Control Center.

Public market data only, no keys, no orders: mode OBSERVE, trading_actions 0.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.data_ingestion.catchup import CatchUpCoordinator, CatchUpResult
from src.data_ingestion.durable import DurableIngestionStore

log = logging.getLogger(__name__)
UTC = timezone.utc
STATUS_PATH = Path("data/operational/gap_filler.json")


@dataclass
class GapFillerStatus:
    mode: str = "OBSERVE"
    trading_actions: int = 0
    state: str = "STARTING"  # IDLE, FILLING, BACKING_OFF, ERROR
    symbol: str = ""
    checked_at_utc: str | None = None
    open_gaps: int = 0
    missing_trades: int = 0
    last_progress_at_utc: str | None = None
    last_resolved_gap: str | None = None
    resolved_total: int = 0
    persisted_total: int = 0
    candles_rebuilt_total: int = 0
    last_error: str | None = None
    waiting_gaps: int = 0  # in backoff or being caught up inline right now
    too_large_gaps: int = 0  # above max_gap_trades: left for a reviewed offline backfill
    candle_error: str | None = None  # last failed candle rebuild; gap filling goes on regardless
    rebuild_from_trade_id: int | None = None  # lowest trade ID the filler wrote; candles are rebuilt from here
    rounds: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Backoff:
    failures: int = 0
    until: float = 0.0


@dataclass
class RoundReport:
    examined: int = 0
    resolved: int = 0
    persisted: int = 0
    duplicates: int = 0
    work_left: bool = False
    candles_rebuilt: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


def _gap_size(gap: Mapping[str, Any]) -> int | None:
    start, end = gap.get("missing_from_id"), gap.get("missing_to_id")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
        return None
    return end - start + 1


class GapFiller:
    def __init__(
        self,
        store: DurableIngestionStore,
        coordinator: CatchUpCoordinator,
        symbol: str,
        *,
        candle_rebuilder: Callable[[int], Any] | None = None,
        max_gaps_per_round: int = 20,
        idle_seconds: float = 60.0,
        busy_pause_seconds: float = 1.0,
        catching_up_stale_seconds: float = 900.0,
        max_backoff_seconds: float = 6 * 3600.0,
        max_gap_trades: int = 20_000_000,
        rebuild_idle_seconds: float = 1800.0,
        on_status: Callable[[dict[str, Any]], None] | None = None,
        status_path: Path | None = STATUS_PATH,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= max_gaps_per_round <= 1_000:
            raise ValueError("max_gaps_per_round must be between 1 and 1000")
        self.store = store
        self.coordinator = coordinator
        self.symbol = symbol.upper()
        self.candle_rebuilder = candle_rebuilder
        self.max_gaps_per_round = max_gaps_per_round
        self.idle_seconds = idle_seconds
        self.busy_pause_seconds = busy_pause_seconds
        self.catching_up_stale = timedelta(seconds=catching_up_stale_seconds)
        self.max_backoff_seconds = max_backoff_seconds
        # About a week of BTCUSDT aggTrades. A larger row is an old evidence range, not an outage
        # the runtime should pull in on its own: it stays OPEN and is counted in the status.
        self.max_gap_trades = max_gap_trades
        # The candle rebuild scans every DEFERRED outbox row (millions of legacy rows on
        # the live database). Run it each round only while it rebuilds something or the
        # filler wrote new trades; otherwise at most every rebuild_idle_seconds.
        self.rebuild_idle_seconds = rebuild_idle_seconds
        self._rebuild_due = 0.0
        self._rebuild_failures = 0
        self.on_status = on_status
        self.status_path = status_path
        self.clock = clock
        self.status = GapFillerStatus(symbol=self.symbol)
        self._backoff: dict[str, _Backoff] = {}
        self._restore_progress()

    def _restore_progress(self) -> None:
        """Keep "last progress" and the totals across runtime restarts (the 6 h stall rule needs them)."""
        if self.status_path is None:
            return
        try:
            previous = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(previous, dict) or previous.get("symbol") != self.symbol:
            return
        if isinstance(previous.get("last_progress_at_utc"), str):
            self.status.last_progress_at_utc = previous["last_progress_at_utc"]
        for name in ("resolved_total", "persisted_total", "candles_rebuilt_total", "rebuild_from_trade_id"):
            if isinstance(previous.get(name), int) and not isinstance(previous.get(name), bool):
                setattr(self.status, name, previous[name])

    def _eligible(self, gap: Mapping[str, Any], now: datetime) -> bool:
        size = _gap_size(gap)
        if size is None or size > self.max_gap_trades:
            return False  # no authoritative ID range, or far too large: governed offline review, not REST
        if gap.get("status") == "CATCHING_UP":
            # The inline catch-up of the stream (or another tool) is on it right now;
            # a CATCHING_UP row left behind by a crash is taken after a while.
            updated = gap.get("updated_at")
            if isinstance(updated, datetime) and now - updated < self.catching_up_stale:
                return False
        backoff = self._backoff.get(str(gap.get("gap_id")))
        return backoff is None or backoff.until <= self.clock()

    def _fail(self, gap_id: str) -> None:
        entry = self._backoff.setdefault(gap_id, _Backoff())
        entry.failures += 1
        entry.until = self.clock() + min(self.max_backoff_seconds, 30.0 * 2 ** min(entry.failures, 12))

    async def run_once(self) -> RoundReport:
        report = RoundReport()
        now = datetime.now(UTC)
        gaps = await self.store.open_gaps(self.symbol, limit=self.max_gaps_per_round, newest_first=True)
        self.status.open_gaps = len(gaps)
        self.status.missing_trades = sum(_gap_size(gap) or 0 for gap in gaps)
        eligible = [gap for gap in gaps if self._eligible(gap, now)]
        self.status.too_large_gaps = sum((_gap_size(gap) or 0) > self.max_gap_trades for gap in gaps)
        self.status.waiting_gaps = len(gaps) - len(eligible) - self.status.too_large_gaps
        for gap in eligible:
            gap_id = str(gap["gap_id"])
            result: CatchUpResult = await self.coordinator.recover_open_gap(gap)
            report.examined += 1
            report.persisted += result.persisted
            report.duplicates += result.duplicates
            report.results.append({"gap_id": gap_id, "status": result.status, "persisted": result.persisted,
                                   "reason": result.reason})
            if result.persisted or result.duplicates or result.status == "COMPLETE":
                self._note_filled(gap)
            if result.status == "COMPLETE":
                report.resolved += 1
                self._backoff.pop(gap_id, None)
                self.status.last_resolved_gap = gap_id
                log.info("Gap %s..%s closed by the background filler", gap.get("missing_from_id"), gap.get("missing_to_id"))
            elif result.persisted or result.duplicates:
                report.work_left = True  # bounded run ended with progress: continue next round
                self._backoff.pop(gap_id, None)
            else:
                self._fail(gap_id)
                self.status.last_error = (result.reason or "no progress")[:300]
        if report.persisted or report.resolved:
            self.status.last_progress_at_utc = now.isoformat()
        await self._rebuild_candles(report)
        self.status.resolved_total += report.resolved
        self.status.persisted_total += report.persisted
        self.status.candles_rebuilt_total += report.candles_rebuilt
        self.status.rounds += 1
        self.status.checked_at_utc = now.isoformat()
        self.status.state = "FILLING" if report.work_left else ("BACKING_OFF" if self.status.waiting_gaps else "IDLE")
        if report.resolved:
            # Ledger counts after the round, so the Control Center shows the result.
            remaining = await self.store.open_gaps(self.symbol, limit=self.max_gaps_per_round)
            self.status.open_gaps = len(remaining)
            self.status.missing_trades = sum(_gap_size(gap) or 0 for gap in remaining)
        self._publish()
        return report

    def _note_filled(self, gap: Mapping[str, Any]) -> None:
        start = gap.get("missing_from_id")
        if isinstance(start, int) and not isinstance(start, bool) and start >= 0:
            floor = self.status.rebuild_from_trade_id
            self.status.rebuild_from_trade_id = start if floor is None else min(floor, start)

    async def _rebuild_candles(self, report: RoundReport) -> None:
        """Rebuild the DEFERRED 1m candles of what the filler wrote; a failure never stops the gap filling.

        Only DEFERRED rows from the lowest filled trade ID on are scanned. The live
        database holds millions of older DEFERRED rows from earlier cutovers; reading
        them all took over ten minutes (07.11.) and they stay with the offline tool
        (scripts/rebuild_deferred_candles.py).
        """
        floor = self.status.rebuild_from_trade_id
        if self.candle_rebuilder is None or floor is None:
            return
        if not report.persisted and self.clock() < self._rebuild_due:
            return
        try:
            report.candles_rebuilt = int(await self.candle_rebuilder(floor) or 0)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._rebuild_failures += 1
            self._rebuild_due = self.clock() + min(self.max_backoff_seconds, 300.0 * 2 ** min(self._rebuild_failures, 6))
            self.status.candle_error = f"{type(error).__name__}: {error}"[:300]
            log.warning("Candle rebuild failed (%s); gap filling continues", type(error).__name__)
            return
        self._rebuild_failures = 0
        self.status.candle_error = None
        if report.candles_rebuilt:
            report.work_left = True  # more DEFERRED minutes may wait
            self._rebuild_due = 0.0
        else:
            self._rebuild_due = self.clock() + self.rebuild_idle_seconds

    def _publish(self) -> None:
        payload = self.status.as_dict()
        if self.on_status is not None:
            try:
                self.on_status(payload)
            except Exception:  # status display must never stop the filler
                log.debug("gap filler status callback failed", exc_info=True)
        if self.status_path is not None:
            try:
                self.status_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.status_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                temporary.replace(self.status_path)
            except OSError:
                log.debug("gap filler status file not written", exc_info=True)

    async def run(self, stop: asyncio.Event) -> None:
        """Loop until ``stop`` is set; never raises except on cancellation."""
        failures = 0
        while not stop.is_set():
            delay = self.idle_seconds
            try:
                report = await self.run_once()
                failures = 0
                if report.work_left:
                    delay = self.busy_pause_seconds
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failures += 1
                delay = min(self.max_backoff_seconds, 30.0 * 2 ** min(failures, 8))
                self.status.state = "ERROR"
                self.status.last_error = f"{type(error).__name__}: {error}"[:300]
                self._publish()
                log.warning("Gap filler round failed (%s); next try in %.0fs", type(error).__name__, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass


class _LongQueries:
    """Connection view with a longer per-query timeout than the pool's 30 s command timeout.

    The DEFERRED inventory reads the whole DEFERRED outbox (millions of legacy rows),
    which takes longer than the runtime pool allows for one query.
    """

    def __init__(self, connection: Any, timeout: float) -> None:
        self._connection = connection
        self._timeout = timeout

    async def fetch(self, query: str, *args: Any) -> Any:
        return await self._connection.fetch(query, *args, timeout=self._timeout)

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return await self._connection.fetchrow(query, *args, timeout=self._timeout)

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._connection.fetchval(query, *args, timeout=self._timeout)

    async def execute(self, query: str, *args: Any) -> Any:
        return await self._connection.execute(query, *args, timeout=self._timeout)

    def transaction(self, *args: Any, **kwargs: Any) -> Any:
        return self._connection.transaction(*args, **kwargs)


def deferred_candle_rebuilder(
    database: Any, symbol: str, *, max_minutes: int = 500, query_timeout_seconds: float = 300.0,
) -> Callable[[int], Any]:
    """Callable for ``GapFiller``: rebuild closed DEFERRED minutes from a trade ID on, return how many."""
    from src.data_ingestion.deferred_candles import rebuild_deferred_candles

    async def rebuild(min_trade_id: int) -> int:
        async with database.acquire() as connection:
            report = await rebuild_deferred_candles(
                _LongQueries(connection, query_timeout_seconds), symbol, apply=True, max_minutes=max_minutes,
                min_trade_id=min_trade_id, count_deferred=False,
            )
        return int(report.rebuilt_minutes)

    return rebuild
