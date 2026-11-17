from src.dashboard import absorption_shadow as a


def lage(*levels):
    return {"levels": [{"name": n, "distance_pct": d, "absorption": ab} for n, d, ab in levels]}


def test_short_blocked_by_absorption_below():
    r = a.check("SHORT", lage(("1D VAL", -0.10, True)))
    assert r["blocked"] and r["level"]["name"] == "1D VAL"


def test_long_blocked_by_absorption_above_only():
    assert a.check("LONG", lage(("1D VAH", 0.20, True)))["blocked"]
    assert not a.check("LONG", lage(("1D VAH", -0.20, True)))["blocked"]


def test_no_absorption_or_too_far_passes():
    assert not a.check("SHORT", lage(("x", -0.1, False)))["blocked"]
    assert not a.check("SHORT", lage(("x", -0.5, True)))["blocked"]


def test_no_lage_is_unreadable_not_blocked():
    r = a.check("LONG", None)
    assert not r["readable"] and not r["blocked"]


def test_bad_distance_ignored():
    assert not a.check("LONG", lage(("x", True, True), ("y", None, True)))["blocked"]


def _plan(direction, net, ab):
    return {"direction": direction, "lage_at_plan": lage(("L", 0.1 if direction == "LONG" else -0.1, ab)),
            "journal": {"status": "CLOSED", "net_r": net}}


def test_evaluate_waits_below_min():
    out = a.evaluate({"plans": {str(i): _plan("LONG", -1.0, True) for i in range(5)}})
    assert out["verdict"] == "NOCH_NICHT_BEURTEILBAR" and out["groups"]["blocked"]["n"] == 5


def test_evaluate_passes_when_blocked_lose():
    plans = {str(i): _plan("SHORT", -0.5 - 0.01 * (i % 3), True) for i in range(40)}
    plans["p"] = _plan("SHORT", 0.4, False)
    out = a.evaluate({"plans": plans})
    assert out["verdict"] == "BESTANDEN" and out["groups"]["passed"]["n"] == 1


def test_evaluate_fails_when_blocked_win():
    out = a.evaluate({"plans": {str(i): _plan("LONG", 0.3, True) for i in range(40)}})
    assert out["verdict"] == "NICHT_BESTANDEN"


def test_open_plans_not_counted():
    p = _plan("LONG", None, True)
    p["journal"]["status"] = "FILLED"
    assert a.evaluate({"plans": {"1": p}})["groups"]["blocked"]["n"] == 0
