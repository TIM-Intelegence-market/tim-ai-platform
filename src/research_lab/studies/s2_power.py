"""Study S2, section 3: the power simulation that gates release 1.0.

Planning model, exactly as pre-registered: per week and group an independent
beta-binomial count with mean p (controls) or p + 0.03 (cases) and
concentration 1/ICC - 1 (binomial when ICC = 0). Weekly case and control
numbers come from the outcome-blind count run, never from a guess. The
statistic and the test are the ones of the study:

    delta = sum_w nK_w (pK_w - pB_w) / sum_w nK_w

moving-block bootstrap over four consecutive weeks of the section's calendar
positions (excluded weeks stay as empty positions), overhang truncated,
one-sided null-centred p = (1 + #(delta* - delta >= delta)) / (B + 1), compared
with the conservative threshold 0.05 / 18 per section. Degenerate draws without
any case count conservatively in the numerator.

Needs numpy; a run with the registered 10 000 replications and B = 19 999 is a
matter of hours, see ``docs/research_lab/studien/S2_...md``. Deterministic for a
given seed: one ``numpy.random.default_rng(seed)`` stream per scenario, in a
fixed scenario order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

REPLICATIONS = 10_000
SEED = 20261023
BOOTSTRAP_B = 19_999
BOOTSTRAP_SEED = 20261022
BLOCK_WEEKS = 4
BASE_RATES = (0.35, 0.50, 0.65)
TRUE_DELTA = 0.03
ICCS = (0.0, 0.05, 0.10)
FAMILY = 18
ALPHA_SECTION = 0.05 / FAMILY
EFFECT_HURDLE = 0.03
REQUIRED_POWER = 0.90


def _np():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - exercised only without numpy
        raise RuntimeError("the S2 power simulation needs numpy (pip install numpy)") from exc
    return numpy


@dataclass(frozen=True, slots=True)
class Scenario:
    base_rate: float
    icc: float
    true_delta: float = TRUE_DELTA

    @property
    def id(self) -> str:
        return f"p{self.base_rate:.2f}_icc{self.icc:.2f}_d{self.true_delta:.2f}"


def scenarios(base_rates: Sequence[float] = BASE_RATES, iccs: Sequence[float] = ICCS, true_delta: float = TRUE_DELTA) -> list[Scenario]:
    return [Scenario(p, icc, true_delta) for p in base_rates for icc in iccs]


def standardized_delta(cases: Sequence[int], hits_cases: Sequence[int], controls: Sequence[int], hits_controls: Sequence[int]) -> float | None:
    """The study's statistic over weekly counts; None when no week carries a case."""
    numerator = 0.0
    weight = 0
    for n_k, k_k, n_b, k_b in zip(cases, hits_cases, controls, hits_controls, strict=True):
        if n_k <= 0 or n_b <= 0:
            continue
        numerator += k_k - n_k * (k_b / n_b)
        weight += n_k
    return numerator / weight if weight else None


def block_plan(weeks: int, block: int = BLOCK_WEEKS) -> tuple[int, int]:
    """(number of blocks drawn, length of the truncated last block) to fill ``weeks`` positions."""
    if weeks < block:
        raise ValueError(f"a section needs at least {block} calendar weeks")
    blocks = -(-weeks // block)
    tail = weeks - block * (blocks - 1)
    return blocks, tail


def bootstrap_p_values(a, n, delta, *, rng, b: int = BOOTSTRAP_B, block: int = BLOCK_WEEKS):
    """Null-centred one-sided bootstrap p for each replication.

    ``a`` and ``n`` are arrays of shape (replications, weeks): per week the
    numerator term nK (pK - pB) and the weight nK, zero at empty positions.
    ``delta`` has shape (replications,). Returns p of shape (replications,).
    """
    np = _np()
    a = np.asarray(a, dtype=float)
    n = np.asarray(n, dtype=float)
    reps, weeks = a.shape
    blocks, tail = block_plan(weeks, block)
    starts = weeks - block + 1
    # Sums of every full block and of every truncated block, per replication.
    cum_a = np.concatenate([np.zeros((reps, 1)), np.cumsum(a, axis=1)], axis=1)
    cum_n = np.concatenate([np.zeros((reps, 1)), np.cumsum(n, axis=1)], axis=1)
    full_a = cum_a[:, block:] - cum_a[:, :-block]
    full_n = cum_n[:, block:] - cum_n[:, :-block]
    tail_starts = weeks - tail + 1
    tail_a = cum_a[:, tail:] - cum_a[:, :-tail]
    tail_n = cum_n[:, tail:] - cum_n[:, :-tail]
    rows = np.arange(reps)[:, None, None]
    idx_full = rng.integers(0, starts, size=(reps, b, blocks - 1), dtype=np.int32)
    idx_tail = rng.integers(0, tail_starts, size=(reps, b, 1), dtype=np.int32)
    num = full_a[rows, idx_full].sum(axis=2) + tail_a[rows, idx_tail][:, :, 0]
    den = full_n[rows, idx_full].sum(axis=2) + tail_n[rows, idx_tail][:, :, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        star = num / den
    delta = np.asarray(delta, dtype=float)[:, None]
    extreme = (star - delta >= delta) | (den <= 0)  # degenerate draws count conservatively
    return (1 + extreme.sum(axis=1)) / (b + 1)


def draw_weekly_hits(n, p, icc, rng):
    """Beta-binomial (binomial when icc == 0) counts for an array of weekly denominators."""
    np = _np()
    n = np.asarray(n)
    if icc <= 0:
        return rng.binomial(n, p)
    concentration = 1.0 / icc - 1.0
    probs = rng.beta(p * concentration, (1.0 - p) * concentration, size=n.shape)
    return rng.binomial(n, probs)


@dataclass(frozen=True, slots=True)
class PowerResult:
    scenario: Scenario
    replications: int
    rejections: int
    rejections_with_hurdle: int
    evaluable: int

    @property
    def power(self) -> float:
        return self.rejections / self.replications

    @property
    def joint_rate(self) -> float:
        return self.rejections_with_hurdle / self.replications

    def to_dict(self) -> dict:
        return {"scenario": self.scenario.id, "base_rate": self.scenario.base_rate, "icc": self.scenario.icc,
                "true_delta": self.scenario.true_delta, "replications": self.replications, "rejections": self.rejections,
                "power": round(self.power, 4), "rejections_with_effect_hurdle": self.rejections_with_hurdle,
                "joint_rate": round(self.joint_rate, 4), "evaluable_replications": self.evaluable,
                "meets_requirement": self.power >= REQUIRED_POWER}


def simulate_power(weekly: Sequence[tuple[int, int]], scenario: Scenario, *, replications: int = REPLICATIONS, seed: int = SEED,
                   b: int = BOOTSTRAP_B, alpha: float = ALPHA_SECTION, chunk: int = 8) -> PowerResult:
    """Power of the section test for one kind and section, given (cases, controls) per calendar week."""
    np = _np()
    n_k = np.array([c for c, _ in weekly], dtype=np.int64)
    n_b = np.array([c for _, c in weekly], dtype=np.int64)
    if n_k.sum() == 0:
        return PowerResult(scenario, replications, 0, 0, 0)
    rng = np.random.default_rng([seed, int(round(scenario.base_rate * 100)), int(round(scenario.icc * 100))])
    rejections = joint = evaluable = 0
    done = 0
    while done < replications:
        size = min(chunk, replications - done)
        k_k = draw_weekly_hits(np.broadcast_to(n_k, (size, n_k.size)), scenario.base_rate + scenario.true_delta, scenario.icc, rng)
        k_b = draw_weekly_hits(np.broadcast_to(n_b, (size, n_b.size)), scenario.base_rate, scenario.icc, rng)
        usable = (n_k > 0) & (n_b > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            term = np.where(usable, k_k - n_k * (k_b / np.where(n_b > 0, n_b, 1)), 0.0)
        weight = np.where(usable, n_k, 0).astype(float)
        delta = term.sum(axis=1) / weight.sum()
        weight = np.broadcast_to(weight, term.shape)
        p = bootstrap_p_values(term, weight, delta, rng=rng, b=b)
        reject = p <= alpha
        rejections += int(reject.sum())
        joint += int((reject & (delta >= EFFECT_HURDLE)).sum())
        evaluable += size
        done += size
    return PowerResult(scenario, replications, rejections, joint, evaluable)


def power_task(section: str, kind: str, index: int, weekly: Sequence[tuple[int, int]], scenario: Scenario,
               replications: int, seed: int, b: int) -> tuple[str, str, int, PowerResult]:
    """Worker entry for one (section, kind, scenario) run. Each run seeds its own generator from
    (seed, scenario), so running the 108 registered runs in several processes gives byte-identical
    results to the sequential loop; only the order of completion differs."""
    return section, kind, index, simulate_power(weekly, scenario, replications=replications, seed=seed, b=b)


def build_power_report(results: dict[str, dict[str, list[PowerResult]]], *, count_report: dict, commit: str, replications: int, b: int, seed: int, created: str) -> dict:
    """results[section][kind] -> PowerResult per scenario."""
    sections = {}
    for section, kinds in results.items():
        rows = {}
        for kind, items in kinds.items():
            rows[kind] = {"scenarios": [item.to_dict() for item in items],
                          "min_power": round(min(item.power for item in items), 4) if items else None,
                          "all_scenarios_meet_90": bool(items) and all(item.power >= REQUIRED_POWER for item in items)}
        sections[section] = rows
    directional = [kind for kind in results.get("train", {}) if count_report["sections"]["train"]["kinds"][kind]["directional"]]
    passing = [kind for kind in directional if all(sections[section][kind]["all_scenarios_meet_90"] for section in results)]
    return {"study": "S2", "step": "power_gate", "commit": commit, "count_commit": count_report["commit"],
            "count_dataset_hash": count_report["dataset_hash"], "replications": replications, "bootstrap_b": b, "seed": seed,
            "alpha_section": ALPHA_SECTION, "required_power": REQUIRED_POWER, "true_delta": TRUE_DELTA,
            "base_rates": list(BASE_RATES), "iccs": list(ICCS), "created": created, "sections": sections,
            "directional_kinds_with_power_in_both_sections": passing,
            "gate": "power shown for every scenario and section" if passing else "no directional kind reaches 90 % power in every scenario",
            "outcome_blind": True}


def render_power_markdown(report: dict) -> str:
    lines = [f"# S2 Power-Simulation, Stand {report['created']}", "",
             f"{report['replications']} Replikationen, B = {report['bootstrap_b']}, Seed {report['seed']}, Schwelle {report['alpha_section']:.5f} je Abschnitt,",
             f"Zählstand `{report['count_dataset_hash'][:16]}…` (Commit `{report['count_commit'][:12]}`), Rechenstand `{report['commit'][:12]}`.", "",
             "Planungsmodell Beta-Binomial je Woche und Gruppe (Studie Abschnitt 3); keine Marktergebnisse gelesen.", ""]
    for section, kinds in report["sections"].items():
        lines += [f"## Abschnitt {section}", "", "| Art | kleinste Power über 9 Szenarien | alle ≥ 90 % |", "|---|---|---|"]
        for kind, row in kinds.items():
            power = "–" if row["min_power"] is None else f"{row['min_power']:.3f}"
            lines.append(f"| {kind} | {power} | {'ja' if row['all_scenarios_meet_90'] else 'nein'} |")
        lines.append("")
    lines += [f"**Gate:** {report['gate']}.", "",
              "Arten mit Power in beiden Abschnitten: " + (", ".join(report["directional_kinds_with_power_in_both_sections"]) or "keine"), ""]
    return "\n".join(lines)
