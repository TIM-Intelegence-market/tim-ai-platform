"""Versioned learning proposals from the closed cases of the plan journal.

Closed journal entries are read, never changed (docs/ACCEPTANCE.md section 4).
The output is a proposal file: descriptive statistics per setup family,
direction and grade, with cluster-aware counts and a cluster-block bootstrap
of the mean net R. Entries that were created within one chart window
(80 x 15m) of an earlier entry of the same family and direction share its
cluster: they were derived from almost the same candles and are not
independent cases. A family becomes a "candidate for registration" only when
it has enough clusters and the bootstrap interval of the net mean lies above
zero. Even then nothing changes: the champion (grade rules, evidence mapping,
cost model) stays as it is, and the only sanctioned next step is a registered
hypothesis in the research lab register with its own train/validation/holdout.
No threshold is read from the journal, so nothing is tuned on it.
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROPOSAL_VERSION = "journal-review/1"
CLUSTER_WINDOW = timedelta(minutes=15 * 80)  # one Setup-Pfad chart window
MIN_CLUSTERS = 30          # below this a family is "insufficient", whatever its numbers
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_LEVEL = 0.95
INSUFFICIENT, CANDIDATE, NO_EDGE_FOUND = "INSUFFICIENT_CASES", "CANDIDATE_FOR_REGISTRATION", "NO_POSITIVE_EDGE_FOUND"


def _time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def closed_cases(journal: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Closed entries with a net result, oldest first. Nothing is modified."""
    cases = [dict(e) for e in journal.get("entries") or [] if e.get("status") == "CLOSED" and e.get("net_r") is not None]
    cases.sort(key=lambda e: (_time(e["created_at"]), e["id"]))
    return cases


def family_of(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(entry.get("scenario_type")), str(entry.get("direction")), str(entry.get("setup_grade"))


def assign_clusters(cases: Sequence[Mapping[str, Any]], window: timedelta = CLUSTER_WINDOW) -> dict[str, str]:
    """entry id -> cluster id. A case joins the open cluster of its family and
    direction when it was created less than `window` after that cluster began."""
    clusters: dict[str, str] = {}
    open_cluster: dict[tuple[str, str], tuple[str, datetime]] = {}
    for case in sorted(cases, key=lambda e: (_time(e["created_at"]), e["id"])):
        key = (str(case.get("scenario_type")), str(case.get("direction")))
        created = _time(case["created_at"])
        current = open_cluster.get(key)
        if current is None or created - current[1] >= window:
            current = (f"{key[0]}|{key[1]}|{created.isoformat()}", created)
            open_cluster[key] = current
        clusters[case["id"]] = current[0]
    return clusters


def cluster_block_bootstrap(blocks: Sequence[Sequence[float]], *, draws: int = BOOTSTRAP_DRAWS, seed: int, level: float = BOOTSTRAP_LEVEL) -> tuple[float, float]:
    """Interval of the mean, resampling whole clusters (like the month blocks of the research lab)."""
    groups = [list(b) for b in blocks if b]
    if not groups:
        raise ValueError("no blocks")
    rng = random.Random(seed)
    means = sorted(statistics.fmean([r for _ in groups for r in rng.choice(groups)]) for _ in range(draws))
    tail = (1 - level) / 2
    return means[int(tail * (len(means) - 1))], means[int((1 - tail) * (len(means) - 1))]


def family_statistics(cases: Sequence[Mapping[str, Any]], clusters: Mapping[str, str], *, seed: int) -> list[dict[str, Any]]:
    by_family: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for case in cases:
        by_family[family_of(case)].append(case)
    result = []
    for family, mine in sorted(by_family.items()):
        blocks: dict[str, list[float]] = defaultdict(list)
        for case in mine:
            blocks[clusters[case["id"]]].append(float(case["net_r"]))
        net = [float(c["net_r"]) for c in mine]
        gross = [float(c["gross_r"]) for c in mine]
        costs = [float(c.get("fee_r") or 0.0) + float(c.get("slippage_r") or 0.0) for c in mine]
        exits: dict[str, int] = defaultdict(int)
        for case in mine:
            exits[str(case.get("exit_reason"))] += 1
        low, high = cluster_block_bootstrap(list(blocks.values()), seed=seed)
        n_clusters = len(blocks)
        if n_clusters < MIN_CLUSTERS:
            verdict = INSUFFICIENT
        elif low > 0:
            verdict = CANDIDATE
        else:
            verdict = NO_EDGE_FOUND
        result.append({
            "scenario_type": family[0], "direction": family[1], "setup_grade": family[2],
            "cases": len(mine), "clusters": n_clusters, "min_clusters": MIN_CLUSTERS,
            "mean_gross_r": round(statistics.fmean(gross), 4), "mean_net_r": round(statistics.fmean(net), 4),
            "sum_net_r": round(sum(net), 4), "win_rate_net": round(sum(r > 0 for r in net) / len(net), 3),
            "mean_cost_r": round(statistics.fmean(costs), 4),
            "net_mean_ci95_cluster_bootstrap": [round(low, 4), round(high, 4)],
            "exit_reasons": dict(sorted(exits.items())),
            "data_gaps": sum(bool(c.get("data_gap")) for c in mine),
            "verdict": verdict,
        })
    return result


def propose(journal: Mapping[str, Any], *, now: datetime | None = None, seed: int = 20261023) -> dict[str, Any]:
    """A learning proposal. Pure: the journal is not modified; same input, same id."""
    now = now or datetime.now(timezone.utc)
    cases = closed_cases(journal)
    clusters = assign_clusters(cases)
    families = family_statistics(cases, clusters, seed=seed) if cases else []
    champion = {
        "grade_ruleset_version": sorted({str(c.get("grade_ruleset_version")) for c in cases}) or [],
        "evidence_mapping_version": sorted({str((c.get("evidence_ref") or {}).get("mapping_version")) for c in cases}) or [],
        "cost_model_version": sorted({str(c.get("cost_model_version")) for c in cases}) or [],
        "changed_by_this_proposal": False,
    }
    body = {
        "proposal_version": PROPOSAL_VERSION,
        "journal_schema": journal.get("schema"),
        "journal_source": journal.get("source"),
        "journal_log_head": journal.get("log_head"),
        "journal_log_seq": journal.get("log_seq"),
        "cases_closed": len(cases),
        "clusters": len(set(clusters.values())),
        "cluster_window_minutes": int(CLUSTER_WINDOW.total_seconds() // 60),
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "level": BOOTSTRAP_LEVEL, "seed": seed, "blocks": "clusters"},
        "champion": champion,
        "families": families,
        "candidates_for_registration": [f for f in families if f["verdict"] == CANDIDATE],
        "status": "PROPOSED",
        "adoption": "none; a candidate becomes a registered hypothesis in docs/research_lab/REGISTER.jsonl with its own holdout; the journal never tunes thresholds",
        "holdout_untouched": True,
        "limits": [
            "paper journal cases overlap in time; clusters are an approximation of independence, not a proof",
            "results are hypothetical fills of unconfirmed preview plans, all NO_TRADE/RESEARCH_ONLY",
            "no fee tier, funding or partial fills; costs per protocol/1.1",
        ],
    }
    proposal_id = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {**body, "proposal_id": proposal_id, "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


def write_proposal(proposal: Mapping[str, Any], directory: Path) -> Path:
    """Write the proposal as its own file; an existing file for the same id is left untouched."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"journal_review_{proposal['proposal_id']}.json"
    if not path.exists():
        path.write_text(json.dumps(proposal, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path
