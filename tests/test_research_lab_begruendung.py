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
