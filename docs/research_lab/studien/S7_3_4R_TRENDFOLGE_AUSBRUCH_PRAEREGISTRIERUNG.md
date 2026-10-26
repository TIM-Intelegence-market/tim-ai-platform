# S7: 3–4 R je Gewinntrade durch Trendfolge-Ausbruch auf 4h-Kerzen (Präregistrierung)

| Feld | Wert |
|---|---|
| Studie | S7 |
| Version | **0.3 (Entwurf, Gate gerechnet, nicht freigegeben)** |
| Status | ENTWURF, **Zähllauf 6.1 gerechnet (26.10., 10:38 Ortszeit, Commit 2a9d3be, Datensatz-Hash 9ac4d135…)**: S7-D20-T3 und S7-D20-T4 bestehen das Gate, S7-D55-T3/T4 nicht (hochgerechnet 59,5 Holdout-Signal-Wochen, Schwelle 60). Keine Registrierung, kein Ergebnis gerechnet. Holdout zu. Bericht `../reports/s7_count_2026-10-26T0938Z.md` |
| Anlass | Uzi 26.10.2026, 01:38 Ortszeit: „Ich möchte eine Strategie die mir 3-4R bringt pro Trade“; „go“ 10:49 Ortszeit. Bauplan: `/mnt/project-files/plaene/s7-3-4r-trendfolge-bauplan.md` |
| Lesart des Ziels | **Ziel je Gewinntrade 3 R bzw. 4 R** (Gewinn = Drei- bzw. Vierfaches des Anfangsrisikos). Nicht: Erwartungswert 3–4 R je Trade über alle Trades. Bei Erfolg liegt der Erwartungswert einer solchen Strategie typisch bei +0,2 bis +0,5 R je Trade |
| Protokoll | `../PROTOKOLL.md` Version **1.2** (Stand dieses Branches). Version 1.3 aus PR #428 enthält nur S6-Ausnahmen (A1–A5), die laut Wortlaut für S6-artige Maker-Studien gelten und für S7 nicht zitiert werden. S7 braucht **keinen neuen Protokoll-Eintrag**; die Abweichungen in 5.5 sind alle strenger |
| Register | `../REGISTER.jsonl`: 48 Einträge in diesem Branch, 54 nach Merge von PR #428 (S6). m = Zahl der `register`-Zeilen (jede Variante hat zusätzlich eine `status`-Zeile). Nach dem Gate bringt S7 **2** Varianten (D20-T3, D20-T4 → 56 von 60); **für alle Rechnungen gilt m = 60**. Registrierung (P4) erst nach Merge von #428 und Uzis Karte |
| Branch / PR | `claude/project-thread-0yalj1-s7` (ab platform-main 90f4b64), PR folgt |
| Vorgänger | S4 (NICHT TESTBAR), S5 (NICHT TESTBAR), S6 (NICHT BESTANDEN): Ziele 75 % und 95 % Trefferquote nicht erreichbar, siehe Abschnitt 2.3 |

## 1. Fragestellung

Hat ein regelbasierter Ausbruchseinstieg in Trendrichtung auf 4h-Kerzen von BTC/ETH/SOL (USD-M Perpetual) mit festem
Ziel von 3 bzw. 4 R und Stop 1 R nach allen Kosten einen positiven Erwartungswert, der sich von zufälligen
Einstiegen gleicher Geometrie unterscheidet? Vorab festgelegt: Regeln, Varianten, Kriterien, Zufallsvergleiche, Gate.

## 2. Ausgangslage und Rechnung

### 2.1 Gewinnschwelle bei großem Ziel (Rechenhilfe, kein Kriterium)

Für einen Trade mit nur zwei Ausgängen (Ziel oder Stop) gilt: Treffer bringt T − c_w, Verlierer kostet 1 + c_l
(R-Einheiten; c = Kosten in R). E = p·(T − c_w) − (1 − p)·(1 + c_l) > 0 ⇔ **p > p* = (1 + c_l) / (1 + T + c_l − c_w)**.

Kosten nach Protokoll 4.4 (alles Taker): Einstieg 0,05 % + 0,03 %, Ausstieg am Ziel 0,05 % + 0,03 %, Ausstieg am Stop
0,05 % + 0,05 %. Roundtrip Gewinner 0,16 %, Verlierer 0,18 % des Nominals, ohne Funding (bis zu 15 Funding-Zeitpunkte
in 5 Tagen; bei 0,01 % je 8 h und Stop 2,5 % ≈ 0,06 R zusätzlich, in der Simulation historisch gebucht). In R hängt
das vom Stopabstand ab:

| Stopabstand (1 R) | c_w | c_l | p* bei T = 3 | p* bei T = 4 |
|---:|---:|---:|---:|---:|
| 1,0 % (Kostentor, Minimum) | 0,160 R | 0,180 R | 29,4 % | 23,5 % |
| 2,5 % (Rechenbeispiel) | 0,064 R | 0,072 R | 26,7 % | 21,4 % |

**Was p* nicht sagt:** Die Trades dieser Studie haben einen dritten Ausgang, den Zeitstop nach 30 Kerzen, mit
Zwischenergebnissen zwischen −1 und +T R. Damit ist p* keine Hürde für die Trefferquote: Eine Strategie kann mit
Trefferquote unter p* positiven Erwartungswert haben (Zeitstop-Gewinne) und umgekehrt. Nach einer Monte-Carlo-Rechnung
der Prüfung (driftfreier Zufallsweg, 1 R ≈ 1,8–2,4 Kerzenstandardabweichungen, Annahme) trifft ein zufälliger Einstieg
das Ziel in etwa 15–23 % (T = 3) bzw. 7–14 % (T = 4) der Fälle, 7–30 % enden im Zeitstop. **Der Vergleich mit Zufall
läuft deshalb über den Erwartungswert (K2), nicht über die Trefferquote.** Trefferquote, p* mit dem tatsächlichen
Stopabstand und die Trefferquoten aller Zufallsvergleiche werden berichtet (K6).

### 2.2 Was ein Erfolg brächte

Bei Trefferquote 35 % und T = 3 (Stop 2,5 %, nur Ziel/Stop): E ≈ 0,35·2,94 − 0,65·1,07 = **+0,33 R je Trade**.
Bei 30 %: +0,13 R. Bei 40 % und T = 4: +0,93 R. Die Streuung je Trade ist groß (≈ 1,6–2,0 R), darum braucht der
Nachweis viele Trades (6).

### 2.3 Befunde aus dem Labor, die S7 berühren (nicht neu gerechnet)

- **R4, Hypothese M1 (Donchian-Ausbruch auf Tageskerzen BTC, N ∈ {20, 55}, Stop 2–3 × ATR, Ausstieg am Gegenkanal
  oder nach 20 Tagen):** E[R] im Training +0,02 bis +0,58 R, in der Validierung +0,19 bis +0,44 R, PF 1,4–1,8, aber nur
  19–35 Trades je Abschnitt → `failed_train` (Mindesttrades, p ≥ 0,10). Die Idee zeigte große R je Trade, nur zu
  selten für einen Nachweis. **S7 ist dieselbe Idee auf 4h, drei Instrumenten und mit festem Ziel.** Das macht
  Tageskerzen-Ergebnisse von BTC 2020–2024 zu „gesehenen“ Daten (10).
- **R4, L1 (Trendfolge SMA 100–200, Tageskerzen BTC):** E[R] +0,8 bis +2,5 R im Training (Validierung +0,4 bis
  +2,5 R), 14–61 Trades, `failed_validation`/`failed_train`. Der SMA-200-Filter von S7 ist damit auf Tageskerzen BTC
  gesehen.
- **S4-Erkundung (1h, Ziel 0,75 R, 10 Regeln inkl. Trend-Rücksetzer H4) und S4-Trefferquote-95-Raster (210 Zellen,
  1h BTC/ETH/SOL, Stop 1–4 × ATR):** alle E[R] negativ, Treffer 38–53 %.
- **S6 (1m, Maker-Mean-Reversion, Ziel 0,15–0,25 R):** Treffer 72–82 % gleich der Zufalls-Baseline, E[R] negativ.
- Gesamtbild: 68 registrierte Varianten (48 R4, 10 S4, 4 S5, 6 S6) ohne nachgewiesenen Vorsprung. Die ehrliche
  Vorab-Erwartung für S7 ist „kein Vorsprung“; M1 war positiv, aber unbewiesen.

### 2.4 Ausgeschlossen (vorab)

Trailing-Stops, Teilschließungen, Nachkäufe, Pyramiden, Parameter-Raster über Stop, Zeitstop, Filterlänge oder
Zielfaktor jenseits von T ∈ {3, 4}, Optimierung nach dem Gate, Maker-Fills (Protokoll 4.4 bleibt), andere
Instrumente als das Universum.

## 3. Daten und Datenherkunft

- **Kerzen:** USD-M Perpetual 4h-Klines BTCUSDT, ETHUSDT, SOLUSDT, Monatsarchive von data.binance.vision
  (`futures/um/monthly/klines/<SYM>/4h`), je gegen die offizielle Prüfsumme geprüft, Hash je Datensatz
  (`ArchiveStore.dataset_hash`). Archive: BTC/ETH ab 2020-01, SOL ab 2020-09 (Vorlauf; gezählt ab 2020-10, erster
  vollständiger Monat), bis 2024-12. **Holdout ab 2025-01: wird nicht geladen** (Loader verweigert).
- **Funding:** 8h-Fundingraten USD-M je Instrument (gleiche Archive wie S4/S6).
- **Abschnitte (Protokoll 3.2):** Training bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31, Holdout ab
  2025-01-01 bis zum letzten vollständigen Monat vor dem Holdout-Lauf (Protokoll 3.2; die Hochrechnung in 6.1 rechnet
  als Untergrenze mit 21 Monaten 2025-01 bis 2026-09 = 63 Coin-Monate, ≈ 91 Kalenderwochen). Abschnittsregel 1.2: Ein
  Trade zählt zum Abschnitt seines Signals nur, wenn sein Ausstieg spätestens am Abschnittsende feststand; sonst zählt
  er in keinen Abschnitt und wird als „offen T/V“ ausgewiesen.
- **Lücken (Protokoll 3.1):** Fehlende 4h-Kerzen werden gezählt und gelistet. Die Engine schließt einen offenen Trade
  bei **jeder** fehlenden Kerze zum letzten Schlusskurs vor der Lücke (`gap`, Slippage 0,03 %); ein Signal, dessen
  Einstiegskerze fehlt, verfällt (`invalid`, gezählt). Indikatoren überspringen Lücken nicht: Fehlt eine Kerze in den
  letzten max(200, N + 1) Kerzen, entsteht an diesem Schluss kein Signal (eigene Prüfung in `hypotheses/s7.py`,
  gezählt als `skipped_gap`; Baselines nehmen nur Vergleichskerzen mit lückenlosem ATR-Fenster).
- **Vorlauf:** Indikatoren dürfen Kerzen vor Abschnittsbeginn nutzen (SMA 200 braucht 200 Kerzen ≈ 33 Tage); die
  ersten Signale von BTC/ETH fallen daher ab Februar 2020, von SOL ab Mitte Oktober 2020.
- Universum und Survivorship: Protokoll 3.1 (`UNIVERSE_LIMITATION`) steht in jedem Bericht. Bekannte Grenze des
  Holdouts 2025/26 wie S4 3.1: Die Jahre sind als Marktphase allgemein bekannt; die Regeln von S7 wurden ohne Blick auf
  4h-Kurse dieser Jahre festgelegt, mehr lässt sich nicht garantieren.

## 4. Hypothesen-Register (wird mit Version 1.0 eingefroren)

### 4.1 Gemeinsame Regeln aller S7-Varianten

Alle Größen aus **geschlossenen** 4h-Kerzen. Kerze t ist die zuletzt geschlossene. Umsetzung `hypotheses/s7.py`,
Lauf über `backtest.engine.run_backtest` mit `gap_entry_as_loss=True` und `atr_at_signal`.

- **Indikatoren.** SMA200_t = Mittel der Schlusskurse t−199 … t. ATR14_t = Mittel der True Range der Kerzen
  t−13 … t (True Range = max(high − low, |high − close_{−1}|, |low − close_{−1}|)). Kanal: HH_N(t) = höchstes Hoch,
  LL_N(t) = tiefstes Tief der Kerzen t−N … t−1 (**ohne** Kerze t).
- **Signal am Schluss von Kerze t.** Long, wenn close_t > HH_N(t) **und** close_t > SMA200_t. Short, wenn
  close_t < LL_N(t) **und** close_t < SMA200_t. Beides zugleich ist unmöglich. Die Regel ist zustandslos: Jede Kerze,
  die sie erfüllt, erzeugt ein Signal. Ist in diesem Instrument ein Trade der Variante offen, wird das Signal gezählt
  (`ignored_signals`), nicht gehandelt.
- **Stop (am Signal festgelegt).** 1 R₀ = max(1,5 × ATR14_t, 1,0 % von close_t) (Kostentor wie S4, Protokoll 4.3).
  Long: Stop = close_t − R₀; Short: Stop = close_t + R₀. Der Stop ist ein fester Kurs.
- **Einstieg.** Eröffnungskurs der Kerze t+1 mit Slippage 0,03 % in Handelsrichtung (Taker-Gebühr 0,05 %). Kein Limit,
  kein Durchhandel. **1 R = |Einstiegsfill − Stop|** (tatsächlicher Abstand, weicht um die Eröffnungslücke von R₀ ab);
  Ziel = Einstieg ± T·R. Öffnet Kerze t+1 auf oder jenseits des Stops, wird der Trade als voller Verlust gebucht
  (−1 R minus Stopkosten, `stop_before_entry`, Engine `gap_entry_as_loss`), nicht verworfen: Ein Verwerfen wäre eine
  Auswahl auf die Zukunft.
- **Ausstieg** (Protokoll 4.2, Engine `exit_on_bar`): Öffnet eine Kerze jenseits des Stops → Ausstieg zur Eröffnung
  (`stop_gap`); jenseits des Ziels → zur Eröffnung (`target_gap`). Sonst Stop, wenn Tief ≤ Stop (Long), Fill zum Stop
  mit Stop-Slippage 0,05 % und Taker-Gebühr; Ziel, wenn Hoch ≥ Ziel, Fill zum Ziel mit Taker-Gebühr und Slippage
  0,03 %. **Berühren Stop und Ziel dieselbe Kerze, gilt der Stop.** Zeitstop: kein Ausstieg bis zum Schluss der
  30. Kerze (Einstiegskerze = 1, also 5 Tage) → Ausstieg zu deren Schlusskurs (Taker + Slippage). `gap` und
  Abschnittsende nach Abschnitt 3. Ausstiegsgründe: `stop`, `stop_gap`, `stop_before_entry`, `target`, `target_gap`,
  `time`, `gap`.
- **Wiedereinstieg.** Die Engine schließt in Kerze t vor der Signalprüfung. Ein neues Signal ist daher frühestens am
  Schluss derselben Kerze t möglich, in der der Ausstieg lag (Einstieg t+1); nach einem Zeitstop frühestens 30 Kerzen
  nach dem vorigen Signal. Keine weitere Sperre. Im Trend sind Serien von Wiedereinstiegen wahrscheinlich; sie hängen
  zusammen (Wochencluster, 5.2).
- **Funding.** Jeder Funding-Zeitpunkt f (00/08/16 UTC) mit Einstieg ≤ f < Ausstiegsmoment wird mit historischer Rate
  gebucht, Vorzeichen nach Seite; Stress: nie zugunsten des Trades (Protokoll 4.4).
- **Netto-R** je Trade = (Richtung · (Ausstieg − Einstieg) · q − Gebühren − Funding) / (R · q); Slippage steckt in
  den Fills. **Treffer** = Ausstiegsgrund `target`/`target_gap` und Netto > 0 (bei T ≥ 3 praktisch gleichbedeutend
  mit „Ziel erreicht“). Alle Ausstiegsgründe zählen in allen Kriterien.
- Eine Position je Variante und Instrument; Long und Short gehören zur selben Variante. Kein Hebel-Raster, keine
  Positionsgröße (Ergebnisse in R).

### 4.2 Varianten

Zwei geordnete Parameter, keine weiteren: Kanallänge N (4h-Kerzen) und Ziel T (R).

| Variante | N | T | Begründung |
|---|---|---|---|
| S7-D20-T3 | 20 (≈ 3,3 Tage) | 3 R | häufigste Signale; Turtle-Konvention (M1) |
| S7-D20-T4 | 20 | 4 R | |
| S7-D55-T3 | 55 (≈ 9 Tage) | 3 R | seltenere, längere Ausbrüche (M1) |
| S7-D55-T4 | 55 | 4 R | |

Vier Varianten. Alle Varianten, die das Gate (6.1) bestehen, kommen ins Register, auch wenn sie später verworfen
werden (m sinkt nie). Es gibt keine weiteren S7-Varianten. Die Rücksetzer-Variante aus dem Bauplan ist gestrichen
(Register-Plätze, Überschneidung mit S4-H4).

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

0. **Machbarkeits-Gate vor der Registrierung** (6.1).
1. **Training:** E[R] > 0 (Basis-Kosten), **≥ 200 Trades** gepoolt über drei Instrumente **und** ≥ 100 Signal-Wochen
   (6), p < 0,10 gegen Zufall A (Protokoll 7.1) **und** p < 0,10 gegen Zufall A′ (volatilitätsangepasst, 7).
2. **Validierung (24 Monate):** ≥ 100 Trades und ≥ 50 Signal-Wochen, E[R] > 0, p < 0,05 gegen A und A′,
   Profitfaktor > 1,1, Drawdown ≤ K4, alle Robustheitsregeln (5.4).
3. **Kandidatenliste einfrieren:** höchstens **zwei** Varianten, je Ziel T höchstens eine, gewählt nach dem höchsten
   E[R] in der Validierung (keine weitere Wahl); mit Hash und Protokollversion committen, bevor Holdout-Daten geladen
   werden.
4. **Holdout,** genau ein Lauf, nur nach Uzis Entscheidung per Entscheidungskarte (8).

### 5.2 Urteil im Holdout

| # | Bedingung | Schwelle |
|---|---|---|
| K1 | Netto-Erwartungswert (Basis-Kosten) | > 0 R je Trade |
| K2 | schlägt den Zufallsvergleich A (Protokoll 7.1) auf E[R] | Holm-Bonferroni, Familien-α 5 %, m = 60 (verworfene mit p = 1) |
| K3 | Mindeststichprobe (drei Instrumente zusammen), **ergebnisfrei** | ≥ 100 Trades **und** ≥ 60 Signal-Wochen (ISO-Kalenderwochen der Signalkerze mit mindestens einem gehandelten Signal, über alle Instrumente); darunter **KEIN URTEIL** |
| K4 | maximaler Drawdown der R-Kurve (1 % Risiko je Trade, Protokoll 4.3) | ≤ **20 R** (Protokoll K4: 20 % bei 1 % Risiko) |
| K5 | Profitfaktor netto | > 1,0 |
| K6 | Trefferquote (Treffer = Ziel erreicht und Netto > 0) | **berichtet, kein Kriterium** (2.1): Punktwert, einseitige 95-%-Untergrenze (Clopper-Pearson mit n_eff = ⌊n / D⌋ und Nicht-Treffer_eff = ⌈(n − Treffer) / D⌉, D = Designeffekt der Treffer-Indikatoren über das Wochencluster), p* mit dem tatsächlichen mittleren Stopabstand, Trefferquoten der Baselines A, A′, B, C |
| K7 | Stress (Protokoll 4.4: Gebühren und Slippage ×2, Funding nie zugunsten) | E[R] > 0 |
| K8 | keine versteckten Großverluste | größter Einzelverlust ≥ −2,0 R; mittlerer Verlust ≥ −1,2 R; `stop_gap` + `stop_before_entry` ≤ 10 % der Trades; `time` + `gap` zusammen ≤ 50 % der Trades |
| K9 | Treffer liefern das Ziel netto (Lesart des Ziels) | mittleres Netto-R der Treffer ≥ T − 0,5 R |
| K10 | Breite | jedes Instrument ≥ 15 % der Trades; **berichtet, kein Kriterium:** Anteil je Seite (hängt vom Marktregime unter dem SMA-200-Filter ab), E[R] je Instrument und Seite; **Long-Trades zusätzlich gegen Kaufen-und-Halten im selben Zeitraum** (Protokoll 5) |

Urteile: **BESTANDEN (Holdout)** (K1–K5, K7–K10), **NICHT BESTANDEN**, **KEIN URTEIL** (K3 verfehlt).
BESTANDEN (Holdout) ist nicht das Protokoll-K5 (Papier-Betrieb, Abschnitt 9): Das wäre ein eigener Schritt nach Uzis
Entscheidung. Masterprompt-Vokabular: PASS / FAIL / INCONCLUSIVE. Berichtet, kein Kriterium: alle Kennzahlen der
Zufallsvergleiche A, A′, B, C; Verteilung der Haltedauern; Anteile der Ausstiegsgründe; mittlerer Stopabstand in %;
ignorierte Signale; Designeffekt D und n_eff; Monatsblock-Bootstrap des E[R] (Protokoll 5); SPA/StepM.

### 5.3 Kosten (Protokoll 4.4, unverändert) und Stress

| Posten | Basis | Stress |
|---|---|---|
| Taker-Gebühr je Fill | 0,05 % | 0,10 % |
| Slippage Einstieg, Ziel, Zeitstop, `gap` | 0,03 % | 0,06 % |
| Slippage Stop | 0,05 % | 0,10 % |
| Funding | historisch | nie zugunsten |
| Roundtrip Gewinner / Verlierer | 0,16 % / 0,18 % des Nominals | 0,32 % / 0,36 % |

Keine Abweichung vom Protokoll. Ein Test je Ausstiegsgrund belegt vor dem Trainingslauf: Richtung · Kursdifferenz · q
− Gebühren − Funding = Netto (Engine `run_backtest`, bestehend seit R4; S7 fügt keine eigene Kostenrechnung hinzu).

### 5.4 Robustheit (Protokoll 7.3)

- Jahresstabilität: E[R] > 0 in mindestens 60 % der Kalenderjahre mit ≥ 20 Trades (Training + Validierung; strenger
  als Protokoll ≥ 5).
- Walk-Forward: 24 Monate Anpassung / 6 Monate Test, Auswahl über alle vier Varianten nach E[R], in der Anpassung nur
  Trades mit Ausstieg bis Fensterende (`known_at`). Verketteter Test-Erwartungswert > 0. Scheitert der Walk-Forward,
  ist S7 für den Holdout gesperrt.
- Nachbarschaft: Jede Kandidatin braucht E[R] > 0 im Training bei allen direkten Nachbarn (gleiches T, anderes N;
  gleiches N, anderes T). Ein Nachbar, der das Gate nicht bestand, wird für diese Prüfung trotzdem auf Training
  gerechnet (nicht registriert, nicht für den Holdout). Das ist nur ein Veto, kein Leck: Es kann Varianten nur
  ausschließen.
- SPA/StepM wird berichtet, ist kein Kriterium.

### 5.5 Abweichungen vom Protokoll 1.2

Keine Lockerung. Vom Protokoll abweichend, jeweils strenger oder Klarstellung (kein Eintrag nötig):

- **Horizont.** Signale auf 4h-Kerzen, Haltedauer Stunden bis 5 Tage. Das Protokoll kennt Mid (Tageskerzen) und
  Short (Minuten bis Stunden). S7 wird nach der Haltedauer als **Mid** geführt (Mindesttrades Protokoll: Training ≥ 50,
  Holdout ≥ 30); die Schwellen hier (200 / 100 / 100) sind strenger. Würde S7 als Short gelten (Holdout ≥ 200), wäre
  „Holdout ≥ 100“ eine Lockerung; die Einordnung ist eine Festlegung dieses Entwurfs, offen für Uzis Wort (O3).
- Zufallsvergleich A′ (7) als zweite Vorauswahl; Baseline C (7) berichtet.
- Signal-Wochen als ergebnisfreie Clusterzahl in K3 und im Gate; Designeffekt D nur im Bericht (K6).
- m = 60 statt der tatsächlichen Registergröße 58 (strenger).
- Jahresstabilität mit ≥ 20 statt ≥ 5 Trades je Jahr.
- Baseline A: Vergleichskerzen nur so, dass jeder Zufallstrade vor dem Abschnittsende enden kann (7).

## 6. Mindeststichprobe, Power und Gate

Streuung je Trade bei T = 3: Treffer +2,9 R, Verlierer −1,1 R, Zeitstops dazwischen → Standardabweichung
≈ 1,7 R (T = 4: ≈ 2,1 R). Standardfehler des Mittels bei n Trades ≈ 1,7/√n. Hilfsrechnung für E > 0 als einseitiger
Test (p < 0,05) und für K2 (Holm 0,05/60, z ≥ 3,14), jeweils unter der Annahme Baseline-E = 0:

| n | SE (T = 3) | z bei wahrem E = +0,30 R | Power E > 0 (p < 0,05) | Power K2 | Power K2 bei E = +0,50 R |
|---:|---:|---:|---:|---:|---:|
| 100 | 0,17 | 1,8 | ≈ 55 % | ≈ 8 % | ≈ 42 % |
| 150 | 0,14 | 2,2 | ≈ 70 % | ≈ 16 % | ≈ 68 % |
| 200 | 0,12 | 2,5 | ≈ 80 % | ≈ 26 % | ≈ 85 % |
| 300 | 0,10 | 3,1 | ≈ 92 % | ≈ 47 % | ≈ 97 % |
| 500 | 0,08 | 3,9 | ≈ 99 % | ≈ 79 % | > 99 % |

Die Baseline A liegt wegen der Kosten eher bei −0,1 R als bei 0; die K2-Power ist dann höher als in der Tabelle (bei
n = 150 grob 40 %). Die Clusterung (Trades in derselben Woche an drei Instrumenten, Serien im Trend) senkt die Power
wieder; D wird gemessen und berichtet.

**Offengelegt:** Der Holdout 2025-01 bis 2026-09 hat 63 Coin-Monate. Mit geschätzt 1,5–2,5 Signalen je Coin-Monat
(N = 20, Vorab-Schätzung ohne 4h-Daten, Obergrenze 6 bei durchgehender Sperre) ergibt das 95–160 Holdout-Trades: K2
hat dann selbst bei einer echten Strategie mit +0,3 R nur etwa 10–25 % Chance. Ein positiver, aber nicht
signifikanter Holdout heißt **NICHT BESTANDEN**, nicht „fast“. Uzi muss das vor der Freigabe wissen (O3). Der Weg zu
mehr Power wäre ein längerer Holdout (später) oder Papier-Betrieb nach einem Holdout mit E > 0.

**Schwellen:** Training ≥ 200 Trades und ≥ 100 Signal-Wochen (von ≈ 150 Wochen); Validierung ≥ 100 Trades und ≥ 50
Signal-Wochen (von 104); Holdout ≥ 100 Trades und ≥ 60 Signal-Wochen (von ≈ 91, K3). Die Trainingsschwelle 200
entspricht einer Power von ≈ 80 % für E > 0 bei +0,3 R; mit der Vorab-Schätzung (Training 99 Coin-Monate × 1,5–2,5 =
150–250) ist **das Gate unsicher, ein Scheitern („nicht testbar“) nach eigener Schätzung möglich.** Die Schwellen
werden deshalb vor dem Zähllauf festgeschrieben und danach nicht gesenkt.

### 6.1 Machbarkeits-Gate (vor Registrierung, ergebnisblind bezüglich R)

Ein Zähllauf auf Training und Validierung zählt je Variante und Instrument die **Signale nach 4.1** (Kanal, SMA-Filter,
Lückenregel). Der Zähler kennt weder Stop noch Ziel noch Kurse nach dem Signal: Er nimmt konservativ an, dass jeder
Trade den Zeitstop erreicht (Sperre bis einschließlich Kerze t+29, nächstes Signal frühestens t+30, wie die Engine),
und berichtet zusätzlich die Zahl ohne Sperre als Obergrenze. Er zählt außerdem Signal-Wochen (ISO-Wochen der
Signalkerze mit mindestens einem Signal der unteren Zählung, über alle Instrumente). Hochrechnung aus dem
**schwächsten Kalenderjahr, gepoolt über die drei Instrumente**, für jede Größe getrennt gewählt: Signale je Coin-Monat
× 63; Signal-Wochen je Kalendermonat × 21.

- Variante mit Training ≥ 200 Signalen (untere Zählung) und ≥ 100 Signal-Wochen, Validierung ≥ 100 Signalen und ≥ 50
  Signal-Wochen, hochgerechnet ≥ 100 Holdout-Signalen **und** ≥ 60 Holdout-Signal-Wochen → wird registriert.
- Sonst → wird nicht registriert, im Bericht mit Zahlen genannt.
- Besteht keine Variante → **S7 ist nicht testbar**, Ende ohne Register-Eintrag und ohne Trainingslauf. Keine
  Lockerung im selben Entwurf.

**Ergebnis des Zähllaufs (26.10., Commit 2a9d3be, Hash 9ac4d135…, `../reports/s7_count_2026-10-26T0938Z.md`):**

| Variante | Training (untere Zählung / Wochen) | Validierung | Holdout hochgerechnet (Signale / Wochen) | Gate |
|---|---:|---:|---:|---|
| S7-D20-T3, S7-D20-T4 | 341 / 138 | 260 / 102 | 196,0 / 70,0 | **bestanden** |
| S7-D55-T3, S7-D55-T4 | 263 / 121 | 203 / 95 | 145,2 / **59,5** | nicht bestanden (Wochen-Schwelle 60) |

Die D55-Varianten scheitern um eine halbe Woche an der vorab festgelegten Wochen-Schwelle; nach der Regel oben werden sie
nicht registriert und nicht gelockert. Sie werden nach 5.4 nur als Nachbarn auf Training gerechnet. Die Vorab-Schätzung
(1,5–2,5 Signale je Coin-Monat) war zu niedrig: gemessen 3,1–3,4 (D20) bzw. 2,3–2,7 (D55) je Coin-Monat. Lücken: SOL
2020-09 (Listungsmonat, 79 Kerzen), 2022-02 (18), 2022-04 (12); 31 (D20) bzw. 19 (D55) SOL-Signale im Training wegen
Lücken im Indikatorfenster nicht erzeugt.

Das Gate liest Kurse bis zum Signal und ist deshalb nur bezüglich der Ergebnisse blind; Marktrichtung und Signaldichte
sind sichtbar. Darum: **Der Regelstand (Commit) wird vor dem Zähllauf festgehalten; jede Änderung an N, SMA, ATR,
Zeitstop, Stop, Ziel oder Filter nach dem Zähllauf ist eine neue Studie, keine Fassung 1.0 von S7.** Der Zählbericht
nennt keine Seitenanteile. Die Zählung wird mit Commit und Datensatz-Hash festgehalten, bevor irgendein Ergebnis
gerechnet wird.

## 7. Zufallsvergleiche (Baselines)

Alle Baselines nutzen dieselben Ausstiegsregeln (Stop, Ziel T, Stop gewinnt, `gap`) und dieselben Kosten wie die
Variante, damit nur der Einstieg verglichen wird. 10 000 Läufe, Seed **20261101**. Umsetzung `studies/s7_eval.py`
auf `stats/random_entry.py`.

- **A (K2, Protokoll 7.1 in der Umsetzung des Labors, je Instrument gepoolt):** je Variante und Abschnitt 10 000
  Zufallsstrategien. Je Instrument so viele Zufallstrades wie echte Trades der Variante in diesem Instrument; je
  Zufallstrade werden **Seite, Stopabstand in ATR-Einheiten, Ziel T und maximale Haltedauer gemeinsam** aus einem
  zufällig gewählten echten Trade des Instruments gezogen (so rechnet `random_entry` seit R4: die Haltedauer des
  echten Trades begrenzt den Zufallstrade wie ein Zeitstop; der Stopabstand wird mit dem ATR14 der Zufallskerze
  skaliert, das 1-%-Tor steckt in den gezogenen ATR-Einheiten). Einstiegskerze gleichverteilt über die Kerzen des
  Abschnitts mit lückenlosem ATR-Fenster, mindestens 31 Kerzen vor Abschnittsende (damit der Zufallstrade vor dem
  Abschnittsende enden kann, Abschnittsregel). Einstieg zur Eröffnung der Folgekerze. Überlappung erlaubt.
  Monte-Carlo-Pool je Instrument (≥ 50 × n, ≥ 5 000, Protokoll-Eintrag 2026-09-29 (a)). Gepoolter
  p = (1 + Läufe mit gepooltem E[R] ≥ Variante) / 10 001. Nullhypothese: „Ein Einstieg nach Kanalausbruch in
  Trendrichtung hat keinen besseren Erwartungswert als ein zufälliger Einstieg gleicher Geometrie und Kosten.“
  Zufällige Long-Einstiege im steigenden Markt haben selbst positiven Erwartungswert; K2 verlangt mehr als die
  Marktdrift. A zieht Long/Short ohne Trendzustand, prüft also Ausbruch **und** Trendfilter zusammen.
- **A′ (Vorauswahl in 5.1, berichtet im Holdout):** wie A, aber je echtem Trade werden Vergleichskerzen nur aus
  demselben Instrument, demselben Abschnitt und demselben **ATR14/Kurs-Dezil** der Signalkerze gezogen, und die
  Vorlage (Seite, Stop, Haltedauer) aus den echten Trades desselben Dezils (Pool-Methode: je Dezil 2 000
  Vergleichstrades einmal gerechnet). Verhindert, dass K2 Volatilität statt Einstieg misst.
- **C (berichtet):** wie A, aber die Einstiegskerze wird nur aus Kerzen mit demselben SMA-200-Trendzustand wie die
  Seite der Vorlage gezogen (Long nur bei close > SMA200, Short nur bei close < SMA200). Trennt den Beitrag des
  Ausbruchs vom Beitrag des Trendfilters.
- **B (berichtet):** dieselben Signale in **Gegenrichtung** (Fade des Ausbruchs), gleicher Stopabstand, Ziel T,
  Zeitstop 30 Kerzen, gleiche Kosten.
- **Kaufen-und-Halten** (Protokoll 5, Long, je Instrument und Abschnitt, berichtet).
- Berichtet: Trefferquoten und E[R] aller Baselines neben denen der Variante; Monatsblock-Bootstrap (10 000
  Ziehungen) als Konfidenzintervall des E[R].

## 8. Holdout-Freigabe

Der Holdout ab 2025-01 wird nur nach Uzis ausdrücklichem Wort geöffnet, abgefragt per Entscheidungskarte vor dem
Lauf. Die Karte nennt Kandidatenliste (Hash), m, Protokollversion, die K2-Power aus Abschnitt 6 und den Ablauf.
Ein Lauf, danach ist der Holdout für S7 und für alle Registereinträge verbraucht; auch ein KEIN URTEIL verbraucht ihn.

## 9. Arbeitspakete

| # | Paket | Prüfbefehl |
|---|---|---|
| P1 | Entwurf 0.1 → adversariale Prüfung (anderes Modell) → 0.2 | Befunde im Änderungsprotokoll |
| P2 | 4h-Klines USD-M BTC/ETH/SOL 2020–2024 und Funding auf dem Mac laden (`scripts/research_lab_s7.py fetch`), Lücken, Hash | Fetch-Protokoll, Hash im Gate-Bericht |
| P3 | Code: `hypotheses/s7.py` (Indikatoren, Signal, Varianten, ergebnisblinder Zähler), Lauf über `backtest.engine.run_backtest`, Baselines A/A′/B/C, Kennzahlen/Urteil in `studies/s7_eval.py`; Tests: Kanal ohne Kerze t, SMA-Filter, Signal nur auf geschlossenen Kerzen, Einstieg nächste Eröffnung, Stop-Minimum 1 %, Ziel T·R, Stop gewinnt, Zeitstop Kerze 30, Lücken, Funding, Kosten je Ausstiegsgrund, Zähler gegen Engine-Signale | `pytest tests/test_research_lab_s7*.py tests/test_research_lab_clustered.py` grün |
| P4 | ~~Zähllauf 6.1 auf dem Mac~~ erledigt 26.10. (Commit 2a9d3be, Hash 9ac4d135…, 2 von 4 Varianten bestehen); Entscheidungskarte: Freigabe 1.0 + Registrierung D20-T3/D20-T4 (54 → 56, nach Merge #428) + Kenntnisnahme K2-Power | `../reports/s7_count_2026-10-26T0938Z.md` |
| P5 | Training/Validierung, Baselines, Stress, Robustheit; Register-Status; Bericht `s7_train_<stamp>.md` | K1–K10, 5.4 |
| P6 | Holdout, genau ein Lauf, nur per Entscheidungskarte, nur mit Kandidatin | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

- R4-Bericht (`../reports/r4_2026-09-29T2219Z.md`): M1 Donchian und L1 SMA-Trendfolge auf **Tageskerzen BTC**
  2020–2024 mit E[R], PF und Tradezahlen (2.3); Kaufen-und-Halten BTC (Training +253 %, Validierung +466 %), also die
  Marktrichtung beider Abschnitte. **BTC 2020–2024 gilt für Donchian- und SMA-Regeln auf Tageskerzen als gesehen**;
  ETH und SOL sowie 4h-Kerzen aller drei Instrumente wurden für diese Regeln nie gerechnet. Die Parameter N 20/55
  stammen aus M1 (Turtle-Konvention), SMA 200 aus L1, nicht aus einem Blick auf 4h-Daten.
- S4-Erkundung (`s4_explore`, 1h BTC/ETH/SOL 2020–2024, 10 Regeln inkl. Trend-Rücksetzer mit Tagesregime) und
  S4-Trefferquote-95-Raster (`s4_hitrate95`, 210 Zellen, Stop 1–4 × ATR): **2020–2024 gelten für S4-artige
  1h-Regeln als gesehen.** S5/S6 Abschnitt 10: Funding-Statistiken, 1m-Fills 2020–2024. Nichts davon rechnete
  4h-Ausbrüche.
- S1 (CPI-Studie, `s1_cpi_volatility.md`): 4h-Volatilitätsfenster um CPI-Termine auf BTC 2020–2024, nur
  Volatilität, keine Richtungsregel.
- SMA 200, ATR 14, Faktor 1,5, Zeitstop 30 Kerzen, Kostentor 1 % sind Konventionen bzw. aus S4 übernommen; T aus
  Uzis Ziel. Kein 4h-Kurs wurde für diesen Entwurf angesehen oder gerechnet.
- Holdout 2025+: nie geladen.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | ~~Adversariale Prüfung durch ein anderes Modell, Befunde einarbeiten (0.2)~~ erledigt 26.10. | Claude |
| O2 | ~~4h-Archive laden, Lücken und Hash berichten (P2); Zähllauf 6.1 (P4)~~ erledigt 26.10. | Claude, Mac |
| O3 | Uzis Wort per Entscheidungskarte: Lesart des Ziels (3–4 R je Gewinntrade), Horizont-Einordnung Mid (5.5), Kenntnisnahme der K2-Power (6), Freigabe 1.0 und Registrierung von S7-D20-T3 und S7-D20-T4 (→ 56) | Uzi |
| O4 | Holdout nur per zweiter Entscheidungskarte | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-26 | 0.1 | Erstfassung nach Bauplan; 4 statt 6 Varianten (Rücksetzer gestrichen), K2 = Protokoll 7.1 plus A′ als Vorauswahl, Wochencluster, Mindesttrades 300/150/100, K2-Power offengelegt | Uzis „go“ 10:49 | R4-Bericht (M1, L1), S4/S5/S6-Berichte; keine 4h-Kurse |
| 2026-10-26 | 0.2 | Adversariale Prüfung (anderes Modell, 23 Befunde): K4 25 → **20 R** (Protokoll); K6 nur noch berichtet (p* gilt nicht mit Zeitstop, Zufallstrefferquote 15–23 %/7–14 %, keine „2–4 Punkte“); K9 neu (Netto-R der Treffer ≥ T − 0,5) statt faktischem PF ≥ 1,5; K3 ergebnisfrei (Trades + Signal-Wochen statt n_eff aus Ergebnissen); K10 Seitenanteil nur berichtet; Stop als fester Kurs ab Signalschluss, R = Fill–Stop, `stop_before_entry` statt Verwerfen; Wiedereinstieg und Lücken wie Engine; Baseline A wie `random_entry` (gemeinsame Vorlage, Haltedauer, 31-Kerzen-Rand), Baseline C mit Trendzustand; Horizont Mid festgelegt und offengelegt; Gate 300/150 → 200/100 mit ehrlicher Vorab-Schätzung, Regelstand-Commit vor dem Zähllauf; Power-Tabelle korrigiert (n = 300: 92 %, E = 0,5 R: 42/68/85/97 %, Baseline-E < 0); Protokollstand 1.2/Register 48 im Branch, m = 60; Offenlegung ergänzt (S4-Erkundung, Hitrate-Raster, L1, Kaufen-und-Halten, S1-4h-Fenster, Holdout-Grenze); Zahlen 2.3 korrigiert (19–35 Trades, 68 Varianten) | Befunde der Prüfung | wie 0.1; keine 4h-Kurse |
| 2026-10-26 | 0.3 | Zähllauf 6.1 gerechnet und eingetragen: D20-T3/D20-T4 bestehen, D55-T3/T4 nicht (59,5 < 60 Holdout-Signal-Wochen); Register-Ziel 54 → 56; Vorab-Schätzung der Signaldichte als zu niedrig vermerkt. Keine Regeländerung | Gate-Ergebnis | zusätzlich: Signalzahlen des Zähllaufs (ergebnisblind, keine Kurse nach dem Signal, kein R) |
