from src.research_lab import gedaechtnis, gedaechtnis_fehler as gf


def A(i, status, nutzung):
    return {"id": i, "aussage": f"Aussage {i}", "status": status, "nutzung": nutzung}


def plan(net, ids):
    return {"net_r": net, "begruendung": [{"id": i} for i in ids]}


def test_reihenfolge_und_maximum():
    aussagen = [A("A", "ungeprueft", "entscheidet"), A("B", "widerlegt", "papier"), A("C", "belegt", "entscheidet"),
                A("D", "hinweis", "entscheidet"), A("E", "belegt", "anzeige")]
    plaene = [plan(-0.5, ["C"]) for _ in range(10)] + [plan(0.5, ["E"]) for _ in range(10)]
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



def test_ergebnistabelle_je_aussage():
    aussagen = [A("A", "belegt", "entscheidet"), A("B", "ungeprueft", "papier"), A("C", "belegt", "anzeige")]
    plaene = [plan(1.0, ["A", "B"]), plan(-0.5, ["A"]), {"net_r": 3.0}, {"net_r": None, "begruendung": [{"id": "B"}]}]
    t = gf.ergebnistabelle(aussagen, plaene)
    assert [(z["id"], z["plaene"], z["summe_r"], z["mittel_r"]) for z in t] == [("A", 2, 0.5, 0.25), ("B", 1, 1.0, 1.0)]
    assert [z["trennt"] for z in t] == [False, True]
    text = "\n".join(gf.render_tabelle(t))
    assert "B (ungeprueft)" in text and "1 Aussagen stehen in jedem Plan" in text


def test_belegte_aussage_in_jedem_plan_ist_kein_journalfehler():
    r = gf.finde([A("C", "belegt", "entscheidet")], [plan(-1.0, ["C"]) for _ in range(28)])
    assert r["punkte"] == []


def test_bausteine_gegen_ergebnis():
    def p(net, **parts):
        return {"net_r": net, "score_schatten": {"score": 0.3, "parts": {"basis": 0.3, **parts}}}
    plaene = [p(1.0, aggressor=0.08, oi=0.03), p(-1.0, aggressor=-0.06), p(0.5, aggressor=0.08),
              {"net_r": 2.0}, {"net_r": None, "score_schatten": {"parts": {"oi": 0.03}}}]
    t = {z["baustein"]: z for z in gf.bausteine(plaene)}
    assert set(t) == {"aggressor", "oi"}
    assert t["aggressor"]["dafuer"] == {"plaene": 2, "mittel_r": 0.75}
    assert t["aggressor"]["dagegen"] == {"plaene": 1, "mittel_r": -1.0}
    assert t["oi"]["ohne"] == {"plaene": 2, "mittel_r": -0.25}
    text = "\n".join(gf.render_bausteine(list(t.values())))
    assert "Aggressive Seite: dafür +0,75 (2), dagegen -1,00 (1)" in text and "Noch kein Urteil" in text
    assert gf.bausteine([{"net_r": 1.0}]) == [] and gf.render_bausteine([]) == []


def _sp(net, live, schatten):
    return {"net_r": net, "score": live, "score_schatten": {"score": schatten}}


def test_score_vergleich_konstanter_live_score_hat_keine_korrelation():
    plaene = [_sp(n, 0.2363, s) for n, s in ((-1.0, 0.20), (0.5, 0.30), (1.5, 0.35), (-0.2, 0.25))]
    v = gf.score_vergleich(plaene)
    assert v["live"]["werte"] == 1 and v["live"]["rang_korrelation"] is None
    assert v["schatten"]["rang_korrelation"] == 1.0
    assert v["schatten"]["oben_r"] == 1.0 and v["schatten"]["unten_r"] == -0.6
    assert v["schatten"]["urteil_moeglich"] is False
    assert "Noch kein Urteil" in gf.render_score(v)[0]


def test_score_vergleich_nur_plaene_mit_beiden_scores():
    plaene = [{"net_r": 1.0, "score": 0.3}, {"net_r": None, "score": 0.3, "score_schatten": {"score": 0.4}},
              {"net_r": 1.0, "score": 0.3, "score_schatten": None}]
    v = gf.score_vergleich(plaene)
    assert v["schatten"]["plaene"] == 0 and gf.render_score(v) == []


def test_spearman_mit_gleichstaenden():
    assert gf._spearman([1, 1, 2, 3], [4, 3, 2, 1]) < 0
    assert gf._spearman([1, 2], [1, 2]) is None
