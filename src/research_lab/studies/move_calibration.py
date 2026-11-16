"""Calibration of the move detector (src/dashboard/move_context.py) on the training years, validation 2024.

Bauplan "Preisbewegungen erklären" (Uzi 15./16.11.2026): the thresholds of ``move-context/0.1`` were set by hand.
This run counts, for a grid of thresholds, how many large moves the detector finds per year on BTCUSDT hour
candles built from the S8 minute bars (the same store as S17). It measures nothing about returns or trades:
the only question is how often the detector fires, so the chart shows a handful of moves a month, not every
ordinary candle and not only the crashes of the decade.

- Training 2020-01-01 to 2023-12-31 picks the thresholds: the grid point whose moves per year come closest to
  ``TARGET_PER_YEAR`` (inside ``TARGET_RANGE``), ties broken by the distance to the current rules.
- Validation 2024 is counted once for the chosen point and for the current rules, after the choice.
- The 2025 holdout is never read (``s17.load_candles`` refuses it).

Usage (PS5): ``PYTHONPATH=. ../.venv/bin/python -m src.research_lab.studies.move_calibration --root DATA --out DIR``
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from typing import Any

from src.dashboard import move_context as M

TRAINING = (date(2020, 1, 1), date(2023, 12, 31))
VALIDATION = (date(2024, 1, 1), date(2024, 12, 31))
TARGET_PER_YEAR = 20.0
TARGET_RANGE = (10.0, 30.0)
GRID = {
    "h1_ratio": (2.5, 3.0, 3.5, 4.0, 5.0, 6.0),
    "h1_floor": (0.004, 0.006, 0.008, 0.010, 0.015),
    "h4_sigma": (2.5, 3.0, 3.5, 4.0, 5.0),
}
CURRENT = M.Thresholds()


def hour_rows(candles: Mapping[int, Any]) -> list[dict[str, Any]]:
    """S17 hour candles as move_context candles (hours without a trade are left out)."""
    rows = []
    for start in sorted(candles):
        c = candles[start]
        if not c.trades or c.faulty:
            continue
        opened = datetime.fromtimestamp(start / 1000, timezone.utc)
        rows.append({"open_time": opened, "close_time": opened + timedelta(hours=1), "open": c.open, "high": c.high,
                     "low": c.low, "close": c.close, "volume": float(c.buy_quote + c.sell_quote) or 1.0})
    return rows


def four_hour_rows(h1: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Complete 4h candles (00, 04, ... UTC) from four contiguous hours; incomplete blocks are dropped."""
    groups: dict[datetime, list[Mapping[str, Any]]] = {}
    for c in h1:
        t = c["open_time"]
        groups.setdefault(t.replace(hour=t.hour - t.hour % 4), []).append(c)
    rows = []
    for start in sorted(groups):
        block = groups[start]
        if len(block) != 4:
            continue
        rows.append({"open_time": start, "close_time": start + timedelta(hours=4), "open": block[0]["open"], "close": block[-1]["close"],
                     "high": max(c["high"] for c in block), "low": min(c["low"] for c in block), "volume": sum(c["volume"] for c in block)})
    return rows


def count(h1: Sequence[Mapping[str, Any]], h4: Sequence[Mapping[str, Any]], s1: Sequence[tuple[int, float, float]],
          s4: Sequence[tuple[int, float, float]], limits: M.Thresholds, first: date, last: date) -> dict[str, Any]:
    """Moves whose start lies in ``first..last``, per year, with their direction."""
    moves = M.merge(M.flags_from(h1, "1h", s1, limits) + M.flags_from(h4, "4h", s4, limits))
    moves = [m for m in moves if first <= m["start"].date() <= last]
    years = Counter(m["start"].year for m in moves)
    n_years = last.year - first.year + 1
    return {"moves": len(moves), "per_year": round(len(moves) / n_years, 1), "by_year": dict(sorted(years.items())),
            "only_4h": sum(all(f["tf"] == "4h" for f in m["triggers"]) for m in moves)}


def _distance(limits: M.Thresholds) -> float:
    return (abs(limits.h1_ratio - CURRENT.h1_ratio) / CURRENT.h1_ratio + abs(limits.h1_floor - CURRENT.h1_floor) / CURRENT.h1_floor
            + abs(limits.h4_sigma - CURRENT.h4_sigma) / CURRENT.h4_sigma)


def calibrate(h1: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Grid on training, choice on training only, validation counted after the choice."""
    if any(c["open_time"].date() > VALIDATION[1] for c in h1):
        raise PermissionError("calibration reads no holdout hour")
    h4 = four_hour_rows(h1)
    s1, s4 = M.scores(h1, "1h"), M.scores(h4, "4h")
    grid = []
    for ratio, floor, sigma in product(GRID["h1_ratio"], GRID["h1_floor"], GRID["h4_sigma"]):
        limits = M.Thresholds(ratio, floor, sigma)
        grid.append({"limits": limits.__dict__, "training": count(h1, h4, s1, s4, limits, *TRAINING)})
    inside = [g for g in grid if TARGET_RANGE[0] <= g["training"]["per_year"] <= TARGET_RANGE[1]] or grid
    best = min(inside, key=lambda g: (abs(g["training"]["per_year"] - TARGET_PER_YEAR), _distance(M.Thresholds(**g["limits"]))))
    chosen = M.Thresholds(**best["limits"])
    return {
        "rules_before": M.MOVE_RULES, "target_per_year": TARGET_PER_YEAR, "target_range": TARGET_RANGE,
        "training": [d.isoformat() for d in TRAINING], "validation": [d.isoformat() for d in VALIDATION],
        "hours": len(h1), "four_hours": len(h4),
        "current": {"limits": CURRENT.__dict__, "training": count(h1, h4, s1, s4, CURRENT, *TRAINING),
                    "validation": count(h1, h4, s1, s4, CURRENT, *VALIDATION)},
        "chosen": {"limits": chosen.__dict__, "training": best["training"], "validation": count(h1, h4, s1, s4, chosen, *VALIDATION)},
        "grid": grid,
    }


def report(result: Mapping[str, Any]) -> str:
    cur, ch = result["current"], result["chosen"]

    def line(name: str, block: Mapping[str, Any]) -> str:
        lim = block["limits"]
        return (f"| {name} | {lim['h1_ratio']} x Median, mind. {lim['h1_floor'] * 100:.1f} % | {lim['h4_sigma']} σ | "
                f"{block['training']['per_year']} ({block['training']['by_year']}) | {block['validation']['moves']} |")
    return "\n".join([
        "# Kalibrierung Bewegungs-Detektor (move-context)", "",
        f"Training {result['training'][0]} bis {result['training'][1]}, Validierung {result['validation'][0]} bis {result['validation'][1]}, "
        f"Holdout 2025 nicht gelesen. Ziel {result['target_per_year']:.0f} Bewegungen je Jahr (Bereich {result['target_range'][0]:.0f}–{result['target_range'][1]:.0f}), "
        "Wahl nur auf Training. Gezählt wird nur, wie oft der Detektor anschlägt, keine Rendite, kein Trade.", "",
        f"Stunden: {result['hours']}, 4h-Kerzen: {result['four_hours']}.", "",
        "| Regeln | 1h | 4h | Training je Jahr (je Jahr) | Validierung 2024 |", "|---|---|---|---|---|",
        line("bisher 0.1", cur), line("gewählt", ch), "",
    ])


def main(argv: Sequence[str] | None = None) -> int:
    from src.research_lab.studies import s17

    parser = argparse.ArgumentParser(prog="move_calibration")
    parser.add_argument("--root", type=Path, required=True, help="S8 store with bars/ and bars_manifest.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    candles, digest = s17.load_candles(args.root, TRAINING[0], VALIDATION[1])
    result = calibrate(hour_rows(candles))
    result["dataset_hash"] = digest
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "move_calibration.json").write_text(json.dumps(result, indent=1, default=str))
    (args.out / "move_calibration.md").write_text(report(result))
    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
