"""S7b forward journal: the frozen candidates S7b-D20-T3/T4 on live 4h USD-M bars, paper only.

Uzi, 2026-11-01: "go s7b-Journal". Study doc section 14
(docs/research_lab/studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md).

What it does on every step (the research workshop calls it every 15 minutes on the Mac):

1. Fetch the closed 4h klines of BTCUSDT, ETHUSDT and SOLUSDT from Binance USD-M (public REST) and
   the funding settlements, and append them to a local cache. Only bars whose close lies in the past
   are kept; a bar once cached is never replaced.
2. Re-run the study's own engine (``engine.run_portfolio``, cap 1, BTC > ETH > SOL, base costs,
   funding, ``gap_entry_as_loss``) exactly like ``scripts/research_lab_s7b.py simulate``, with signals
   allowed only from ``start_ms`` on. ``start_ms`` is the first 4h open at or after the moment the
   journal was started, so every counted signal lies after the start (prospective, no back-dating).
3. Append what is new to a hash-chained journal: each signal when it is first seen (with the real
   clock and the delay after the bar close), each closed trade once. A recomputed trade that differs
   from the logged one is written as a ``mismatch`` event, never overwritten.

Nothing here sends an order, changes a rule, touches the register or the holdout 2025+, or counts in
the plan journal's net R. The register status of both variants stays ``candidate``.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.research_lab.backtest.engine import BacktestResult, Trade, run_portfolio
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s7, s7b
from src.research_lab.protocol import BASE_COSTS
from src.research_lab.stats.random_entry import atr_at_signal

SCHEMA = "tim_forward_journal/1"
STUDY = "S7b"
FOLDER = Path("data/research/forward/S7b")
GENESIS = "0" * 64
FAPI = "https://fapi.binance.com"
TIMEOUT_SECONDS = 10
MAX_BYTES = 4_000_000
KLINE_LIMIT = 1500
FUNDING_LIMIT = 1000
INTERVAL_MS = s7.INTERVAL_MS
SYMBOLS: tuple[str, ...] = s7b.PRIORITY
VARIANTS: tuple[s7.S7Variant, ...] = s7b.GATE_VARIANTS  # S7b-D20-T3, S7b-D20-T4: the registered candidates
WARMUP_BARS = 260  # >= the 200-bar warm-up of the rule, with room for one or two missing bars
LATE_AFTER_MS = INTERVAL_MS  # a signal first written more than one bar after its close is flagged as late
# Reference numbers from the study (section 12, validation 2023-2024) and its holdout minimum (section 5.1).
REFERENCE = {"S7b-D20-T3": {"e_r": 0.272, "n": 207, "months": 24, "hit_rate": 0.261},
             "S7b-D20-T4": {"e_r": 0.251, "n": 189, "months": 24, "hit_rate": 0.169}}
MIN_TRADES = 100
# Register entries of the two candidates (docs/research_lab/REGISTER.jsonl), for the start event.
REGISTER_HASHES = {"S7b-D20-T3": "def643b5ba4875d59697452dafe933b56ef1b1289020be7ba8afc18a7d4d8c94",
                   "S7b-D20-T4": "c46780f19669b3d1c6277fe7295ed24b637d1c3a0f3a1af3bce1dd3c9080ae4a"}

Fetch = Callable[[str, Mapping[str, str]], Any]


class ForwardError(RuntimeError):
    pass


def fetch_json(path: str, params: Mapping[str, str]) -> Any:
    request = Request(f"{FAPI}{path}?{urlencode(params)}", headers={"User-Agent": "TIM-research-forward/1 (read-only)"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed public https host
            body = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        raise ForwardError(f"binance http {error.code}") from error
    if len(body) > MAX_BYTES:
        raise ForwardError("binance answer too large")
    return json.loads(body)


def _ms(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ForwardError("time without zone")
    return int(moment.timestamp() * 1000)


def _iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def first_open_at_or_after(ms: int) -> int:
    return -(-ms // INTERVAL_MS) * INTERVAL_MS


def _digest(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ForwardError("non-finite number from the exchange")
    return number


def parse_kline(row: Sequence[Any]) -> Kline:
    """One row of /fapi/v1/klines: [open time, o, h, l, c, volume, close time, quote, trades, taker buy base, ...]."""
    if not isinstance(row, (list, tuple)) or len(row) < 10:
        raise ForwardError("kline row malformed")
    bar = Kline(int(row[0]), _finite(row[1]), _finite(row[2]), _finite(row[3]), _finite(row[4]), _finite(row[5]),
                int(row[6]), _finite(row[9]))
    if bar.open_time % INTERVAL_MS or bar.close_time != bar.open_time + INTERVAL_MS - 1:
        raise ForwardError("kline not on the 4h grid")
    if not (bar.low <= min(bar.open, bar.close) and bar.high >= max(bar.open, bar.close) and bar.low > 0):
        raise ForwardError("kline prices inconsistent")
    return bar


def _bar_row(bar: Kline) -> list[Any]:
    return [bar.open_time, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.close_time, bar.taker_buy_volume]


def _row_bar(row: Sequence[Any]) -> Kline:
    return Kline(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), int(row[6]), float(row[7]))


class ForwardJournal:
    """Cache, journal and status of the S7b forward observation in one folder (``data/research/forward/S7b``)."""

    def __init__(self, folder: Path | str = FOLDER, *, fetch: Fetch | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.folder = Path(folder)
        self.fetch = fetch or fetch_json
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # -- files -----------------------------------------------------------------------------------

    @property
    def journal_path(self) -> Path:
        return self.folder / "journal.jsonl"

    @property
    def status_path(self) -> Path:
        return self.folder / "status.json"

    def _write_json(self, path: Path, data: Any) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default

    def events(self) -> list[dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        events, previous = [], GENESIS
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            body = {k: v for k, v in event.items() if k != "hash"}
            if body.get("previous") != previous or event.get("hash") != _digest(previous, body):
                raise ForwardError("forward journal: hash chain broken")
            previous = event["hash"]
            events.append(event)
        return events

    def _append(self, bodies: Sequence[Mapping[str, Any]]) -> None:
        if not bodies:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            events = self.events()
            previous = events[-1]["hash"] if events else GENESIS
            for body in bodies:
                full = {**body, "schema": SCHEMA, "study": STUDY, "counts_in_net_r": False, "previous": previous}
                previous = _digest(previous, full)
                handle.write(json.dumps({**full, "hash": previous}, sort_keys=True, ensure_ascii=False) + "\n")

    def start_event(self) -> dict[str, Any] | None:
        events = self.events()
        return events[0] if events and events[0].get("kind") == "start" else None

    # -- data --------------------------------------------------------------------------------------

    def load_bars(self, symbol: str) -> list[Kline]:
        return [_row_bar(r) for r in self._read_json(self.folder / f"bars_{symbol}.json", [])]

    def load_funding(self, symbol: str) -> list[FundingRate]:
        return [FundingRate(int(t), float(r)) for t, r in self._read_json(self.folder / f"funding_{symbol}.json", [])]

    def update_bars(self, symbol: str, from_ms: int, now_ms: int) -> list[Kline]:
        bars = self.load_bars(symbol)
        cursor = bars[-1].open_time + INTERVAL_MS if bars else from_ms
        for _ in range(50):  # bounded paging
            rows = self.fetch("/fapi/v1/klines", {"symbol": symbol, "interval": s7.INTERVAL, "startTime": str(cursor),
                                                  "limit": str(KLINE_LIMIT)})
            if not isinstance(rows, list):
                raise ForwardError(f"{symbol}: klines answer is not a list")
            fresh = [b for b in (parse_kline(r) for r in rows) if b.open_time >= cursor and b.close_time < now_ms]
            for bar in fresh:
                if bars and bar.open_time <= bars[-1].open_time:
                    raise ForwardError(f"{symbol}: klines out of order")
                bars.append(bar)
            if len(rows) < KLINE_LIMIT or not fresh:
                break
            cursor = bars[-1].open_time + INTERVAL_MS
        self._write_json(self.folder / f"bars_{symbol}.json", [_bar_row(b) for b in bars])
        return bars

    def update_funding(self, symbol: str, from_ms: int, now_ms: int) -> list[FundingRate]:
        rates = self.load_funding(symbol)
        cursor = rates[-1].time + 1 if rates else from_ms
        for _ in range(50):
            rows = self.fetch("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": str(cursor), "limit": str(FUNDING_LIMIT)})
            if not isinstance(rows, list):
                raise ForwardError(f"{symbol}: funding answer is not a list")
            fresh = sorted((FundingRate(int(r["fundingTime"]), _finite(r["fundingRate"])) for r in rows
                            if int(r["fundingTime"]) >= cursor and int(r["fundingTime"]) <= now_ms), key=lambda f: f.time)
            rates.extend(fresh)
            if len(rows) < FUNDING_LIMIT or not fresh:
                break
            cursor = rates[-1].time + 1
        self._write_json(self.folder / f"funding_{symbol}.json", [[f.time, f.rate] for f in rates])
        return rates

    # -- one step ----------------------------------------------------------------------------------

    def start(self, *, code_commit: str = "") -> dict[str, Any]:
        """Write the start event once. Signals count from the first 4h open at or after now."""
        existing = self.start_event()
        if existing is not None:
            return existing
        if self.journal_path.exists() and self.events():
            raise ForwardError("journal has events but no start event")
        now = self.clock()
        start_ms = first_open_at_or_after(_ms(now))
        self._append([{"kind": "start", "at": _iso_ms(_ms(now)), "start_ms": start_ms, "start": _iso_ms(start_ms),
                       "variants": [v.variant_id for v in VARIANTS], "register_hashes": REGISTER_HASHES,
                       "symbols": list(SYMBOLS), "rules": "S7b 1.0, Abschnitt 4 (unverändert), Kosten BASE_COSTS",
                       "approval": "Uzi 2026-11-01 09:04 Ortszeit: \"go s7b-Journal\"", "code_commit": code_commit}])
        return self.start_event() or {}

    def simulate(self, bars_by_symbol: Mapping[str, Sequence[Kline]], funding_by_symbol: Mapping[str, Sequence[FundingRate]],
                 start_ms: int, variant: s7.S7Variant) -> dict[str, BacktestResult]:
        """Same call as ``scripts/research_lab_s7b.py simulate`` with the base costs, signals from ``start_ms`` on."""
        return run_portfolio(bars_by_symbol, {sym: s7.breakout(variant) for sym in SYMBOLS}, INTERVAL_MS, priority=SYMBOLS,
                             costs=BASE_COSTS, funding_by_symbol=funding_by_symbol,
                             start_ms_by_symbol={sym: start_ms for sym in SYMBOLS}, end_ms=None, atr_at_signal=atr_at_signal,
                             gap_entry_as_loss=True, max_positions=s7b.MAX_POSITIONS)

    def step(self, *, code_commit: str = "") -> dict[str, Any]:
        start = self.start(code_commit=code_commit)
        start_ms = int(start["start_ms"])
        now = self.clock()
        now_ms = _ms(now)
        from_ms = start_ms - WARMUP_BARS * INTERVAL_MS
        bars = {sym: self.update_bars(sym, from_ms, now_ms) for sym in SYMBOLS}
        funding = {sym: self.update_funding(sym, start_ms, now_ms) for sym in SYMBOLS}
        last_closed = {sym: (b[-1].open_time if b else None) for sym, b in bars.items()}
        events = self.events()
        logged_signals = {(e["variant"], e["symbol"], e["signal_time"]) for e in events if e["kind"] == "signal"}
        logged_trades = {(e["variant"], e["symbol"], e["signal_time"]): e for e in events if e["kind"] == "trade"}
        mismatches = {e["key"] for e in events if e["kind"] == "mismatch"}
        new: list[dict[str, Any]] = []
        variants: dict[str, Any] = {}
        for variant in VARIANTS:
            results = self.simulate(bars, funding, start_ms, variant)
            closed: list[tuple[str, Trade]] = []
            open_trades: list[dict[str, Any]] = []
            pending: list[dict[str, Any]] = []
            for sym in SYMBOLS:
                result, sym_bars = results[sym], bars[sym]
                last_bar = sym_bars[-1] if sym_bars else None
                ignored, locked = set(result.ignored_times), set(result.locked_times)
                for time, side, stop in result.signals:
                    if time < start_ms:
                        continue
                    status = "locked" if time in locked else "ignored" if time in ignored else "taken"
                    if last_bar is not None and time == last_bar.open_time and status == "taken":
                        # no next bar yet: the entry (and, with two coins on one bar, the priority) is still open
                        status = "pending"
                    if (variant.variant_id, sym, time) not in logged_signals:
                        delay = now_ms - (time + INTERVAL_MS)
                        new.append({"kind": "signal", "variant": variant.variant_id, "symbol": sym, "signal_time": time,
                                    "signal": _iso_ms(time), "side": "LONG" if side == 1 else "SHORT", "stop": stop,
                                    "status": status, "at": _iso_ms(now_ms), "delay_minutes": round(delay / 60000, 1),
                                    "late": delay > LATE_AFTER_MS})
                        logged_signals.add((variant.variant_id, sym, time))
                    if status == "pending":
                        pending.append({"symbol": sym, "side": "LONG" if side == 1 else "SHORT", "stop": stop,
                                        "signal": _iso_ms(time), "entry_at": _iso_ms(time + INTERVAL_MS)})
                for trade in result.trades:
                    if trade.signal_time < start_ms:
                        continue
                    if trade.reason == "end":  # still open at the last closed bar
                        open_trades.append({"symbol": sym, "side": "LONG" if trade.side == 1 else "SHORT",
                                            "entry": trade.entry_price, "stop": trade.stop, "entry_time": _iso_ms(trade.entry_time),
                                            "signal": _iso_ms(trade.signal_time), "bars_held": trade.bars_held,
                                            "unrealized_r": round(trade.r, 3), "target_r": trade.target_r})
                        continue
                    closed.append((sym, trade))
                    key = (variant.variant_id, sym, trade.signal_time)
                    body = _trade_body(variant.variant_id, sym, trade)
                    logged = logged_trades.get(key)
                    if logged is None:
                        new.append({**body, "at": _iso_ms(now_ms)})
                        logged_trades[key] = body
                    elif any(logged.get(f) != body[f] for f in TRADE_FIELDS):
                        mkey = f"{variant.variant_id}|{sym}|{trade.signal_time}|{_digest('', body)[:16]}"
                        if mkey not in mismatches:
                            new.append({"kind": "mismatch", "key": mkey, "variant": variant.variant_id, "symbol": sym,
                                        "signal_time": trade.signal_time, "logged": {f: logged.get(f) for f in TRADE_FIELDS},
                                        "recomputed": {f: body[f] for f in TRADE_FIELDS}, "at": _iso_ms(now_ms)})
                            mismatches.add(mkey)
            # The cap admits one entry: with an open trade nothing is pending (the engine marks it locked);
            # with two signals on the same last bar, the first in priority order (BTC > ETH > SOL) wins.
            variants[variant.variant_id] = {"open": open_trades, "pending": [] if open_trades else pending[:1],
                                            "locked_signals": sum(len(r.locked_times) for r in results.values()),
                                            "invalid_signals": sum(r.invalid_signals for r in results.values())}
        self._append(new)
        status = {"schema": SCHEMA, "study": STUDY, "checked_at": _iso_ms(now_ms), "start": start["start"],
                  "last_closed_bar": {sym: (_iso_ms(t) if t is not None else None) for sym, t in last_closed.items()},
                  "new_events": len(new), **summary(self.events(), variants)}
        self._write_json(self.status_path, status)
        return status

    def status(self) -> dict[str, Any] | None:
        return self._read_json(self.status_path, None)


TRADE_FIELDS = ("entry_time", "exit_time", "side", "entry_price", "exit_price", "stop", "reason", "bars_held", "r",
                "cost_r", "funding_r")


def _trade_body(variant_id: str, symbol: str, trade: Trade) -> dict[str, Any]:
    return {"kind": "trade", "variant": variant_id, "symbol": symbol, "signal_time": trade.signal_time,
            "signal": _iso_ms(trade.signal_time), "entry_time": trade.entry_time, "exit_time": trade.exit_time,
            "exit": _iso_ms(trade.exit_time), "side": "LONG" if trade.side == 1 else "SHORT",
            "entry_price": round(trade.entry_price, 8), "exit_price": round(trade.exit_price, 8), "stop": round(trade.stop, 8),
            "reason": trade.reason, "bars_held": trade.bars_held, "r": round(trade.r, 6), "cost_r": round(trade.cost_r, 6),
            "funding_r": round(trade.funding_r, 6), "target_r": trade.target_r}


def max_drawdown(values: Sequence[float]) -> float:
    peak = equity = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def summary(events: Sequence[Mapping[str, Any]], live: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Counts from the journal only (logged trades, in exit order); ``live`` adds open/pending positions."""
    live = live or {}
    rows: dict[str, Any] = {}
    for variant in VARIANTS:
        vid = variant.variant_id
        trades = sorted((e for e in events if e.get("kind") == "trade" and e.get("variant") == vid), key=lambda e: e["exit_time"])
        values = [float(e["r"]) for e in trades]
        reference = REFERENCE[vid]
        rows[vid] = {"target_r": variant.target_r, "trades": len(values), "net_r": round(sum(values), 3),
                     "mean_r": round(sum(values) / len(values), 3) if values else None,
                     "hits": sum(e["reason"] in ("target", "target_gap") for e in trades),
                     "wins": sum(v > 0 for v in values), "max_drawdown_r": round(max_drawdown(values), 3),
                     "signals": sum(1 for e in events if e.get("kind") == "signal" and e.get("variant") == vid
                                    and e.get("status") in ("taken", "pending")),
                     "late_signals": sum(1 for e in events if e.get("kind") == "signal" and e.get("variant") == vid and e.get("late")),
                     "mismatches": sum(1 for e in events if e.get("kind") == "mismatch" and e.get("variant") == vid),
                     "reference_e_r": reference["e_r"], "reference_hit_rate": reference["hit_rate"],
                     "reference_trades_per_month": round(reference["n"] / reference["months"], 1), "min_trades": MIN_TRADES,
                     "recent": [{k: e[k] for k in ("symbol", "side", "signal", "exit", "reason", "r")} for e in trades[-5:][::-1]],
                     **{k: v for k, v in (live.get(vid) or {}).items()}}
    return {"variants": rows}
