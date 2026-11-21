# S32-R: Wohin geht die Range? Begleitstudie zu S32 (Präregistrierung, Entwurf 0.1)

| Feld | Wert |
|---|---|
| Studie | S32-R, Begleitstudie zu S32 (gleiche Daten, gleiche Range-Erkennung, eigene Fragen) |
| Version | **0.1, Entwurf.** Regeln als Code: `src/research_lab/studies/s32r.py` (`Config`, SHA-256 schließt die S32-Regeln ein), Tests `tests/test_research_lab_s32r.py`. `evaluate` gesperrt bis 1.x |
| Anlass | Barti 16.11.2026: „bei welcher Range es in welche Richtung geht“, Grundverhalten und Buch „Hand in Hand“. Parameter von Uzi angenommen (Issue #315, 17.11.) |
| Daten | wie S32: 55 kostenlose Tardis-Tage, Training 2020-06 bis 2022-12, Validierung 2023–2024, Holdout ab 2025 gesperrt |
| Einfrieren | **zusammen mit S32**, bevor S32 ausgewertet wird (Barti 16.11.). Danach ist der eigene Recorder (#253) der Vorwärtstest für beide |

## 1. Die Range

Wie S32 (P4–P6): Hoch und Tief der Mitte der letzten 15 Minuten, beide Ränder verteidigt, mindestens 3 Berührungen,
mindestens 95 % gültige Sekunden. Gruppen wie S32 0.9: vier Breiten (10–20, 20–60, 60–100, 100–150 bp) über den
ganzen Tag und je Sitzung (Asien, London, New York, spät), jede Gruppe eine eigene Frage.

Eine Range zählt **einmal**, in der Sekunde, in der sie zum ersten Mal als verteidigt gilt. Danach zählt dieselbe
Breitengruppe frühestens nach 60 Minuten wieder, damit sich die Ausgänge nicht überlappen.

## 2. Buch

Menge im ±5-bp-Band, **Bid geteilt durch Ask**. Über 1 heißt: oben dünner, unter 1: unten dünner. Von den letzten
3 Sekunden zählt der Wert, der am nächsten an 1 liegt (die Schiefe muss halten). Alle Verhältnisse, keine Schwelle.

## 3. Ausgang (Uzi, #315)

Innerhalb von **60 Minuten** zuerst:

- **oben**: Mitte ein Viertel der Breite über dem oberen Rand,
- **unten**: dasselbe unten,
- **bleibt**: keins von beiden.

Tag endet vor Ablauf: „fehlt“, nicht gewertet. Beschreibend: Liegt der Preis 60 Minuten nach dem Ausbruch noch
jenseits des Rands? (S20: nur ~31 % der Linienbrüche hielten 24 h.)

## 4. Fragen

| | Frage | Messung | Bestehen |
|---|---|---|---|
| B | Wie verhält sich jede Range-Breite normalerweise? | Anteile oben / unten / bleibt je Gruppe | beschreibend |
| A1 | Gehen Ausbrüche zur dünnen Seite? | unter allen Ausbrüchen: Steigung von „oben“ über log(Bid/Ask), begrenzt auf 1:10 bis 10:1 | untere Grenze > 0 in Training **und** Validierung |
| A2 | Brechen Ranges mit schiefem Buch öfter aus? | Steigung von „Ausbruch“ über \|log(Bid/Ask)\| | untere Grenze > 0 in Training **und** Validierung |

- Je Gruppe α = 0,05, je Hälfte für A1 und A2. Block-Bootstrap über Tage, 9 999 Ziehungen, Seed 3232.
- Unter 30 Fällen je Abschnitt (A1: Ausbrüche, A2: Ranges): gezeigt, kein Urteil. Hinterher wird nichts ausgesiebt.
- Keine Kostenfrage in 0.1: Sie folgt erst, wenn A1 besteht (eigener Schritt, neue Präregistrierung).
- Kein Handelsvorteil, daher kein Deflated-Sharpe-Versuch; die Zahl der Fragen wird im Bericht genannt.

## 5. Vorbelastung

Dieselben Tage wie S32; S32 ist nicht ausgewertet, nur gezählt (ergebnisblind). Keine Ausgänge gesehen.

## 6. Ablauf

1. `pytest tests/test_research_lab_s32r.py` grün.
2. Zähllauf (ergebnisblind): `python -m src.research_lab.studies.s32r count --dir ~/TIM-research/tardis --out DIR --fetch`
3. Einfrieren als 1.0 zusammen mit S32, mit Uzis Wort und Bartis Go.
4. Einmal auswerten. Kein Nachbessern.

## 7. Nicht Teil von S32-R

Weitere Hinweise (Trend davor, Dauer der Range, Zahl der Berührungen, Marktorders), andere Horizonte oder
Ausbruchsgrenzen, Kosten, Echtgeld.
