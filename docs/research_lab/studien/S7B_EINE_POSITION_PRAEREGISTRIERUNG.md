# S7b: S7 mit höchstens einer offenen Position über BTC/ETH/SOL (Präregistrierung)

| Feld | Wert |
|---|---|
| Studie | S7b (Ableitung aus S7, offen deklariert) |
| Version | **0.1 (Entwurf, nicht freigegeben)** |
| Status | ENTWURF: keine Registrierung, kein Lauf, Holdout zu. Vor der Registrierung: adversariale Prüfung (anderes Modell), ergebnisblinder Zähllauf (6.1), Uzis Freigabe per Entscheidungskarte |
| Anlass | S7 scheiterte am 26.10.2026 in der Validierung **nur an K4** (maximaler Drawdown 30,2 R bzw. 30,8 R > 20 R), alle anderen Kriterien erfüllt (`S7_3_4R_TRENDFOLGE_AUSBRUCH_PRAEREGISTRIERUNG.md` Abschnitt 12). Uzi wählte am 26.10. 12:34 Ortszeit per Karte „S7b: eine Position über alle Coins“ |
| Hypothese | Dieselben Regeln wie S7 mit **höchstens einer offenen Position über alle drei Instrumente zusammen** halten den Drawdown unter 20 R, ohne dass der Netto-Erwartungswert je Trade verloren geht |
| Lesart des Ziels | wie S7: Ziel je Gewinntrade 3 R bzw. 4 R; Erwartungswert je Trade voraussichtlich +0,1 bis +0,4 R |
| Protokoll | `../PROTOKOLL.md` Version 1.3; kein neuer Protokoll-Eintrag nötig, alle Abweichungen in 5.5 sind strenger als das Protokoll oder gleich |
| Register | `../REGISTER.jsonl`: 56 Einträge, davon S7-D20-T3/T4 `failed_validation`. S7b will **2 Einträge** (S7b-D20-T3, S7b-D20-T4; 56 → 58 von 60). Für alle Rechnungen gilt weiter m = 60 |
| Branch / PR | `claude/project-thread-0yalj1-s7`, PR #437 (gemeinsam mit S7, Reihenfolge erst #428, dann #437) |
| Vorgänger | S7 (NICHT BESTANDEN, nur K4), S4/S5 (NICHT TESTBAR), S6 (NICHT BESTANDEN) |

## 1. Fragestellung

Hat der S7-Ausbruchseinstieg (Donchian 20 in SMA-200-Richtung, 4h USD-M BTC/ETH/SOL, Stop max(1,5×ATR14, 1 %), Ziel 3
bzw. 4 R, Zeitstop 30 Kerzen) mit der zusätzlichen Portfolio-Regel „höchstens eine offene oder angemeldete Position
über alle drei Instrumente“ nach allen Kosten einen positiven Erwartungswert, der sich von zufälligen Einstiegen
gleicher Geometrie unterscheidet, **und** bleibt der maximale Drawdown dabei unter 20 R (K4)?

## 2. Ableitung aus S7 und Vorbelastung (Offenlegung)

S7b ist **keine neue Idee, sondern eine Reaktion auf ein gesehenes Ergebnis.** Das wird hier festgehalten, damit niemand
die Studie später als unabhängige Bestätigung liest:

- Bekannt vor dieser Fassung: alle S7-Kennzahlen aus Training (2020–2022) und Validierung (2023–2024) für vier Varianten,
  darunter E[R], Trefferquote, Drawdown, Verteilung der Ausstiegsgründe, Jahres- und Seitenaufteilung, Baselines
  (`../reports/s7_train_2026-10-26T1049Z.md`). Außerdem die Einzeltrades aller vier Varianten (Datei auf dem Mac).
- Aus den Einzeltrades wurde **ergebnisblind** (nur Signal-, Einstiegs- und Ausstiegszeiten, kein R) vorgezählt, wie
  viele S7-Trades eine Positionsgrenze 1 überleben: D20-T3 Training 244 von 557, Validierung 176 von 420; D20-T4
  Training 228 von 509, Validierung 159 von 383; jeweils 99–100 Signal-Wochen in der Validierung. Diese Vorzählung
  ist eine Näherung (sie filtert die aufgezeichneten S7-Trades, statt die Sperre im Lauf anzuwenden) und hat die
  Mindestzahlen in 5.1 und das Gate in 6.1 mitbestimmt.
- Nicht gesehen: Ergebnisse (R, Trefferquote, Drawdown) irgendeines Laufs **mit** Positionsgrenze. Nicht geladen: Holdout
  2025-01 bis 2026-09.
- Folge: Training und Validierung von S7b sind **vorbelastet** und können einen positiven Erwartungswert nicht mehr
  unabhängig belegen; sie dienen als Filter (Kriterien in 5), nicht als Beweis. Der einzige unberührte Abschnitt ist der
  Holdout 2025+. Deshalb zählt S7b im Register mit zwei weiteren Einträgen (Holm m = 60 bleibt), und das Holdout-Urteil
  wird mit der in 6 ausgewiesenen, niedrigen Power gelesen.
- Was S7b **nicht** tut: K4 oder ein anderes Kriterium lockern, die Geometrie (Stop, Ziel, Zeitstop, Kanal, Filter) anpassen,
  die D55-Varianten nachträglich registrieren (sie haben das S7-Gate verfehlt und laufen nur als Nachbarn mit) oder die
  Baselines ändern.

## 3. Daten und Datenherkunft

Identisch mit S7 Abschnitt 3: 4h-Klines und Funding USD-M Perpetual BTCUSDT, ETHUSDT (Archive ab 2020-01, gezählt ab
2020-01), SOLUSDT (Archive ab 2020-09, gezählt ab 2020-10), Monatsarchive data.binance.vision bis 2024-12, Datensatz-Hash
9ac4d1357e57e84ebd08ce2eedf19766d27e27bbeae1e21dc68e8e3073415ecc (S7-Zähllauf). Training 2020-01 bis 2022-12,
Validierung 2023-01 bis 2024-12, Holdout ab 2025-01 (Store verweigert ihn). Universum 2026 mit Wissen um das Überleben
gewählt (Survivorship-Grenze, Protokoll 3.1).

## 4. Regeln und Hypothesen-Register

### 4.1 Signal- und Trade-Regeln je Instrument (unverändert S7 4.1)

Donchian-Kanal über t−N…t−1 (ohne Kerze t), N = 20; Long bei Schluss über Kanalhoch und über SMA 200, Short bei Schluss
unter Kanaltief und unter SMA 200; Signal am Schluss, Einstieg nächste Eröffnung (Taker); Stop = Schluss ∓ max(1,5×ATR14,
1 % des Schlusses) als fester Kurs; 1 R = |Fill − Stop|; Ziel T ∈ {3, 4} R; Zeitstop 30 Kerzen (Einstiegskerze = 1); Stop
gewinnt in der Kerze; Lücke schließt die Position; `gap_entry_as_loss` (Eröffnung jenseits des Stops = voller Verlust
plus Kosten). Code: `src/research_lab/hypotheses/s7.py` (unverändert).

### 4.2 Portfolio-Regel (neu, `src/research_lab/backtest/engine.py::run_portfolio`)

1. Über BTCUSDT, ETHUSDT und SOLUSDT zusammen ist **höchstens eine Position offen oder zur nächsten Eröffnung angemeldet**
   (`max_positions = 1`).
2. Ein Signal, das kommt, während der Platz belegt ist, **verfällt**; es wird nichts nachgeholt und nichts in eine
   Warteschlange gestellt. Verfallene Signale werden gezählt und berichtet (`locked_signals`).
3. Zwei Signale auf derselben Kerze bei freiem Platz: feste Reihenfolge **BTCUSDT > ETHUSDT > SOLUSDT**
   (Liquiditätsreihenfolge, vorab festgelegt, ohne Blick auf Ergebnisse).
4. Je Zeitstempel laufen zuerst für alle Instrumente die Ausstiege und angemeldeten Einstiege (Phase 1), dann die
   Signalprüfung in der Reihenfolge aus 3 (Phase 2). Ein Ausstieg in Kerze t gibt den Platz für ein Signal am Schluss
   derselben Kerze frei, genau wie die Einzel-Engine auf ihrer Ausstiegskerze wieder einsteigt.
5. Ein als `stop_before_entry` gebuchter Einstieg (Eröffnung jenseits des Stops) belegt den Platz nur bis zu dieser
   Eröffnung. Schließt eine Lücke eine Position, wird der Platz erst mit der nächsten vorhandenen Kerze dieses Instruments
   frei (konservativ; 4h-Lücken sind selten und im Zähllauf ausgewiesen).
6. Ohne bindende Grenze sind die Ergebnisse je Instrument identisch mit `run_backtest` (Test).

### 4.3 Varianten

| Variante | Kanal N | Ziel T | Registrierung |
|---|---:|---:|---|
| S7b-D20-T3 | 20 | 3 R | ja, nach Gate 6.1 und Uzis Karte |
| S7b-D20-T4 | 20 | 4 R | ja, nach Gate 6.1 und Uzis Karte |
| S7b-D55-T3 | 55 | 3 R | **nein**, nur Nachbar für 5.4 (S7-Gate verfehlt) |
| S7b-D55-T4 | 55 | 4 R | **nein**, nur Nachbar für 5.4 |

Register-Parameter je Eintrag: S7-Geometrie plus `max_positions`, `priority`, `parent = S7`, Gate-Bericht, Gate-Commit,
Datensatz-Hash. Höchstens zwei Kandidatinnen, höchstens eine je T (wie S7 5.1).

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

0. **Machbarkeits-Gate vor der Registrierung** (6.1).
1. **Training (2020–2022):** E[R] > 0 (Basis-Kosten), **≥ 150 Trades** gepoolt **und** ≥ 80 Signal-Wochen, p < 0,10 gegen
   Zufall A und p < 0,10 gegen Zufall A′. (S7: 200/100; gesenkt wegen der Positionsgrenze, mit der Vorzählung aus 2 im
   Blick, Protokoll Mid verlangt 50.)
2. **Validierung (2023–2024):** ≥ 100 Trades und ≥ 50 Signal-Wochen (wie S7), E[R] > 0, p < 0,05 gegen A und A′,
   Profitfaktor > 1,1, **Drawdown ≤ 20 R (K4)**, alle Robustheitsregeln (5.4).
3. **Kandidatinnen:** höchstens eine je T (höheres Validierungs-E), höchstens zwei.
4. **Holdout (2025-01 bis 2026-09):** ein Lauf, nur per Entscheidungskarte, K1–K10 wie 5.2 mit **Mindestzahl 50 Trades
   und 30 Signal-Wochen** (Protokoll K3 Mid ≥ 30; S7 verlangte 100/60). Holm m = 60 über alle Registereinträge.

### 5.2 Kriterien K1–K10 (Holdout)

Wörtlich wie S7 5.2 mit den Mindestzahlen aus 5.1 Punkt 4: K1 E > 0; K2 Holm-signifikant gegen A (m = 60); K3 ≥ 50
Trades und ≥ 30 Signal-Wochen (ergebnisfrei); K4 maximaler Drawdown ≤ 20 R; K5 PF > 1; K6 Trefferquote nur
berichtet (p*, Clopper-Pearson mit n_eff, Designeffekt über ISO-Woche des Signals); K7 Stress-E > 0 (Kosten ×2, Funding
nie zugunsten); K8 schlechtester Trade ≥ −2 R, mittlerer Verlust ≥ −1,2 R, `stop_gap` + `stop_before_entry` ≤ 10 %,
Zeitstop + Lücke ≤ 50 %; K9 mittleres Netto-R der Treffer ≥ T − 0,5; K10 jedes Instrument ≥ 15 % der Trades
(Seitenanteile berichtet). Zusätzlich berichtet: Zahl der verfallenen Signale je Abschnitt.

### 5.3 Trainingsregel

Wie 5.1 Punkt 1; K4 ist im Training kein Kriterium, der Trainings-Drawdown wird berichtet (bei S7 lag er bei 22 R).

### 5.4 Robustheit (Validierung, wie S7)

Jahresstabilität (E > 0 in ≥ 60 % der Kalenderjahre mit ≥ 20 Trades, Training und Validierung zusammen); Walk-Forward
24/6 über alle vier S7b-Varianten (mit Positionsgrenze) mit verkettetem Test-E > 0; Nachbarschaft positiv im Raster
N ∈ {20, 55} × T ∈ {3, 4} (D55 nur als Nachbar).

### 5.5 Abweichungen vom Protokoll

Alle strenger oder gleich: Mindesttrades Training 150 (Protokoll 50), Validierung 100 (Protokoll 25), Holdout 50
(Protokoll 30), Signal-Wochen zusätzlich; K4 Protokollwert; Baselines A/A′/C/B wie S7 (A = Protokoll 7.1, A′/C/B nur
berichtet bzw. Vorauswahl); Horizont Mid.

## 6. Mindeststichprobe, Power und Gate

Je Trade bleibt die Streuung wie bei S7 (≈ 1,7 R bei T = 3, ≈ 2,1 R bei T = 4). Die Positionsgrenze senkt die Tradezahl
auf grob 45 % von S7. Hochgerechnet aus der Vorzählung (2) hat der Holdout etwa **80–90 Trades**. Power-Hilfsrechnung
(einseitig, Baseline-E = 0, ohne Cluster):

| n Holdout | SE (T = 3) | z bei E = +0,30 R | Power E > 0 (p < 0,05) | Power K2 (Holm 0,05/60) | Power K2 bei E = +0,50 R |
|---:|---:|---:|---:|---:|---:|
| 50 | 0,24 | 1,2 | ≈ 35 % | ≈ 3 % | ≈ 18 % |
| 85 | 0,18 | 1,6 | ≈ 50 % | ≈ 6 % | ≈ 35 % |
| 100 | 0,17 | 1,8 | ≈ 55 % | ≈ 8 % | ≈ 42 % |

**Offengelegt:** Mit 80–90 Holdout-Trades ist K2 (Holm über 60 Einträge) nur bei einem sehr großen Effekt erreichbar;
das wahrscheinlichste Holdout-Ergebnis bei echtem E ≈ +0,2 R ist **NICHT BESTANDEN wegen K2** oder **KEIN URTEIL** (K3
knapp). Uzi nimmt das mit der Freigabe-Karte zur Kenntnis. S7b ist deshalb vor allem ein Test von K4 (Drawdown) und
E > 0 in Validierung und Holdout; ein Holm-signifikanter Edge ist mit dieser Stichprobe nicht zu erwarten.

### 6.1 Machbarkeits-Gate (ergebnisblind, vor der Registrierung)

`python scripts/research_lab_s7b.py count`: untere Schranke der Signalzahl, bei der **jedes gezählte Signal alle drei
Instrumente für 30 Kerzen (120 h) sperrt**, Signale in Zeitreihenfolge mit Reihenfolge BTC > ETH > SOL bei gleichem
Zeitstempel; keine Ausstiege, kein R, keine Kurse nach dem Signal. Gate je Variante: Training ≥ 100 Signale und ≥ 60
Signal-Wochen, Validierung ≥ 50 und ≥ 30, hochgerechneter Holdout (schwächstes Kalenderjahr, 63 Coin-Monate bzw. 21
Monate) ≥ 50 Signale und ≥ 30 Signal-Wochen. Die Schranke liegt deutlich unter der echten Tradezahl (bei S7: 341 untere
Zahl gegen 557 Trades im Training), die Mindestzahlen in 5.1 gelten für die echten Trades. Fällt eine Variante durch,
wird sie nicht registriert; fallen beide durch, ist S7b **NICHT TESTBAR** und endet ohne Lauf. Registriert werden nur
N-20-Varianten.

## 7. Zufallsvergleiche (Baselines)

Wie S7 Abschnitt 7, unverändert: A (Protokoll 7.1, gemeinsame Vorlage Seite/Stopabstand/T/Haltedauer, gepoolt je
Instrument, 10 000 Läufe, Seed 20261101), A′ (gleiches ATR/Schluss-Dezil, 2 000 je Dezil), C (gleicher SMA-200-Trendzustand
wie die Seite), B (gespiegelte Signale), Kaufen-und-Halten je Instrument berichtet. Die Baselines bekommen **keine**
Positionsgrenze: Sie prüfen den Einstiegszeitpunkt je Instrument bei gleicher Trade-Geometrie; die Portfolio-Regel ändert
die Auswahl der Trades, nicht ihre Geometrie. Das ist eine Entscheidung vor dem Lauf und wird so berichtet.

## 8. Holdout-Freigabe

Nur nach Uzis ausdrücklichem Wort per Entscheidungskarte vor dem Lauf; die Karte nennt Kandidatinnen (Hash), m,
Protokollversion, die Power aus Abschnitt 6 und dass der Holdout danach für S7b verbraucht ist (auch bei KEIN URTEIL).

## 9. Arbeitspakete

| # | Paket | Prüfbefehl |
|---|---|---|
| P1 | Entwurf 0.1 → adversariale Prüfung (anderes Modell) → 0.2 | Befunde im Änderungsprotokoll |
| P2 | Code: `engine.run_portfolio` (Positionsgrenze, zwei Phasen, Reihenfolge), `hypotheses/s7b.py` (Varianten, gesperrter Zähler), `scripts/research_lab_s7b.py` (count, register, train); S7-Engine-Pfad unverändert | `pytest tests/test_research_lab_s7b.py tests/test_research_lab_backtest.py tests/test_research_lab_s7*.py` grün; **S7-Regression auf dem Mac: `research_lab_s7.py train` liefert dieselbe Trades-Datei (SHA-256 8106fd37…)** |
| P3 | Zähllauf 6.1 auf dem Mac, Bericht `s7b_count_<stamp>.md` | Gate-Tabelle |
| P4 | Entscheidungskarte: Freigabe 1.0, Registrierung S7b-D20-T3/T4 (56 → 58), Kenntnisnahme Power 6 | Register-Zeilen |
| P5 | Training/Validierung mit Positionsgrenze, Baselines, Stress, Robustheit; Register-Status; Bericht `s7b_train_<stamp>.md` | K1–K10, 5.4 |
| P6 | Holdout, ein Lauf, nur per Karte, nur mit Kandidatin | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

Alles aus S7 Abschnitt 10 (R4, S4/S5/S6, Kaufen-und-Halten, S1-4h-Fenster) **plus** die vollständigen S7-Ergebnisse
aus Training und Validierung (Abschnitt 2 oben) und die ergebnisblinde Vorzählung der Positionsgrenze. Kein Holdout.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | Adversariale Prüfung durch ein anderes Modell, Befunde einarbeiten (0.2) | Claude |
| O2 | S7-Regression nach dem Engine-Umbau auf dem Mac (Trades-Hash gleich), Zähllauf 6.1 | Claude, Mac |
| O3 | Uzis Wort per Entscheidungskarte: Freigabe 1.0, Registrierung 56 → 58, Kenntnisnahme der Power (6) | Uzi |
| O4 | Holdout nur per weiterer Entscheidungskarte | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-26 | 0.1 | Erstfassung als offen deklarierte Ableitung aus S7: Positionsgrenze 1 (4.2), Reihenfolge BTC > ETH > SOL, Signale verfallen; Mindestzahlen Training 150/80, Validierung 100/50, Holdout 50/30; Gate mit globaler 30-Kerzen-Sperre 100/60, 50/30, 50/30; Power bei 80–90 Holdout-Trades offengelegt; Baselines ohne Positionsgrenze | Uzis Wahl „S7b“ 12:34 Ortszeit | S7-Ergebnisse Training/Validierung (alle vier Varianten), ergebnisblinde Vorzählung der Positionsgrenze; kein Lauf mit Positionsgrenze, kein Holdout |
