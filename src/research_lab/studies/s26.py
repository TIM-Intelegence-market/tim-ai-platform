"""S26: effort against result per 1h candle. Does absorption, initiative or a book sweep sort trades?

Rules: docs/research_lab/studien/S26_AUFWAND_GEGEN_ERGEBNIS_PRAEREGISTRIERUNG.md (version 1.0, frozen 2026-11-12). Source: the
order flow video summary Uzi posted on 11.11.2026 ("Effort vs Result"), "go" the same evening. The holdout from
2025-01-01 is never loaded.

    python -m src.research_lab.studies.s26 count    --root data/research_lab --out DIR [--fetch]
    python -m src.research_lab.studies.s26 evaluate --root data/research_lab --out DIR [--fetch]

Moments and trades are S22's (``s22.moments``), the outcome is S24's (Bitunix taker fee, slippage, stop slippage and
funding, ``s24.outcome``). S26 reads only the candle that just closed and the 24 before it, with fixed thresholds:

    effort  = volume against the median of the 24 candles before (``vol_rel``)
    result  = body and close position inside the range, range against ATR14
    delta   = taker buy minus taker sell, as a share of the volume (``delta_share``)

Patterns, each read for the trade's direction (Long; mirrored for Short):

    ABSORPTION  sellers were aggressive (delta share <= -0.10) on high effort (vol_rel >= 1.5), yet the candle
                closed in its upper half: the selling was absorbed, which speaks for a Long
    INITIATIVE  buyers were aggressive (delta share >= +0.10) on high effort (vol_rel >= 1.5), the candle closed in
                its top quarter and its body is at least 0.5 ATR: effort and result agree, continuation
    SWEEP       large range (>= 1.5 ATR) on low effort (vol_rel <= 0.8), body in the trade's direction: the book was
                thin there, continuation

Nothing is fitted. ``count`` is results-blind (how often each pattern fires), ``evaluate`` refuses a draft (a version starting with 0).
"""
from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.research_lab.data.parse import Kline
from src.research_lab.studies import s22
from src.research_lab.studies.s20 import HOUR, atr_series, week_of

VERSION = "1.0"  # frozen 2026-11-12 on Uzi's word ("Starte die Auswertung"); a change needs a new version
SEED = 26
PATTERNS = ("ABSORPTION", "INITIATIVE", "SWEEP")
BASE_HOURS = 24
DELTA_MIN = 0.10
HIGH_EFFORT = 1.5
LOW_EFFORT = 0.8
INITIATIVE_CLOSE = 0.75  # close in the top quarter of the range (Long)
INITIATIVE_BODY_ATR = 0.5
SWEEP_RANGE_ATR = 1.5
MIN_TRADES = 200  # per pattern and section with the pattern firing
MIN_WEEKS = 50
MIN_DIFF_R = 0.05
HOLM_M = len(PATTERNS)


@dataclass(frozen=True, slots=True)
class Row:
    time: int  # close of the 1h candle = entry, UTC ms
    section: str
    direction: str
    patterns: tuple[str, ...]  # patterns that fire for this direction
    net_r: float | None = None


def candle_reading(bars: Sequence[Kline], i: int, atr: float) -> dict | None:
    """Effort and result of ``bars[i]`` for a Long; None without 24 earlier candles or with an empty candle."""
    if i < BASE_HOURS or atr <= 0:
        return None
    bar = bars[i]
    rng = bar.high - bar.low
    if bar.volume <= 0 or rng <= 0:
        return None
    base = sorted(b.volume for b in bars[i - BASE_HOURS:i])
    median = base[len(base) // 2]
    if median <= 0:
        return None
    return {"vol_rel": bar.volume / median, "delta_share": bar.delta / bar.volume,
            "close_pos": (bar.close - bar.low) / rng, "body_atr": (bar.close - bar.open) / atr, "range_atr": rng / atr}


def patterns_for(reading: dict, direction: str) -> tuple[str, ...]:
    """Fixed rules from the module docstring; a Short reads the mirrored candle."""
    s = 1.0 if direction == "LONG" else -1.0
    delta = s * reading["delta_share"]
    close = reading["close_pos"] if s > 0 else 1.0 - reading["close_pos"]
    body = s * reading["body_atr"]
    out = []
    if delta <= -DELTA_MIN and reading["vol_rel"] >= HIGH_EFFORT and close >= 0.5:
        out.append("ABSORPTION")
    if delta >= DELTA_MIN and reading["vol_rel"] >= HIGH_EFFORT and close >= INITIATIVE_CLOSE and body >= INITIATIVE_BODY_ATR:
        out.append("INITIATIVE")
    if reading["range_atr"] >= SWEEP_RANGE_ATR and reading["vol_rel"] <= LOW_EFFORT and body > 0:
        out.append("SWEEP")
    return tuple(out)


def build_rows(bars: Sequence[Kline], *, rates: Sequence[tuple[int, float]] | None = None) -> list[Row]:
    """One row per S22 moment and direction. The outcome is computed only with ``rates`` (``evaluate``)."""
    from src.research_lab.studies import s24

    atrs = atr_series(bars)
    keyed = None if rates is None else ([t for t, _ in rates], [r for _, r in rates])
    rows = []
    for i in s22.moments(bars, atrs):
        reading = candle_reading(bars, i, atrs[i])
        if reading is None:
            continue
        close_time = bars[i].open_time + HOUR
        section = s22.section_of(close_time)
        for direction in s22.DIRECTIONS:
            net_r = None
            if keyed is not None:
                net_r = s24.outcome(bars, i, direction, atrs[i], keyed)
                if net_r is None:
                    continue
            rows.append(Row(close_time, section, direction, patterns_for(reading, direction), net_r))
    return rows


def count(rows: Sequence[Row]) -> dict:
    """Results-blind: how often each pattern fires per section and direction."""
    out: dict = {}
    for name in s22.SECTIONS:
        part = [r for r in rows if r.section == name]
        fires = {p: {d: sum(1 for r in part if r.direction == d and p in r.patterns) for d in s22.DIRECTIONS}
                 for p in PATTERNS}
        weeks = len({week_of(r.time) for r in part})
        out[name] = {"momente": len({r.time for r in part}), "zeilen": len(part), "treffer": fires, "wochen": weeks,
                     "gate": {p: sum(fires[p].values()) >= MIN_TRADES for p in PATTERNS}}
    out["gate"] = {p: all(out[n]["gate"][p] for n in s22.SECTIONS) for p in PATTERNS}
    out["gate_wochen"] = out["validierung"]["wochen"] >= MIN_WEEKS
    return out


def as_s22(rows: Sequence[Row], pattern: str) -> list:
    """Rows in S22's shape: NEHMEN where the pattern fires, AUSLASSEN elsewhere (S22's bootstrap and luck test)."""
    from src.dashboard.chart_verdict import SKIP, TAKE

    return [s22.Row(r.time, r.section, r.direction, 0, TAKE if pattern in r.patterns else SKIP, (), r.net_r) for r in rows]


def evaluate(rows: Sequence[Row], *, boot_draws: int = s22.BOOT_DRAWS, shift_draws: int = s22.SHIFT_DRAWS) -> dict:
    """Per pattern on the validation: mean net R where it fires minus where it does not (H_p > 0), Holm over three."""
    from src.dashboard.chart_verdict import SKIP, TAKE
    from src.research_lab.stats.inference import holm

    if VERSION.startswith("0"):
        raise SystemExit(f"S26 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    gate = count(rows)
    train = [r for r in rows if r.section == "training"]
    valid = [r for r in rows if r.section == "validierung"]
    result: dict = {"gate": gate, "muster": {}}
    p = {}
    for pattern in PATTERNS:
        if not (gate["gate"][pattern] and gate["gate_wochen"]):
            result["muster"][pattern] = {"urteil": "nicht testbar (Gate)"}
            continue
        t, v = as_s22(train, pattern), as_s22(valid, pattern)
        diff = s22.diff(v, TAKE, SKIP)
        p[pattern] = s22.diff_bootstrap_p(v, TAKE, SKIP, seed=f"S26:{pattern}", draws=boot_draws)
        fired = [r.net_r for r in v if r.decision == TAKE]
        result["muster"][pattern] = {
            "validierung_n": len(fired),
            "mittel_netto_r": round(sum(fired) / len(fired), 4) if fired else None,
            "abstand_r": None if diff is None else round(diff, 4),
            "abstand_training_r": s22.diff(t, TAKE, SKIP), "p": p[pattern],
            "glueckstest": s22.shift_test(v, diff, draws=shift_draws) if diff is not None else {"getestet": False},
        }
    passed = holm({k: v for k, v in p.items() if v is not None}, HOLM_M, s22.ALPHA)
    for pattern, info in result["muster"].items():
        if "p" not in info:
            continue
        checks = {"holm": pattern in passed, "abstand": (info["abstand_r"] or 0) >= MIN_DIFF_R,
                  "training_gleiches_vorzeichen": (info["abstand_training_r"] or 0) > 0,
                  "glueckstest": bool(info["glueckstest"].get("getestet")) and info["glueckstest"]["p"] < s22.ALPHA,
                  "positiv_nach_kosten": (info["mittel_netto_r"] or 0) > 0}
        info["kriterien"] = checks
        info["urteil"] = "BESTANDEN (Kandidat)" if all(checks.values()) else "NICHT BESTANDEN"
    passed_any = any(i.get("urteil", "").startswith("BESTANDEN") for i in result["muster"].values())
    result["urteil"] = "BESTANDEN (Kandidat für den Live-Schatten)" if passed_any else "NO ROBUST EDGE PROVEN"
    return result


def main(argv: Sequence[str] | None = None) -> int:
    from src.research_lab.studies import s24

    parser = argparse.ArgumentParser(prog="s26")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Monatsdateien laden (nur bis 2024-12)")
    args = parser.parse_args(argv)
    if args.step == "evaluate" and VERSION.startswith("0"):
        raise SystemExit(f"S26 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    bars, _, digest = s22.load(args.root, fetch=args.fetch)
    rates = s24.load_rates(args.root, fetch=args.fetch) if args.step == "evaluate" else None
    rows = build_rows(bars, rates=rates)
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    result = {"studie": "S26", "version": VERSION, "seed": SEED, "datensatz_sha256": digest, "zaehllauf": count(rows)}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s26_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
