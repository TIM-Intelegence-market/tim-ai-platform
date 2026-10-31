"""Turns existing TIM outputs into ideas (F1 adapters).

Each adapter only reads a proposal file; it never changes the journal, the
reflection or any rule. The proposal id becomes ``source_ref`` so a second
import of the same file adds nothing.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.research_lab.workshop.ideas import IdeaQueue


def import_journal_review(queue: IdeaQueue, proposal: Mapping[str, Any]) -> list[str]:
    added = []
    for family in proposal.get("candidates_for_registration") or []:
        name = f"{family['scenario_type']} {family['direction']} {family['setup_grade']}"
        lo, hi = family["net_mean_ci95_cluster_bootstrap"]
        idea_id = queue.add(
            source="journal_review",
            title=f"Setup-Familie {name} aus dem Plan-Journal",
            hypothesis=(f"Die Setup-Familie {name} hat netto einen positiven Erwartungswert je Trade "
                        f"(Journal: {family['clusters']} Cluster, Mittel {family['mean_net_r']} R, Band {lo} bis {hi} R)."),
            data=["archive_spot_klines", "plan_journal"],
            tags=[family["scenario_type"], family["direction"], f"grade-{family['setup_grade']}"],
            template="regel_backtest",
            counterargument="Journal-Fälle überlappen sich und sind wenige; das Band kann Zufall sein.",
            source_ref=f"journal_review:{proposal['proposal_id']}:{name}",
        )
        if idea_id:
            added.append(idea_id)
    return added


def import_reflection(queue: IdeaQueue, report: Mapping[str, Any]) -> list[str]:
    proposal = report.get("proposal")
    if not proposal:
        return []
    idea_id = queue.add(
        source="reflection",
        title=f"Beobachtungsart {proposal['kind']} ({'über' if proposal['direction'] == 'above' else 'unter'} Basisrate)",
        hypothesis=f"Woche {report['week']}: {proposal['text']}",
        data=["live_orderflow", "archive_spot_klines"],
        tags=[proposal["kind"], "reflexion"],
        template="regel_backtest",
        counterargument=proposal.get("question", ""),
        source_ref=f"reflection:{report['report_hash']}",
    )
    return [idea_id] if idea_id else []
