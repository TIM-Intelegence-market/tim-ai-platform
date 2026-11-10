"""Joint view over several OFX searches (PS5 and PS4 search the same space with different seeds).

Each machine's sieve counts only its own configurations. For the joint search the multiple-testing count is the sum
over all machines, so every candidate is checked again against the stricter joint threshold. The threshold only
grows with the count, so a filter that failed locally can never pass jointly; re-checking the local candidates is
enough.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from src.research_lab.ofx.sieve import DEFAULT_RULES, Rules, t_threshold


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def combine(outs: Sequence[Path], rules: Rules = DEFAULT_RULES) -> dict:
    """Sum the configurations of all searches and re-check their candidates against the joint threshold."""
    runs, seeds = [], set()
    for out in outs:
        state = json.loads((Path(out) / "state.json").read_text())
        if state["seed"] in seeds:
            raise SystemExit(f"{out}: seed {state['seed']} used twice; the searches would repeat configurations")
        seeds.add(state["seed"])
        runs.append({"ordner": str(out), "seed": state["seed"], "configs_tried": state["configs_tried"],
                     "kandidaten_lokal": state["kandidaten"]})
    total = sum(r["configs_tried"] for r in runs)
    threshold = t_threshold(total, rules.alpha)
    candidates = []
    for out in outs:
        for row in _rows(Path(out) / "kandidaten.jsonl"):
            if row.get("status") != "KANDIDAT":
                continue
            joint = row["metriken"]["t"] >= threshold
            candidates.append({**row, "ordner": str(out), "gemeinsam_ok": joint,
                               "status_gemeinsam": "KANDIDAT" if joint else "MEHRFACHTEST_GEMEINSAM"})
    return {"configs_gesamt": total, "t_schwelle": round(threshold, 3), "laeufe": runs,
            "kandidaten": sum(c["gemeinsam_ok"] for c in candidates), "liste": candidates}
