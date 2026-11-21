"""Absorptions-Schattenfilter: would a counter-absorption in the plan's path have blocked the plan? (paper only)

Uzi 17.11.2026 ("go"), observation from the live chart: TIM shorted under the 1D VAL exactly where heavy absorption
showed buyers taking the selling (a sweep), and bought under the 1D VAH. Hypothesis H1 (new, untested): a plan that runs
INTO a level with absorption is a breakout signal into a held level and loses on average.

This module changes nothing. It reads the orderflow shadow (``orderflow_shadow``: per plan ``lage_at_plan`` with the
nearest levels and their absorption flag, plus the journal outcome) and derives per plan:

- ``blocked``: rule R-ABS-1 (frozen in docs/research_lab/studien/ABSORPTIONS_FILTER_SCHATTEN_PRAEREGISTRIERUNG.md):
  a level with ``absorption`` lies in the direction of travel, from ``BEHIND_PCT`` behind the price up to ``BAND_PCT``
  ahead of it (SHORT: below, LONG: above).
- the verdict after ``MIN_BLOCKED`` closed blocked plans: mean net R of the blocked plans, bootstrap upper bound.

Only information of the plan moment is used (``lage_at_plan``), so there is no look-ahead. Nothing here trades,
filters a journal, or changes a score; the plan journal keeps trading as it does.

    python -m src.dashboard.absorption_shadow [data/journal/tim_orderflow_shadow.json]
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

RULE = "R-ABS-1/1.0"
BAND_PCT = 0.30        # absorbing level up to this far ahead of the price, in the direction of travel
BEHIND_PCT = 0.05      # ... or this far behind it (price already through the level)
MIN_BLOCKED = 30       # closed blocked plans before a verdict
MIN_EFFECT_R = -0.10   # blocked mean net R must be at or below this ...
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 17
UPPER_QUANTILE = 0.95  # ... and the one-sided upper bound of the mean must be below 0


def check(direction: str, lage_at_plan: Mapping[str, Any] | None) -> dict[str, Any]:
    """Rule R-ABS-1 for one plan. ``readable`` False means no fresh Lage: the plan counts as passed, not blocked."""
    levels = (lage_at_plan or {}).get("levels")
    if direction not in ("LONG", "SHORT") or not lage_at_plan or levels is None:
        return {"rule": RULE, "readable": False, "blocked": False, "level": None}
    sign = 1 if direction == "LONG" else -1
    hits = []
    for level in levels:
        distance = level.get("distance_pct")
        if not level.get("absorption") or not isinstance(distance, (int, float)) or isinstance(distance, bool):
            continue
        ahead = sign * float(distance)   # > 0: level lies in the direction of travel
        if -BEHIND_PCT <= ahead <= BAND_PCT:
            hits.append((abs(ahead), level))
    if not hits:
        return {"rule": RULE, "readable": True, "blocked": False, "level": None}
    _, level = min(hits, key=lambda item: item[0])
    return {"rule": RULE, "readable": True, "blocked": True,
            "level": {"name": level.get("name"), "distance_pct": level.get("distance_pct")}}


def _upper_bound(values: list[float]) -> float:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = sorted(mean(rng.choices(values, k=n)) for _ in range(BOOTSTRAP_DRAWS))
    return means[min(BOOTSTRAP_DRAWS - 1, int(UPPER_QUANTILE * BOOTSTRAP_DRAWS))]


def _closed(plan: Mapping[str, Any]) -> float | None:
    journal = plan.get("journal") or {}
    value = journal.get("net_r")
    if journal.get("status") != "CLOSED" or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def evaluate(state: Mapping[str, Any]) -> dict[str, Any]:
    """Blocked against passed plans of an orderflow-shadow state, with the frozen verdict rule."""
    groups: dict[str, list[float]] = {"blocked": [], "passed": [], "unreadable": []}
    plans = list((state.get("plans") or {}).values())
    for plan in plans:
        net = _closed(plan)
        if net is None:
            continue
        result = check(str(plan.get("direction")), plan.get("lage_at_plan"))
        groups["unreadable" if not result["readable"] else "blocked" if result["blocked"] else "passed"].append(net)
    blocked = groups["blocked"]
    row = {name: {"n": len(v), "mean_net_r": round(mean(v), 4) if v else None, "sum_net_r": round(sum(v), 4)}
           for name, v in groups.items()}
    verdict, upper = "NOCH_NICHT_BEURTEILBAR", None
    if len(blocked) >= MIN_BLOCKED:
        upper = round(_upper_bound(blocked), 4)
        ok = mean(blocked) <= MIN_EFFECT_R and upper < 0
        verdict = "BESTANDEN" if ok else "NICHT_BESTANDEN"
    return {"rule": RULE, "plans": len(plans), "groups": row, "blocked_needed": MIN_BLOCKED,
            "blocked_upper_bound_r": upper, "verdict": verdict,
            "note": "Beobachtung auf Papier; kein Filter ist aktiv. Übernahme nur auf Uzis Wort."}


def main(argv: list[str] | None = None) -> int:
    from src.dashboard.orderflow_shadow import DEFAULT_PATH, load

    args = sys.argv[1:] if argv is None else argv
    state = load(Path(args[0]) if args else DEFAULT_PATH)
    if state is None:
        print("Kein Orderflow-Schatten gefunden", file=sys.stderr)
        return 2
    print(json.dumps(evaluate(state), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
