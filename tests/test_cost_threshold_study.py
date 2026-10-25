"""Study K1: cost threshold variants over plan-journal views (descriptive, read only)."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard.plan_cost_check import cost_check
from src.research_lab.protocol import BASE_COSTS, STRESS_COSTS
from src.research_lab.studies import cost_threshold as k1

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _case(i: int, distance: float, net: float, direction: str = "LONG", status: str = "CLOSED", hours: int = 24) -> dict:
    entry = 80000.0
    stop = entry * (1 - distance) if direction == "LONG" else entry * (1 + distance)
    fee, slip = cost_check({"direction": direction, "entry": entry, "stop": stop})["fee_r_estimate"], cost_check({"direction": direction, "entry": entry, "stop": stop})["slippage_r_estimate"]
    return {"id": f"e{i}", "created_at": (T0 + timedelta(hours=hours * i)).isoformat().replace("+00:00", "Z"), "scenario_type": "S", "direction": direction,
            "entry": entry, "stop": stop, "status": status, "exit_reason": "STOP", "gross_r": round(net + fee + slip, 4),
            "fee_r": fee, "slippage_r": slip, "net_r": net if status == "CLOSED" else None}


def _variant(rule: dict, limit, case: str = "base") -> dict:
    return next(v for v in rule["variants"] if v["limit_r"] == limit and v["cost_case"] == case)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("limit", [0.10, 0.25, 0.50])
def test_min_stop_distance_gives_exactly_the_limit(direction, limit) -> None:
    for model in (BASE_COSTS, STRESS_COSTS):
        d = k1.min_stop_distance(limit, direction, model)
        stop = 100.0 * (1 - d) if direction == "LONG" else 100.0 * (1 + d)
        assert k1.stop_out_cost_r({"direction": direction, "entry": 100.0, "stop": stop}, model) == pytest.approx(limit, abs=1e-12)


def test_limit_of_display_needs_about_0_72_percent() -> None:
    assert k1.min_stop_distance(0.25, "LONG") == pytest.approx(0.0072, abs=0.0001)
    assert k1.min_stop_distance(0.25, "LONG", STRESS_COSTS) == pytest.approx(0.0143, abs=0.0001)


def test_estimate_matches_the_page_and_stress_doubles_it() -> None:
    plan = {"direction": "SHORT", "entry": 80000.0, "stop": 80500.0}
    base = k1.stop_out_cost_r(plan)
    assert base == pytest.approx(cost_check(plan)["cost_r"], abs=0.00015)
    assert k1.stop_out_cost_r(plan, STRESS_COSTS) == pytest.approx(2 * base, rel=1e-12)


def test_unknown_plans_are_never_kept() -> None:
    journal = {"entries": [{"id": "x", "direction": "LONG", "entry": 100.0, "stop": None, "status": "OPEN", "created_at": T0.isoformat()}]}
    rule = k1.study_rule(journal)
    assert _variant(rule, None)["plans_kept"] == 0 and _variant(rule, None)["plans_known"] == 0


def test_variants_are_monotone_and_no_limit_keeps_everything() -> None:
    entries = [_case(i, d, net) for i, (d, net) in enumerate([(0.0015, -2.2), (0.004, -1.4), (0.008, 1.0), (0.012, -1.2), (0.02, 2.0)])]
    rule = k1.study_rule({"entries": entries})
    for case in ("base", "stress"):
        kept = [_variant(rule, limit, case)["plans_kept"] for limit in k1.THRESHOLDS]
        assert kept == sorted(kept) and kept[-1] == len(entries)
    assert _variant(rule, 0.25)["closed_kept"] == 3  # 0.8 %, 1.2 %, 2 %


def test_stress_net_is_gross_minus_doubled_booked_costs() -> None:
    entry = _case(0, 0.01, 1.0)
    case = k1.study_rule({"entries": [entry]})["cases"][0]
    booked = entry["fee_r"] + entry["slippage_r"]
    assert case["net"]["base"] == 1.0 and case["net"]["stress"] == pytest.approx(entry["gross_r"] - 2 * booked, abs=1e-4)


def test_few_clusters_are_insufficient_and_thirty_are_described() -> None:
    few = k1.run({"tim": {"entries": [_case(i, 0.01, 0.5) for i in range(5)]}})
    assert few["verdict"] == k1.INSUFFICIENT and all(v["status"] == k1.INSUFFICIENT for v in few["rules"]["tim"]["variants"])
    many = k1.run({"tim": {"entries": [_case(i, 0.01, 0.5 if i % 2 else -0.5) for i in range(30)]}})
    assert many["verdict"] == k1.DESCRIBED and _variant(many["rules"]["tim"], None)["status"] == k1.DESCRIBED
    assert None not in _variant(many["rules"]["tim"], None)["net_mean_ci"]


def test_plans_created_close_together_share_a_cluster() -> None:
    rule = k1.study_rule({"entries": [_case(i, 0.01, 0.5, hours=1) for i in range(6)]})
    assert rule["closed_cases"] == 6 and rule["clusters"] == 1


def test_study_is_deterministic_and_changes_no_journal() -> None:
    journal = {"entries": [_case(i, 0.003 + 0.002 * i, (-1) ** i * 0.8) for i in range(8)]}
    frozen = copy.deepcopy(journal)
    first, second = k1.run({"tim": journal}), k1.run({"tim": journal})
    assert first == second and journal == frozen and first["informational_only"] is True


def test_cli_writes_json_and_markdown(tmp_path) -> None:
    path = tmp_path / "tim.json"
    path.write_text(json.dumps({"entries": [_case(i, 0.01, 0.5) for i in range(3)]}), encoding="utf-8")
    out, md = tmp_path / "k1.json", tmp_path / "k1.md"
    assert k1.main(["--journal", f"tim={path}", "--out", str(out), "--markdown", str(md)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["study"] == "K1" and set(result["rules"]) == {"tim"}
    text = md.read_text(encoding="utf-8")
    assert "Mindest-Stopabstand" in text and "INSUFFICIENT_CASES" in text and "| 0.25 | base |" in text
