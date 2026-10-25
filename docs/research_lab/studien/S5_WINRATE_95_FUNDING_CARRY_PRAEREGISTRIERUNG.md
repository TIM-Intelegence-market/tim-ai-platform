# Studie S5: Winrate ≥ 95 % mit positivem Netto-Erwartungswert durch Funding-Carry (Präregistrierung)

| Feld | Wert |
|---|---|
| Version | 0.1 (Entwurf) |
| Status | **ENTWURF.** Nichts ist gerechnet. Freigabe durch Uzi steht aus (Abschnitt 11). Varianten kommen erst nach dem Machbarkeits-Gate (6.1) ins Register. |
| Erstellt | 2026-10-25, Auftrag Uzi 18:38 Ortszeit: „ich will eine winrate von 95% haben“; Lesart streng und ohne zweite Familie auf Uzis Wort „ich agiere nach deiner empfehlung“ (18:51) |
| Vorgänger | S4 (`S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md`): am Machbarkeits-Gate beendet; Erkundungen zeigten für 1h-Richtungs-Einstiege 38–53 % Trefferquote und in jeder Ziel-/Stop-Geometrie E[R] < 0 (`../reports/s4_hitrate95_2026-10-25T1733Z.md`) |
| Protokollbezug | `../PROTOKOLL.md` Version 1.1: Datensplit 3.2, Kosten 4.4, Zufallsvergleich 7.1, Holm 7.2, Robustheit 7.3, Ablauf 8, Stoppregeln 10 |
| Kostenmodell | `CostModel` / `BASE_COSTS` / `STRESS_COSTS` aus `src/research_lab/protocol.py` für die Perp-Seite; für die Spot-Seite die neue Konstante `SPOT_FEE = 0,10 %` je Fill (Stress 0,20 %), Slippage wie `CostModel.slippage` (Abschnitt 5.3) |
| Bauplan | `/mnt/project-files/plaene/s5-winrate-95-bauplan.md` (Projektablage, 25.10. 19:45 Ortszeit) |

Was dieses Dokument nicht ist: kein Profitversprechen, keine Anlageberatung, keine Freigabe für Papier- oder Echtgeldbetrieb.
Das Ergebnis darf und wird wahrscheinlich **NICHT BESTANDEN**, **KEIN URTEIL** oder **NICHT TESTBAR** lauten (Abschnitt 2 und 6).

---

## 1. Fragestellung

Gibt es unter den unten vorab festgelegten Regeln eine Strategie, die auf Daten, die bei ihrer Auswahl nie benutzt
wurden (Holdout 2025+, genau ein Lauf), **gleichzeitig** erreicht: Netto-Trefferquote ≥ 95 % (strenge Lesart: korrigierte
Untergrenze), positiver Netto-Erwartungswert auch unter Stresskosten, Profitfaktor > 1, begrenzte Einzelverluste,
ausreichende Stichprobe und robuste Walk-Forward-Ergebnisse?

Die Trefferquote wird **nie allein** optimiert. Es gibt kein Raster über Ziel oder Stop, denn S5 hat weder Ziel noch
Stop: Ein Trade ist eine Carry-Episode, und gewonnen hat sie, wenn nach allen Kosten mehr Geld da ist als vorher.

## 2. Ausgangslage und Mathematik der 95 %

### 2.1 Was 95 % erzwingt

Bei 95 % Treffern bleibt pro 20 Trades ein Verlierer. Der mittlere Gewinn muss deshalb mindestens **1/19 des mittleren
Verlusts plus Kosten** betragen, sonst ist der Erwartungswert negativ. Für einen Zufallsweg ohne Kosten ist die Chance,
+T R vor −1 R zu treffen, 1 / (1 + T); 95 % entsprechen T = 0,053 R. **Die Trefferquote allein kann Zufall und Strategie
nicht unterscheiden.** Deshalb testet S5 den Zufallsvergleich (K2) auf dem Erwartungswert, nicht auf der Quote.

### 2.2 Befund aus S4 (heute, nicht neu gerechnet)

Die zehn 1h-Richtungs-Einstiege aus S4 lagen auf 2020–2024 in allen 210 Ziel-/Stop-Kombinationen **unter** der
Zufallsreferenz (höchstens 92 % bei E[R] < 0). Richtungs-Einstiege dieser Art sind kein Kandidat für 95 %.

### 2.3 Warum Funding-Carry (ökonomische Begründung)

Auf Binance USD-M zahlen alle 8 Stunden die Long-Seiten den Shorts eine Funding-Gebühr, wenn der Perpetual über dem
Spot-Index handelt (Rate = Zinsanteil 0,01 % + Prämie, geklemmt). Wer Spot long und denselben Betrag Perpetual short
hält, ist kursneutral und kassiert diese Gebühr. Der Gewinn je Periode ist klein und fast sicher; Verluste entstehen aus
Kosten, aus einer Bewegung der Basis (Spot minus Perpetual) während der Haltezeit und aus einer erzwungenen Schließung
der Short-Seite. Das ist die einzige in TIM mit vorhandenen Daten prüfbare Familie, bei der eine Trefferquote von 95 %
**je Trade** plausibel ist, ohne dass sie über unbegrenzte Verluste erkauft wird.

Vorprüfung am 25.10. (nur Funding-Archiv 2020–2024, nur Vorzeichen und Summen, keine Strategie gerechnet, Abschnitt 10):
Nach einer Periode mit Rate > 0,01 % ist die nächste Periode bei BTC und ETH in 99,9 % positiv und in 84 % (BTC) bzw.
87 % (ETH) wieder > 0,01 %. Jahressummen der Rate: BTC 17,2 / 30,6 / 4,2 / 7,9 / 12,0 % (2020–2024), ETH 27,5 / 37,5 /
0,8 / 8,3 / 13,0 %, SOL −4,0 / 28,6 / −38,0 / 1,3 / 13,7 %. 2022 ist dünn, SOL 2022 stark negativ. Nach Kosten von rund
0,42 % je Episode (5.3) kann S5 daran scheitern.

### 2.4 Ausgeschlossen

- „Halten bis grün“ ohne Stop und ohne Begrenzung: Die Quote entsteht dort nur aus unbegrenzten Verlusten (Masterprompt).
- Maker-Mean-Reversion mit weitem Stop: nach 2.2 Erwartung NICHT BESTANDEN, verbraucht Holdout-Plätze; auf Uzis Wort
  (18:51) nicht aufgenommen.

## 3. Daten und Datenherkunft

| Datensatz | Quelle | Zeitraum | Stand |
|---|---|---|---|
| USD-M Perpetual 1h-Kerzen BTCUSDT, ETHUSDT, SOLUSDT | data.binance.vision, monatliche Archive mit Prüfsumme (`src/research_lab/data/archive.py`) | BTC/ETH ab 2020-01, SOL ab 2020-09 (Warm-up), gezählt ab 2020-10 | geladen (S4) |
| USD-M Funding-Raten (alle 8 h) | wie oben, `Dataset.FUNDING` | wie oben | geladen (S4) |
| Spot 1h-Kerzen BTCUSDT | wie oben, `Market.SPOT` | ab 2020-01 | geladen (R-Studien) |
| Spot 1h-Kerzen ETHUSDT, SOLUSDT | wie oben; `archive.py` erlaubt Spot bisher nur BTC, Erweiterung Paket P2 | ETH ab 2020-01, SOL ab 2020-09 (Listing 2020-08-11) | **offen**, Mac |
| Holdout 2025+ | gesperrt durch `HoldoutLocked` in `data/store.py` | ab 2025-01-01 | nie geladen |

Funding-Zeitpunkte sind 00:00, 08:00 und 16:00 UTC. Die zum Zeitpunkt t gezahlte Rate r_t gilt als **ab t bekannt**;
S5 nutzt sie frühestens für einen Einstieg zur Eröffnung der Stundenkerze, die um t + 1 h beginnt (eine Stunde
Sicherheitsabstand). Bekannte Lücken in den SOL-Archiven (2022-02: 72 h, 2022-04: 48 h) werden übernommen; eine Episode,
die in eine Lücke läuft, wird zum letzten Kurs vor der Lücke geschlossen (`gap`, Protokoll 4.1) und zählt als Trade.

### 3.1 Zeitliche Aufteilung (unverändert aus Protokoll 3.2)

Training bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31, Holdout ab 2025-01-01 bis zum Ende des letzten vollen
Monats vor dem Lauf (bei einem Lauf im November 2026: 21 Monate), genau ein Lauf.

## 4. Hypothesen-Register (wird mit Version 1.0 eingefroren)

### 4.1 Gemeinsame Regeln aller S5-Varianten

- **Trade = Episode.** Eine Episode beginnt mit dem gleichzeitigen Kauf von q Coins Spot und dem Verkauf von q Coins
  Perpetual und endet mit der gleichzeitigen Auflösung beider Seiten. Je Instrument höchstens eine offene Episode.
- **Nominal.** N = 1 (Einheit), q = N / Perp-Einstiegsfill. **R = 1 % von N.** Kein Hebel: Die Short-Seite ist mit
  100 % ihres Nominals besichert (Isolated Margin, 1×). Ergebnisse in R sind damit Prozent des eingesetzten Nominals.
- **Einstieg.** Zum Funding-Zeitpunkt t mit Rate r_t > θ und ohne offene Episode: Signal. Fill beider Seiten zur
  Eröffnung der 1h-Kerze, die um t + 1 h beginnt (Spot-Open für die Long-Seite, Perp-Open für die Short-Seite), mit
  Slippage gegen sich. Ist die Kerze um t + 1 h nicht vorhanden (Lücke), verfällt das Signal (`invalid_signals`).
- **Ausstieg.** Zum Funding-Zeitpunkt t′ mit Rate r_t′ unter der Ausstiegsschwelle (4.2): Fill beider Seiten zur
  Eröffnung der Kerze um t′ + 1 h. Zusätzlich **erzwungene Schließung**, wenn das Hoch des Perpetual eine Kerze lang
  ≥ 1,8 × Perp-Einstiegsfill steht (Sicherung der 1×-Short-Seite, vereinfachte Liquidation): Fill zur Eröffnung der
  nächsten Kerze mit `stop_slippage`, Grund `forced_close`. Eine Episode hat **keinen** Zeit-Stop und kein Kursziel.
- **Funding-Gutschrift.** Zu jedem Funding-Zeitpunkt t″ im Intervall (Einstiegs-Fill, Ausstiegs-Fill] erhält die
  Short-Seite r_t″ × q × Perp-Schluss der Kerze, die um t″ endet (Gutschrift negativ, wenn r_t″ < 0).
- **Netto-Ergebnis** je Episode in N: Funding-Summe + q × [(Perp-Einstieg − Perp-Ausstieg) + (Spot-Ausstieg −
  Spot-Einstieg)] − Gebühren (5.3). Slippage steckt in den Fills. **Treffer** = Netto-Ergebnis > 0.
- Kein Nachkauf, keine Teilschließung, keine Umschichtung zwischen Instrumenten. Es gibt kein Raster über Nominal,
  Hebel, Ziel oder Stop.

### 4.2 Varianten

Zwei geordnete Parameter, keine weiteren: Einstiegsschwelle θ und Ausstiegsregel e.

| Variante | θ (Einstieg: r_t > θ) | e (Ausstieg: r_t′ …) | Begründung |
|---|---|---|---|
| S5-t01-e0 | 0,01 % (über dem Zinsanteil) | ≤ 0 | Prämie vorhanden; halten, solange Shorts bezahlt werden |
| S5-t02-e0 | 0,02 % | ≤ 0 | wie oben, nur bei klarer Prämie einsteigen |
| S5-t03-e0 | 0,03 % | ≤ 0 | wie oben, hohe Prämie |
| S5-t01-e1 | 0,01 % | < 0,01 % (unter den Zinsanteil) | früher raus, weniger Basisrisiko, mehr Kosten |
| S5-t02-e1 | 0,02 % | < 0,01 % | |
| S5-t03-e1 | 0,03 % | < 0,01 % | |

Sechs Varianten. Register m: 48 (Startbestand) + 6 = **54** ≤ 60 (Protokoll, Obergrenze), sofern alle sechs das Gate
(6.1) bestehen. Bestehen weniger, werden nur diese eingetragen. Es gibt keine weiteren S5-Varianten.

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

0. **Machbarkeits-Gate vor der Registrierung** (6.1). Nur Varianten, die es bestehen, kommen ins Register.
1. **Training:** E[R] > 0 (Basiskosten), mindestens **n_min** Episoden (6), Trefferquote mit einseitiger
   95-%-Untergrenze (unkorrigiert, Methode wie K6) ≥ 95 %.
2. **Validierung (24 Monate):** mindestens n_min × 24/21 Episoden, E[R] > 0, Profitfaktor > 1,1, Drawdown ≤ 20 R,
   Trefferquote-Untergrenze wie Schritt 1 ≥ 95 %, alle Robustheitsregeln (5.4).
3. **Kandidatenliste einfrieren:** höchstens eine Variante je Ausstiegsregel e, gewählt nach dem höchsten E[R] in der
   Validierung (nicht nach der Trefferquote), mit Hash und Protokollversion committen, bevor Holdout-Daten geladen werden.
4. **Holdout,** genau ein Lauf, nur nach Uzis Entscheidung (Abschnitt 8).

### 5.2 Urteil im Holdout

| # | Bedingung | Schwelle |
|---|---|---|
| K1 | Netto-Erwartungswert (Basiskosten) | > 0 R je Episode |
| K2 | schlägt den Zufallsvergleich (Abschnitt 7) **auf E[R]** | Holm-Bonferroni, Familien-α 5 %, m = Zahl aller Registereinträge (verworfene mit p = 1) |
| K3 | Mindeststichprobe (drei Instrumente zusammen) | ≥ **n_min** Episoden (Abschnitt 6); darunter **KEIN URTEIL** |
| K4 | maximaler Drawdown der verketteten Episoden (nach Ausstiegszeit) | ≤ 20 R (= 20 % von N) |
| K5 | Profitfaktor netto | > 1,0 (Basiskosten) |
| K6 | Trefferquote, **strenge Lesart** | einseitige Untergrenze ≥ 95 % auf dem Niveau 1 − 0,05/m. Zwei Verfahren, das **strengere** gilt: (a) Monatsblock-Bootstrap nach Einstiegsmonat, alle Instrumente eines Monats gemeinsam, 200 000 Ziehungen, Seed 20261025, einseitiges Quantil; (b) Clopper-Pearson mit effektivem n = n / D, D = Bootstrap-Varianz / Binomialvarianz, mindestens 1 |
| K7 | Kostenstress (`STRESS_COSTS`, Spot 0,20 %) | E[R] > 0 |
| K8 | keine versteckten Großverluste | mittlerer Verlust ≥ −2,0 R; größter Einzelverlust ≥ −5,0 R; Mittel der schlechtesten 5 % der Episoden ≥ −3,0 R; höchstens 1 % der Episoden mit `forced_close` |
| K9 | Gewinn je Treffer trägt die Verlierer | mittlerer Gewinn der Treffer ≥ (1 − Trefferquote) / Trefferquote × mittlerer Verlust der Verlierer × 1,5 (bei 95 %: ≥ 0,079 × mittlerer Verlust; Sicherheitsfaktor 1,5 gegen Stichprobenrauschen) |
| K10 | Breite | jedes Instrument ≥ 15 % der Episoden und E[R] > 0 bei mindestens 2 von 3 Instrumenten (je Instrument nur beschreibend) |

Urteile: **BESTANDEN** (alle K1–K10), **NICHT BESTANDEN**, **KEIN URTEIL** (K3 verfehlt). Masterprompt-Vokabular:
PASS / FAIL / INCONCLUSIVE. Die Trefferquote des Zufallsvergleichs wird berichtet, ist aber kein Kriterium (2.1).

### 5.3 Kosten, genau einmal

| Posten | Basis | Stress |
|---|---|---|
| Perp-Gebühr je Fill (`CostModel.fee`) | 0,05 % | 0,10 % |
| Spot-Gebühr je Fill (`SPOT_FEE`, neu in `protocol.py`) | 0,10 % | 0,20 % |
| Slippage je Fill, beide Seiten (`CostModel.slippage`) | 0,03 % | 0,06 % |
| Slippage bei `forced_close` auf der Perp-Seite (`stop_slippage`) | 0,05 % | 0,10 % |
| **Roundtrip je Episode** (2 Perp-Fills, 2 Spot-Fills, 4× Slippage) | **≈ 0,42 % von N = 0,42 R** | **≈ 0,84 R** |

Eine Episode muss also mindestens 0,42 R Funding einnehmen, bevor sie gewinnt: bei 0,01 % je Periode 42 Perioden
(14 Tage), bei 0,03 % 14 Perioden (knapp 5 Tage). Gebühren werden auf Einstiegs- und Ausstiegsnominal berechnet und
**genau einmal** abgezogen; Slippage steckt in den Fills und wird nicht noch einmal als Kosten gebucht. Ein Test je
Variante belegt vor dem Trainingslauf: Funding-Summe + Basisergebnis aus den Fills − Gebühren = Netto. Funding-Gutschriften
sind Teil des Ergebnisses, nicht der Kosten. Keine Zinsen auf die Spot-Seite, kein Verleih, kein Lending-Ertrag.

### 5.4 Robustheit (Protokoll 7.3)

- Jahresstabilität: E[R] > 0 in mindestens 60 % der Jahre mit ≥ 5 Episoden (Training + Validierung).
- Walk-Forward: 24 Monate Anpassung / 6 Monate Test. Auswahl je Ausstiegsregel e zwischen ihren drei θ-Varianten nach
  E[R], nur Episoden mit Ausstieg bis Fensterende in der Anpassung (`known_at`), Test nach Einstiegszeit
  (`signalled_in`). Verketteter Test-Erwartungswert > 0 **und** verkettete Test-Trefferquote ≥ 90 % (Punktwert).
- Nachbarschaft: Die benachbarte θ-Variante (0,01 ↔ 0,02 ↔ 0,03) hat im Training E[R] > 0.
- SPA/StepM wird berichtet, ist kein Kriterium (Protokoll-Änderungsprotokoll 23.10.).

## 6. Mindeststichprobe und Power (Planungsrechnung, vor jeder Auswertung)

K6 verlangt die einseitige Untergrenze ≥ 95 % auf dem Niveau 1 − 0,05/54 ≈ 0,99907 (z ≈ 3,11). Benötigte effektive
Stichprobe n_eff = z² · p(1 − p) / (p − 0,95)² und mit Designeffekt D = 2,5 (Episoden der drei Instrumente laufen im
selben Funding-Regime) die Zahl der Episoden n = D · n_eff:

| wahre Trefferquote p | n_eff | n (D = 2,5) |
|---|---|---|
| 0,97 | ≈ 704 | ≈ 1 760 |
| 0,98 | ≈ 313 | ≈ 780 |
| 0,99 | ≈ 176 | ≈ 440 |

**n_min = 800** Episoden im Holdout (entspricht p ≈ 0,98). Training braucht ≥ 800, Validierung ≥ 915 (800 × 24/21).
Ehrliche Einschätzung vorab: Episoden dauern Tage bis Wochen. Bei 21 Holdout-Monaten und drei Instrumenten sind eher
100–300 Episoden zu erwarten. **S5 wird mit der strengen Lesart wahrscheinlich am Gate scheitern.** Das ist dann das
Ergebnis, keine Einladung zur Lockerung.

Nicht gewählt: die einzelne Funding-Periode als Trade-Einheit. Sie würde die Stichprobe verzehnfachen, aber die Perioden
einer Episode sind abhängig, und die Kosten müssten auf Perioden verteilt werden; beides öffnet das Ausreizen der Quote.

### 6.1 Machbarkeits-Gate (vor Registrierung, ergebnisblind)

Episodengrenzen hängen nur vom Funding-Vorzeichen ab (θ, e), nicht vom Ergebnis. Ein Zähllauf auf Training und
Validierung zählt je Variante und Instrument die Episoden (ohne `forced_close`, ohne Kurse, ohne R) und rechnet die
Zahl je Coin-Monat auf 63 Holdout-Coin-Monate (21 × 3) hoch.

- Variante ≥ 800 hochgerechnet → wird registriert.
- Variante < 800 → wird **nicht** registriert, im Bericht mit Zahl genannt.
- Besteht keine Variante → **S5 ist mit der strengen Lesart nicht testbar.** Die Studie endet ohne Register-Eintrag und
  ohne Trainingslauf. Dann bleibt als ehrlicher Weg zu 95 % nur die prospektive Sammlung auf Papier über Jahre oder ein
  neuer Entwurf mit eigener Nummer. Keine Lockerung im selben Entwurf.

Die Zählung wird mit Commit und Datensatz-Hash festgehalten, bevor irgendein Ergebnis gerechnet wird.

## 7. Zufallsvergleich (Baseline)

Grundlage Protokoll 7.1, angepasst an Episoden (Paket P4, Code neu):

- **ein gepoolter Test je Variante**: Jeder von 10 000 Zufallsläufen legt je Instrument genauso viele Episoden mit
  genau denselben Dauern (in Funding-Perioden) wie die Variante an, Startzeiten gleichverteilt über die
  Funding-Zeitpunkte des Abschnitts, ohne Überlappung je Instrument; Kosten und Gutschriften wie bei der Variante.
  Statistik E[R] gepoolt. p = (1 + Läufe mit E[R] ≥ Variante) / 10 001. Seed **20261030**.
- Die Nullhypothese lautet damit: „Der Funding-Filter weiß nichts über die nächste Funding-Rate, was ein zufällig
  gewählter Zeitpunkt nicht auch wüsste.“ Weil Funding im Mittel positiv ist, hat auch die Baseline oft E[R] > 0; K1 prüft
  die absolute, K2 die relative Profitabilität.
- Monatsblock-Variante wie S4 7 entfällt, weil die Episodendauer schon aus der Variante übernommen wird.

## 8. Holdout-Freigabe

Der Holdout 2025+ wird nur nach Uzis ausdrücklichem Wort geöffnet, abgefragt per Entscheidungskarte vor jedem Lauf. Die
Karte nennt Kandidatenliste (Hash), m, Protokollversion und den Ablauf. Ein Lauf, danach ist der Holdout für S5 und für
alle 54 Registereinträge verbraucht.

## 9. Arbeitspakete nach Freigabe

| # | Paket | Prüfbefehl |
|---|---|---|
| P2 | Spot 1h ETH/SOL ins Archivmodul und auf dem Mac laden (Prüfsummen, Lücken berichten) | `research_lab_fetch --market spot --symbol ETHUSDT` ohne Fehler; Datensatz-Hash im Bericht |
| P3 | Zähllauf 6.1, JSON mit Commit und Hashes | Hochrechnung je Variante ≥ 800? |
| P4 | Code: `hypotheses/s5.py` (Episodenlogik), Carry-Motor oder Erweiterung von `run_backtest` um zwei Seiten, `SPOT_FEE`, Zufallsvergleich nach 7, Tests: Funding erst ab t bekannt, Einstieg t + 1 h, Gebühren genau einmal, `forced_close`, Lücken | `pytest tests/test_research_lab_s5.py` grün, Cloud-Suite grün |
| P5 | Training und Validierung auf dem Mac (nicht während CI-Jobs), Bericht; Register-Eintrag nur bei Erfolg in beiden | K1–K10 in Training und Validierung |
| P6 | Holdout, genau ein Lauf, nur per Entscheidungskarte | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

- Alles aus S4 Abschnitt 10 sowie die S4-Erkundungen auf 2020–2024 (Trefferquoten und E[R] der zehn 1h-Varianten,
  210 Ziel-/Stop-Zellen). Diese Daten betreffen Richtungs-Einstiege, nicht Funding-Carry.
- Funding-Archiv 2020–2024 (BTC/ETH ab 2020-01, SOL ab 2020-10), nur: Anteil positiver Perioden (BTC 87,6 %, ETH 89,2 %,
  SOL 77,1 %), bedingte Anteile P(nächste > 0 | aktuelle > 0 / > 0,01 % / > 0,03 %) und P(nächste > 0,01 % | …),
  Jahressummen der Raten (2.3). **Keine** Episode, kein Kurs, keine Basis, kein Ergebnis einer S5-Regel gerechnet.
- Holdout 2025+: nie geladen.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | Unabhängige adversariale Prüfung dieses Entwurfs (anderes Modell), Befunde einarbeiten | Thread |
| O2 | Spot-Archivbeginn ETH/SOL prüfen (Dateiexistenz, eine Probedatei) | Mac, P2 |
| O3 | Freigabe Version 1.0 durch Uzi; Registrierung nur der Varianten, die das Gate 6.1 bestehen | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-25 | 0.1 | Entwurf: Funding-Carry, 6 Varianten (θ × e), Trade = Episode, R = 1 % Nominal, K1–K10 mit K2 und K9 auf E[R] statt Quote, n_min = 800, Machbarkeits-Gate, Zufallsvergleich mit gleichen Episodendauern | Uzis Ziel 95 % (18:38), Empfehlungen angenommen (18:51) | Abschnitt 10; keine S5-Ergebnisse, kein Holdout |
