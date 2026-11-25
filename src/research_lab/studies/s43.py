"""S43: the S32 / S42 setup with a limit (maker) entry instead of a market entry. Follow-up to S32, own question.

Rules: docs/research_lab/studien/S42_S43_ORDERBUCH_GROSSE_RANGES_MAKER_PRAEREGISTRIERUNG_ENTWURF.md (draft 0.1).

Same events as S32 (15-minute window, S32 widths) and S42 (1 h, 2 h, 4 h windows, S42 widths). Instead of buying at
the mid one second after the event, a limit order rests at that mid:

- placed 1 s after the event (latency); only trades in later seconds count;
- filled only when a trade prints **through** the limit (buy limit: a trade strictly below it; protocol 1.3, 4.4);
- not filled within ``cancel_s`` (30 s, 60 s, 300 s, each its own question): cancelled, no trade (counted, not a loss);
- after the fill: target and stop as in S32, measured from the fill second; the target exit is a resting limit as
  well and needs a trade strictly through the target; the stop is a market exit (mid based, as in S32) and is checked
  first within a second; at the horizon a market exit at the mid;
- costs: maker 2 bp for each limit fill, taker 5 bp plus 3 bp slippage for a time exit, plus 5 bp more for a stop
  (protocol 1.3); stress doubles all of it.

Reported besides H1/H2: the fill rate and whether the filled events are the worse ones (S32 market outcome of filled
against unfilled events, descriptive).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.depth import tardis
from src.research_lab.protocol import BASE_COSTS, MAKER_FEE, STRESS_COSTS, CostModel
from src.research_lab.studies import s32, s42
from src.research_lab.studies.s32 import Event, Outcome, Second

VERSION = "0.1"
SEED = 43
CANCEL_S = (30, 60, 300)
WINDOWS = {"15m": 900, **s42.WINDOWS}


@dataclass(frozen=True)
class TradeSec:
    lo: float  # lowest trade price in the second
    hi: float  # highest trade price in the second


def trade_seconds_from_csv(path: Path, day: date) -> list[TradeSec | None]:
    """Lowest and highest trade price per second of the UTC day (local receive time, as the book seconds)."""
    tardis.check_day(day)
    start_us = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) * 1_000_000
    lo: list[float | None] = [None] * 86_400
    hi: list[float | None] = [None] * 86_400
    with gzip.open(path, "rt", newline="") as fh:
        for r in csv.DictReader(fh):
            sec = (int(r["local_timestamp"]) - start_us) // 1_000_000
            if not 0 <= sec < 86_400:
                continue
            p = float(r["price"])
            if lo[sec] is None or p < lo[sec]:
                lo[sec] = p
            if hi[sec] is None or p > hi[sec]:
                hi[sec] = p
    return [TradeSec(a, b) if a is not None else None for a, b in zip(lo, hi)]


def load_trades(folder: Path, day: date, *, fetch: bool) -> list[TradeSec | None]:
    path = folder / f"trades_{day.isoformat()}_BTCUSDT.csv.gz"
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        path = tardis.download("trades", day, folder)
    return trade_seconds_from_csv(path, day)


@dataclass(frozen=True)
class MakerOutcome(Outcome):
    fill_s: int = -1  # seconds from placing to the fill, -1 if not filled


def maker_outcome(secs: Sequence[Second | None], trades: Sequence[TradeSec | None], ev: Event, chain: s32.Config,
                  cancel_s: int, target_kind: str = "mitte") -> MakerOutcome:
    j0 = ev.i + chain.entry_delay_s
    if j0 >= len(secs) or secs[j0] is None:
        return MakerOutcome("missing", 0.0, 0.0)
    if target_kind not in s32.TARGETS:
        raise ValueError(target_kind)
    limit = secs[j0].mid
    target = (ev.lo + ev.hi) / 2 if target_kind == "mitte" else (ev.hi if ev.side > 0 else ev.lo)
    stop = ev.lo * (1 - chain.stop_bp / 10_000) if ev.side > 0 else ev.hi * (1 + chain.stop_bp / 10_000)
    if (target - limit) * ev.side <= 0 or (limit - stop) * ev.side <= 0:
        return MakerOutcome("no_room", 0.0, 0.0)
    if j0 + cancel_s + chain.horizon_s >= len(secs):
        return MakerOutcome("missing", 0.0, 0.0)  # cut by the end of the day file
    fill = None
    for j in range(j0 + 1, j0 + cancel_s + 1):
        t = trades[j]
        if t is not None and ((ev.side > 0 and t.lo < limit) or (ev.side < 0 and t.hi > limit)):
            fill = j
            break
    if fill is None:
        return MakerOutcome("unfilled", 0.0, 0.0)
    risk_bp = abs(limit - stop) / limit * 10_000
    last_mid = limit
    for j in range(fill, fill + chain.horizon_s + 1):
        s = secs[j]
        if s is not None:
            last_mid = s.mid
            if (s.mid - stop) * ev.side <= 0:
                return MakerOutcome("stop", (stop - limit) / limit * 10_000 * ev.side, risk_bp, fill - j0)
        t = trades[j]
        if j > fill and t is not None and ((ev.side > 0 and t.hi > target) or (ev.side < 0 and t.lo < target)):
            return MakerOutcome("target", (target - limit) / limit * 10_000 * ev.side, risk_bp, fill - j0)
    return MakerOutcome("time", (last_mid - limit) / limit * 10_000 * ev.side, risk_bp, fill - j0)


def net_r(o: Outcome, costs: CostModel = BASE_COSTS, maker_fee: float = MAKER_FEE) -> float:
    """Net R: maker fee for the limit entry; exit maker at the target, taker plus slippage otherwise."""
    if o.exit == "target":
        cost = 2 * maker_fee
    elif o.exit == "stop":
        cost = maker_fee + costs.fee + costs.stop_slippage
    else:
        cost = maker_fee + costs.fee + costs.slippage
    return (o.gross_bp - cost * 10_000) / o.risk_bp


def net_r_stress(o: Outcome) -> float:
    return net_r(o, STRESS_COSTS, 2 * MAKER_FEE)


def window_setup(name: str) -> tuple[s32.Config, tuple[str, ...], object]:
    """Chain, groups and membership test of one window: 15 min as S32, the others as S42."""
    if name == "15m":
        return s32.CONFIG, s32.GROUPS, s32.in_group
    return s42.CONFIG.chain(WINDOWS[name]), s42.GROUPS, s42.in_group


def day_events(secs: Sequence[Second | None], day: str) -> dict[str, list[Event]]:
    out = {"15m": s32.find_events(secs, day)}
    for k, w in s42.WINDOWS.items():
        out[k] = s42.find_events(secs, day, s42.CONFIG.chain(w))
    return out


def fills(results: dict[date, list[tuple[Event, Outcome]]], market: dict[date, list[tuple[Event, Outcome]]],
          groups: Sequence[str], member) -> dict:
    """Descriptive: fill rate and S32 market outcome (net R) of filled against unfilled events, per section and group."""
    out: dict = {}
    for name in ("training", "validierung"):
        out[name] = {}
        for grp in groups:
            rows = [(o, m) for d in results if s32.section(d) == name
                    for (e, o), (_, m) in zip(results[d], market[d]) if member(e, grp)
                    and o.exit not in ("missing", "no_room") and m.exit in ("target", "stop", "time")]
            filled = [s32.net_r(m) for o, m in rows if o.exit != "unfilled"]
            unfilled = [s32.net_r(m) for o, m in rows if o.exit == "unfilled"]
            out[name][grp] = {"orders": len(rows), "fuellquote": len(filled) / len(rows) if rows else None,
                              "markt_netto_r_gefuellt": sum(filled) / len(filled) if filled else None,
                              "markt_netto_r_nicht_gefuellt": sum(unfilled) / len(unfilled) if unfilled else None}
    return out


def digest() -> str:
    base = {"cancel_s": CANCEL_S, "maker_fee": MAKER_FEE, "s42": s42.CONFIG.digest(), "s32": s32.CONFIG.digest()}
    return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.studies.s43")
    p.add_argument("step", choices=("count", "evaluate"))
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    a = p.parse_args(argv)
    folder, out_dir = a.dir.expanduser(), a.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.step == "evaluate" and not VERSION.startswith("1."):
        raise SystemExit("evaluate is locked while S43 is a draft")
    events: dict[str, dict[date, list[Event]]] = {k: {} for k in WINDOWS}
    res: dict = {k: {c: {t: {} for t in s32.TARGETS} for c in CANCEL_S} for k in WINDOWS}
    mkt: dict = {k: {t: {} for t in s32.TARGETS} for k in WINDOWS}
    for day in s32.study_days():
        secs = s32.load_day(folder, day, fetch=a.fetch)
        trades = load_trades(folder, day, fetch=a.fetch) if a.step == "evaluate" else None
        for k, evs in day_events(secs, day.isoformat()).items():
            events[k][day] = evs
            if a.step == "evaluate":
                chain = window_setup(k)[0]
                for t in s32.TARGETS:
                    mkt[k][t][day] = [(e, s32.outcome(secs, e, chain, target_kind=t)) for e in evs]
                    for c in CANCEL_S:
                        res[k][c][t][day] = [(e, maker_outcome(secs, trades, e, chain, c, t)) for e in evs]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    report = {"studie": "S43", "version": VERSION, "config_sha256": digest(), "tage": len(s32.study_days())}
    if a.step == "count":
        report["zaehlung"] = {k: s42.count(events[k], window_setup(k)[1], window_setup(k)[2]) for k in WINDOWS}
    else:
        ausw: dict = {}
        for k in WINDOWS:
            _, groups, member = window_setup(k)
            for c in CANCEL_S:
                for t in s32.TARGETS:
                    ausw[f"{k}|loeschen_{c}s|ziel_{t}"] = {
                        "h": s42.evaluate(res[k][c][t], groups=groups, member=member, net=net_r,
                                          net_stress=net_r_stress, version=VERSION, seed=SEED),
                        "fuellung": fills(res[k][c][t], mkt[k][t], groups, member)}
        report["auswertung"] = ausw
    path = out_dir / f"s43_{a.step}_{stamp}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
