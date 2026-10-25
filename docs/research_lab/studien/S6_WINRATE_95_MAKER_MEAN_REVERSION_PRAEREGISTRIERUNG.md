# Studie S6: Winrate ≥ 95 % mit positivem Netto-Erwartungswert durch Maker-Mean-Reversion (Präregistrierung)

| Feld | Wert |
|---|---|
| Version | 0.1 (Entwurf) |
| Status | **ENTWURF.** Nichts ist gerechnet, keine 1m-Daten geladen. Adversariale Prüfung (O1) und Uzis Freigabe (Abschnitt 11) stehen aus. Varianten kommen erst nach dem Machbarkeits-Gate (6.1) ins Register. |
| Erstellt | 2026-10-25, 20:00 Ortszeit. Auftrag: Uzis Wahl „Neue Studie S6 mit anderer Familie“ (Entscheidungskarte 19:51) und „go“ zum Bauplan (19:58) |
| Bauplan | `/mnt/project-files/plaene/s6-maker-mean-reversion-bauplan.md` (Projektablage) |
| Vorgänger | S4 (Richtungs-Einstiege 1h): am Gate beendet, Einstiege unter Zufall (`S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md`). S5 (Funding-Carry): am Gate beendet, 0 hochgerechnete Episoden, 2022 ohne Einstieg (`S5_WINRATE_95_FUNDING_CARRY_PRAEREGISTRIERUNG.md`, `../reports/s5_count_2026-10-25T1836Z.md`) |
| Protokollbezug | `../PROTOKOLL.md` Version 1.1: Datensplit 3.2, Kosten 4.4, Zufallsvergleich 7.1, Holm 7.2, Robustheit 7.3, Ablauf 8, Stoppregeln 10. **Abweichung mit Begründung:** Maker-Gebühr für Limit-Fills (5.3) statt „alles Taker“ (Protokoll 4.4); braucht Protokoll-Eintrag 1.3 auf Uzis Wort |
| Kostenmodell | `CostModel` aus `src/research_lab/protocol.py` für Taker-Fills; neue Konstante `MAKER_FEE = 0,02 %` je Maker-Fill; Stress nach 5.3 |

Was dieses Dokument nicht ist: kein Profitversprechen, keine Anlageberatung, keine Freigabe für Papier- oder
Echtgeldbetrieb. Das Ergebnis darf und wird wahrscheinlich **NICHT BESTANDEN**, **KEIN URTEIL** oder **NICHT TESTBAR**
lauten (Abschnitt 2 und 8).

---

## 1. Fragestellung

Gibt es unter den unten vorab festgelegten Regeln eine Strategie, die auf Daten, die bei ihrer Auswahl nie benutzt
wurden (Holdout 2025-01 bis 2026-09, genau ein Lauf), **gleichzeitig** erreicht: Netto-Trefferquote ≥ 95 % (Punktwert)
mit Untergrenze ≥ 90 %, positiver Netto-Erwartungswert auch unter Stress, Profitfaktor > 1, begrenzter Drawdown,
ausreichende Stichprobe, robuste Walk-Forward-Ergebnisse und ein Erwartungswert **über** zufälligen Einstiegen mit
gleicher Geometrie und gleichen Kosten?

Die Trefferquote wird **nie allein** optimiert. **Treffer = Netto-Ergebnis > 0 nach allen Kosten**, bei jedem
Ausstiegsgrund. Ziel T und Stop R sind vorab fest (4.2); es gibt kein Raster darüber hinaus.

## 2. Ausgangslage und Mathematik der 95 %

### 2.1 Was 95 % erzwingt

Mit Ziel T (in R) und Roundtrip-Kosten c (in R) liegt die Gewinnschwelle der Trefferquote bei p* = (1 + c) / (1 + T).
Für 95 % **und** E[R] > 0 muss T > 0,0526 + 1,0526 · c sein. Ein Zufallsweg ohne Drift trifft +T R vor −1 R mit
Wahrscheinlichkeit 1 / (1 + T). Die Quote allein unterscheidet Zufall und Strategie nicht; S6 testet deshalb den
Zufallsvergleich (K2) auf dem Erwartungswert.

| Kostenmodell | Gewinner-Roundtrip | Verlierer-Roundtrip | T | p* | Zufall 1/(1+T) | nötiger Vorsprung |
|---|---|---|---|---|---|---|
| S6 (Maker rein, Maker-Ziel, Taker-Stop; 5.3), R = 1,5 % | 0,04 % = 0,027 R | 0,12 % = 0,080 R | 0,10 | 93,7 % | 90,9 % | +2,8 Punkte |
| | | | 0,15 | 89,8 % | 87,0 % | +2,8 Punkte |
| | | | 0,20 | 86,2 % | 83,3 % | +2,9 Punkte |
| Protokoll 4.4 (alles Taker + Slippage) | 0,16 % = 0,107 R | 0,18 % = 0,120 R | 0,10 | **nie** (Kosten > Ziel) | 90,9 % | unerreichbar |
| | | | 0,15 | 96,3 % | 87,0 % | +9,3 Punkte |
| | | | 0,20 | 92,4 % | 83,3 % | +9,1 Punkte |

p* ist die Trefferquote, bei der E[R] = p·(T − c_win) − (1 − p)·(1 + c_loss) gerade null ist. Bei genau 95 % und
T = 0,10 R bleibt im S6-Modell E[R] ≈ +0,015 R je Trade: positiv, aber klein. Unter dem Protokoll-Kostenmodell ist die
Familie bei T = 0,10 chancenlos und bei T ≥ 0,15 nur mit einem Vorsprung von 9 Punkten vor dem Zufall möglich. Darum
die Abweichung in 5.3; beide Rechnungen werden in jedem Bericht nebeneinander ausgewiesen.

### 2.2 Nachweis (Lesart K6, wie S5)

Eine korrigierte Untergrenze ≥ 95 % (strenge Lesart aus S4) braucht selbst bei null Verlierern 137 unabhängige Trades
und mit 80 % Power bei wahrer Quote 98 % rund 620. S6 nutzt die Lesart aus S5 (Punktwert ≥ 95 %, einseitige
95-%-Untergrenze ≥ 90 % mit effektivem n), weil sie der einzige in 21 Monaten prüfbare Nachweis ist, und sagt offen,
dass das schwächer ist als in S4 geplant. Die Mehrfachtest-Korrektur bleibt vollständig bei K2 (Holm, m = 60). Anders
als bei S5 ist die Stichprobe hier voraussichtlich kein Engpass (Trades dauern Minuten bis Stunden); der Engpass ist
der Vorsprung vor dem Zufall.

### 2.3 Befunde aus S4 und S5 (nicht neu gerechnet)

- S4: Zehn 1h-Richtungs-Einstiege lagen 2020–2024 in allen 210 Ziel-/Stop-Zellen **unter** der Zufallsreferenz
  (höchstens 92 % bei E[R] < 0). Richtungs-Einstiege nach Struktur sind kein Kandidat.
- S5: Funding-Carry trifft plausibel oft, handelt aber zu selten (39–52 Episoden in fünf Jahren, 2022 null).

### 2.4 Warum Maker-Mean-Reversion (ökonomische Begründung)

Ein Limit-Kauf weit unter dem kurzfristigen Mittel wird nur gefüllt, wenn der Kurs in einer Minute stark fällt. Wer
dann hält, bekommt (a) die Maker-Gebühr statt der Taker-Gebühr, (b) keinen Spread und keine Slippage beim Einstieg und
(c) im Mittel den Teil des Ausschlags zurück, der Liquiditätsnot und nicht Information war. Der Gewinn je Trade ist
klein (T = 0,10–0,20 R), der Verlust bei Weiterlaufen voll (1 R). Dagegen spricht: Der Füllende ist genau dann dran,
wenn jemand dringend verkaufen musste, und in Trendminuten ist das Information (adverse Selektion). Ob (c) die
Verlierer trägt, ist die offene Frage; S4 zeigt, dass es für Richtungs-Einstiege nicht gilt.

### 2.5 Ausgeschlossen

- „Halten bis grün“, Nachkauf, Grid, Martingale: Quote nur aus unbegrenzten Verlusten (Masterprompt).
- Orderbuch-Simulation (Queue-Position, Teilfills): nicht aus Kerzen oder aggTrades ableitbar. S6 ersetzt sie durch
  die Durchhandel-Regel (3) und eine aggTrades-Prüfung der Fills (P5); der Rest ist benanntes Restrisiko.
- Fill-Annahme „Berührung = Fill“: ausgeschlossen, weil sie Backtests von Limit-Strategien systematisch schönt.

## 3. Daten und Datenherkunft

| Datensatz | Quelle | Zeitraum | Stand |
|---|---|---|---|
| USD-M Perpetual **1m**-Kerzen BTCUSDT, ETHUSDT, SOLUSDT | data.binance.vision, monatliche Archive mit Prüfsumme (`src/research_lab/data/archive.py`, Intervall „1m“ vorhanden) | BTC/ETH ab 2020-01, SOL ab 2020-09 (Warm-up), gezählt ab 2020-10, bis 2024-12 | **nicht geladen** (P2, Mac, ~180 Archive) |
| USD-M Funding-Raten | wie oben, `Dataset.FUNDING`, Zeitstempel normalisiert wie S5 (`normalize_funding`) | wie oben | geladen (S4/S5) |
| aggTrades-Stichprobe (Fill-Prüfung P5) | data.binance.vision Tagesarchive, Werkzeuge aus S2 (`src/research_lab/data/aggtrades.py`) | 10 Tage je Instrument aus dem Training, Ziehung mit Seed vor jedem Ergebnis | nicht geladen |
| Holdout 2025+ | gesperrt durch `HoldoutLocked` in `data/store.py` | ab 2025-01-01 | nie geladen |

**Kerzen und Lücken.** Eine 1m-Kerze gilt ab ihrem Schluss als bekannt. Fehlende Minuten bis 5 min werden überbrückt
(offene Orders bleiben stehen, keine Fills in der Lücke); Lücken über 5 min schließen einen offenen Trade zur letzten
Kerze davor zum Schlusskurs (Taker, `gap`) und löschen offene Orders.

**Durchhandel-Regel (Fill).** Ein Limit L gilt in Minute t als gefüllt, wenn der Kurs mindestens um die Marge δ
**durch** L gehandelt hat: Kauf-Limit, wenn `low_t ≤ L · (1 − δ)`; Verkaufs-Limit, wenn `high_t ≥ L · (1 + δ)`.
δ = max(0,01 % von L, eine Preiseinheit der Archivpräzision des Instruments im jeweiligen Monat). Berührung zählt
nicht. Fill-Preis ist L (keine Kursverbesserung). Ein Limit, das die Minute bereits jenseits ihres Eröffnungskurses
beginnen würde (`open_t ≤ L` beim Kauf, `open_t ≥ L` beim Verkauf), würde kreuzen und wird **nicht** platziert
(Post-only; gezählt als `skipped_cross`). Stress (5.3) verdoppelt δ.

**Zeitliche Aufteilung (3.1).** Training 2020-01-01 (SOL: 2020-10-01) bis 2022-12-31, Validierung 2023-01-01 bis
2024-12-31, **Holdout 2025-01-01 bis 2026-09-30** (21 Monate, fest), genau ein Lauf. Trades gehören zum Abschnitt
ihres Einstiegsfills (Protokoll 3.2). Kein Abschnitt rechnet über sein Ende hinaus: Ein offener Trade wird zur letzten
Kerze des Abschnitts zum Schlusskurs geschlossen (Taker, `section_end`) und zählt.

## 4. Hypothesen-Register (wird mit Version 1.0 eingefroren)

### 4.1 Gemeinsame Regeln aller S6-Varianten

- **Instrumente und Seiten.** BTC, ETH, SOL USD-M Perpetual, Long und Short spiegelbildlich innerhalb derselben
  Variante. Je Instrument höchstens ein offener Trade und höchstens eine ruhende Order je Seite.
- **Nominal und R.** N = 1 000 USDT Nominal je Trade (für die Fill-Prüfung P5 nötig; Ergebnisse in R sind davon
  unabhängig), q = N / Fill. **R = 1,5 % des Einstiegsfills** (fest; aus dem S4-Kostentor „Stop ≥ 1 %“ abgeleitet).
  Kein Hebel-Raster; Margin ist nicht Teil der Rechnung.
- **Referenz.** Zu Beginn jeder Minute t aus den **geschlossenen** Kerzen t−30 … t−1: VWAP₃₀ (Schluss ×
  Volumen, durch Volumen; bei Volumen 0 der einfache Mittelwert) und σ₁ = Standardabweichung der 1m-Log-Renditen der
  letzten 120 geschlossenen Kerzen, σ₃₀ = σ₁ · √30. Fehlen Kerzen im Fenster (Lücke), gibt es in Minute t keine Order.
  Keine weiteren Indikatoren, kein Trend- oder Volumenfilter.
- **Orders.** In Minute t ruhen ein Kauf-Limit L_long = VWAP₃₀ · (1 − k·σ₃₀) und ein Verkaufs-Limit
  L_short = VWAP₃₀ · (1 + k·σ₃₀), jeweils nur, wenn sie nicht kreuzen (3) und kein Trade offen ist. Orders gelten für
  diese eine Minute und werden in der nächsten Minute neu gestellt (Re-Pricing). Wird in derselben Minute die
  Durchhandel-Bedingung für **beide** Seiten erfüllt, wird kein Trade eröffnet (`skipped_both`, gezählt).
- **Einstieg.** Fill zu L (Maker-Gebühr, keine Slippage) in Minute t. Stop und Ziel stehen ab Fill fest: Long
  Stop = Fill · (1 − 0,015), Ziel = Fill · (1 + T · 0,015); Short spiegelbildlich.
- **Ausstieg** (erste erfüllte Bedingung, geprüft ab Minute t + 1; in der Fill-Minute selbst kein Ausstieg):
  - `stop`: Long `low ≤ Stop` → Fill zu min(Stop, open) mit `stop_slippage` und Taker-Gebühr; Short spiegelbildlich.
  - `target`: Long `high ≥ Ziel · (1 + δ)` (Durchhandel-Regel) → Fill zu Ziel, Maker-Gebühr.
  - Treffen `stop` und `target` in derselben Minute zu, gilt **`stop`** (`ambiguous`, gezählt und berichtet).
  - `time`: 240 Minuten nach dem Einstiegsfill ohne Ausstieg → Schluss der 240. Kerze, Taker-Gebühr + Slippage.
  - `gap`, `section_end` wie Abschnitt 3.
- **Sperre.** Nach jedem Ausstieg 5 Minuten ohne Orders im Instrument; nach `stop` 30 Minuten.
- **Funding.** Liegt ein Funding-Zeitpunkt (00/08/16 UTC) zwischen Einstiegs- und Ausstiegsfill, wird die Rate × N mit
  Vorzeichen nach Seite gebucht (Protokoll 4.4; Stress: nie zugunsten des Trades).
- **Netto-Ergebnis** je Trade in R: `(Richtung · (Aus − Ein) · q − Gebühren − Funding-Kosten) / (0,015 · N)`,
  Slippage steckt in den Fills. **Treffer** = Netto > 0. Alle Ausstiegsgründe zählen in K1–K10.
- Kein Nachkauf, keine Teilschließung, kein Trailing, keine Umschichtung. Es gibt kein Raster über R, Zeitstop, Fenster,
  Sperren, δ oder Referenz.

### 4.2 Varianten

Zwei geordnete Parameter, keine weiteren: Abstand k (in σ₃₀) und Ziel T (in R).

| Variante | k | T | Begründung |
|---|---|---|---|
| S6-k2-t10 | 2 | 0,10 R | häufige Fills, Quote nahe 95 % rechnerisch möglich (2.1) |
| S6-k2-t15 | 2 | 0,15 R | |
| S6-k2-t20 | 2 | 0,20 R | größerer Puffer über den Kosten, Quote schwerer |
| S6-k3-t10 | 3 | 0,10 R | seltene, extreme Ausschläge |
| S6-k3-t15 | 3 | 0,15 R | |
| S6-k3-t20 | 3 | 0,20 R | |

Sechs Varianten. Register m: 48 (Startbestand) + 6 = 54; **für alle Rechnungen in S6 gilt fest m = 60** (Obergrenze
des Protokolls, konservativ). Registriert werden nur Varianten, die das Gate (6.1) bestehen. Es gibt keine weiteren
S6-Varianten.

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

0. **Machbarkeits-Gate vor der Registrierung** (6.1) und **Fill-Prüfung** (6.2) vor jedem Ergebnis.
1. **Training:** E[R] > 0 (S6-Kosten), mindestens n_min effektive Trades (6), p < 0,10 gegen den Zufallsvergleich
   (Abschnitt 7, unkorrigiert), Trefferquote Punktwert ≥ 95 % und Untergrenze (K6) ≥ 90 %. Diese Vorfilterung nach
   Trefferquote ist bewusst und benannt.
2. **Validierung (24 Monate):** mindestens n_min × 24/21 effektive Trades, E[R] > 0, p < 0,05 (unkorrigiert),
   Profitfaktor > 1,1, Trefferquote wie Schritt 1, alle Robustheitsregeln (5.4).
3. **Kandidatenliste einfrieren:** höchstens eine Variante je Ziel T (also höchstens drei), gewählt nach dem höchsten
   E[R] in der Validierung (nicht nach der Quote), mit Hash und Protokollversion committen, bevor Holdout-Daten geladen
   werden.
4. **Holdout,** genau ein Lauf, nur nach Uzis Entscheidung (Abschnitt 8).

### 5.2 Urteil im Holdout

| # | Bedingung | Schwelle |
|---|---|---|
| K1 | Netto-Erwartungswert (S6-Kosten) | > 0 R je Trade |
| K2 | schlägt den Zufallsvergleich (Abschnitt 7) **auf E[R]** | Holm-Bonferroni, Familien-α 5 %, m = 60 (verworfene mit p = 1) |
| K3 | Mindeststichprobe (drei Instrumente zusammen) | ≥ **n_min = 80 effektive Trades** (n / D, Abschnitt 6); darunter **KEIN URTEIL** |
| K4 | maximaler Drawdown der R-Kurve (1 % Risiko je Trade, Protokoll 4.3) | ≤ 20 R |
| K5 | Profitfaktor netto | > 1,0 |
| K6 | Trefferquote | **Punktwert ≥ 95 %** und einseitige **95-%-Untergrenze ≥ 90 %** (unkorrigiert) nach Clopper-Pearson mit n_eff = n / D, k_eff = ⌊k / D⌋, D = Designeffekt aus dem **Tagescluster**-Schätzer (Varianz des Cluster-Mittels geteilt durch Binomialvarianz, mindestens 1; bei p̂ = 100 % gilt D = 1). Ein Verfahren, keine Alternative |
| K7 | Stress (5.3: Gebühren und Slippage ×2, δ ×2, Funding nie zugunsten) | E[R] > 0 |
| K8 | keine versteckten Großverluste | größter Einzelverlust ≥ −2,0 R; mittlerer Verlust ≥ −1,2 R; `ambiguous` ≤ 5 % der Trades; `time` + `gap` + `section_end` zusammen ≤ 25 % der Trades |
| K9 | Gewinn je Treffer trägt die Verlierer | mittlerer Gewinn der Treffer ≥ 1,5 × (1 − Trefferquote) / Trefferquote × mittlerer Verlust der Verlierer |
| K10 | Breite | jedes Instrument ≥ 15 % der Trades; jede Seite (Long/Short) ≥ 25 % der Trades; E[R] je Instrument und Seite wird berichtet |

Urteile: **BESTANDEN (Holdout)** (alle K1–K10), **NICHT BESTANDEN**, **KEIN URTEIL** (K3 verfehlt).
Masterprompt-Vokabular: PASS / FAIL / INCONCLUSIVE. „BESTANDEN (Holdout)“ ist nicht das Protokoll-K5 (Papier-Betrieb).
Berichtet, aber kein Kriterium: Trefferquote und E[R] des Zufallsvergleichs, alle Kennzahlen unter dem
Protokoll-Kostenmodell (alles Taker), Verteilung der Haltedauern, Fills je Tag, Anteil `skipped_cross` und
`skipped_both`, Ergebnis der Fill-Prüfung (6.2).

### 5.3 Kosten, genau einmal, und Stress

| Posten | Basis (S6) | Stress |
|---|---|---|
| Maker-Gebühr je Limit-Fill (Einstieg, `target`): `MAKER_FEE`, neu in `protocol.py` | 0,02 % | 0,04 % |
| Taker-Gebühr je Markt-Fill (`stop`, `time`, `gap`, `section_end`): `CostModel.fee` | 0,05 % | 0,10 % |
| Slippage bei `time`, `gap`, `section_end`: `CostModel.slippage` | 0,03 % | 0,06 % |
| Slippage bei `stop`: `CostModel.stop_slippage` | 0,05 % | 0,10 % |
| Slippage bei Limit-Fills | 0 (Fill zu L) | 0, aber δ verdoppelt (0,02 %) |
| Funding, falls Zeitpunkt im Trade | historische Rate | nie zugunsten des Trades |
| **Roundtrip Gewinner** (Maker + Maker) | **0,04 % = 0,027 R** | 0,08 % = 0,053 R |
| **Roundtrip Verlierer** (Maker + Taker-Stop + Stop-Slippage) | **0,12 % = 0,080 R** | 0,24 % = 0,160 R |

Protokoll 4.4 rechnet alle Fills als Taker, „auch wenn ein Limit-Einstieg denkbar wäre“. Der Grund ist die
Unsicherheit, ob ein Limit wirklich gefüllt worden wäre. S6 begegnet genau dieser Unsicherheit mit der Durchhandel-
Regel, der Post-only-Regel und der aggTrades-Prüfung (6.2) und rechnet deshalb Limit-Fills als Maker. Das ist eine
Abweichung vom Protokoll, die Uzi vor Version 1.0 freigeben muss (Protokoll-Eintrag 1.3, nur für Studien mit
Durchhandel-Regel und Fill-Prüfung). Jeder Bericht weist zusätzlich alle Kennzahlen mit dem Protokoll-Kostenmodell aus.
Gebühren werden je Fill auf das Fill-Nominal berechnet und genau einmal abgezogen; Slippage steckt in den Fills. Ein
Test je Ausstiegsgrund belegt vor dem Trainingslauf: Richtung · Kursdifferenz · q − Gebühren − Funding = Netto.

### 5.4 Robustheit (Protokoll 7.3)

- Jahresstabilität: E[R] > 0 in mindestens 60 % der Jahre mit ≥ 30 Trades (Training + Validierung).
- Walk-Forward: 24 Monate Anpassung / 6 Monate Test. Auswahl je Ziel T zwischen seinen zwei k-Varianten nach E[R],
  in der Anpassung nur Trades mit Ausstieg bis Fensterende (`known_at`), im Test alle Trades mit Einstiegsfill im
  Fenster. Verketteter Test-Erwartungswert > 0 **und** verkettete Test-Trefferquote ≥ 90 % (Punktwert). Scheitert der
  Walk-Forward eines T, sind beide Varianten dieses T für den Holdout gesperrt.
- Nachbarschaft: Jede Variante braucht E[R] > 0 im Training bei **allen** direkten Nachbarn (gleiches T, anderes k;
  gleiches k, benachbartes T), die das Gate bestanden haben. Hat kein Nachbar das Gate bestanden, entfällt die Regel
  und das wird berichtet.
- SPA/StepM wird berichtet, ist kein Kriterium (Protokoll-Änderungsprotokoll 23.10.).

## 6. Mindeststichprobe, Gate und Fill-Prüfung

Lesart K6 wie S5 Abschnitt 6: **n_min = 80 effektive Trades** (bei 0 Verlierern Untergrenze 96,3 %, erlaubt bis 3
Verlierer; Power 78 % / 92 % bei wahrer Quote 97 % / 98 %). Training ≥ 80, Validierung ≥ 92 effektive Trades.
Der Designeffekt D kommt aus dem **Tagescluster** (Cluster = Kalendertag und Instrument), weil Fills derselben
Stunde dieselbe Bewegung handeln; die Planung nimmt D = 2 an (Gate-Schwelle 160).

### 6.1 Machbarkeits-Gate (vor Registrierung, ergebnisblind)

Ein Zähllauf auf Training und Validierung zählt je Variante und Instrument die **Einstiegsfills** nach genau den
Regeln aus 3 und 4.1 (Referenz, Durchhandel-Regel, Post-only, Sperren) sowie `skipped_cross` und `skipped_both`.
Dafür werden Kurse bis zum Fill gelesen, **kein Ausstieg und kein R**; der Zähler kennt weder Stop noch Ziel. Weil die
Sperren vom Ausstieg abhängen, zählt der Zähllauf mit der konservativen Annahme, dass jeder Trade den Zeitstop
(240 min) erreicht, und berichtet zusätzlich die Zahl ohne Sperren als Obergrenze. Hochrechnung: Fill-Dichte je
Coin-Monat des **schwächsten Kalenderjahres** × 63 Holdout-Coin-Monate.

- Variante ≥ **160** hochgerechnet (= n_min × D_Planung) → wird registriert.
- Variante < 160 → wird **nicht** registriert, im Bericht mit Zahl genannt.
- Besteht keine Variante → **S6 ist nicht testbar**, Ende ohne Register-Eintrag und ohne Trainingslauf. Keine
  Lockerung im selben Entwurf.

Die Zählung wird mit Commit und Datensatz-Hash festgehalten, bevor irgendein Ergebnis gerechnet wird.

### 6.2 Fill-Prüfung an aggTrades (vor jedem Ergebnis, Paket P5)

Je Instrument werden 10 Kalendertage aus dem Training mit Seed **20261031** gezogen (gleichverteilt über Tage mit
mindestens einem Einstiegsfill laut 6.1). Für jeden Einstiegsfill dieser Tage wird aus den aggTrades geprüft, ob in der
Fill-Minute Trades zu Preisen ≤ L · (1 − δ) (Kauf) bzw. ≥ L · (1 + δ) (Verkauf) mit **kumulierter Menge ≥ q**
stattfanden. Bestätigungsquote ≥ 90 % → Regel bleibt. Darunter wird δ **vor** dem ersten Trainingslauf so weit erhöht
(in Schritten von 0,01 %), bis die Quote ≥ 90 % ist, und das im Änderungsprotokoll festgehalten; der Zähllauf 6.1
wird dann wiederholt. Diese Änderung ist nur strenger möglich. Die Prüfung liest keine Ausstiege.

## 7. Zufallsvergleich (Baseline)

Grundlage Protokoll 7.1, angepasst (Code neu in P4):

- **Zufallsvergleich (K2):** zufällige **Einstiegsminuten** je Instrument und Abschnitt, genauso viele wie die
  Variante dort Trades hat, mit zufälliger Seite (50/50), Fill zum **Eröffnungskurs** der Minute mit **denselben
  Kosten wie die Variante** (Maker-Gebühr, keine Slippage am Einstieg) und denselben Ausstiegsregeln (Stop 1 R, Ziel
  T R per Durchhandel-Regel, Zeitstop, Sperren, `gap`, `section_end`). Ein gezogener Zeitpunkt, der mit einem offenen
  Zufallstrade oder einer Sperre kollidiert, wird neu gezogen (maximal 100 Versuche, sonst entfällt er und wird
  gezählt). 10 000 Läufe, Statistik E[R] gepoolt, p = (1 + Läufe mit E[R] ≥ Variante) / 10 001. Seed **20261030**.
  Nullhypothese: „Ein Limit-Fill nach einem k·σ-Ausschlag hat keinen besseren Erwartungswert als ein Einstieg zu einer
  zufälligen Minute mit gleichen Kosten und gleicher Geometrie.“ Weil der Zufallsvergleich dieselben Maker-Kosten
  bekommt, misst K2 nur den Einstiegsvorteil, nicht den Kostenvorteil.
- **Berichtet, kein Kriterium:** derselbe Zufallsvergleich mit Protokoll-Kosten (alles Taker), und die
  Trefferquote beider Zufallsvergleiche neben der der Variante.

## 8. Holdout-Freigabe

Der Holdout 2025-01 bis 2026-09 wird nur nach Uzis ausdrücklichem Wort geöffnet, abgefragt per Entscheidungskarte vor
dem Lauf. Die Karte nennt Kandidatenliste (Hash), m, Protokollversion und den Ablauf. Ein Lauf, danach ist der Holdout
für S6 und für alle Registereinträge verbraucht; auch ein KEIN URTEIL (K3) verbraucht ihn.

## 9. Arbeitspakete nach Freigabe

| # | Paket | Prüfbefehl |
|---|---|---|
| P1 | Dieser Entwurf 0.1 → adversariale Prüfung (anderes Modell) → 0.2 | Befunde im Änderungsprotokoll |
| P2 | 1m-Klines USD-M BTC/ETH/SOL 2020–2024 auf dem Mac laden (nur ohne CI-Job), Prüfsummen, Lücken > 5 min je Monat berichten | `research_lab_fetch`-Lauf ohne Fehler; Datensatz-Hash im Bericht |
| P3 | Zähllauf 6.1 (`scripts/research_lab_s6.py count`), JSON mit Commit und Hashes | Hochrechnung je Variante ≥ 160? |
| P4 | Code: `hypotheses/s6.py` (Referenz, Orders, Durchhandel-Regel, Ausstiege, Sperren), `MAKER_FEE` und S6-Stress in `protocol.py` (mit Protokoll-Eintrag 1.3), Zufallsvergleich nach 7, Tests: Referenz nur aus geschlossenen Kerzen, Post-only, δ-Marge, `ambiguous` = Stop, Zeitstop, Gebühren genau einmal je Ausstiegsgrund, Funding im Trade, Lücken, `section_end` | `pytest tests/test_research_lab_s6.py` grün, Cloud-Suite grün |
| P5 | Fill-Prüfung 6.2 an aggTrades (30 Tage, ~3–9 GB Download auf dem Mac) | Bestätigungsquote ≥ 90 %, sonst δ erhöhen und P3 wiederholen |
| P6 | Training und Validierung auf dem Mac (nicht während CI-Jobs), Bericht; Register-Eintrag nur bei Erfolg in beiden | K1–K10, 5.4 |
| P7 | Holdout, genau ein Lauf, nur per Entscheidungskarte | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

- Alles aus S4 und S5 Abschnitt 10: 1h-Richtungs-Einstiege 2020–2024 (Trefferquoten, E[R], 210 Ziel-/Stop-Zellen),
  Funding-Statistiken 2020–2024, Carry-Episodenzahlen. Nichts davon betrifft 1m-Kerzen oder Limit-Fills.
- **1m-Kerzen: nie geladen.** k, T, R, Fenster, Zeitstop, δ und Sperren wurden ohne Blick auf Minutendaten gewählt;
  R = 1,5 % stammt aus dem S4-Kostentor, T aus der Rechnung in 2.1, k aus der Konvention „2–3 σ“.
- Holdout 2025+: nie geladen.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | Adversariale Prüfung durch ein anderes Modell (Fill-Regel, Kostenmodell, Look-ahead in der Referenz, Zufallsvergleich) | Cloud |
| O2 | 1m-Archive geladen, Lücken und Hash berichtet (P2) | Mac |
| O3 | Uzis Wort zu: (a) Lesart K6 wie S5 (Punktwert ≥ 95 %, Untergrenze ≥ 90 %), (b) Maker-Gebühr für Limit-Fills als Protokoll-Eintrag 1.3 | Uzi |
| O4 | Freigabe Version 1.0; Registrierung nur der Varianten, die das Gate 6.1 bestehen | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-25 | 0.1 | Entwurf: Maker-Mean-Reversion auf 1m-Kerzen (VWAP₃₀, k·σ₃₀-Limits, Post-only, Durchhandel-Regel mit δ), Stop 1 R = 1,5 %, Ziel T per Limit, Zeitstop 240 min, 6 Varianten k × T, Treffer = Netto > 0, K1–K10, n_min = 80 effektiv mit Tagescluster, Gate ≥ 160 Fills hochgerechnet, Fill-Prüfung an aggTrades, Zufallsvergleich mit gleichen Kosten, S6-Kostenmodell als Protokoll-Abweichung 1.3 | Uzis Wahl S6 (19:51) und „go“ (19:58) | Abschnitt 10; keine 1m-Daten, kein Holdout |
