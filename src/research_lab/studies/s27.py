"""S27 (draft): the S24 indicators on larger trades. Does a wider stop leave room for an edge after Bitunix costs?

Rules: docs/research_lab/studien/S27_GROESSERE_TRADES_PRAEREGISTRIERUNG_ENTWURF.md (version 0.1). Source: S24 1.0
failed on 11.11.2026 because every standard trade (stop 1 ATR14 on 1h) lost after costs, even the ones M2 picked;
Uzi said "go" to a new study with fewer, larger trades the same evening. The holdout from 2025-01-01 is never
loaded.

    python -m src.research_lab.studies.s27 count    --root data/research_lab --out DIR [--fetch] [--workers N] --footprint S8_ROOT --fp-cache DIR
    python -m src.research_lab.studies.s27 evaluate --root data/research_lab --out DIR --workers N --footprint S8_ROOT --fp-cache DIR

Everything is S24 1.0 except the trade itself, which is fixed once (no search):

    stop 3 ATR14 (1h), target 6 ATR14 (1h), at most 168 h (7 days); then the trade leaves at the close

Features, the six families, both models (M1 votes, M2 logistic regression fitted once on the training), the costs
(Bitunix taker, slippage, stop slippage, funding over the whole holding time), the tests and the five S24 criteria
are reused unchanged (``s24.build_rows``, ``s24.evaluate``). Two things are added:

    purge     a moment counts only when its 168 h lie inside its own section (S22 did this for 48 h)
    sequence  a sixth criterion: the trades a model takes one after the other, never two at once (the next
              NEHMEN after the exit), must also be positive after costs on the validation, with >= 30 trades

``count`` is results-blind. ``evaluate`` refuses a draft.
"""
from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from src.research_lab.bitunix.contract import FEE_TAKER
from src.research_lab.bitunix.leverage import SLIPPAGE, STOP_SLIPPAGE
from src.research_lab.data.parse import Kline
from src.research_lab.studies import s22, s24
from src.research_lab.studies.s20 import HOUR, atr_series, week_of

VERSION = "0.1"
SEED = 27
STOP_ATR = 3.0
TARGET_ATR = 6.0
HORIZON = 168  # hours
MIN_SEQUENCE = 30  # trades in the validation sequence before the sixth criterion can pass


def outcome(bars: Sequence[Kline], i: int, direction: str, atr: float,
            rates: tuple[Sequence[int], Sequence[float]]) -> tuple[float, int] | None:
    """(net R, exit close time) of the S27 trade at the close of ``bars[i]``; costs exactly as ``s24.outcome``.

    Stop first when one candle holds both. None when the 168 following candles are not all there.
    """
    from bisect import bisect_right

    if i + HORIZON >= len(bars) or bars[i + HORIZON].open_time - bars[i].open_time != HORIZON * HOUR:
        return None
    entry = bars[i].close
    risk = STOP_ATR * atr
    sign = 1.0 if direction == "LONG" else -1.0
    stop, target = entry - sign * risk, entry + sign * TARGET_ATR * atr
    exit_k, exit_price, stopped = i + HORIZON, bars[i + HORIZON].close, False
    for k in range(i + 1, i + HORIZON + 1):
        bar = bars[k]
        if (bar.low <= stop) if sign > 0 else (bar.high >= stop):
            exit_k, exit_price, stopped = k, stop, True
            break
        if (bar.high >= target) if sign > 0 else (bar.low <= target):
            exit_k, exit_price = k, target
            break
    gross = sign * (exit_price - entry) / risk
    side = FEE_TAKER + SLIPPAGE
    cost = entry * side + exit_price * (side + (STOP_SLIPPAGE if stopped else 0.0))
    times, values = rates
    lo = bisect_right(times, bars[i].open_time + HOUR)
    hi = bisect_right(times, bars[exit_k].open_time + HOUR)
    funding = sign * sum(values[lo:hi]) * entry
    return gross - (cost + funding) / risk, bars[exit_k].open_time + HOUR


def window_inside(bars: Sequence[Kline], i: int) -> bool:
    """Times only, no price: the 168 candles after ``bars[i]`` exist and end inside the moment's own section."""
    close_time = bars[i].open_time + HOUR
    section = s22.section_of(close_time)
    if section is None or close_time + HORIZON * HOUR > s22.SECTIONS[section][1]:
        return False
    return i + HORIZON < len(bars) and bars[i + HORIZON].open_time - bars[i].open_time == HORIZON * HOUR


def build_rows(bars_1h: Sequence[Kline], bars_30m: Sequence[Kline], *, footprint: Mapping | None = None,
               funding: Mapping | None = None, workers: int = 1,
               rates: Sequence[tuple[int, float]] | None = None) -> tuple[list[s24.Row], dict]:
    """S24's feature rows, only moments whose 168 h fit (purge). With ``rates`` (evaluate only) each row gets the
    S27 net R, and the second value maps (time, direction) to the exit close time."""
    index = {b.open_time: k for k, b in enumerate(bars_1h)}
    atrs = atr_series(bars_1h)
    keyed = None if rates is None else ([t for t, _ in rates], [r for _, r in rates])
    out, exits = [], {}
    for row in s24.build_rows(bars_1h, bars_30m, footprint=footprint, funding=funding, workers=workers):
        i = index[row.time - HOUR]
        if not window_inside(bars_1h, i):
            continue
        if keyed is not None:
            res = outcome(bars_1h, i, row.direction, atrs[i], keyed)
            if res is None:
                continue
            row = replace(row, net_r=res[0])
            exits[(row.time, row.direction)] = res[1]
        out.append(row)
    return out, exits


def sequence(rows: Sequence[s24.Row], decide, exits: Mapping[tuple[int, str], int]) -> list[float]:
    """Net R of the trades taken one after the other: the first NEHMEN, then the next NEHMEN after its exit."""
    from src.dashboard.chart_verdict import TAKE

    taken, free_at = [], 0
    for r in sorted(rows, key=lambda r: (r.time, r.direction)):
        if r.time >= free_at and decide(r) == TAKE:
            taken.append(r.net_r)
            free_at = exits[(r.time, r.direction)]
    return taken


def evaluate(rows: Sequence[s24.Row], loaded: Sequence[str], exits: Mapping[tuple[int, str], int], *,
             boot_draws: int = s22.BOOT_DRAWS, shift_draws: int = s22.SHIFT_DRAWS) -> dict:
    """S24's evaluation on the S27 trades, plus the sequence criterion per model."""
    from src.dashboard.chart_verdict import SKIP, TAKE

    if VERSION.startswith("0"):
        raise SystemExit(f"S27 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    result = s24.evaluate(rows, loaded, boot_draws=boot_draws, shift_draws=shift_draws)
    if "modelle" not in result:
        return result
    full = [r for r in rows if s24.complete(r, s24.FAMILIES) and r.net_r is not None]
    train = [r for r in full if r.section == "training"]
    valid = [r for r in full if r.section == "validierung"]
    logit, take_at, skip_at = s24.m2_rule(train)  # deterministic: the same rule s24.evaluate just used

    def m2(r: s24.Row) -> str:
        p = logit.prob(r)
        return TAKE if p >= take_at else SKIP if p <= skip_at else "NEUTRAL"

    weeks = len({week_of(r.time) for r in valid}) or 1
    verdicts = {}
    for name, decide in {"M1": s24.m1_decision, "M2": m2}.items():
        seq = sequence(valid, decide, exits)
        mean = sum(seq) / len(seq) if seq else None
        info = result["modelle"][name]
        info["folge"] = {"n": len(seq), "je_woche": round(len(seq) / weeks, 2),
                         "mittel_netto_r": None if mean is None else round(mean, 4),
                         "summe_r": round(sum(seq), 2)}
        info["kriterien"]["folge_positiv_nach_kosten"] = len(seq) >= MIN_SEQUENCE and mean is not None and mean > 0
        verdicts[name] = "BESTANDEN (Kandidat)" if all(info["kriterien"].values()) else "NICHT BESTANDEN"
    result["handel"] = {"stop_atr": STOP_ATR, "ziel_atr": TARGET_ATR, "stunden": HORIZON}
    result["urteil_je_modell"] = verdicts
    result["urteil"] = ("BESTANDEN (Kandidat für den Live-Schatten)" if "BESTANDEN (Kandidat)" in verdicts.values()
                        else "NO ROBUST EDGE PROVEN")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s27")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Monatsdateien laden (nur bis 2024-12)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--footprint", type=Path, help="S8-Speicher; ohne ihn fehlt Familie F")
    parser.add_argument("--fp-cache", type=Path)
    args = parser.parse_args(argv)
    if args.step == "evaluate" and VERSION.startswith("0"):
        raise SystemExit(f"S27 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    bars_1h, bars_30m, digest = s22.load(args.root, fetch=args.fetch)
    events = s24.moment_events(bars_1h)
    rates = s24.load_rates(args.root, fetch=args.fetch)
    funding = s24.load_funding(rates, events)
    footprint = s24.load_footprint(args.footprint, events, workers=args.workers, cache=args.fp_cache) if args.footprint else None
    loaded = [f for f in s24.FAMILIES if not (f == "F" and footprint is None)]
    rows, exits = build_rows(bars_1h, bars_30m, footprint=footprint, funding=funding, workers=args.workers,
                             rates=rates if args.step == "evaluate" else None)
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    result = {"studie": "S27", "version": VERSION, "seed": SEED, "datensatz_sha256": digest,
              "handel": {"stop_atr": STOP_ATR, "ziel_atr": TARGET_ATR, "stunden": HORIZON},
              "zaehllauf": s24.count(rows, loaded)}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(rows, loaded, exits)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s27_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
