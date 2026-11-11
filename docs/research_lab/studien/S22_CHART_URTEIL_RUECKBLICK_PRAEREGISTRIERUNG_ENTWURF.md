# S22: Chart-Urteil im Rückblick: Sortieren die Kerzen-Regeln R1–R5 von `chart-urteil/1.0` Standard-Trades nach ihrem Ergebnis? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S22 (nächste freie Nummer nach S21, 11.11.2026) |
| Version | **0.2, Entwurf.** Regeln als Code: `src/research_lab/studies/s22.py`, Tests `tests/test_research_lab_s22.py`. Ein Zähllauf mit 0.1 (ergebnisblind, Abschnitt 5.1), kein Ergebnis gelesen. `evaluate` verweigert den Lauf, solange die Version mit 0 beginnt |
| Anlass | Uzi 11.11.2026: „TIM soll den ganzen Chart beurteilen“, „go“ auf Paket 3 (Rückblick). Der Live-Schatten `src/dashboard/chart_verdict.py` (PR #217) braucht 30 geschlossene Pläne und 28 Tage; S22 stellt dieselbe Frage auf der Historie |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Regelwerk | `chart-urteil/1.0`, eingefroren am 11.11.2026 vor jedem Blick auf Ergebnisse. S22 ruft `chart_verdict.chart_lage` und `chart_verdict.judge` unverändert auf |
| Daten | Binance Spot BTCUSDT 1h und 30m, 2019-10 bis 2024-12 (Vorlauf 60 Tage, Momente ab 2020-01-01) |
| Holdout | ab 2025-01-01, wird nicht geladen. Training 2020–2022, Validierung 2023–2024 (Protokoll) |
| Einordnung | Beobachtungsstudie mit hypothetischen Standard-Trades, ohne Registerplatz. Auch bei Bestehen kein Filter für Engine, Journale oder Echtgeld (Abschnitt 8) |

## 1. Fragestellung

Jede geschlossene 1h-Kerze ist ein Moment. An jedem Moment werden ein Long und ein Short zum Schlusskurs eröffnet:
Stop 1 ATR14, Ziel 2 ATR14, spätestens nach 48 Stunden Ausstieg zum Schluss. Treffen Stop und Ziel in derselben
Kerze, zählt der Stop. Kosten 5 Basispunkte je Seite (wie die Papier-Schatten).

Für jeden dieser Trades fällt das Chart-Urteil aus den bis dahin geschlossenen Kerzen (60 Tage 1h, 30 Tage 30m):

| Regel | Inhalt |
|---|---|
| R1 | Einstieg am 1D VAL/VAH (Rand des Vortages-Werts) oder am 1D POC |
| R2 | 1h- und 4h-Struktur (BOS/MSS) mit oder gegen den Trade |
| R3 | Stop hinter dem Strong Low/High der 1h-Struktur |
| R4 | 1D/1W-Level, naked POC oder BOS-Ziel der Gegenrichtung zwischen Einstieg und Ziel |
| R5 | ungebrochene 1h-Trendlinie stützt oder bremst |

Score = Punkte dafür minus Punkte dagegen; ≥ 2 NEHMEN, ≤ −2 AUSLASSEN, sonst NEUTRAL.

- **H1:** Das mittlere Netto-R von NEHMEN liegt über dem von AUSLASSEN.
- **H2:** Das mittlere Netto-R von NEHMEN liegt über dem aller Trades (das Urteil ist besser als „alles nehmen“).

Nicht geprüft: R6–R8 (Absorption, Orderflow-Welle, CVD und Perp-Delta). Sie brauchen die Live-Orderflow-Lage und
laufen nur im Schatten vorwärts. Nicht geprüft werden auch TIMs echte Pläne (die Historie der Plan-Journale
beginnt 2026), andere Stops/Ziele, andere Coins.

## 2. Vorbelastung

- Die Regeln wurden am 11.11.2026 geschrieben, ohne Ergebnisdaten anzusehen. Der Live-Schatten hatte beim Entwurf
  0 Pläne.
- BTC 2020–2024 ist durch viele Studien gesehen (S7b, S9, S13–S21). Bekannt ist daraus unter anderem, dass
  Trendfolge auf BTC in Teilen des Zeitraums trägt. R2 ist eine Trendregel; ein Bestehen allein durch R2 wäre
  deshalb keine neue Erkenntnis. Der Bericht weist jede Regel einzeln aus (Abschnitt 5, ohne Test).
- Die Validierung 2023–2024 ist nicht frisch (allgemeine Marktkenntnis). Es wird nichts angepasst: keine Gewichte,
  keine Schwellen, keine Auswahl von Regeln.

## 3. Momente und Ausschluss

- Ein Moment zählt nur, wenn in den 60 Tagen davor höchstens 24 Stundenkerzen fehlen, die letzten 24 Kerzen
  lückenlos sind und die 48 Kerzen danach lückenlos sind. (0.1 verlangte 60 lückenlose Tage; siehe 5.1.)
- Ein Trade muss ganz in seinem Abschnitt liegen: Momente in den letzten 48 Stunden vor 2023-01-01 und vor
  2025-01-01 entfallen (kein Trade des Trainings läuft in die Validierung, keiner in den Holdout).
- Es wird nichts aufgefüllt.

## 4. Abweichungen vom Live-Schatten (bekannt, bleiben)

- Die Level stammen aus der Kerzen-Näherung, nicht aus echten Trades (live nutzt der Schatten den Footprint-Store,
  wenn er da ist).
- Die Struktur hängt von der Länge der geladenen Historie ab; S22 legt 60 Tage 1h fest.
- Standard-Trades statt TIMs Plänen. Ein Ergebnis sagt, ob die Regeln beliebige Einstiege sortieren, nicht, ob sie
  TIMs Pläne verbessern. Das zeigt nur der Schatten.
- Long und Short am selben Moment sind fast Spiegelbilder, und stündliche Trades mit 48 Stunden Laufzeit
  überlappen stark. Die Tests rechnen deshalb in Wochenblöcken (Abschnitt 5).

## 5. Erfolgskriterien

In der Validierung:

| # | Kriterium |
|---|---|
| 1 | Machbarkeits-Gate: je Abschnitt mindestens 300 Trades NEHMEN und 300 AUSLASSEN, Validierung mindestens 50 Wochen |
| 2 | H1: NEHMEN minus AUSLASSEN mindestens 0,05 R; im Training dasselbe Vorzeichen |
| 3 | Block-Bootstrap über Wochen (Blocklänge 4, 9 999 Ziehungen, Seed 22), Holm über H1 und H2 (m = 2): beide p < 0,05 |
| 4 | Glückstest: Entscheidungen je Richtung im Kreis gegen die Ergebnisse verschoben (mindestens 14 Tage, 199 Verschiebungen): p < 0,05 |

Urteil: „BESTANDEN (Kandidat)“, „NICHT BESTANDEN“ oder „nicht testbar (Gate)“. Zusätzlich wird ausgewiesen, ob
NEHMEN nach Kosten im Mittel über 0 R liegt. Das ist kein Kriterium: Die Standard-Trades sind kein Handelssystem.

Nur Bericht, ohne Test: mittleres Netto-R je Entscheidung, je Score und je Regel (dafür/dagegen), in beiden
Abschnitten.

### 5.1 Machbarkeits-Gate (ergebnisblind)

`count` zählt Momente, Trades und Entscheidungen je Abschnitt. Es liest kein Ergebnis. Das Gate wird nicht gelockert.

Zähllauf mit 0.1 auf der PS5 am 11.11.2026 (Commit ee464491, Datensatz `9083b6ae…4826`, 46 021 Stundenkerzen,
35 fehlen): Training 13 283 Momente (NEHMEN 2 986, AUSLASSEN 9 716, 84 Wochen), Validierung 16 009 Momente
(NEHMEN 4 024, AUSLASSEN 12 436, 98 Wochen), Gate erfüllt. Im Training fehlte die Hälfte der Momente: Jede
fehlende Stundenkerze sperrte die 60 Tage danach, also gerade die Phasen nach Börsenausfällen. 0.2 erlaubt
deshalb bis zu 24 fehlende Kerzen im Vorlauf. Die Änderung fiel ohne Kenntnis eines Ergebnisses: `count` liest
keine Ergebnisse, `evaluate` war gesperrt.

## 6. Was nicht geändert wird

Regelwerk `chart-urteil/1.0`, Stop/Ziel/Laufzeit/Kosten, Fensterlängen, Kriterien. Kein zweiter Lauf mit anderen
Stops, Zeitrahmen oder Coins als „zweiter Versuch“. Ändert sich das Regelwerk, ist das eine neue Studie.

## 7. Ablauf bis 1.0

1. Code und Tests (0.1, erledigt): Ergebnisregel (Stop zuerst, Zeitausstieg, Kosten), Abschnittsgrenze, keine
   Vorausschau (Kerzen nach dem Moment ändern das Urteil nicht), ergebnisblinder Zähllauf, Sperre von `evaluate`.
   Gepflanzter Effekt besteht, reines Rauschen besteht nicht.
2. Zähllauf auf der PS5:
   `python -m src.research_lab.studies.s22 count --root data/research_lab --out ~/tim-research/results/s22 --fetch --workers 16`
3. Einfrieren als 1.0 auf Uzis Wort.
4. Ergebnislauf: derselbe Befehl mit `evaluate`. Bericht nach Abschnitt 5.

## 8. Einordnung ins Gesamtsystem

Ein Bestehen ändert nichts an Engine, Journalen oder Echtgeld. Es ist ein Hinweis für den Vergleich des
Live-Schattens (frühestens 09.12.2026 und ab 30 geschlossenen Plänen). Übernommen wird nur auf Uzis Wort. Ein
Nichtbestehen heißt: Die Kerzen-Regeln sortieren Standard-Trades nicht; der Schatten läuft trotzdem bis zu seiner
Frist, weil er auch R6–R8 und TIMs echte Pläne prüft.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Entwurf mit Code und Tests. Keine Daten geladen. |
| 2026-11-11 | 0.2 | Vorlauf: bis zu 24 fehlende Stundenkerzen in 60 Tagen erlaubt, letzte 24 Kerzen lückenlos (vorher 60 lückenlose Tage). Anlass: Zähllauf 0.1 verlor die Hälfte des Trainings. Regelwerk, Trades, Kriterien unverändert; kein Ergebnis gelesen. |
