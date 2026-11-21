# Absorptions-Filter als Schattenregel R-ABS-1 (Präregistrierung 1.0 – eingefroren 17.11.2026)

Auftrag Uzi 17.11.2026 ("Go"), Anlass: BTCUSDT-15m-Chart vom 17.11. (Handy). TIM zeigte ein Short-Dreieck unter dem 1D VAL (~64.150) genau dort, wo große Absorption (344, 1,6M) einen Sweep zeigte; das Long-Dreieck kam erst bei ~65.000 direkt unter dem 1D VAH (65.100). **Nichts gerechnet, kein Ergebnis gesehen.**

## Version 1.0 – eingefroren (17.11.2026, Uzis Wort "Go, einfrieren")
Ab hier ändern sich Regel, Schwellen (Band 0,30 % voraus, 0,05 % dahinter), Mindestzahl (30 blockierte Pläne) und Kriterium nicht mehr. Geprüft werden nur Pläne, die nach diesem Zeitpunkt im Orderflow-Schatten entstehen. Ein Fehlschlag wird berichtet; andere Schwellen oder Footprint-Cluster (Version 2.0) wären eine neue Version mit neuen Plänen. Ein Zeitplan läuft erst auf Uzis "Zeitplan an".

## Hypothese H1 (neu, ungeprüft)
Ein Plan, der **in Richtung seiner Fahrt auf ein Level mit Absorption trifft**, ist ein Ausbruchssignal in ein gehaltenes Level und hat im Mittel negatives Netto-R. Die Umkehr-Variante (Gegenrichtung handeln) ist **nicht** Teil dieser Regel; sie wäre eine eigene Hypothese.

## Art der Prüfung
Nur live, nur vorwärts, Papier. Orderflow wird nicht per Backtest geprüft (Daten fehlen). Holdout 2025 tabu, Echtgeld gesperrt. Es wird kein Filter aktiviert und kein Journal, Score oder Limit verändert. Die Regel liest ausschließlich den bestehenden Orderflow-Schatten (`data/journal/tim_orderflow_shadow.json`: `lage_at_plan` und Journal-Ergebnis je Plan, nur Pläne ab dessen `started_at`, also prospektiv). Code: `src/dashboard/absorption_shadow.py`.

## Regel R-ABS-1/1.0
- Plan-Richtung d. `lage_at_plan.levels` (die drei nächsten Level der Live-Orderflow-Lage zum Planzeitpunkt, Flag `absorption`, `distance_pct` = (Level − Kurs) / Kurs).
- **blocked**, wenn ein Level mit `absorption = true` in Fahrtrichtung liegt: Abstand in Fahrtrichtung von −0,05 % (Kurs schon knapp durch) bis +0,30 %. Short = darunter, Long = darüber.
- Keine frische Lage = "nicht lesbar", zählt weder als blockiert noch als durchgelassen (eigene Gruppe).
- Nur Information des Planzeitpunkts, kein Look-ahead.

## Auswertung (Kriterium, fest)
- Beurteilbar bei **≥ 30 geschlossenen blockierten Plänen** (Netto-R aus dem Journal, Kosten wie der Orderflow-Schatten: 5 bps je Seite).
- **Bestanden**, wenn das Mittel Netto-R der blockierten Pläne ≤ −0,10 R **und** die einseitige obere 95-%-Bootstrap-Grenze des Mittels < 0 (10.000 Ziehungen, Seed 17).
- Sonst nicht bestanden. Gezeigt werden immer alle drei Gruppen (blockiert, durchgelassen, nicht lesbar) mit n, Mittel und Summe. Ein Fehlschlag wird berichtet, die Regel danach nicht mit anderen Schwellen auf denselben Plänen nachgezogen (neue Schwellen = neue Version, neue Pläne).
- Übernahme als echter Filter nur auf Uzis Wort.

## Bekannte Grenzen (ehrlich)
- Der Orderflow-Schatten speichert nur die **drei nächsten Level**; ein absorbierendes Level dahinter fehlt.
- `absorption` der Live-Lage heißt "Level berührt, nicht durchbrochen, Volumen ≥ 3× Median". Die großen Kreise im Chart (z. B. 344/1,6M, Footprint-Cluster) sind nicht zwingend ein markiertes Level; ob R-ABS-1 den Fall vom 17.11. überhaupt erfasst, zeigt sich erst an den Live-Daten. Eine Erweiterung (Footprint-Cluster am Extrem der letzten Kerzen mitspeichern) wäre Version 2.0 und braucht neue Datenerfassung.
- Stichprobe: Der Orderflow-Schatten sammelt wenige Pläne pro Woche; die 30 blockierten Pläne können Monate dauern. Seit dem 11.11. verwirft das OF-/Kostentor fast alles (0 Trades); die Zählung hängt von den journalisierten Plänen ab.

## Betrieb
`python -m src.dashboard.absorption_shadow [Pfad]` gibt die Auswertung aus (nur lesend). Ein Zeitplan kommt erst auf Uzis "Zeitplan an".
