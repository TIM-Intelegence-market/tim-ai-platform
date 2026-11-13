from src.research_lab import gedaechtnis, gedaechtnis_fehler as gf


def A(i, status, nutzung):
    return {"id": i, "aussage": f"Aussage {i}", "status": status, "nutzung": nutzung}


def plan(net, ids):
    return {"net_r": net, "begruendung": [{"id": i} for i in ids]}


def test_reihenfolge_und_maximum():
    aussagen = [A("A", "ungeprueft", "entscheidet"), A("B", "widerlegt", "papier"), A("C", "belegt", "entscheidet"),
                A("D", "hinweis", "entscheidet"), A("E", "belegt", "anzeige")]
    plaene = [plan(-0.5, ["C"]) for _ in range(10)]
    r = gf.finde(aussagen, plaene)
    assert [p["art"] for p in r["punkte"]] == ["widerspruch", "journal", "ungeprueft"]
    assert [p["id"] for p in r["punkte"]][:2] == ["B", "C"]
    assert r["gesamt"] == 4 and len(r["punkte"]) == 3


def test_zu_wenige_plaene_kein_journalhinweis():
    r = gf.finde([A("C", "belegt", "entscheidet")], [plan(-1, ["C"]) for _ in range(9)])
    assert r["punkte"] == []


def test_ohne_begruendung_ist_unbekannt_nie_beleg():
    r = gf.finde([A("C", "belegt", "entscheidet")], [{"net_r": -1.0}, {"net_r": 2.0, "begruendung": []}])
    assert r["plaene_ohne_begruendung"] == 2 and r["punkte"] == []


def test_offene_plaene_zaehlen_nicht():
    r = gf.finde([], [{"net_r": None}])
    assert r["plaene"] == 0 and r["plaene_ohne_begruendung"] == 0


def test_render_und_echte_liste():
    r = gf.finde(gedaechtnis.laden(), [])
    text = "\n".join(gf.render(r))
    assert "Fehler im Gedächtnis" in text and len(r["punkte"]) <= 3


def test_wochenbericht_hat_abschnitt():
    from datetime import datetime, timezone
    from src.research_lab.workshop import weekly_report as wr
    report = wr.build({}, {"filters": {}}, [], datetime(2026, 11, 15, tzinfo=timezone.utc))
    assert report["gedaechtnis"] is not None
    assert "Fehler im Gedächtnis" in wr.render(report)


def test_fehler_im_finder_wird_gemeldet(monkeypatch):
    from datetime import datetime, timezone
    from src.research_lab.workshop import weekly_report as wr
    monkeypatch.setattr(gedaechtnis, "laden", lambda *a, **k: (_ for _ in ()).throw(ValueError("kaputt")))
    report = wr.build({}, {"filters": {}}, [], datetime(2026, 11, 15, tzinfo=timezone.utc))
    assert "kaputt" in report["gedaechtnis"]["fehler"]
    assert "nicht gelaufen" in wr.render(report)
    report["gedaechtnis"] = None
    assert "Fehler im Gedächtnis" not in wr.render(report)

