# S25: Positionsgröße nach GARCH-Prognose für S7b (Präregistrierung 1.0)

| Feld | Wert |
|---|---|
| Studie | S25 |
| Version | **1.0, eingefroren am 12.11.2026** auf Uzis Wort „Merge einfrieren“ (10:25 Ortszeit), nach dem bestandenen Zähllauf (6.1). Eingefrorener Code: `src/research_lab/studies/s25.py` mit `FROZEN = True`, Commit siehe Ergebnisabschnitt. Ab jetzt keine Regeländerung |
| Auftrag | Studien-Ideen 11.11.2026, Punkt 1; Uzis „go“ 11.11.2026, 20:45 Ortszeit |
| Bezug | S7b (`S7B_EINE_POSITION_PRAEREGISTRIERUNG.md`, Kandidatin S7b-D20-T3), S15-4h (`S15_GARCH_VOLATILITAET_PRAEREGISTRIERUNG.md`, bestanden), `src/research_lab/vol_4h.py` (Papier-Gewicht seit 03.11.) |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, **nicht** Teil dieser Studie; nur mit Uzis ausdrücklichem Wort |
| Register | Eigene Familie (Größenregel, kein Einstieg), belegt keinen Registerplatz, zählt aber als Versuch für den Deflated Sharpe (`../reports/deflated_sharpe_2026-11-11.md`) |
| Echtgeld | Keine Wirkung. Ein Bestehen ändert nichts automatisch, weder Papier noch Kraken |

## 1. Fragestellung

Senkt eine Positionsgröße nach der GARCH-4h-Prognose den maximalen Drawdown von S7b-D20-T3, ohne den Ertrag je
eingesetztem Risiko zu verschlechtern? Einstieg, Stop, Ziel und Ausstieg bleiben unverändert.

Literatur: Moreira & Muir (2017), „Volatility-Managed Portfolios“, Journal of Finance; Harvey u. a. (2018), „The Impact
of Volatility Targeting“, Journal of Portfolio Management. Laut diesen Arbeiten senkt Volatilitätssteuerung vor allem
Drawdown und Ausreißer, mehr Rendite ist seltener. (Inhalt aus vorhandenem Wissen, für diesen Entwurf nicht neu gelesen.)

## 2. Was schon bekannt ist (Vorbelastung)

- S7b ist bereits schwankungsbereinigt: Der Stop ist max(1,5 × ATR14, 1 %), und jeder Trade riskiert 1 R. Die Frage ist
  also nicht „Größe nach Schwankung ja/nein“, sondern **ob die GARCH-Prognose zusätzlich zum ATR-Stop hilft**.
- Bekannt: alle S7b-Kennzahlen aus Training 2020–2022 und Validierung 2023–2024 (ungewichtet), darunter Drawdown 20,8 R
  (Training) und 10,9 R (Validierung) für D20-T3, sowie die ungewichtete Tradeliste (am 11.11. für den Deflated Sharpe
  geladen). **Nicht berechnet und nicht gesehen:** irgendein Ergebnis mit GARCH-Gewicht auf 2020–2024.
- Bekannt: S15-4h-Ergebnis (Prognose schlägt das 14-Tage-Mittel) und die Papier-Journal-Auswertung „Netto-R mit
  GARCH-Größe“ seit 03.11.2026. Letztere liegt im Holdout-Zeitraum und wird hier nicht verwendet.
- Gewicht, Grenzen und Normierung werden von `vol_4h.py` übernommen, nicht neu gewählt (siehe 4). Abweichung nur dort,
  wo `vol_4h.py` Daten aus der Zukunft nutzen würde.

## 3. Daten

Wie S7b Abschnitt 3: 4h-Klines und Funding USD-M BTCUSDT, ETHUSDT, SOLUSDT, Datensatz-Hash 9ac4d135…; Training
2020-01 bis 2022-12, Validierung 2023-01 bis 2024-12. Trades = die unveränderten S7b-D20-T3-Trades (Code-Stand des
S7b-Laufs, Positionsgrenze 1, Reihenfolge BTC > ETH > SOL).

Prognosen: S15-4h aus `src/research_lab/studies/s15.py` mit den S15-Regeln (Neuschätzung alle 30 Tage auf allen
früheren Perioden, 365 Tage Anlauf). Für einen Trade zählt die Prognose der 4h-Periode, die **nach** der Signalkerze
beginnt, also der Periode, die mit dem Einstieg beginnt. Sie nutzt nur Perioden, die bis zum Einstieg geschlossen
haben (die Signalkerze eingeschlossen, deren Schluss beim Einstieg bekannt ist). Code: `s25.weight`.

Folge des Anlaufs: Erste Prognosen ab etwa 2021-01 (BTC/ETH) und 2021-10 (SOL). Trades ohne Prognose fallen in
**beiden** Armen heraus, damit beide dieselben Trades vergleichen. Das Training ist dadurch kürzer als bei S7b.

## 4. Regeln

1. Gewicht je Trade: w = clip(ref / σ, 0,5, 2,0), σ = Wurzel der GARCH-Prognose in Prozent, Grenzen wie `vol_4h.py`.
2. ref = Median aller σ desselben Instruments in den 365 Tagen vor dem Einstieg (nur Vergangenheit). Liegen dort
   Prognosen für weniger als 90 Tage vor (kurz nach dem Anlauf), bekommt der Trade kein Gewicht und fällt in beiden
   Armen heraus. `vol_4h.py` nutzt einen festen Median aus 2023–2024; das wäre hier ein Blick in die Validierung und ist
   deshalb ersetzt.
3. Gewichteter Trade: R′ = w · R / mittleres w des Abschnitts. Damit haben beide Arme dieselbe mittlere Größe, und der
   Unterschied zeigt nur die Umverteilung zwischen ruhigen und wilden Phasen (wie im Papier-Journal, Issue #100).
4. Kosten, Funding und Slippage sind in R schon enthalten und werden mitgewichtet. Stress (nur berichtet): Gebühren
   doppelt, also R − cost_r je Trade. Das ist eine Näherung: S7b rechnet Stress als eigenen Portfolio-Lauf, dessen
   Trades hier nicht vorliegen.
5. Keine weiteren Varianten. D20-T4 wird nur berichtet.

## 5. Messgrößen und Urteil

Hauptgröße: maximaler Drawdown in R (Summe der R′ in Trade-Reihenfolge, nach Ausstiegszeit).

Nebengrößen (nur berichtet): E[R′] / Drawdown („R pro Risiko“), schlechtester Monat, längste Verlustphase, Anteil der
Trades an den Gewichtsgrenzen, Korrelation von w mit R.

Placebo: Die Gewichte des Abschnitts werden 2 000-mal zufällig auf die Trades verteilt (Seed 20261111). p = Anteil der
Zufallsverteilungen mit Drawdown ≤ GARCH-Drawdown. So prüft die Studie, ob gerade die Prognose hilft und nicht jede
beliebige Umverteilung.

**BESTANDEN** nur, wenn in der Validierung alle vier gelten:

1. Drawdown GARCH ≤ 0,9 × Drawdown fest,
2. Placebo p ≤ 0,05,
3. E[R′] / Drawdown GARCH ≥ E[R] / Drawdown fest,
4. im Training dieselbe Richtung (Drawdown GARCH < Drawdown fest).

Sonst **NICHT BESTANDEN**. Weniger als 80 Validierungs-Trades mit Prognose (6.1) heißt **KEIN URTEIL**.
Erwartung vorab: Weil der ATR-Stop die Schwankung schon zum Teil abfängt, ist ein kleiner Effekt wahrscheinlich.
Ein Drawdown ist ein einzelner Pfadwert und schwankt stark; deshalb das Placebo.

## 6. Ablauf

| Paket | Inhalt | Stand |
|---|---|---|
| P0 | Dieser Entwurf | erledigt (0.1) |
| P1 | `src/research_lab/studies/s25.py` + `tests/test_research_lab_s25.py`: Gewichte aus S15-Prognosen, Normierung, Placebo, Urteil. `count` liest nur Symbol und Einstiegszeit, nie R; `run` ist gesperrt, bis `FROZEN` gesetzt ist und die Tradeliste den eingefrorenen Hash hat | erledigt (0.2) |
| 6.1 | Zähllauf, ergebnisblind: `python -m src.research_lab.studies.s25 count --trades <S7b-Tradeliste> --root <Labor-Daten> --out <Ordner>`; nur Zahl der Trades mit Gewicht je Abschnitt und Instrument; Gate ≥ 80 in der Validierung | **erledigt 11.11. 21:59 Ortszeit, Gate bestanden**: Validierung 207/207 mit Gewicht, Training 139/292 (Anlaufzeit). `../reports/s25_count_2026-11-11T2059Z.md` |
| P2 | Einfrieren 1.0 auf Uzis Wort | erledigt 12.11.2026 |
| P3 | Ein Lauf Training, dann Validierung, Bericht `../reports/s25_<stamp>.md` | offen |

## 7. Was ein Ergebnis bedeutet

- BESTANDEN: Die GARCH-Größe senkt das Risiko von S7b auf vergangenen Daten. Das Papier-Journal nutzt sie schon; eine
  Übernahme in den Kraken-Test oder einen S7b-Holdout wäre ein eigener Schritt mit Uzis Freigabe.
- NICHT BESTANDEN: Der ATR-Stop reicht; das Papier-Gewicht bleibt eine Beobachtung.
- Beides ändert nichts an S7b selbst, an der Kandidatin oder am Register.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Erstfassung (zuerst als S24 angelegt, umbenannt, weil S24 schon an die Indikator-Studie in #229 vergeben ist) |
| 2026-11-11 | 0.2 | Code und Tests (P1). Präzisiert vor jedem Ergebnis: Prognose der Einstiegsperiode, Referenz braucht 90 Tage Vorlauf, Stress als Näherung R − cost_r |
| 2026-11-11 | 0.2 | Zähllauf 6.1 eingetragen (ergebnisblind, Gate bestanden). Nächster Schritt: Einfrieren 1.0 auf Uzis Wort |
| 2026-11-12 | 1.0 | Eingefroren auf Uzis Wort, keine Regeländerung gegenüber 0.2 |
