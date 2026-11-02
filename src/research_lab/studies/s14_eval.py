"""Study S14, section 5: key figures and verdicts (own family proposed, no holdout).

The criteria are those of S13 (horizon "short", pooled over the pairs ETH/BTC, SOL/BTC, SOL/ETH), so
the key figures, section verdicts, year rule and walk-forward come from ``s13_eval``. In addition
S14 has a neighbour rule (preregistration 4.2): the window lengths 168 and 720 are neighbours, so a
variant needs E[R] > 0 in training for the other window as well. The filter is a category.
"""
from __future__ import annotations

from collections.abc import Mapping

from src.research_lab.studies.s13_eval import (  # noqa: F401  (re-exported for the script)
    MIN_N,
    MIN_N_EFF,
    P_MAX,
    PF_VALIDATION,
    day_of,
    needs_pvalue,
    pooled,
    section_figures,
    section_verdict,
    walk_forward_rule,
    year_rule,
)

NEIGHBOURS = {"S14-W168": ("S14-W720",), "S14-W720": ("S14-W168",)}


def neighbour_rule(variant_id: str, train_expectancy: Mapping[str, float]) -> dict:
    """E[R] > 0 in training for every neighbour; a neighbour without trades counts as failed."""
    values = {n: train_expectancy.get(n, float("-inf")) for n in NEIGHBOURS[variant_id]}
    return {"pass": all(v > 0 for v in values.values()), "neighbours": values}


def final_verdict(train: Mapping, validation: Mapping, years_ok: bool, walk: Mapping, neighbours: Mapping) -> str:
    if not train["pass"]:
        return "NICHT BESTANDEN (Training)"
    failed = list(validation["reasons"])
    if not years_ok:
        failed.append("Jahresstabilität")
    if not walk["pass"]:
        failed.append("Walk-Forward")
    if not neighbours["pass"]:
        failed.append("Nachbarschaft")
    return "KANDIDAT (prospektiver Test nötig)" if not failed else "NICHT BESTANDEN (Validierung)"
