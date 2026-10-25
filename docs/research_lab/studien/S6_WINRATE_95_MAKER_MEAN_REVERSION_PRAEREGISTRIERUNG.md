# Studie S6: Winrate ≥ 95 % mit positivem Netto-Erwartungswert durch Maker-Mean-Reversion (Präregistrierung)

| Feld | Wert |
|---|---|
| Version | **1.0 (freigegeben)** |
| Status | **FREIGEGEBEN UND REGISTRIERT.** Uzi 25.10. 23:45 Ortszeit (Entscheidungskarte „Ja, freigeben und registrieren“). Sechs Varianten im Register (`../REGISTER.jsonl`, m = 54), Protokoll-Eintrag 1.3 für A1–A5. Gate 6.1 bestanden (`../reports/s6_count_2026-10-25T2229Z.md`). Offen: Latenzprüfung 6.2 (P5), dann Training/Validierung (P6). Kein Ausstieg und kein R gerechnet. Holdout zu, nur per Entscheidungskarte. |
| Erstellt | 2026-10-25, 20:00 Ortszeit. Auftrag: Uzis Wahl „Neue Studie S6 mit anderer Familie“ (Entscheidungskarte 19:51) und „go“ zum Bauplan (19:58). 0.2 nach adversarialer Prüfung (anderes Modell, 17 Befunde, 20:15) |
| Freigabe | 2026-10-25, 23:45 Ortszeit, Uzi (Entscheidungskarte); O3 (a)–(c) und O4 damit erledigt |
| Bauplan | `/mnt/project-files/plaene/s6-maker-mean-reversion-bauplan.md` (Projektablage) |
| Vorgänger | S4 (Richtungs-Einstiege 1h): am Gate beendet, Einstiege unter Zufall (`S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md`). S5 (Funding-Carry): am Gate beendet, 0 hochgerechnete Episoden, 2022 ohne Einstieg (`S5_WINRATE_95_FUNDING_CARRY_PRAEREGISTRIERUNG.md`, `../reports/s5_count_2026-10-25T1836Z.md`) |
| Protokollbezug | `../PROTOKOLL.md` Version 1.1: Datensplit 3.2, Kosten 4.4, Zufallsvergleich 7.1, Holm 7.2, Robustheit 7.3, Ablauf 8, Stoppregeln 10. **Abweichungen mit Begründung in 5.5**, voran die Maker-Gebühr für Limit-Fills; Protokoll-Eintrag 1.3 vom 25.10. (freigegeben) |
| Kostenmodell | `CostModel` aus `src/research_lab/protocol.py` für Taker-Fills; neue Konstante `MAKER_FEE = 0,02 %` je Maker-Fill; Stress nach 5.3 |

Was dieses Dokument nicht ist: kein Profitversprechen, keine Anlageberatung, keine Freigabe für Papier- oder
Echtgeldbetrieb. Das Ergebnis darf und wird wahrscheinlich **NICHT BESTANDEN**, **KEIN URTEIL** oder **NICHT TESTBAR**
lauten (Abschnitt 2, 6 und 8).

---

## 1. Fragestellung

Gibt es unter den unten vorab festgelegten Regeln eine Strategie, die auf Daten, die bei ihrer Auswahl nie benutzt
wurden (Holdout 2025-01 bis 2026-09, genau ein Lauf), **gleichzeitig** erreicht: Netto-Trefferquote ≥ 95 % (Punktwert)
mit Untergrenze ≥ 90 %, positiver Netto-Erwartungswert auch unter Stress, Profitfaktor > 1, begrenzter Drawdown,
ausreichende Stichprobe, robuste Walk-Forward-Ergebnisse und ein Erwartungswert **über** zufälligen Einstiegen mit
gleicher Geometrie, gleichen Kosten und gleicher Volatilität?

Die Trefferquote wird **nie allein** optimiert. **Treffer = Netto-Ergebnis > 0 nach allen Kosten**, bei jedem
Ausstiegsgrund. Ziel T und Stop R sind vorab fest (4.2); es gibt kein Raster darüber hinaus.

## 2. Ausgangslage und Mathematik der 95 %

### 2.1 Was 95 % erzwingt

Mit Ziel T (in R), Gewinner-Kosten c_w und Verlierer-Kosten c_l (in R) ist E[R] = p·(T − c_w) − (1 − p)·(1 + c_l) und
die Gewinnschwelle p* = (1 + c_l) / (1 + c_l + T − c_w). Für 95 % **und** E[R] > 0 muss T > c_w + 0,0526·(1 + c_l) sein:
im S6-Kostenmodell **T > 0,083 R** (Basis) und **T > 0,114 R** (Stress). Ein Zufallsweg ohne Drift trifft +T R vor
−1 R mit Wahrscheinlichkeit 1 / (1 + T). Die Quote allein unterscheidet Zufall und Strategie nicht; S6 testet deshalb
den Zufallsvergleich (K2) auf dem Erwartungswert.

| Kostenmodell (R = 1,5 %) | c_w | c_l | T | p* | Zufall 1/(1+T) | p* − Zufall | E[R] bei genau 95 % |
|---|---|---|---|---|---|---|---|
| S6 Basis (Maker rein, Maker-Ziel, Taker-Stop; 5.3) | 0,027 R | 0,080 R | 0,15 | 89,8 % | 87,0 % | +2,8 | +0,063 R |
| | | | 0,20 | 86,2 % | 83,3 % | +2,8 | +0,111 R |
| | | | 0,25 | 82,9 % | 80,0 % | +2,9 | +0,158 R |
| S6 Stress (Gebühren, Slippage ×2) | 0,053 R | 0,160 R | 0,15 | 92,3 % | 87,0 % | +5,3 | +0,034 R |
| | | | 0,20 | 88,8 % | 83,3 % | +5,4 | +0,081 R |
| | | | 0,25 | 85,5 % | 80,0 % | +5,5 | +0,129 R |
| Protokoll 4.4 (alles Taker + Slippage) | 0,107 R | 0,120 R | 0,15 | 96,3 % | 87,0 % | +9,3 | −0,015 R |
| | | | 0,20 | 92,3 % | 83,3 % | +9,0 | +0,033 R |
| | | | 0,25 | 88,7 % | 80,0 % | +8,7 | +0,080 R |

Die Spalte „p* − Zufall“ sagt, wie viele Punkte der Einstieg besser sein muss als ein Zufallsweg, damit der
Erwartungswert überhaupt positiv wird. Das Ziel 95 % liegt noch darüber: Gegen den Zufall braucht S6 bei T = 0,15 /
0,20 / 0,25 einen Vorsprung von 8,0 / 11,7 / 15,0 Punkten. **Ein Ziel von 0,10 R wurde gestrichen** (Entwurf 0.1
hatte es): Dort läge die Stress-Schwelle bei 96,1 %, 95 % wären im Stress ein Verlust (K7 per Konstruktion verfehlt),
und K9 verlangte 95,7 %. Unter dem Protokoll-Kostenmodell ist T = 0,15 bei 95 % negativ; darum die Abweichung in 5.3,
und jeder Bericht weist beide Rechnungen nebeneinander aus.

### 2.2 Nachweis (Lesart K6 wie S5, Stichprobe größer)

Eine korrigierte Untergrenze ≥ 95 % (strenge Lesart aus S4, Niveau 1 − 0,05/60) braucht selbst bei null Verlierern
139 unabhängige Trades und mit 80 % Power bei wahrer Quote 98 % rund 620. S6 nutzt die Lesart aus S5 (Punktwert
≥ 95 %, einseitige 95-%-Untergrenze ≥ 90 % mit effektivem n) und sagt offen, dass das schwächer ist als in S4 geplant.
Anders als S5 hat S6 voraussichtlich genug Trades; darum ist **n_min = 160 effektive Trades** (Abschnitt 6), nicht 80:
Bei 80 wäre der Zufallsvergleich K2 selbst für eine echte Strategie meist nicht zu bestehen (6, Power-Tabelle).

### 2.3 Befunde aus S4 und S5 (nicht neu gerechnet)

- S4: Zehn 1h-Richtungs-Einstiege lagen 2020–2024 in allen 210 Ziel-/Stop-Zellen **unter** der Zufallsreferenz
  (höchstens 92 % bei E[R] < 0). Richtungs-Einstiege nach Struktur sind kein Kandidat.
- S5: Funding-Carry trifft plausibel oft, handelt aber zu selten (39–52 Episoden in fünf Jahren, 2022 null).

### 2.4 Warum Maker-Mean-Reversion (ökonomische Begründung)

Ein Limit-Kauf weit unter dem kurzfristigen Mittel wird nur gefüllt, wenn der Kurs in einer Minute stark fällt. Wer
dann hält, bekommt (a) die Maker-Gebühr statt der Taker-Gebühr, (b) keinen Spread und keine Slippage beim Einstieg und
(c) im Mittel den Teil des Ausschlags zurück, der Liquiditätsnot und nicht Information war. Der Gewinn je Trade ist
klein (T = 0,15–0,25 R), der Verlust bei Weiterlaufen voll (1 R). Dagegen spricht: Der Füllende ist genau dann dran,
wenn jemand dringend verkaufen musste, und in Trendminuten ist das Information (adverse Selektion). Ob (c) die
Verlierer trägt, ist die offene Frage; S4 zeigt, dass es für Richtungs-Einstiege nicht gilt. Der eigentliche Hebel
der 95 % ist der **weite Stop** (1,5 % bei etwa 0,05–0,1 % Minutenvolatilität): Verluste werden selten, aber groß.
Genau dagegen stehen K7, K8 und K9.

### 2.5 Ausgeschlossen

- „Halten bis grün“, Nachkauf, Grid, Martingale: Quote nur aus unbegrenzten Verlusten (Masterprompt).
- Orderbuch-Simulation (Queue-Position, Teilfills): nicht aus Kerzen oder aggTrades ableitbar. S6 ersetzt sie durch
  die Durchhandel-Regel (3), die Latenzprüfung an aggTrades (6.2) und einen Fill-Abschlag im Stress (5.3).
- Fill-Annahme „Berührung = Fill“: ausgeschlossen, weil sie Backtests von Limit-Strategien systematisch schönt.
- Stille Filter: Jede Minute, in der eine Order gefüllt worden wäre, führt zu einem Trade oder zu einem gezählten
  Verlierer (4.1, `both`). Es gibt keinen Weg, unangenehme Fills aus der Stichprobe zu nehmen.

## 3. Daten und Datenherkunft

| Datensatz | Quelle | Zeitraum | Stand |
|---|---|---|---|
| USD-M Perpetual **1m**-Kerzen BTCUSDT, ETHUSDT, SOLUSDT | data.binance.vision, monatliche Archive mit Prüfsumme (`src/research_lab/data/archive.py`, Intervall „1m“ vorhanden) | BTC/ETH ab 2020-01, SOL ab 2020-09 (Warm-up), gezählt ab 2020-10, bis 2024-12 | geladen 25.10. 20:04–20:13 Ortszeit (P2, 172 Monatsarchive mit Prüfsumme); Hashes, Tick je Monat und Lücken im Gate-Bericht `../reports/s6_count_2026-10-25T2229Z.md`; SOL hat zwei Archivlücken (26.–28.02.2022, 01.–02.04.2022); kein Kurs angesehen, nur Fills gezählt |
| USD-M Funding-Raten | wie oben, `Dataset.FUNDING`, Zeitstempel normalisiert wie S5 (`normalize_funding`) | wie oben | geladen (S4/S5) |
| aggTrades-Stichprobe (Latenzprüfung P5) | data.binance.vision Tagesarchive, Werkzeuge aus S2 (`src/research_lab/data/aggtrades.py`) | 10 Tage je Instrument aus dem Training, Ziehung mit Seed vor jedem Ergebnis | nicht geladen |
| Holdout 2025+ | gesperrt durch `HoldoutLocked` in `data/store.py` | ab 2025-01-01 | nie geladen |

**Kerzen, Fenster, Lücken.** Eine 1m-Kerze gilt ab ihrem Schluss als bekannt. Die Referenz (4.1) braucht die 121
geschlossenen Kerzen t−121 … t−1 lückenlos; fehlt eine, gibt es in Minute t keine Order (eine fehlende Minute sperrt
also bis zu 120 Minuten; das ist gewollt und wird gezählt, `no_reference`). Fehlende Minuten bis 5 min werden für
offene Trades überbrückt: keine Fills in der Lücke, auf der ersten Kerze danach wird der Stop gegen min(Stop, open)
geprüft. Lücken über 5 min schließen einen offenen Trade zur letzten Kerze davor zum Schlusskurs (Taker, `gap`,
Protokoll 3.1) und löschen offene Orders; der Bericht nennt zusätzlich das Ergebnis mit Schluss zur ersten Kerze nach
der Lücke (min(Stop, open)), weil der Protokoll-Weg bei Ausfällen in Crashs optimistisch sein kann.

**Preisschritt (Tick) und Marge δ.** Tick je Instrument und Monat = kleinste positive Differenz zwischen zwei
beliebigen Open/High/Low/Close-Werten des 1m-Archivs dieses Monats (empirisch, reproduzierbar, im Bericht je Monat
genannt). δ = max(0,01 % von L, 1 Tick). Stress verdoppelt δ. L, Stop und Ziel werden auf den Tick gerundet, immer
zuungunsten des Trades: Kauf-Limit abwärts, Verkaufs-Limit aufwärts, Long-Stop aufwärts (löst früher aus), Long-Ziel
aufwärts (weiter weg), Short spiegelbildlich.

**Durchhandel-Regel (Fill).** Ein Limit L gilt in Minute t als gefüllt, wenn der Kurs mindestens um δ **durch** L
gehandelt hat: Kauf-Limit, wenn `low_t ≤ L · (1 − δ)`; Verkaufs-Limit, wenn `high_t ≥ L · (1 + δ)`. Berührung zählt
nicht. Fill-Preis ist L (keine Kursverbesserung). **Post-only:** Eine Order wird nicht gestellt, wenn sie kreuzen
würde, geprüft gegen den letzten bekannten Kurs **und** die Eröffnung: Kauf nicht, wenn `close_{t−1} ≤ L` oder
`open_t ≤ L`; Verkauf spiegelbildlich (`skipped_cross`, gezählt). Die Eröffnung ist bei Orderaufgabe streng genommen
noch nicht bekannt; sie dient nur als zweiter Schutz gegen einen Taker-Fill, nie zugunsten des Trades.

**Zeitliche Aufteilung.** Training 2020-01-01 (SOL: 2020-10-01) bis 2022-12-31, Validierung 2023-01-01 bis
2024-12-31, **Holdout 2025-01-01 bis 2026-09-30** (21 Monate, fest), genau ein Lauf. Trades gehören zum Abschnitt
ihres Einstiegsfills (Protokoll 3.2). Kein Abschnitt rechnet über sein Ende hinaus: Ein offener Trade wird zur letzten
Kerze des Abschnitts zum Schlusskurs geschlossen (Taker, `section_end`) und zählt (Abweichung von Protokoll 3.2, das
Trades über die Grenze laufen lässt; benannt in 5.5).

## 4. Hypothesen-Register (eingefroren mit Version 1.0 am 25.10.)

### 4.1 Gemeinsame Regeln aller S6-Varianten

- **Instrumente und Seiten.** BTC, ETH, SOL USD-M Perpetual, Long und Short spiegelbildlich innerhalb derselben
  Variante. Je Instrument höchstens ein offener Trade und höchstens eine ruhende Order je Seite.
- **Nominal und R.** N = 1 000 USDT Nominal je Trade (für die aggTrades-Prüfung nötig; Ergebnisse in R sind davon
  unabhängig), q = N / Fill. **R = 1,5 % des Einstiegsfills** (fest; aus dem S4-Kostentor „Stop ≥ 1 %“ abgeleitet).
  Kein Hebel-Raster; Margin ist nicht Teil der Rechnung.
- **Referenz.** Zu Beginn jeder Minute t aus den **geschlossenen** Kerzen: VWAP₃₀ = Σ(close·volume) / Σ volume über
  t−30 … t−1 (Basisvolumen aus dem Archiv; bei Σ volume = 0 der einfache Mittelwert der Schlusskurse); σ₁ =
  Standardabweichung (Grundgesamtheit, ddof 0, Mittelwert abgezogen) der 120 Log-Renditen ln(close_i / close_{i−1})
  aus den 121 Schlusskursen t−121 … t−1; σ₃₀ = σ₁ · √30. Keine weiteren Indikatoren, kein Trend- oder Volumenfilter.
- **Orders.** In Minute t ruhen ein Kauf-Limit L_long = VWAP₃₀ · (1 − k·σ₃₀) und ein Verkaufs-Limit
  L_short = VWAP₃₀ · (1 + k·σ₃₀), jeweils auf den Tick gerundet (3), nur wenn sie nicht kreuzen und kein Trade offen
  ist. Orders gelten für diese eine Minute und werden in der nächsten Minute neu gestellt (Re-Pricing). Erfüllt
  dieselbe Minute die Durchhandel-Bedingung für **beide** Seiten, ist die Seite des Fills aus Kerzen nicht
  bestimmbar; S6 bucht dann einen **Verlierer-Trade** mit Ergebnis −(1 + c_l) R (Grund `both`, zählt in n, K6 und
  allen Kriterien). Nichts wird stillschweigend übersprungen.
- **Einstieg.** Fill zu L (Maker-Gebühr, keine Slippage) in Minute t. Stop und Ziel stehen ab Fill fest: Long
  Stop = Fill · (1 − 0,015), Ziel = Fill · (1 + T · 0,015), beide auf den Tick gerundet (3); Short spiegelbildlich.
- **Ausstieg.** Die Fill-Kerze zählt als Kerze 1 des Trades.
  - `stop`: Long `low ≤ Stop` → Fill zu min(Stop, open) mit `stop_slippage` und Taker-Gebühr; Short spiegelbildlich.
    **Der Stop wird schon in der Fill-Minute geprüft** (dort liegt open > L, also ist jeder Stand ≤ Stop zwingend nach
    dem Fill eingetreten; Fill zu Stop, nicht zu min(Stop, open)).
  - `target`: Long `high ≥ Ziel · (1 + δ)` (Durchhandel-Regel) → Fill zu Ziel, Maker-Gebühr. **Nicht** in der
    Fill-Minute (Reihenfolge innerhalb der Minute unbekannt, zuungunsten des Trades).
  - Treffen `stop` und `target` in derselben Minute zu, gilt **`stop`** (`ambiguous`, gezählt und berichtet).
  - `time`: kein Ausstieg bis zum Schluss der Kerze 240 (= Fill-Minute + 239) → Ausstieg zu deren Schlusskurs,
    Taker-Gebühr + Slippage.
  - `gap`, `section_end` wie Abschnitt 3.
- **Sperre.** Nach jedem Ausstieg 5 Minuten ohne Orders im Instrument; nach `stop`, `both` und `gap` 30 Minuten.
- **Funding.** Ein Funding-Zeitpunkt F (00/08/16 UTC, normalisiert) wird gebucht, wenn Einstiegsminute < Minute(F)
  ≤ Ausstiegsminute: Rate × N mit Vorzeichen nach Seite (Protokoll 4.4; Stress: nie zugunsten des Trades).
- **Netto-Ergebnis** je Trade in R: `(Richtung · (Aus − Ein) · q − Gebühren − Funding-Kosten) / (0,015 · N)`,
  Slippage steckt in den Fills. **Treffer** = Netto > 0. Alle Ausstiegsgründe zählen in K1–K10.
- Kein Nachkauf, keine Teilschließung, kein Trailing, keine Umschichtung. Es gibt kein Raster über R, Zeitstop, Fenster,
  Sperren, δ oder Referenz.

### 4.2 Varianten

Zwei geordnete Parameter, keine weiteren: Abstand k (in σ₃₀) und Ziel T (in R).

| Variante | k | T | Begründung |
|---|---|---|---|
| S6-k2-t15 | 2 | 0,15 R | häufige Fills; kleinstes Ziel, bei dem 95 % auch im Stress positiv bleibt (2.1) |
| S6-k2-t20 | 2 | 0,20 R | |
| S6-k2-t25 | 2 | 0,25 R | größter Puffer über den Kosten, Quote am schwersten |
| S6-k3-t15 | 3 | 0,15 R | seltene, extreme Ausschläge |
| S6-k3-t20 | 3 | 0,20 R | |
| S6-k3-t25 | 3 | 0,25 R | |

Sechs Varianten. Register m: 48 (Startbestand) + 6 = 54; **für alle Rechnungen in S6 gilt fest m = 60** (Obergrenze
des Protokolls, konservativ). **Alle Varianten, die das Gate (6.1) bestehen, kommen ins Register**, auch wenn sie
später im Training oder in der Validierung verworfen werden (Protokoll 6, m sinkt nie). Es gibt keine weiteren
S6-Varianten.

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

0. **Machbarkeits-Gate vor der Registrierung** (6.1) und **Latenzprüfung** (6.2) vor jedem Ergebnis.
1. **Training:** E[R] > 0 (S6-Kosten), mindestens **500 Trades** (Protokoll 8, Horizont Short) **und** mindestens
   160 effektive Trades (6), p < 0,10 gegen den Zufallsvergleich A (Abschnitt 7, unkorrigiert), Trefferquote Punktwert
   ≥ 95 % und Untergrenze (K6) ≥ 90 %. Diese Vorfilterung nach Trefferquote ist bewusst und benannt.
2. **Validierung (24 Monate):** mindestens 183 effektive Trades (160 × 24/21), E[R] > 0, p < 0,05 (unkorrigiert),
   Profitfaktor > 1,1, Drawdown ≤ K4, Trefferquote wie Schritt 1, alle Robustheitsregeln (5.4).
3. **Kandidatenliste einfrieren:** höchstens **zwei** Varianten (Protokoll 8, Schritt 3), je Ziel T höchstens eine,
   gewählt nach dem höchsten E[R] in der Validierung (nicht nach der Quote), mit Hash und Protokollversion committen,
   bevor Holdout-Daten geladen werden.
4. **Holdout,** genau ein Lauf, nur nach Uzis Entscheidung (Abschnitt 8).

### 5.2 Urteil im Holdout

| # | Bedingung | Schwelle |
|---|---|---|
| K1 | Netto-Erwartungswert (S6-Kosten) | > 0 R je Trade |
| K2 | schlägt den Zufallsvergleich A (Abschnitt 7) **auf E[R]** | Holm-Bonferroni, Familien-α 5 %, m = 60 (verworfene mit p = 1) |
| K3 | Mindeststichprobe (drei Instrumente zusammen) | ≥ 200 Trades (Protokoll K3, Short) **und** ≥ **n_min = 160 effektive Trades** (n_eff = ⌊n / D⌋, Abschnitt 6); darunter **KEIN URTEIL** |
| K4 | maximaler Drawdown der R-Kurve (1 % Risiko je Trade, Protokoll 4.3) | ≤ 20 R |
| K5 | Profitfaktor netto | > 1,0 |
| K6 | Trefferquote | **Punktwert ≥ 95 %** und einseitige **95-%-Untergrenze ≥ 90 %** (unkorrigiert) nach Clopper-Pearson mit n_eff = ⌊n / D⌋ und Verlierer_eff = ⌈Verlierer / D⌉, D = Designeffekt aus dem **Tagescluster über alle Instrumente** (Cluster = Kalendertag UTC; Varianz des Cluster-Mittels geteilt durch Binomialvarianz, mindestens 1; bei p̂ = 100 % gilt D = 1). Zusätzlich berichtet, kein Kriterium: D mit 4-Stunden-Blöcken. Ein Verfahren, keine Alternative |
| K7 | Stress (5.3: Gebühren und Slippage ×2, δ ×2, Funding nie zugunsten, **Fill-Abschlag λ**) | E[R] > 0 |
| K8 | keine versteckten Großverluste | größter Einzelverlust ≥ −2,0 R; mittlerer Verlust ≥ −1,2 R; `ambiguous` + `both` ≤ 5 % der Trades; `time` + `gap` + `section_end` zusammen ≤ 25 % der Trades |
| K9 | Gewinn je Treffer trägt die Verlierer | mittlerer Gewinn der Treffer ≥ 1,5 × (1 − Trefferquote) / Trefferquote × mittlerer Verlust der Verlierer |
| K10 | Breite | jedes Instrument ≥ 15 % der Trades; jede Seite (Long/Short) ≥ 25 % der Trades; E[R] je Instrument und Seite wird berichtet |

Urteile: **BESTANDEN (Holdout)** (alle K1–K10), **NICHT BESTANDEN**, **KEIN URTEIL** (K3 verfehlt).
Masterprompt-Vokabular: PASS / FAIL / INCONCLUSIVE. „BESTANDEN (Holdout)“ ist nicht das Protokoll-K5 (Papier-Betrieb).
Berichtet, aber kein Kriterium: Trefferquote und E[R] aller Zufallsvergleiche (7), alle Kennzahlen unter dem
Protokoll-Kostenmodell (alles Taker), Verteilung der Haltedauern, Fills je Tag, Anteile `skipped_cross`, `both`,
`no_reference`, Tick je Monat, Ergebnis der Latenzprüfung (6.2), Ergebnis mit `gap`-Schluss nach der Lücke (3).

**Offengelegt:** K6 mit effektivem n ist strenger als der Punktwert. Bei D = 2 und 320 Trades sind n_eff = 160 und
höchstens 9 effektive Verlierer erlaubt (Untergrenze 90,4 %), also höchstens 18 rohe Verlierer = 94,4 %; hier bindet
der Punktwert 95 %. Bei D = 3 wären es n_eff = 106 und 5 effektive Verlierer (15 rohe, 95,3 %): dann bindet die
Untergrenze. Beide Grenzen werden im Bericht nebeneinander gezeigt.

### 5.3 Kosten, genau einmal, und Stress

| Posten | Basis (S6) | Stress |
|---|---|---|
| Maker-Gebühr je Limit-Fill (Einstieg, `target`): `MAKER_FEE`, neu in `protocol.py` | 0,02 % | 0,04 % |
| Taker-Gebühr je Markt-Fill (`stop`, `time`, `gap`, `section_end`): `CostModel.fee` | 0,05 % | 0,10 % |
| Slippage bei `time`, `gap`, `section_end`: `CostModel.slippage` | 0,03 % | 0,06 % |
| Slippage bei `stop`: `CostModel.stop_slippage` | 0,05 % | 0,10 % |
| Slippage bei Limit-Fills | 0 (Fill zu L) | 0, aber δ verdoppelt |
| Funding, falls Zeitpunkt im Trade | historische Rate | nie zugunsten des Trades |
| **Fill-Abschlag λ** (6.2) | – | die λ·n Trades mit dem höchsten R werden gestrichen, λ ≥ 5 % |
| **Roundtrip Gewinner** (Maker + Maker) | **0,04 % = 0,027 R** | 0,08 % = 0,053 R |
| **Roundtrip Verlierer** (Maker + Taker-Stop + Stop-Slippage) | **0,12 % = 0,080 R** | 0,24 % = 0,160 R |

Protokoll 4.4 rechnet alle Fills als Taker, „auch wenn ein Limit-Einstieg denkbar wäre“. Der Grund ist die
Unsicherheit, ob ein Limit wirklich gefüllt worden wäre. S6 begegnet genau dieser Unsicherheit mit der
Durchhandel-Regel, der Post-only-Regel, der Latenzprüfung (6.2) und dem Fill-Abschlag im Stress und rechnet deshalb
Limit-Fills als Maker. Das ist eine Abweichung vom Protokoll, die Uzi vor Version 1.0 freigeben muss
(Protokoll-Eintrag 1.3, nur für Studien mit Durchhandel-Regel und Latenzprüfung). Jeder Bericht weist zusätzlich alle
Kennzahlen mit dem Protokoll-Kostenmodell aus. Gebührensätze gelten pauschal für 2020–2024 (historisch lag die
Taker-Gebühr zeitweise bei 0,04 %, die Annahme 0,05 % ist konservativ). Gebühren werden je Fill auf das Fill-Nominal
berechnet und genau einmal abgezogen; Slippage steckt in den Fills. Ein Test je Ausstiegsgrund belegt vor dem
Trainingslauf: Richtung · Kursdifferenz · q − Gebühren − Funding = Netto.

### 5.4 Robustheit (Protokoll 7.3)

- Jahresstabilität: E[R] > 0 in mindestens 60 % der Jahre mit ≥ 30 Trades (Training + Validierung; strenger als
  Protokoll ≥ 5).
- Walk-Forward: 24 Monate Anpassung / 6 Monate Test. Auswahl **über alle sechs Varianten** nach E[R] (Protokoll 7.3),
  in der Anpassung nur Trades mit Ausstieg bis Fensterende (`known_at`), im Test alle Trades mit Einstiegsfill im
  Fenster. Verketteter Test-Erwartungswert > 0 **und** verkettete Test-Trefferquote ≥ 90 % (Punktwert). Scheitert der
  Walk-Forward, ist die ganze Hypothese S6 für den Holdout gesperrt.
- Nachbarschaft: Jede Kandidatin braucht E[R] > 0 im Training bei **allen** direkten Nachbarn im Raster (gleiches T,
  anderes k; gleiches k, benachbartes T). Ein Nachbar, der das Gate nicht bestanden hat, wird für diese Prüfung
  trotzdem auf Training gerechnet (nicht registriert, nicht für den Holdout), damit die Regel nicht leerläuft.
- SPA/StepM wird berichtet, ist kein Kriterium (Protokoll-Änderungsprotokoll 23.10.).

### 5.5 Abweichungen vom Protokoll 1.2 (vollständig, Protokoll-Eintrag 1.3 vom 25.10.)

| # | Protokoll | S6 | Grund |
|---|---|---|---|
| A1 | 4.4: alle Fills Taker | Maker-Gebühr für Limit-Fills mit Durchhandel-Regel | 5.3 |
| A2 | 3.2 (Abschnittsregel 1.2 seit PR #429): am Abschnittsende offene Trades zählen in keinen Abschnitt | `section_end` schließt zur letzten Kerze des Abschnitts (Taker) und zählt; bei 240-min-Zeitstop höchstens ein Trade je Instrument und Abschnitt, Anteil im Bericht | kein Abschnitt liest Daten des nächsten; Zwangsschluss zählt als Kosten |
| A3 | 8/K3: Short ≥ 500 (Training) / ≥ 200 (Holdout) Trades | zusätzlich ≥ 160 effektive Trades (Tagescluster) | Fills clustern an Crash-Tagen |
| A4 | 7.1: Zufallsvergleich mit zufälligen Einstiegen | volatilitäts-gematcht (7, A), Pool-Methode wie R4(a) | sonst misst K2 Volatilität statt Einstieg |
| A5 | 3.1: `gap` schließt vor der Lücke | gleich, zusätzlich Bericht mit Schluss nach der Lücke | Transparenz |

### 6. Mindeststichprobe, Power, Gate und Latenzprüfung

Lesart K6 (Clopper-Pearson einseitig 95 %, Untergrenze ≥ 90 %), exakt nachgerechnet:

| n_eff | erlaubte Verlierer | Punktschwelle aus K6 | Untergrenze bei 0 Verlierern | Power bei p = 0,96 | p = 0,97 | p = 0,98 |
|---|---|---|---|---|---|---|
| 80 | 3 | 96,3 % | 96,3 % | 60 % | 78 % | 92 % |
| **160** | **9** | 94,4 % (Punktwert 95 % bindet) | 98,2 % | **89 %** | **98 %** | 100 % |
| 183 | 11 | 94,0 % | 98,4 % | 94 % | 99 % | 100 % |
| 320 | 22 | 93,1 % | 99,1 % | 100 % | 100 % | 100 % |

**n_min = 160 effektive Trades.** Training ≥ 500 Trades und ≥ 160 effektive, Validierung ≥ 183 effektive, Holdout ≥ 200
Trades und ≥ 160 effektive. Der Designeffekt D kommt aus dem Tagescluster über alle Instrumente (5.2); die Planung nimmt
D = 2 an (Gate-Schwellen 6.1).

**Power von K2 (offengelegt).** K2 muss im Holdout die Holm-Schwelle 0,05/60 (z ≈ 3,15) schaffen. Grobe Näherung mit
Streuung 0,33 R je Trade und einem Zufallsvergleich bei E[R] ≈ −0,03 R: Bei 160 Trades liegt die Erfolgswahrscheinlichkeit
selbst bei wahrer Quote 98 % nur um 50 %, bei 320 Trades und 97 % um 75 %, bei 320 und 98 % um 90 %. Die Clusterung
der Trades (Baseline unabhängig, Variante geclustert) macht K2 eher zu optimistisch; der Bericht zeigt zusätzlich einen
Tages-Block-Bootstrap der Variante. **Uzi muss vor dem Holdout wissen: Auch eine echte Strategie mit 97 % Quote
scheitert mit spürbarer Wahrscheinlichkeit an K2.** Das ist der Preis eines Einmalschusses mit 60 Registereinträgen.

#### 6.1 Machbarkeits-Gate (vor Registrierung, ergebnisblind bezüglich R)

Ein Zähllauf auf Training und Validierung zählt je Variante und Instrument die **Einstiegsfills** nach genau den
Regeln aus 3 und 4.1 (Referenz, Tick, Durchhandel-Regel, Post-only, `both`, Sperren) sowie `skipped_cross` und
`no_reference`. Dafür werden Kurse bis zum Fill gelesen, **kein Ausstieg und kein R**; der Zähler kennt weder Stop
noch Ziel. Die Sperren hängen vom Ausstieg ab; der Zähllauf nimmt konservativ an, dass jeder Trade den Zeitstop
(240 Kerzen) erreicht, und berichtet zusätzlich die Zahl ohne Sperren als Obergrenze. Er zählt außerdem die
**Fill-Tage** (Kalendertage UTC mit mindestens einem Fill, über alle Instrumente) als Zahl unabhängiger Cluster.
Hochrechnung: Dichte je Coin-Monat des **schwächsten Kalenderjahres, gepoolt über die drei Instrumente** (2020
zählt mit seinen 27 Coin-Monaten) × 63 Holdout-Coin-Monate; für Fill-Tage Dichte je Kalendermonat × 21.

- Variante mit hochgerechnet ≥ **320 Fills** (= n_min × D_Planung) **und** ≥ **160 Fill-Tagen** → wird registriert.
- Sonst → wird **nicht** registriert, im Bericht mit Zahlen genannt.
- Besteht keine Variante → **S6 ist nicht testbar**, Ende ohne Register-Eintrag und ohne Trainingslauf. Keine
  Lockerung im selben Entwurf.

Das Gate liest Kurse bis zum Fill und ist deshalb nur bezüglich der Ergebnisse blind, nicht bezüglich der
Marktphasen; wer die Zählung sieht, weiß, an welchen Tagen gefüllt wurde. Darum liegen alle Regeln, die den Ausstieg
betreffen, mit diesem Entwurf fest und werden nach dem Gate nicht mehr geändert. Die Zählung wird mit Commit und
Datensatz-Hash festgehalten, bevor irgendein Ergebnis gerechnet wird.

#### 6.2 Latenzprüfung an aggTrades (vor jedem Ergebnis, Paket P5)

Das Kerzen-Tief ist selbst ein echter Trade, darum ist „gab es Trades unter L(1 − δ)“ trivial erfüllt. Geprüft wird
stattdessen, was Kerzen nicht zeigen: Je Instrument werden 10 Kalendertage aus dem Training mit Seed **20261031**
gezogen (gleichverteilt über Tage mit mindestens einem Fill laut 6.1). Für jeden Fill dieser Tage wird aus den
aggTrades bestimmt: (a) der Zeitpunkt des ersten Trades ≤ L(1 − δ) (Kauf) bzw. ≥ L(1 + δ) in der Fill-Minute;
(b) ob in den ersten 3 Sekunden der Minute, während die Order gestellt wird und noch nicht im Buch liegt, bereits
Trades ≤ L lagen (Post-only hätte sie abgelehnt); (c) die kumulierte Menge zu Preisen jenseits L(1 − δ) ab (a),
einschließlich des Trades aus (a). Ein Fill gilt als **zweifelhaft**, wenn (a) in den ersten 3 Sekunden der Minute
liegt (Order noch nicht im Buch), (b) zutrifft, (c) < q ist oder kein Trade jenseits L(1 − δ) gefunden wird.
*Klarstellung 0.4 (vor der Prüfung, vor jedem Ergebnis):* 0.2 formulierte (b) als „irgendein Trade ≤ L vor (a)“. Der
Kurs muss L aber passieren, um L(1 − δ) zu erreichen, darum träfe das fast jeden Fill, obwohl eine ruhende Order dabei
regulär gefüllt wird; die wörtliche Zählung wird im Bericht zusätzlich ausgewiesen, entscheidet aber nicht über λ.
Die 10 Tage je Instrument werden aus der Vereinigung der Fill-Tage beider k-Familien gezogen (eine Ziehung, Seed
20261031, Instrumente in alphabetischer Reihenfolge); geprüft werden alle gezählten Fills beider Familien an diesen
Tagen, λ je Familie und gepoolt. Umsetzung: `src/research_lab/studies/s6_latency.py`, `scripts/research_lab_s6.py latency`;
die Tagesarchive der USD-M-Perpetuals werden gegen die Prüfsumme verifiziert, auf die Fill-Minuten reduziert und nicht
aufbewahrt. λ = Anteil zweifelhafter Fills, mindestens 5 %. λ geht als Fill-Abschlag in den Stress (5.3) ein. Liegt
λ > 25 %, wird δ **vor** dem ersten Trainingslauf in Schritten von 0,01 % erhöht, bis λ ≤ 25 %, mit Eintrag im
Änderungsprotokoll, und der Zähllauf 6.1 wird wiederholt. Diese Änderung ist nur strenger möglich. Die Prüfung liest
keine Ausstiege.

## 7. Zufallsvergleiche (Baselines)

Grundlage Protokoll 7.1, angepasst (Code neu in P4). Alle Baselines nutzen dieselben Ausstiegsregeln wie die
Variante (Stop 1 R, Ziel T R per Durchhandel-Regel, Stop-Prüfung ab der Einstiegsminute, Ziel ab der folgenden,
Zeitstop, `gap`, `section_end`) und dieselben Kosten (Maker-Gebühr am Einstieg und am Ziel, keine Slippage am
Einstieg), damit nur der Einstieg verglichen wird.

- **Baseline A (K2, volatilitäts-gematcht):** Pool aller Minuten je Instrument und Abschnitt mit vollständiger
  Referenz. Jeder Fill der Variante bekommt zufällige Vergleichsminuten aus demselben Instrument, demselben Abschnitt
  und demselben **σ₃₀-Dezil** (Dezile aus dem Pool des Abschnitts), Seite 50/50, Einstieg zum Eröffnungskurs der
  Minute. **Pool-Methode** (wie Protokoll-Änderung R4(a)): Je Dezil werden einmalig 2 000 Vergleichsminuten gezogen
  und ihre Trades deterministisch gerechnet; die 10 000 Läufe ziehen daraus mit Zurücklegen je Fill eine
  Vergleichsminute aus dem passenden Dezil. Kollisionen zwischen Vergleichstrades werden ignoriert (benannt).
  Statistik E[R] gepoolt, p = (1 + Läufe mit E[R] ≥ Variante) / 10 001. Seed **20261030**. Nullhypothese: „Ein
  Limit-Fill nach einem k·σ-Ausschlag hat keinen besseren Erwartungswert als ein Einstieg zu einer zufälligen Minute
  gleicher Volatilität mit gleichen Kosten und gleicher Geometrie.“
- **Baseline B (berichtet):** dieselben Fills **in Gegenrichtung** (Trend-Fortsetzung statt Rückkehr), gleiche
  Geometrie und Kosten. Zeigt, ob der Vorteil in der Richtung oder nur im Fill-Zeitpunkt liegt.
- **Baseline C (berichtet):** ungematchte Zufallsminuten (Protokoll 7.1 wörtlich), einmal mit S6-Kosten, einmal mit
  Protokoll-Kosten.
- Berichtet: Trefferquoten aller Baselines neben der der Variante; Tages-Block-Bootstrap der Variante (Blöcke =
  Kalendertage, 10 000 Ziehungen) als Streuungsmaß für E[R].

## 8. Holdout-Freigabe

Der Holdout 2025-01 bis 2026-09 wird nur nach Uzis ausdrücklichem Wort geöffnet, abgefragt per Entscheidungskarte vor
dem Lauf. Die Karte nennt Kandidatenliste (Hash), m, Protokollversion, die K2-Power aus Abschnitt 6 und den Ablauf.
Ein Lauf, danach ist der Holdout für S6 und für alle Registereinträge verbraucht; auch ein KEIN URTEIL (K3) verbraucht
ihn.

## 9. Arbeitspakete nach Freigabe

| # | Paket | Prüfbefehl |
|---|---|---|
| P1 | Entwurf 0.1 → adversariale Prüfung (anderes Modell) → 0.2 | erledigt 25.10., Befunde im Änderungsprotokoll |
| P2 | ~~1m-Klines USD-M BTC/ETH/SOL 2020–2024 auf dem Mac laden~~ erledigt 25.10. (172 Archive, Hashes/Lücken/Ticks im Gate-Bericht) | erledigt |
| P3 | ~~Zähllauf 6.1~~ erledigt 25.10. 23:29 Ortszeit, Commit 3be449f: alle sechs Varianten bestehen (`../reports/s6_count_2026-10-25T2229Z.md`) | erledigt |
| P4 | Code (Motor und Zähllauf in `hypotheses/s6.py`, Kennzahlen/Urteil/Baselines in `studies/s6_eval.py`, 18 Tests grün, Commits 6828e04 und 3be449f; offen: `MAKER_FEE` in `protocol.py` erst mit Protokoll-Eintrag 1.3, Baseline C, Latenzprüfung): `hypotheses/s6.py` (Referenz, Tick, Orders, Post-only, Durchhandel-Regel, `both`, Ausstiege inkl. Stop in der Fill-Minute, Sperren, Funding), `MAKER_FEE` und S6-Stress in `protocol.py` (mit Protokoll-Eintrag 1.3), Baselines A/B/C nach 7, Tests: Referenz nur aus geschlossenen Kerzen (121 Schlusskurse), Post-only gegen close und open, δ und Tick-Rundung zuungunsten, `ambiguous` = Stop, Stop in der Fill-Minute, Ziel nicht in der Fill-Minute, Zeitstop Kerze 240, Gebühren genau einmal je Ausstiegsgrund, Funding-Grenzfälle, Lücken ≤ 5 min und > 5 min, `section_end`, `both` als Verlierer, Fill-Abschlag | `pytest tests/test_research_lab_s6.py` grün, Cloud-Suite grün |
| P5 | Latenzprüfung 6.2 an aggTrades (30 Tage, ~3–9 GB Download auf dem Mac, nur ohne CI-Job); Code fertig (`s6_latency.py`, 9 Tests), Lauf steht aus | λ bestimmt; bei λ > 25 % δ erhöhen und P3 wiederholen |
| P6 | Training und Validierung auf dem Mac (nicht während CI-Jobs), Bericht; Register-Eintrag für alle Gate-Varianten | K1–K10, 5.4 |
| P7 | Holdout, genau ein Lauf, nur per Entscheidungskarte | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

- Alles aus S4 und S5 Abschnitt 10: 1h-Richtungs-Einstiege 2020–2024 (Trefferquoten, E[R], 210 Ziel-/Stop-Zellen),
  Funding-Statistiken 2020–2024, Carry-Episodenzahlen. Nichts davon betrifft 1m-Kerzen oder Limit-Fills.
- **1m-Kerzen: werden geladen, kein Kurs angesehen.** k, T, R, Fenster, Zeitstop, δ und Sperren wurden ohne Blick
  auf Minutendaten gewählt; R = 1,5 % stammt aus dem S4-Kostentor, T aus der Rechnung in 2.1 (T = 0,10 nach der
  Prüfung gestrichen, bevor Daten vorlagen), k aus der Konvention „2–3 σ“.
- Holdout 2025+: nie geladen.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | ~~Adversariale Prüfung durch ein anderes Modell~~ erledigt 25.10. (17 Befunde, alle in 0.2 eingearbeitet, Änderungsprotokoll) | erledigt |
| O2 | ~~1m-Archive geladen, Lücken, Tick je Monat und Hash berichtet (P2)~~ erledigt 25.10.; Gate 6.1 gelaufen, alle sechs Varianten bestehen (P3) | erledigt |
| O3 | ~~Uzis Wort zu (a) Lesart K6, (b) Abweichungen A1–A5 als Protokoll-Eintrag 1.3, (c) Kenntnisnahme der K2-Power~~ erledigt 25.10. 23:45 (Karte) | erledigt |
| O4 | ~~Freigabe Version 1.0; Registrierung aller sechs Varianten~~ erledigt 25.10. 23:45; Register m = 54. Latenzprüfung 6.2 läuft vor dem Training; bei λ > 25 % wird δ erhöht und der Zähllauf wiederholt (Änderungsprotokoll) | erledigt |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-25 | 0.1 | Entwurf: Maker-Mean-Reversion auf 1m-Kerzen (VWAP₃₀, k·σ₃₀-Limits, Post-only, Durchhandel-Regel mit δ), Stop 1 R = 1,5 %, Ziel T ∈ {0,10, 0,15, 0,20} per Limit, Zeitstop 240 min, 6 Varianten k × T, Treffer = Netto > 0, K1–K10, n_min = 80 effektiv mit Tagescluster, Gate ≥ 160 Fills hochgerechnet, Fill-Prüfung an aggTrades, Zufallsvergleich mit gleichen Kosten, S6-Kostenmodell als Protokoll-Abweichung 1.3 | Uzis Wahl S6 (19:51) und „go“ (19:58) | Abschnitt 10; keine 1m-Daten, kein Holdout |
| 2026-10-25 | 0.2 | Nach adversarialer Prüfung (anderes Modell, 17 Befunde): Stop wird schon in der Fill-Minute geprüft (Crash-Minuten zählten sonst nie als Verlust); T = 0,10 gestrichen, T = 0,25 ergänzt (Stress-Schwelle 96,1 %, K9 95,7 % bei 0,10); Formel T > c_w + 0,0526·(1 + c_l) statt symmetrischem c, Tabelle 2.1 neu gerechnet mit Stress-Zeile und E[R] bei 95 %; `skipped_both` → Verlierer-Trade `both` (kein stiller Filter); Cluster = Kalendertag über alle Instrumente, n_eff = ⌊n/D⌋, Verlierer_eff = ⌈Verlierer/D⌉, Doppelgrenze offengelegt; n_min 80 → 160 effektiv wegen K2-Power, Power-Tabelle und Warnung für Uzi; Gate ≥ 320 Fills und ≥ 160 Fill-Tage, schwächstes Jahr gepoolt, Blindheit des Gates präzisiert; Zufallsvergleich volatilitäts-gematcht (σ₃₀-Dezil) mit Pool-Methode, Baselines B (Gegenrichtung) und C (ungematcht), Tages-Block-Bootstrap; Register: alle Gate-Varianten, Kandidaten ≤ 2, Training ≥ 500 / Holdout ≥ 200 Trades (Protokoll), K4 in der Validierung, Walk-Forward über alle Varianten, Nachbarn ohne Gate werden für die Nachbarschaftsregel mitgerechnet; Abweichungstabelle 5.5 (A1–A5); Post-only zusätzlich gegen close_{t−1}; Latenzprüfung statt Mengenprüfung, Fill-Abschlag λ im Stress; Tick empirisch je Monat, Rundung zuungunsten; Referenz exakt (121 Schlusskurse, ddof 0, Basisvolumen); Funding-Grenzfälle; Zeitstop = Kerze 240; Lücken: Fenster-Regel, Stop nach überbrückter Lücke, Bericht mit Schluss nach der Lücke; Gebührenhistorie benannt; 139 statt 137 bei m = 60; Nummerierung berichtigt | O1 | unverändert; 1m-Daten im Download, kein Kurs angesehen, kein Holdout |
| 2026-10-25 | 0.3 | Gate 6.1 ausgewertet (Zähllauf auf dem Mac, Commit 3be449f, 23:29 Ortszeit): alle sechs Varianten bestehen, k = 2 hochgerechnet 2 770 Fills / 621 Fill-Tage, k = 3 572 / 333 (Schwellen 320 / 160); Datenbefunde (SOL-Archivlücken Feb/Apr 2022, empirische Ticks, Post-only selten) im Bericht; P2/P3/O2 erledigt; Kennzahlen-, Urteils- und Baseline-Code (P4) ergänzt. Keine Regel geändert. | P3 | 1m-Fills und Fill-Tage je Variante/Instrument/Jahr gesehen (Marktphasen der Fills bekannt, 6.1); kein Ausstieg, kein R, kein Holdout |
| 2026-10-25 | 0.4 | Latenzprüfung 6.2 präzisiert, bevor sie läuft: (b) = Trades ≤ L in den ersten 3 s (Orderaufgabe), wörtliche Lesart nur zur Offenlegung; (c) ab und einschließlich (a); „kein Trade jenseits L(1 − δ)“ zählt als zweifelhaft; Ziehung aus der Vereinigung der Fill-Tage beider Familien. Zähllauf intern auf `list_fills` umgestellt (Test belegt identische Zählung zur Gate-Fassung 3be449f). Keine Fill-, Ausstiegs- oder Kostenregel geändert. | P5 | wie 0.3; keine aggTrades gelesen, kein Ausstieg, kein R, kein Holdout |
| 2026-10-25 | 1.0 | **Freigegeben** (Uzi, 23:45 Ortszeit, Entscheidungskarte): O3 (a)–(c) und O4 bejaht; sechs Varianten registriert (`REGISTER.jsonl`, m = 54), Protokoll-Eintrag 1.3 für A1–A5, `MAKER_FEE` in `protocol.py`. Regeln aus 0.4 unverändert eingefroren. | Freigabe | wie 0.4; kein Ausstieg, kein R, keine aggTrades, kein Holdout |
| 2026-10-25 | 1.0 | Nachtrag ohne Regeländerung: Der Protokoll-Eintrag für A1–A5 trägt die Nummer 1.3, weil PR #429 (Abschnittsregel 3.2, Universum/Survivorship) am selben Abend als 1.2 gemergt wurde; A2 bezieht sich jetzt auf die Abschnittsregel 1.2. Jeder S6-Bericht nennt die Universum-Grenze (`UNIVERSE_LIMITATION`). | Merge platform-main | unverändert |
