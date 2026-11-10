"""OF2 footprint and relative-volume calibration on the training section (preregistration 5.3 and 9).

Results-blind: only how often a building block fires, never what price did afterwards. Reads 2020-01-01 to
2022-12-31 from the S8 store (training only; the validation section and the holdout are refused).

    python -m src.research_lab.of2.calibrate --bars <orderflow_ml root> --out DIR [--workers 16]

Selection rule, fixed in the preregistration before this runs (section 5.3 "Kalibrierung"):
- Footprint step: keep ``fp_step_pct`` 0.1 % if at least half of the traded 15m candles are readable
  (>= ``fp_min_bins`` merged bins), else the native S8 bins (0.05 %).
- For each threshold (imbalance ratio via stacks >= ``fp_stack``, absorption ratio, zero levels) the grid value whose
  share of readable 15m candles lies in 5-15 % and is nearest to 10 %; on a tie the stricter value; if no value is
  inside 5-15 %, the nearest one to that band, and the report says so.
- Relative volume: reported per time frame for the record; ``relvol_min`` 2.0 stays unless its share leaves 5-15 %.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date, timedelta
from multiprocessing import Pool
from pathlib import Path

from src.research_lab.of2.candles import CandleBuilder, relative_volume
from src.research_lab.of2.config import DEFAULT_CONFIG, Config
from src.research_lab.of2.footprint import DayFootprints
from src.research_lab.orderflow_ml.store import MinuteBarStore

STEPS = (0.001, 0.0005)
IMBALANCE = (3.0, 4.0, 5.0, 6.0, 8.0)
ABSORB = (1.5, 2.0, 3.0, 4.0)
ZEROS = (1, 2, 3)
RELVOL = (1.4, 2.0, 2.5)
BAND = (0.05, 0.15)
TARGET = 0.10


def count_day(bars, profile, cfg: Config) -> dict:
    """Counts of one day: traded candles, readable candles and firing building blocks per step and grid value."""
    out: dict = {"c15": 0, "c30": 0, "relvol15": dict.fromkeys(map(str, RELVOL), 0), "relvol30": dict.fromkeys(map(str, RELVOL), 0),
                 "rv15_n": 0, "rv30_n": 0, "steps": {}}
    first_price = next((b.first_price_e8 / 1e8 for b in bars if b.has_trades), 0.0)
    b15, b30 = CandleBuilder(15), CandleBuilder(30)
    c15, c30 = [], []
    for bar in bars:
        if (c := b15.push(bar)) is not None and c.has_trades:
            c15.append(c)
        if (c := b30.push(bar)) is not None and c.has_trades:
            c30.append(c)
    out["c15"], out["c30"] = len(c15), len(c30)
    for name, candles in (("15", c15), ("30", c30)):
        for i, c in enumerate(candles):
            rv = relative_volume(candles[:i], c, cfg.relvol_bars)
            if rv is None:
                continue
            out[f"rv{name}_n"] += 1
            for r in RELVOL:
                out[f"relvol{name}"][str(r)] += rv >= r
    for step in STEPS:
        fps = DayFootprints(profile, step, first_price)
        cell = {"readable": 0, "stack": dict.fromkeys(map(str, IMBALANCE), 0), "absorb": dict.fromkeys(map(str, ABSORB), 0),
                "zeros": dict.fromkeys(map(str, ZEROS), 0)}
        for c in c15:
            fp = fps.candle(c.start, c.minutes)
            if fp.n_bins < cfg.fp_min_bins:
                continue
            cell["readable"] += 1
            for r in IMBALANCE:
                buys, sells = fp.stacks(r, cfg.fp_stack)
                cell["stack"][str(r)] += bool(buys or sells)
            for a in ABSORB:
                cell["absorb"][str(a)] += fp.absorption(1, cfg.fp_absorb_levels, a) or fp.absorption(-1, cfg.fp_absorb_levels, a)
            for z in ZEROS:
                cell["zeros"][str(z)] += fp.zeros_at(1, z) or fp.zeros_at(-1, z)
        out["steps"][str(step)] = cell
    return out


def _add(acc: dict, part: dict) -> dict:
    for k, v in part.items():
        if isinstance(v, dict):
            _add(acc.setdefault(k, {}), v)
        else:
            acc[k] = acc.get(k, 0) + v
    return acc


def _chunk(args: tuple) -> dict:
    root, days = args
    store, acc = MinuteBarStore(root), {}
    for day in days:
        _add(acc, count_day(store.load(day), store.load_profile(day), DEFAULT_CONFIG))
    return acc


def pick(shares: dict[str, float], stricter_is_higher: bool = True) -> tuple[str, bool]:
    """Grid value nearest to 10 % inside 5-15 %; tie -> stricter; none inside -> nearest to the band."""
    def dist_band(x: float) -> float:
        return 0.0 if BAND[0] <= x <= BAND[1] else min(abs(x - BAND[0]), abs(x - BAND[1]))
    inside = {k: v for k, v in shares.items() if BAND[0] <= v <= BAND[1]}
    pool = inside or shares
    key = (lambda k: (round(abs(pool[k] - TARGET), 9), -float(k) if stricter_is_higher else float(k))) if inside else \
          (lambda k: (round(dist_band(pool[k]), 9), -float(k) if stricter_is_higher else float(k)))
    return min(pool, key=key), bool(inside)


def calibrate(totals: dict, cfg: Config = DEFAULT_CONFIG) -> dict:
    steps = {s: totals["steps"][str(s)] for s in STEPS}
    readable_share = {str(s): steps[s]["readable"] / totals["c15"] if totals["c15"] else 0.0 for s in STEPS}
    step = 0.001 if readable_share["0.001"] >= 0.5 else 0.0005
    cell = steps[step]
    n = cell["readable"] or 1
    shares = {fam: {k: v / n for k, v in cell[fam].items()} for fam in ("stack", "absorb", "zeros")}
    imbalance, imb_ok = pick(shares["stack"])
    absorb, abs_ok = pick(shares["absorb"])
    zeros, zer_ok = pick(shares["zeros"])
    rv = {tf: {k: v / totals[f"rv{tf}_n"] for k, v in totals[f"relvol{tf}"].items()} if totals[f"rv{tf}_n"] else {} for tf in ("15", "30")}
    relvol_ok = all(BAND[0] <= rv[tf].get("2.0", 0.0) <= BAND[1] for tf in rv)
    relvol = 2.0 if relvol_ok else float(pick({k: min(rv["15"][k], rv["30"][k]) for k in rv["15"]})[0])
    return {"candles_15m": totals["c15"], "candles_30m": totals["c30"], "readable_share": readable_share,
            "shares": shares, "relvol_share": rv,
            "chosen": {"fp_step_pct": step, "fp_imbalance": float(imbalance), "fp_absorb_ratio": float(absorb),
                       "fp_zero_levels": int(zeros), "relvol_min": relvol},
            "inside_band": {"fp_imbalance": imb_ok, "fp_absorb_ratio": abs_ok, "fp_zero_levels": zer_ok, "relvol_min": relvol_ok}}


def report(result: dict) -> str:
    def pct(x: float) -> str:
        return f"{x:.1%}"
    lines = ["# OF2 Kalibrierung Training 2020–2022 (nur Häufigkeiten)", "",
             f"15m-Kerzen mit Handel: {result['candles_15m']}, 30m: {result['candles_30m']}.", "",
             "| Stufe | lesbare 15m-Kerzen |", "|---|---|"]
    lines += [f"| {k} | {pct(v)} |" for k, v in result["readable_share"].items()]
    for fam, title in (("stack", "Stapel ≥ 3 je Imbalance-Faktor"), ("absorb", "Absorption je Faktor"), ("zeros", "Nullen je Stufenzahl")):
        lines += ["", f"## {title} (Anteil lesbarer Kerzen)", "", "| Wert | Anteil |", "|---|---|"]
        lines += [f"| {k} | {pct(v)} |" for k, v in result["shares"][fam].items()]
    for tf, rows in result["relvol_share"].items():
        lines += ["", f"## Relativvolumen {tf}m", "", "| ab | Anteil |", "|---|---|"] + [f"| {k} | {pct(v)} |" for k, v in rows.items()]
    lines += ["", "## Gewählt (Regel aus der Präregistrierung)", ""]
    lines += [f"- `{k}` = {v}{'' if result['inside_band'].get(k, True) else ' (kein Wert im Band 5–15 %)'}" for k, v in result["chosen"].items()]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.of2.calibrate")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    cfg = DEFAULT_CONFIG
    first, last = date.fromisoformat(cfg.first_day), date.fromisoformat(cfg.training_end)
    present = set(MinuteBarStore(args.bars).present_days())
    days = [d for d in (first + timedelta(days=i) for i in range((last - first).days + 1)) if d in present]
    workers = max(1, min(args.workers, len(days)))
    chunks = [(args.bars, days[i::workers]) for i in range(workers)]
    if workers > 1:
        with Pool(workers) as pool:
            parts = pool.map(_chunk, chunks)
    else:
        parts = [_chunk(chunks[0])]
    totals: dict = {}
    for part in parts:
        _add(totals, part)
    result = calibrate(totals, cfg)
    result.update({"tage": len(days), "erster_tag": first.isoformat(), "letzter_tag": last.isoformat(),
                   "datensatz_hash": MinuteBarStore(args.bars).dataset_hash(days)})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "of2_kalibrierung.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (args.out / "of2_kalibrierung.md").write_text(report(result))
    print(json.dumps(result["chosen"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
