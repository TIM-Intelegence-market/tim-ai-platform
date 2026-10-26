"""Study K1: cost threshold for plan-journal plans, compared as research variants.

Question: is 0.25 R (plan_cost_check.COST_LIMIT_R) a sensible research limit
for the estimated roundtrip costs of a plan, compared with other limits?

Fixed before any data was read (docs/research_lab/studien/K1_KOSTEN_SCHWELLE.md):
- variants: 0.10, 0.15, 0.20, 0.25, 0.33, 0.50 R and no limit (THRESHOLDS);
- cost model: research protocol 1.1 (protocol.BASE_COSTS) and its stress case
  (protocol.STRESS_COSTS); nothing here sets its own rates;
- cost estimate: the stop-out case from entry to stop, as plan_cost_check shows it;
- outcome: the booked result of closed plan-journal entries (gross_r, fee_r,
  slippage_r, net_r); under stress the booked costs are doubled, because the
  stress case doubles every rate and the booked costs are linear in the rates;
- counting: cluster-aware like journal_review (MIN_CLUSTERS, cluster-block
  bootstrap of the mean net R with a fixed seed).

Descriptive only. The study reads journal views and changes nothing. No limit
is picked from the data and nothing here becomes a filter, an order rule or a
risk parameter: a variant is at most a candidate for a registered hypothesis.
The estimate is known when a plan is recorded, so filtering on it uses no
future information.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from src.dashboard.plan_cost_check import COST_LIMIT_R, COST_UNKNOWN, cost_check
from src.research_lab.journal_review import MIN_CLUSTERS, assign_clusters, closed_cases, cluster_block_bootstrap
from src.research_lab.protocol import BASE_COSTS, STRESS_COSTS, CostModel

STUDY_ID = "K1"
STUDY_VERSION = "cost-threshold/1"
THRESHOLDS: tuple[float | None, ...] = (0.10, 0.15, 0.20, 0.25, 0.33, 0.50, None)
COST_CASES: dict[str, CostModel] = {"base": BASE_COSTS, "stress": STRESS_COSTS}
BOOTSTRAP_SEED = 20261025
INSUFFICIENT = "INSUFFICIENT_CASES"
DESCRIBED = "DESCRIBED"


def stop_out_cost_r(plan: Mapping[str, Any], model: CostModel = BASE_COSTS) -> float | None:
    """Unrounded costs in R of a fill at entry and a stop execution at stop.

    Validity is decided by plan_cost_check.cost_check, so a plan the page shows
    as COST_UNKNOWN is unknown here too."""
    if cost_check(plan)["cost_status"] == COST_UNKNOWN:
        return None
    entry, stop = float(plan["entry"]), float(plan["stop"])
    cost = model.fee * entry + model.slippage * entry + model.fee * stop + model.stop_slippage * stop
    return cost / abs(entry - stop)


def min_stop_distance(limit_r: float, direction: str, model: CostModel = BASE_COSTS) -> float:
    """Smallest stop distance (fraction of entry) whose stop-out costs stay within limit_r.

    LONG, stop = e(1-d): (fee + slip + (fee + stop_slip)(1-d)) / d = L
    SHORT, stop = e(1+d): (fee + slip + (fee + stop_slip)(1+d)) / d = L"""
    total = 2 * model.fee + model.slippage + model.stop_slippage
    exit_side = model.fee + model.stop_slippage
    denominator = limit_r + exit_side if direction == "LONG" else limit_r - exit_side
    if denominator <= 0:
        raise ValueError("limit below the exit-side rate")
    return total / denominator


def _within(cost_r: float | None, limit: float | None) -> bool:
    if cost_r is None:
        return False  # unknown never passes a limit
    return limit is None or round(cost_r, 4) <= limit + 1e-9


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}
    ordered = sorted(values)
    if len(ordered) == 1:
        p25 = p75 = ordered[0]
    else:
        p25, _, p75 = statistics.quantiles(ordered, n=4, method="inclusive")
    return {"n": len(ordered), "min": round(ordered[0], 4), "p25": round(p25, 4), "median": round(statistics.median(ordered), 4),
            "p75": round(p75, 4), "max": round(ordered[-1], 4)}


def _case_rows(journal: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Closed cases with their estimate and their booked outcome under both cost cases."""
    cases = closed_cases(journal)
    clusters = assign_clusters(cases)
    rows = []
    for case in cases:
        booked = float(case.get("fee_r") or 0.0) + float(case.get("slippage_r") or 0.0)
        gross = float(case["gross_r"]) if case.get("gross_r") is not None else float(case["net_r"]) + booked
        rows.append({"id": case["id"], "cluster": clusters[case["id"]], "direction": case.get("direction"),
                     "rule": case.get("rule") or journal.get("rule") or "tim/1", "exit_reason": case.get("exit_reason"),
                     "estimate": {name: stop_out_cost_r(case, model) for name, model in COST_CASES.items()},
                     "gross_r": gross, "net": {"base": float(case["net_r"]), "stress": gross - 2 * booked}})
    return rows


def _variant(plans: Sequence[Mapping[str, Any]], cases: Sequence[Mapping[str, Any]], limit: float | None, case_name: str) -> dict[str, Any]:
    estimates = [stop_out_cost_r(p, COST_CASES[case_name]) for p in plans]
    known = [c for c in estimates if c is not None]
    kept_plans = [c for c in estimates if _within(c, limit)]
    kept = [c for c in cases if _within(c["estimate"][case_name], limit)]
    nets = [c["net"][case_name] for c in kept]
    blocks: dict[str, list[float]] = {}
    for c in kept:
        blocks.setdefault(c["cluster"], []).append(c["net"][case_name])
    interval = cluster_block_bootstrap(list(blocks.values()), seed=BOOTSTRAP_SEED) if len(blocks) >= 2 else (None, None)
    return {
        "limit_r": limit, "cost_case": case_name,
        "plans": len(estimates), "plans_known": len(known), "plans_kept": len(kept_plans),
        "kept_share": round(len(kept_plans) / len(known), 4) if known else None,
        "closed_kept": len(kept), "clusters_kept": len(blocks),
        "gross_mean_r": round(statistics.fmean([c["gross_r"] for c in kept]), 4) if kept else None,
        "net_mean_r": round(statistics.fmean(nets), 4) if nets else None,
        "net_sum_r": round(sum(nets), 4) if nets else None,
        "win_rate": round(sum(1 for n in nets if n > 0) / len(nets), 4) if nets else None,
        "net_mean_ci": [None if v is None else round(v, 4) for v in interval],
        "status": DESCRIBED if len(blocks) >= MIN_CLUSTERS else INSUFFICIENT,
    }


def study_rule(journal: Mapping[str, Any]) -> dict[str, Any]:
    """All variants for one journal view (one plan rule)."""
    plans = [dict(e) for e in journal.get("entries") or []]
    cases = _case_rows(journal)
    distribution = {name: _quantiles([c for c in (stop_out_cost_r(p, model) for p in plans) if c is not None])
                    for name, model in COST_CASES.items()}
    distances = [abs(float(p["entry"]) - float(p["stop"])) / float(p["entry"]) * 100 for p in plans if stop_out_cost_r(p) is not None]
    return {"plans": len(plans), "closed_cases": len(cases), "clusters": len({c["cluster"] for c in cases}),
            "cost_r": distribution, "stop_distance_pct": _quantiles(distances),
            "variants": [_variant(plans, cases, limit, name) for name in COST_CASES for limit in THRESHOLDS],
            "cases": [{**c, "estimate": {k: None if v is None else round(v, 4) for k, v in c["estimate"].items()},
                       "net": {k: round(v, 4) for k, v in c["net"].items()}, "gross_r": round(c["gross_r"], 4)} for c in cases]}


def run(journals: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The study over several journal views, keyed by rule name."""
    limits = {f"{limit:.2f}": {name: {d: round(min_stop_distance(limit, d, model) * 100, 4) for d in ("LONG", "SHORT")}
                               for name, model in COST_CASES.items()} for limit in THRESHOLDS if limit is not None}
    rules = {name: study_rule(journal) for name, journal in journals.items()}
    total_clusters = sum(r["clusters"] for r in rules.values())
    return {
        "study": STUDY_ID, "version": STUDY_VERSION, "display_limit_r": COST_LIMIT_R,
        "thresholds": list(THRESHOLDS), "cost_cases": {k: {"fee": m.fee, "slippage": m.slippage, "stop_slippage": m.stop_slippage} for k, m in COST_CASES.items()},
        "min_stop_distance_pct": limits, "min_clusters": MIN_CLUSTERS, "bootstrap_seed": BOOTSTRAP_SEED,
        "rules": rules,
        "verdict": DESCRIBED if total_clusters >= MIN_CLUSTERS else INSUFFICIENT,
        "informational_only": True,
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "–"
    if isinstance(value, float) and math.isfinite(value):
        return f"{value:.{digits}f}"
    return str(value)


def markdown(result: Mapping[str, Any]) -> str:
    """A short German report table of a study result."""
    lines = [f"# Studie {result['study']}: Kosten-Schwelle ({result['version']})", "",
             f"Gesamturteil: **{result['verdict']}** (mindestens {result['min_clusters']} Cluster nötig). Nur beschreibend, kein Filter.", "",
             "## Mindest-Stopabstand je Grenze (Prozent vom Einstieg)", "",
             "| Grenze | Basis LONG | Basis SHORT | Stress LONG | Stress SHORT |", "|---|---|---|---|---|"]
    for limit, cases in result["min_stop_distance_pct"].items():
        lines.append(f"| {limit} R | {_fmt(cases['base']['LONG'])} | {_fmt(cases['base']['SHORT'])} | {_fmt(cases['stress']['LONG'])} | {_fmt(cases['stress']['SHORT'])} |")
    for name, rule in result["rules"].items():
        dist = rule["cost_r"]["base"]
        lines += ["", f"## Regel {name}", "",
                  f"Pläne {rule['plans']}, geschlossene Fälle {rule['closed_cases']}, Cluster {rule['clusters']}. "
                  f"Kosten in R (Basis): Median {_fmt(dist['median'], 3)}, Spanne {_fmt(dist['min'], 3)} bis {_fmt(dist['max'], 3)}. "
                  f"Stopabstand Median {_fmt(rule['stop_distance_pct']['median'], 3)} %.", "",
                  "| Grenze | Kosten | Pläne behalten | Anteil | Fälle | Cluster | Netto Ø R | Netto Σ R | Trefferquote | Status |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for v in rule["variants"]:
            limit = "ohne" if v["limit_r"] is None else f"{v['limit_r']:.2f}"
            lines.append(f"| {limit} | {v['cost_case']} | {v['plans_kept']}/{v['plans_known']} | {_fmt(v['kept_share'])} | {v['closed_kept']} | "
                         f"{v['clusters_kept']} | {_fmt(v['net_mean_r'], 3)} | {_fmt(v['net_sum_r'], 3)} | {_fmt(v['win_rate'])} | {v['status']} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Study K1: cost threshold variants over plan-journal views (read only).")
    parser.add_argument("--journal", action="append", required=True, metavar="RULE=PATH", help="journal view JSON, e.g. tim=data/journal/tim_plan_journal.json")
    parser.add_argument("--out", type=Path, help="write the JSON result here")
    parser.add_argument("--markdown", type=Path, help="write the German report table here")
    args = parser.parse_args(argv)
    journals = {}
    for item in args.journal:
        name, _, path = item.partition("=")
        journals[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    result = run(journals)
    text = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(markdown(result), encoding="utf-8")
    if not args.out and not args.markdown:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
