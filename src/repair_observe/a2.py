"""A2 repair enablement gate."""

from src.repair_observe.enablement import a1_go_no_go

DEFAULT_A2_THRESHOLDS = {
    "min_verified_runs": 20,
    "max_failed_runs": 0,
    "max_rollbacks": 0,
}


def _result(decision, recipes=None, reasons=None):
    return {
        "decision": decision,
        "recipes": recipes or {},
        "reasons": sorted(set(reasons or [])),
        "auto_repair_enabled": False,
    }


def a2_go_no_go(metrics, recipe_stats, thresholds=None):
    """Evaluate whether any A2 recipe is eligible for observation."""
    try:
        a1 = a1_go_no_go(metrics)
    except Exception:
        return _result("NO_GO", reasons=["A1 prerequisites not met"])

    reasons = []
    if not isinstance(a1, dict) or a1.get("decision") != "GO":
        reasons.append("A1 prerequisites not met")
        if isinstance(a1, dict) and isinstance(a1.get("reasons"), list):
            reasons.extend(str(reason) for reason in a1["reasons"])

    limits = dict(DEFAULT_A2_THRESHOLDS)
    if thresholds is not None:
        if not isinstance(thresholds, dict):
            reasons.append("Malformed thresholds")
        else:
            unknown = set(thresholds) - set(limits)
            if unknown:
                reasons.append("Unknown threshold")
            else:
                limits.update(thresholds)

    for key in limits:
        if isinstance(limits[key], bool) or not isinstance(limits[key], int) or limits[key] < 0:
            reasons.append("Malformed thresholds")

    recipes = {}
    valid_stats = isinstance(recipe_stats, list)
    seen = set()
    if not valid_stats:
        reasons.append("Malformed recipe_stats")
    else:
        for item in recipe_stats:
            if not isinstance(item, dict):
                reasons.append("Malformed recipe_stats")
                continue
            remediation_id = item.get("remediation_id")
            if not isinstance(remediation_id, str) or not remediation_id:
                reasons.append("Malformed recipe_stats")
                continue
            if remediation_id in seen:
                reasons.append("Duplicate remediation_id")
                continue
            seen.add(remediation_id)

            recipe_reasons = []
            if item.get("autonomy_level") != "A2":
                recipe_reasons.append("autonomy_level is not A2")
            verified_runs = item.get("verified_runs")
            failed_runs = item.get("failed_runs")
            rollbacks = item.get("rollbacks")
            if isinstance(verified_runs, bool) or not isinstance(verified_runs, int):
                recipe_reasons.append("verified_runs is malformed")
            elif verified_runs < limits["min_verified_runs"]:
                recipe_reasons.append("verified_runs below minimum")
            if isinstance(failed_runs, bool) or not isinstance(failed_runs, int):
                recipe_reasons.append("failed_runs is malformed")
            elif failed_runs > limits["max_failed_runs"]:
                recipe_reasons.append("failed_runs exceeds maximum")
            if isinstance(rollbacks, bool) or not isinstance(rollbacks, int) or rollbacks < 0:
                recipe_reasons.append("rollbacks is malformed")
            elif rollbacks > limits["max_rollbacks"]:
                recipe_reasons.append("rollbacks exceeds maximum")
            decision = "GO" if not recipe_reasons else "NO_GO"
            recipes[remediation_id] = {
                "decision": decision,
                "reasons": sorted(recipe_reasons),
            }

    if any(recipe["decision"] == "GO" for recipe in recipes.values()) and not reasons:
        decision = "GO"
    else:
        decision = "NO_GO"
    return _result(decision, recipes, reasons)
