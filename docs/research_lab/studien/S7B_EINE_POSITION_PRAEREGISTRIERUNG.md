# S7b: S7 mit höchstens einer offenen Position über BTC/ETH/SOL (Präregistrierung)

| Feld | Wert |
|---|---|
| Studie | S7b (Ableitung aus S7, offen deklariert) |
| Version | **1.0 (eingefroren, freigegeben von Uzi am 26.10.2026, 13:52 Ortszeit per Entscheidungskarte)** |
| Status | FREIGEGEBEN: Gate 6.1 bestanden (Zähllauf 26.10. 13:36 Ortszeit, Commit 26cd763, `../reports/s7b_count_2026-10-26T1236Z.md`); S7b-D20-T3/T4 registriert (56 → 58). Uzi hat mit der Karte die Vorbelastung (2), die geringe Power von K2 (6), den Holdout-Verbrauch für das ganze Register (8) und die zwei verbleibenden Registerplätze zur Kenntnis genommen. Training/Validierung laufen auf dem Mac; Holdout zu, nur per weiterer Karte |
| Anlass | S7 scheiterte am 26.10.2026 in der Validierung **nur an K4** (maximaler Drawdown 30,2 R bzw. 30,8 R > 20 R), alle anderen Kriterien erfüllt (`S7_3_4R_TRENDFOLGE_AUSBRUCH_PRAEREGISTRIERUNG.md` Abschnitt 12). Uzi wählte am 26.10. 12:34 Ortszeit per Karte „S7b: eine Position über alle Coins“ |
| Hypothese | Dieselben Regeln wie S7 mit **höchstens einer offenen Position über alle drei Instrumente zusammen** halten den Drawdown unter 20 R, ohne dass der Netto-Erwartungswert je Trade verloren geht |
| Lesart des Ziels | wie S7: Ziel je Gewinntrade 3 R bzw. 4 R; Erwartungswert je Trade voraussichtlich +0,1 bis +0,4 R |
| Protokoll | `../PROTOKOLL.md` Version 1.3. Nach Protokoll 10 („Verworfen bleibt verworfen“) ist S7b **keine Neuparametrierung der verworfenen S7-Varianten, sondern ein neuer Registereintrag über das Änderungsprotokoll** (Notiz dort, keine Regeländerung). Alle Abweichungen in 5.5 sind strenger als das Protokoll oder gleich |
| Register | `../REGISTER.jsonl`: 56 Einträge, davon S7-D20-T3/T4 `failed_validation`. S7b will **2 Einträge** (S7b-D20-T3, S7b-D20-T4; 56 → 58 von 60, danach bleiben zwei Plätze für den gesamten Registerzeitraum). Für alle Rechnungen gilt weiter m = 60 |
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
  darunter E[R], Trefferquote, Drawdown, Verteilung der Ausstiegsgründe, Jahres- und Seitenaufteilung, **E[R] je Instrument**
  und Baselines (`../reports/s7_train_2026-10-26T1049Z.md`). Außerdem die Einzeltrades aller vier Varianten (Datei auf dem Mac).
- Aus den Einzeltrades wurde **ohne Blick auf R** vorgezählt, wie viele S7-Trades eine Positionsgrenze 1 überleben: D20-T3
  Training 244 von 557, Validierung 176 von 420; D20-T4 Training 228 von 509, Validierung 159 von 383; jeweils 99–100
  Signal-Wochen in der Validierung. Diese Vorzählung ist **nicht vollständig ergebnisblind**: Sie nutzt die aufgezeichneten
  Ausstiegszeiten, und wann ein S7-Trade endete (Stop, Ziel, Zeitstop), hängt vom Kursverlauf nach dem Einstieg ab. Sie
  ist außerdem eine Näherung (sie filtert aufgezeichnete S7-Trades, statt die Sperre im Lauf anzuwenden). Sie diente nur
  der Abschätzung der Tradezahl (6); die Mindestzahlen in 5.1 sind die von S7 und hängen nicht von ihr ab.
- Reihenfolge bei gleichzeitigen Signalen (4.2 Punkt 3): BTC > ETH > SOL wurde als Liquiditätsreihenfolge gewählt, **aber
  erst nach** dem S7-Bericht, in dem E[R] je Instrument stand. Die Wahl ist deshalb nicht beweisbar ergebnisfrei. Deshalb
  berichtet jeder Lauf (a) die Zahl der Zeitstempel mit gleichzeitigen Signalen („Ties“, 6.1) und (b) alle Kennzahlen
  zusätzlich mit der **gespiegelten Reihenfolge SOL > ETH > BTC** (nur berichtet, entscheidet nichts). Weichen beide
  Reihenfolgen im Urteil voneinander ab, steht das im Bericht; das Urteil folgt der registrierten Reihenfolge.
- Nicht gesehen: Ergebnisse (R, Trefferquote, Drawdown) irgendeines Laufs **mit** Positionsgrenze. Nicht geladen: Holdout
  2025-01 bis 2026-09. Ein Zähllauf 6.1 auf dem 0.1-Stand (Commit 410cbd0, Mac, 26.10. 12:49 Ortszeit) ergab für D20
  Training 156 Signale / 139 Wochen, Validierung 108 / 93 (untere Schranken, ohne R); er gilt als Vorschau, der
  offizielle Zähllauf läuft auf dem 0.2-Stand.
- Folge: Training und Validierung von S7b sind **vorbelastet** und können einen positiven Erwartungswert nicht mehr
  unabhängig belegen; sie dienen als Filter (Kriterien in 5), nicht als Beweis. Der einzige unberührte Abschnitt ist der
  Holdout 2025+. Deshalb zählt S7b im Register mit zwei weiteren Einträgen (Holm m = 60 bleibt), und das Holdout-Urteil
  wird mit der in 6 ausgewiesenen Power gelesen.
- Was S7b **nicht** tut: K4 oder ein anderes Kriterium lockern, Mindestzahlen gegenüber S7 senken, die Geometrie (Stop,
  Ziel, Zeitstop, Kanal, Filter) anpassen, die D55-Varianten nachträglich registrieren (sie haben das S7-Gate verfehlt und
  laufen nur als Nachbarn mit) oder die Baselines ändern.

## 3. Daten und Datenherkunft

Identisch mit S7 Abschnitt 3: 4h-Klines und Funding USD-M Perpetual BTCUSDT, ETHUSDT (Archive ab 2020-01, gezählt ab
2020-01), SOLUSDT (Archive ab 2020-09, gezählt ab 2020-10), Monatsarchive data.binance.vision bis 2024-12, Datensatz-Hash
9ac4d1357e57e84ebd08ce2eedf19766d27e27bbeae1e21dc68e8e3073415ecc (S7-Zähllauf). Training 2020-01 bis 2022-12,
Validierung 2023-01 bis 2024-12, Holdout ab 2025-01 (Store verweigert ihn ohne Lock, 8). Universum 2026 mit Wissen um das
Überleben gewählt (Survivorship-Grenze, Protokoll 3.1). Abschnittsregel 3.2 (Protokoll 1.2): Ein Trade zählt zum
Abschnitt seines Signals, wenn sein Ausstieg bis zum Abschnittsende feststand; am Abschnitts- oder Datenende offene
Trades zählen nicht und werden gezählt ausgewiesen (`open_at_section_end`).

## 4. Regeln und Hypothesen-Register

### 4.1 Signal- und Trade-Regeln je Instrument (unverändert S7 4.1)

Donchian-Kanal über t−N…t−1 (ohne Kerze t), N = 20; Long bei Schluss über Kanalhoch und über SMA 200, Short bei Schluss
unter Kanaltief und unter SMA 200; Signal am Schluss, Einstieg nächste Eröffnung (Taker); Stop = Schluss ∓ max(1,5×ATR14,
1 % des Schlusses) als fester Kurs; 1 R = |Fill − Stop|; Ziel T ∈ {3, 4} R; Zeitstop 30 Kerzen (Einstiegskerze = 1); Stop
gewinnt in der Kerze; Lücke schließt die Position; `gap_entry_as_loss` (Eröffnung jenseits des Stops = voller Verlust
plus Kosten). Code: `src/research_lab/hypotheses/s7.py` (unverändert).

### 4.2 Portfolio-Regel (neu, `src/research_lab/backtest/engine.py::run_portfolio`)

1. Über BTCUSDT, ETHUSDT und SOLUSDT zusammen ist **höchstens eine Position offen oder zur nächsten Eröffnung angemeldet**
   (`max_positions = 1`). Belegt ist der Platz, solange eine Position offen ist oder ein Einstieg angemeldet ist
   (`_Runner.busy`). Eine Position, die per Ausstiegsregel zur nächsten Eröffnung schließt, belegt den Platz auf der
   Signalkerze nicht mehr (wie `run_backtest` beim Richtungswechsel); S7 hat keine solche Regel, der Fall ist nur für
   die Engine festgehalten.
2. Ein Signal, das kommt, während der Platz belegt ist, **verfällt**; es wird nichts nachgeholt und nichts in eine
   Warteschlange gestellt. Verfallene Signale werden gezählt und je Abschnitt berichtet (`locked_signals`,
   `locked_times`), getrennt von Signalen, die am eigenen Instrument verfallen (`ignored_signals`).
3. Zwei Signale auf derselben Kerze bei freiem Platz: feste Reihenfolge **BTCUSDT > ETHUSDT > SOLUSDT** (Offenlegung in 2;
   gespiegelte Reihenfolge wird mitberichtet).
4. Je Zeitstempel laufen zuerst für alle Instrumente die Ausstiege und angemeldeten Einstiege (Phase 1), dann die
   Signalprüfung in der Reihenfolge aus 3 (Phase 2). Ein Ausstieg in Kerze t gibt den Platz für ein Signal am Schluss
   derselben Kerze frei, auch über Instrumente hinweg, genau wie die Einzel-Engine auf ihrer Ausstiegskerze wieder
   einsteigt.
5. Ein als `stop_before_entry` gebuchter Einstieg (Eröffnung jenseits des Stops) belegt den Platz nur bis zu dieser
   Eröffnung. Schließt eine Lücke eine Position, wird der Platz erst mit der nächsten vorhandenen Kerze dieses Instruments
   frei (konservativ; 4h-Lücken sind selten und im Zähllauf ausgewiesen).
6. Unterschiedliche Datenanfänge: Jedes Instrument zählt Signale erst ab seinem Zählbeginn (SOL ab 2020-10), vorher
   dient es nur dem Indikator-Aufwärmen; eine Position eines früher startenden Instruments sperrt die später startenden.
7. Ohne bindende Grenze sind die Ergebnisse je Instrument identisch mit `run_backtest` (Test); die Einzel-Engine liefert
   nach dem Umbau dieselben Trades wie vor dem Umbau, bis auf die letzte Gleitkommastelle der Plattform (Golden-Fixture `tests/fixtures/research_lab/engine_golden_7cefb19.json`,
   S7-Regression auf dem Mac mit identischer Trades-Datei, SHA-256 8106fd37…).

### 4.3 Varianten

| Variante | Kanal N | Ziel T | Registrierung |
|---|---:|---:|---|
| S7b-D20-T3 | 20 | 3 R | ja, nach Gate 6.1 und Uzis Karte |
| S7b-D20-T4 | 20 | 4 R | ja, nach Gate 6.1 und Uzis Karte |
| S7b-D55-T3 | 55 | 3 R | **nein**, nur Nachbar für 5.4 (S7-Gate verfehlt) |
| S7b-D55-T4 | 55 | 4 R | **nein**, nur Nachbar für 5.4 |

Register-Parameter je Eintrag: S7-Geometrie plus `max_positions`, `priority`, `parent = S7`, Gate-Bericht, Gate-Commit,
Datensatz-Hash. `register` verweigert die Eintragung, solange diese Datei nicht auf Version 1.0 steht oder der Bericht
nicht von S7b stammt. Höchstens zwei Kandidatinnen, höchstens eine je T (wie S7 5.1).

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8 (Mindestzahlen = S7, unverändert)

0. **Machbarkeits-Gate vor der Registrierung** (6.1).
1. **Training (2020–2022):** E[R] > 0 (Basis-Kosten), **≥ 200 Trades** gepoolt **und** ≥ 100 Signal-Wochen, p < 0,10 gegen
   Zufall A und p < 0,10 gegen Zufall A′ (wie S7; Protokoll Mid verlangt 50).
2. **Validierung (2023–2024):** ≥ 100 Trades und ≥ 50 Signal-Wochen (wie S7), E[R] > 0, p < 0,05 gegen A und A′,
   Profitfaktor > 1,1, **Drawdown ≤ 20 R (K4)**, alle Robustheitsregeln (5.4).
3. **Kandidatinnen:** höchstens eine je T (höheres Validierungs-E), höchstens zwei.
4. **Holdout (2025-01 bis 2026-09):** ein Lauf, nur per Entscheidungskarte, K1–K10 wie 5.2 mit **Mindestzahl 100 Trades
   und 60 Signal-Wochen (wie S7)**. Holm m = 60 über alle Registereinträge.

Fassung 0.1 hatte Training 150/80 und Holdout 50/30 vorgesehen, begründet mit einer falschen Hochrechnung von 80–90
Holdout-Trades (6). Die Prüfung ergab ≈ 135–155 erwartete Holdout-Trades; damit sind die S7-Zahlen erreichbar, und eine
Senkung wäre eine Lockerung gegenüber der Elternstudie nach gesehenen Ergebnissen. **Die S7-Mindestzahlen bleiben.**
Erreicht der Holdout keine 100 Trades, lautet das Urteil KEIN URTEIL (K3), und der Holdout ist trotzdem verbraucht.

### 5.2 Kriterien K1–K10 (Holdout)

Wörtlich wie S7 5.2: K1 E > 0; K2 Holm-signifikant gegen A (m = 60); K3 ≥ 100 Trades und ≥ 60 Signal-Wochen
(ergebnisfrei); K4 maximaler Drawdown ≤ 20 R; K5 PF > 1; K6 Trefferquote nur berichtet (p*, Clopper-Pearson mit n_eff,
Designeffekt über ISO-Woche des Signals); K7 Stress-E > 0 (Kosten ×2, Funding nie zugunsten); K8 schlechtester Trade
≥ −2 R, mittlerer Verlust ≥ −1,2 R, `stop_gap` + `stop_before_entry` ≤ 10 %, Zeitstop + Lücke ≤ 50 %; K9 mittleres
Netto-R der Treffer ≥ T − 0,5; K10 jedes Instrument ≥ 15 % der Trades (Seitenanteile berichtet).

Zusätzlich berichtet, nie entscheidend: verfallene Signale je Abschnitt (Grenze und eigenes Instrument getrennt);
Kennzahlen mit gespiegelter Reihenfolge; zu K4 der **Anteil zufälliger Umordnungen derselben R-Werte, deren Drawdown
20 R übersteigt** (1 000 Permutationen, Seed 20261101 + 11): Er sagt, wie viel des beobachteten Drawdowns aus der
Reihenfolge (Serien) und wie viel aus der Größe der Verluste kommt. Ein hoher Anteil bei bestandenem K4 oder ein
niedriger bei verletztem K4 wird so sichtbar, ändert aber das Urteil nicht.

**Stress (K7):** Der Stresslauf ist ein **eigener Portfolio-Lauf mit Stresskosten**. Weil Kosten das R eines Trades und
damit nicht den Ausstiegszeitpunkt ändern, ist die Trade-Auswahl normalerweise gleich; sie kann aber abweichen, wenn die
Kosten einen Grenzfall kippen. Deshalb wird n des Stresslaufs mitberichtet (`stress_n`).

### 5.3 Trainingsregel

Wie 5.1 Punkt 1; K4 ist im Training kein Kriterium, der Trainings-Drawdown wird berichtet (bei S7 lag er bei 22 R).

### 5.4 Robustheit (Validierung, wie S7)

Jahresstabilität (E > 0 in ≥ 60 % der Kalenderjahre mit ≥ 20 Trades, Training und Validierung zusammen); Walk-Forward
24/6 über alle vier S7b-Varianten (mit Positionsgrenze) mit verkettetem Test-E > 0; Nachbarschaft positiv im Raster
N ∈ {20, 55} × T ∈ {3, 4} (D55 nur als Nachbar, Raster ausdrücklich mit S7b-Kennungen übergeben).

### 5.5 Abweichungen vom Protokoll

Alle strenger oder gleich: Mindesttrades Training 200 (Protokoll 50), Validierung 100 (Protokoll 25), Holdout 100
(Protokoll 30), Signal-Wochen zusätzlich; K4 Protokollwert; Baselines A/A′/C/B wie S7 (A = Protokoll 7.1, A′/C/B nur
berichtet bzw. Vorauswahl); Horizont Mid. Neu gegenüber dem Protokoll ist nur die Portfolio-Regel 4.2; sie wirkt auf die
Trade-Auswahl, nicht auf Split, Kriterien oder Raster.

## 6. Mindeststichprobe, Power und Gate

Je Trade bleibt die Streuung wie bei S7 (≈ 1,7 R bei T = 3, ≈ 2,1 R bei T = 4). Die Positionsgrenze senkt die Tradezahl
auf grob 40–45 % von S7. Aus der Vorzählung (2) folgen für den Holdout (21 Monate) etwa **155 Trades (T = 3) bzw. 140
(T = 4)**: Validierung 176 bzw. 159 überlebende Trades in 24 Monaten, mal 21/24. Fassung 0.1 nannte 80–90; das war ein
Rechenfehler (untere Gate-Schranke statt erwarteter Tradezahl). Power-Hilfsrechnung (einseitig, Baseline-E = 0, ohne
Cluster; Spalte „K2“ = Holm-Schwelle 0,05/60, z = 3,14):

| n Holdout | T | SE | z bei E = +0,30 R | Power E > 0 (p < 0,05) | Power K2 bei E = +0,30 R | Power K2 bei E = +0,50 R |
|---:|---:|---:|---:|---:|---:|---:|
| 50 | 3 | 0,24 | 1,2 | ≈ 35 % | ≈ 3 % | ≈ 14 % |
| 100 | 3 | 0,17 | 1,8 | ≈ 55 % | ≈ 8 % | ≈ 42 % |
| 140 | 3 | 0,14 | 2,1 | ≈ 67 % | ≈ 15 % | ≈ 63 % |
| 155 | 3 | 0,14 | 2,2 | ≈ 71 % | ≈ 17 % | ≈ 70 % |
| 100 | 4 | 0,21 | 1,4 | ≈ 41 % | ≈ 4 % | ≈ 22 % |
| 140 | 4 | 0,18 | 1,7 | ≈ 52 % | ≈ 7 % | ≈ 37 % |
| 155 | 4 | 0,17 | 1,8 | ≈ 55 % | ≈ 9 % | ≈ 43 % |

**Offengelegt:** Bei echtem E ≈ +0,2 bis +0,3 R (S7-Validierung: +0,19 / +0,24 R) liegt die Power von K2 auch mit 140–155
Holdout-Trades bei etwa 10–17 %. Das wahrscheinlichste Holdout-Ergebnis ist **NICHT BESTANDEN wegen K2**, selbst wenn
E > 0 und K4 halten. Uzi nimmt das mit der Freigabe-Karte zur Kenntnis. S7b ist deshalb vor allem ein Test von K4
(Drawdown) und E > 0 in Validierung und Holdout; ein Holm-signifikanter Edge ist mit dieser Stichprobe nur bei einem
großen Effekt (E ≥ +0,5 R) wahrscheinlich.

### 6.1 Machbarkeits-Gate (ergebnisblind, vor der Registrierung)

`python scripts/research_lab_s7b.py count`: untere Schranke der Signalzahl, bei der **jedes gezählte Signal alle drei
Instrumente für 30 Kerzen (120 h) sperrt**, Signale in Zeitreihenfolge mit Reihenfolge BTC > ETH > SOL bei gleichem
Zeitstempel; keine Ausstiege, kein R, keine Kurse nach dem Signal (Test: Kurse nach dem Fenster ändern die Zahl nicht).
Gate je Variante: Training ≥ 100 Signale und ≥ 60 Signal-Wochen, Validierung ≥ 50 und ≥ 30, hochgerechneter Holdout
≥ 50 Signale und ≥ 30 Signal-Wochen. **Hochrechnung je Kalendermonat:** Dichte des schwächsten Kalenderjahres (Signale
je Monat, 2020 mit 12 Monaten gezählt, obwohl SOL erst im Oktober beginnt, was die Dichte nur senkt) mal 21
Holdout-Monate. Mit einem gemeinsamen Platz skaliert die Zahl mit Monaten, nicht mit Coin-Monaten; die S7-Hochrechnung
je Coin-Monat wäre hier zu optimistisch. Zusätzlich berichtet: Ties (Zeitstempel mit Signalen mehrerer Instrumente),
Lücken, Anteil je Instrument und Abschnitt (Vorschau auf K10 ≥ 15 %, nur Vorschau).

Die Schranke liegt deutlich unter der echten Tradezahl (bei S7: 341 untere Zahl gegen 557 Trades im Training, Faktor
≈ 0,61; mit Sperre ist das Verhältnis ähnlich, weil die Sperre jeden Trade mit 30 Kerzen ansetzt, obwohl die meisten
früher enden). Die Mindestzahlen in 5.1 gelten für die echten Trades; das Gate verhindert nur, dass ein Registerplatz
für eine offensichtlich zu kleine Stichprobe verbraucht wird. Fällt eine Variante durch, wird sie nicht registriert;
fallen beide durch, ist S7b **NICHT TESTBAR** und endet ohne Lauf. Registriert werden nur N-20-Varianten.

**Ergebnis (26.10. 13:36 Ortszeit, Mac, Commit 26cd763, Datensatz-Hash 9ac4d135…, `../reports/s7b_count_2026-10-26T1236Z.{md,json}`):**

| Variante | Training (untere) / Wochen | Validierung (untere) / Wochen | Holdout hochgerechnet / Wochen (schwächstes Jahr 2020) | Ties | Gate |
|---|---:|---:|---:|---:|---|
| S7b-D20-T3, -T4 | 156 / 139 | 108 / 93 | 78,8 / 68,2 | 473 | **BESTANDEN** (registrierbar) |
| S7b-D55-T3, -T4 | 126 / 112 | 96 / 86 | 64,8 / 56,0 | 293 | nur Nachbar |

Beide N-20-Varianten liegen über allen Schwellen; das schwächste Jahr ist 2020 (SOL erst ab Oktober, konservativ). Anteil je Instrument (Vorschau auf K10): BTC 38–41 %, ETH 19–32 %, SOL 30–40 %, alle über 15 %. 473 Ties bei 2 104 ungesperrten Signalen: die Reihenfolge entscheidet oft, die gespiegelte Reihenfolge wird deshalb mitberichtet (2). Erwartete echte Tradezahl mit Faktor ≈ 0,61 aus S7: Training ≈ 255, Validierung ≈ 175, Holdout ≈ 130; die S7-Mindestzahlen 200/100/100 sind erreichbar, im Holdout ohne großen Spielraum.

## 7. Zufallsvergleiche (Baselines)

Wie S7 Abschnitt 7, unverändert: A (Protokoll 7.1, gemeinsame Vorlage Seite/Stopabstand/T/Haltedauer, gepoolt je
Instrument, 10 000 Läufe, Seed 20261101), A′ (gleiches ATR/Schluss-Dezil, 2 000 je Dezil), C (gleicher SMA-200-Trendzustand
wie die Seite), B (gespiegelte Signale), Kaufen-und-Halten je Instrument berichtet. Die Baselines bekommen **keine**
Positionsgrenze: Sie prüfen den Einstiegszeitpunkt je Instrument bei gleicher Trade-Geometrie; die Portfolio-Regel ändert
die Auswahl der Trades, nicht ihre Geometrie. Das ist eine Entscheidung vor dem Lauf und wird so berichtet.

## 8. Holdout: Freigabe und Ablauf

Nur nach Uzis ausdrücklichem Wort per Entscheidungskarte vor dem Lauf; die Karte nennt Kandidatinnen (Hash), m,
Protokollversion, die Power aus Abschnitt 6 und dass der Holdout danach verbraucht ist (auch bei KEIN URTEIL).

**Befehl (vorab festgelegt):** `python scripts/research_lab_s7b.py holdout --approval "<Karte, Datum, Uhrzeit>"
--commit-register` (auf dem Mac mit `--root` und `--out` wie beim Training). Der Befehl

1. verweigert ohne `--approval`-Text und ohne Kandidatin mit Status `candidate` im Register;
2. schreibt **einmalig** die Sperrdatei `docs/research_lab/HOLDOUT_LOCK.json` (Kandidatinnen, Hash, Registergröße
   m = 58 zum Zeitpunkt des Laufs, Register-Kopf, Protokollversion); ein zweiter Aufruf scheitert an der vorhandenen
   Datei. **Die Sperre gilt für das ganze Register, nicht nur für S7b:** Nach Protokoll 8 und 10 ist der Holdout für den
   gesamten Registerzeitraum (alle bis dahin 58 Einträge) verbraucht; eine spätere Studie müsste mit einem neuen
   Register und neuer Holdout-Grenze beginnen. Die Holm-Korrektur rechnet weiter mit m = 60, nicht mit 58;
3. lädt erst dann die Archive 2025-01 bis 2026-09 (Klines und Funding je Instrument) über den Store mit der
   Holdout-Berechtigung und schneidet die Daten bei 2026-10-01 (ausschließlich) ab;
4. startet **flach am 2025-01-01**: keine Position und kein Signal aus der Validierung wird übernommen; die Indikatoren
   (SMA 200, Kanal, ATR) wärmen aus den Kerzen davor auf; Signale zählen ab 2025-01-01 00:00 UTC;
5. rechnet je Kandidatin den Portfolio-Lauf mit Basis- und Stresskosten (eigener Lauf, 5.2), Baselines A/A′/C/B,
   Kaufen-und-Halten, Permutationsanteil zu K4, Bootstrap-CI; ein am Datenende offener Trade zählt nicht
   (`open_at_section_end`);
6. urteilt K1–K10 mit Holm über m = 60 über alle Kandidatinnen gemeinsam und setzt `passed_holdout`, `failed_holdout` oder
   `no_verdict` (K3 verfehlt) ins Register; Bericht `s7b_holdout_<stamp>.{json,md}`.

Sperrdatei, Register und Bericht werden gemeinsam committet.

## 9. Arbeitspakete

| # | Paket | Prüfbefehl |
|---|---|---|
| P1 | Entwurf 0.1 → adversariale Prüfung (anderes Modell) → 0.2 | Befunde im Änderungsprotokoll (erledigt 26.10.) |
| P2 | Code: `engine.run_portfolio` (Positionsgrenze, zwei Phasen, Reihenfolge, Zeitlisten), `hypotheses/s7b.py` (Varianten, gesperrter Zähler, Ties), `scripts/research_lab_s7b.py` (count, register, train, holdout); S7-Engine-Pfad unverändert | `pytest tests/test_research_lab_s7b.py tests/test_research_lab_backtest.py tests/test_research_lab_s7*.py` grün (27 S7b-Tests inkl. Golden-Fixture); **S7-Regression auf dem Mac: `research_lab_s7.py train` liefert dieselbe Trades-Datei (SHA-256 8106fd37…)** (erledigt) |
| P3 | Offizieller Zähllauf 6.1 auf dem Mac auf dem 0.2-Stand, Bericht `s7b_count_<stamp>.md` ins Repo | erledigt: `../reports/s7b_count_2026-10-26T1236Z.md`, Commit 26cd763 |
| P4 | Entscheidungskarte: Freigabe 1.0, Registrierung S7b-D20-T3/T4 (56 → 58), Kenntnisnahme Power 6, Holdout-Verbrauch 8 und letzte Registerplätze | Register-Zeilen |
| P5 | Training/Validierung mit Positionsgrenze, Baselines, Stress, Robustheit; Register-Status; Bericht `s7b_train_<stamp>.md` | K1–K10, 5.4 |
| P6 | Holdout, ein Lauf, nur per Karte, nur mit Kandidatin (8) | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

Alles aus S7 Abschnitt 10 (R4, S4/S5/S6, Kaufen-und-Halten, S1-4h-Fenster) **plus** die vollständigen S7-Ergebnisse
aus Training und Validierung (Abschnitt 2 oben), die Vorzählung der Positionsgrenze aus den S7-Trades (ohne R, mit
Ausstiegszeiten) und der Zähllauf 6.1 auf dem 0.1-Stand (Signalzahlen ohne R). Kein Lauf mit Positionsgrenze, kein
Holdout.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | ~~Adversariale Prüfung durch ein anderes Modell, Befunde einarbeiten (0.2)~~ erledigt 26.10. | Claude |
| O2 | ~~S7-Regression nach dem Engine-Umbau auf dem Mac (Trades-Hash gleich); offizieller Zähllauf 6.1 auf dem 0.2-Stand~~ erledigt 26.10. 13:36 | Claude, Mac |
| O3 | ~~Uzis Wort per Entscheidungskarte: Freigabe 1.0, Registrierung 56 → 58, Kenntnisnahme Power (6), Holdout-Verbrauch (8), zwei verbleibende Registerplätze~~ erledigt 26.10. 13:52 | Uzi |
| O4 | Holdout nur per weiterer Entscheidungskarte | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-26 | 0.1 | Erstfassung als offen deklarierte Ableitung aus S7: Positionsgrenze 1 (4.2), Reihenfolge BTC > ETH > SOL, Signale verfallen; Mindestzahlen Training 150/80, Validierung 100/50, Holdout 50/30; Gate mit globaler 30-Kerzen-Sperre 100/60, 50/30, 50/30; Power bei 80–90 Holdout-Trades offengelegt; Baselines ohne Positionsgrenze | Uzis Wahl „S7b“ 12:34 Ortszeit | S7-Ergebnisse Training/Validierung (alle vier Varianten), ergebnisblinde Vorzählung der Positionsgrenze; kein Lauf mit Positionsgrenze, kein Holdout |
| 2026-10-26 | 0.2 | **Nach adversarialer Prüfung (anderes Modell, 17 Befunde):** (a) Mindestzahlen zurück auf S7 (Training 200/100, Holdout 100/60): Die Hochrechnung 80–90 Holdout-Trades war falsch (untere Gate-Schranke statt Erwartung), erwartet sind ≈ 140–155; Power-Tabelle neu mit T = 4 und n = 140/155. (b) Vorzählung als „ohne R, aber mit ergebnisabhängigen Ausstiegszeiten“ eingeordnet, nicht mehr als ergebnisblind. (c) Offengelegt, dass E[R] je Instrument vor der Wahl der Reihenfolge bekannt war; Ties und gespiegelte Reihenfolge werden berichtet. (d) Gate-Hochrechnung je Kalendermonat statt je Coin-Monat (ein Platz skaliert mit Monaten). (e) Stress als eigener Portfolio-Lauf mit berichtetem n. (f) Permutationsanteil zu K4 berichtet. (g) Holdout-Befehl festgelegt: flacher Start 2025-01-01, Fenster bis 2026-10-01, Sperrdatei einmalig, m = 58 im Lock gegen Holm m = 60, Verbrauch für das ganze Register. (h) Engine: `busy`-Regel, Lücken, `stop_before_entry`, Datenanfänge in 4.2 festgehalten; Golden-Fixture der alten Engine als Regressionstest. (i) `register` verweigert ohne Version 1.0 und bei fremder Studie; Nachbarschaftsregel mit S7b-Raster. (j) Verhältnis Schranke/echte Trades (S7 ≈ 0,61) und Folge für die Registerplätze (58 von 60) ergänzt; Protokoll-10-Einordnung (neuer Eintrag, keine Neuparametrierung). Keine Lockerung gegenüber S7 | Prüfbefunde | zusätzlich: Zähllauf 6.1 auf dem 0.1-Stand (Signalzahlen ohne R, Commit 410cbd0); kein Lauf mit Positionsgrenze, kein Holdout |
| 2026-10-26 | 0.3 | Gate-Ergebnis 6.1 eingetragen (D20 bestanden, D55 nur Nachbar), Status und offene Punkte aktualisiert; keine Regeländerung | Zähllauf 13:36 Ortszeit | zusätzlich: Signalzahlen, Wochen, Ties und Instrumentanteile des Zähllaufs (ohne R); kein Lauf mit Positionsgrenze, kein Holdout |
| 2026-10-26 | 1.0 | Eingefroren und freigegeben; S7b-D20-T3 und S7b-D20-T4 registriert (Register 56 → 58, Gate-Bericht `s7b_count_2026-10-26T1236Z`, Gate-Commit 26cd763). Keine inhaltliche Änderung gegenüber 0.3 | Uzis Karte „Ja, freigeben und registrieren“ 13:52 Ortszeit | wie 0.3; kein Lauf mit Positionsgrenze, kein Holdout |
