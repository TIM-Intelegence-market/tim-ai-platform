from src.research_lab import begruendung


def test_plan_gets_statements_that_apply():
    plan = {"setup_grade": "C", "score": 0.23, "vol_4h": {"weight": 1.0}}
    ids = [b["id"] for b in begruendung.fuer_plan(plan)]
    assert {"C01", "C03", "C46", "C47", "C21", "C22"} <= set(ids)
    c22 = next(b for b in begruendung.fuer_plan(plan) if b["id"] == "C22")
    assert c22["status"] == "widerlegt"  # the plan relied on a refuted statement


def test_plan_without_optional_parts_skips_them():
    ids = [b["id"] for b in begruendung.fuer_plan({})]
    assert "C46" not in ids and "C47" not in ids and "C22" not in ids


def test_failure_never_breaks_journal(monkeypatch):
    monkeypatch.setattr(begruendung, "_register", lambda: (_ for _ in ()).throw(OSError("weg")))
    assert begruendung.fuer_plan({"score": 1}) == []


def test_begruendung_unterscheidet_plaene():
    basis = {"direction": "LONG", "market_state": "BALANCE", "score": 0.2363, "grade": {"grade": "C"}}
    gleich = {b["id"] for b in begruendung.fuer_plan(basis)}
    assert not {"C38", "C09", "C11", "C32"} & gleich
    plan = {**basis, "market_state": "TREND_DOWN",
            "score_schatten": {"score": 0.3, "parts": {"basis": 0.3, "absorption": 0.06, "oi": 0.03, "positionierung": -0.03,
                                                       "aggressor": 0.08}}}
    extra = {b["id"]: b for b in begruendung.fuer_plan(plan) if b.get("rolle")}
    assert set(extra) == {"C38", "C09", "C11", "C32"}
    assert extra["C38"]["rolle"] == "gegen_trend" and extra["C09"] == {**extra["C09"], "rolle": "schatten", "richtung": "dafuer"}
    assert extra["C32"]["richtung"] == "dagegen" and extra["C32"]["status"] == "widerlegt"
    assert begruendung.fuer_plan({**basis, "direction": "SHORT", "market_state": "TREND_DOWN"}) == begruendung.fuer_plan(basis)
    assert {b["id"] for b in begruendung.fuer_plan({**basis, "score_schatten": {"parts": {"oi": True}}})} == gleich
    assert {b["id"] for b in begruendung.fuer_plan({**basis, "score_schatten": "kaputt"})} == gleich
