# Studie S5: Winrate ≥ 95 % mit positivem Netto-Erwartungswert durch Funding-Carry (Präregistrierung)

| Feld | Wert |
|---|---|
| Version | 0.2 (Entwurf nach adversarialer Prüfung) |
| Status | **ENTWURF.** Nichts ist gerechnet. Freigabe durch Uzi steht aus (Abschnitt 11). Varianten kommen erst nach dem Machbarkeits-Gate (6.1) ins Register. |
| Erstellt | 2026-10-25, Auftrag Uzi 18:38 Ortszeit: „ich will eine winrate von 95% haben“; Entwurfsentscheidungen auf Uzis Wort „ich agiere nach deiner empfehlung“ (18:51) |
| Vorgänger | S4 (`S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md`): am Machbarkeits-Gate beendet; Erkundungen zeigten für 1h-Richtungs-Einstiege 38–53 % Trefferquote und in jeder Ziel-/Stop-Geometrie E[R] < 0 (`../reports/s4_hitrate95_2026-10-25T1733Z.md`) |
| Protokollbezug | `../PROTOKOLL.md` Version 1.1: Datensplit 3.2, Kosten 4.4, Zufallsvergleich 7.1, Holm 7.2, Robustheit 7.3, Ablauf 8, Stoppregeln 10. **Abweichung mit Begründung:** Stressregel für Funding-Gutschriften (5.3), braucht Protokoll-Eintrag 1.2 auf Uzis Wort |
| Kostenmodell | `CostModel` / `BASE_COSTS` aus `src/research_lab/protocol.py` für die Perp-Seite; neue Konstante `SPOT_FEE = 0,10 %` je Spot-Fill; Stress nach 5.3 |
| Bauplan | `/mnt/project-files/plaene/s5-winrate-95-bauplan.md` (Projektablage, 25.10. 19:45 Ortszeit) |

Was dieses Dokument nicht ist: kein Profitversprechen, keine Anlageberatung, keine Freigabe für Papier- oder Echtgeldbetrieb.
Das Ergebnis darf und wird wahrscheinlich **NICHT BESTANDEN**, **KEIN URTEIL** oder **NICHT TESTBAR** lauten (Abschnitt 2 und 6).

---

## 1. Fragestellung

Gibt es unter den unten vorab festgelegten Regeln eine Strategie, die auf Daten, die bei ihrer Auswahl nie benutzt
wurden (Holdout 2025-01 bis 2026-09, genau ein Lauf), **gleichzeitig** erreicht: Netto-Trefferquote ≥ 95 % (Punktwert)
mit Untergrenze ≥ 90 %, positiver Netto-Erwartungswert auch unter Stress, Profitfaktor > 1, begrenzte realisierte **und
unrealisierte** Verluste, ausreichende Stichprobe und robuste Walk-Forward-Ergebnisse?

Die Trefferquote wird **nie allein** optimiert. Es gibt kein Raster über Ziel oder Stop, denn S5 hat weder Ziel noch
Stop: Ein Trade ist eine Carry-Episode, und gewonnen hat sie, wenn nach allen Kosten mehr Geld da ist als vorher.

## 2. Ausgangslage und Mathematik der 95 %

### 2.1 Was 95 % erzwingt

Bei 95 % Treffern bleibt pro 20 Trades ein Verlierer. Der mittlere Gewinn muss deshalb mindestens **1/19 des mittleren
Verlusts plus Kosten** betragen, sonst ist der Erwartungswert negativ. Für einen Zufallsweg ohne Kosten ist die Chance,
+T R vor −1 R zu treffen, 1 / (1 + T); 95 % entsprechen T = 0,053 R. **Die Trefferquote allein kann Zufall und Strategie
nicht unterscheiden.** Deshalb testet S5 den Zufallsvergleich (K2) auf dem Erwartungswert, nicht auf der Quote.

### 2.2 Was 95 % als Nachweis kostet (Rechnung, Abschnitt 6)

Eine **korrigierte** Untergrenze ≥ 95 % (Niveau 1 − 0,05/54, die strenge Lesart aus S4) ist mit Clopper-Pearson selbst
bei null Verlierern erst ab 137 unabhängigen Episoden erreichbar; bei 80 % Power und wahrer Quote 98 % wären es rund
620 unabhängige, mit Abhängigkeit zwischen den Instrumenten weit über 1 000 Episoden. Carry-Episoden dauern Tage bis
Wochen und kosten je 0,42 R (5.3): 1 000 Episoden in 21 Monaten wären 420 R Kosten bei historisch 25–30 R Funding je
Instrument. **Die strenge Lesart und ein positiver Erwartungswert schließen sich für Carry rechnerisch aus.** S5 nutzt
deshalb die Lesart in 5.2 K6 (Punktwert ≥ 95 %, unkorrigierte 95-%-Untergrenze ≥ 90 %) und sagt offen, dass das ein
schwächerer Nachweis ist als in S4 geplant. Die Mehrfachtest-Korrektur bleibt vollständig bei K2 (Holm, m = 54).

### 2.3 Befund aus S4 (heute, nicht neu gerechnet)

Die zehn 1h-Richtungs-Einstiege aus S4 lagen auf 2020–2024 in allen 210 Ziel-/Stop-Kombinationen **unter** der
Zufallsreferenz (höchstens 92 % bei E[R] < 0). Richtungs-Einstiege dieser Art sind kein Kandidat für 95 %.

### 2.4 Warum Funding-Carry (ökonomische Begründung)

Auf Binance USD-M zahlen alle 8 Stunden die Long-Seiten den Shorts eine Funding-Gebühr, wenn der Perpetual über dem
Spot-Index handelt (Rate = Zinsanteil 0,01 % + Prämie, geklemmt). Wer Spot long und denselben Betrag Perpetual short
hält, ist kursneutral und kassiert diese Gebühr. Der Gewinn je Periode ist klein und fast sicher; Verluste entstehen aus
Kosten, aus einer Bewegung der Basis (Spot minus Perpetual) während der Haltezeit und aus einer erzwungenen Schließung
der Short-Seite. Das ist die einzige in TIM mit vorhandenen Daten prüfbare Familie, bei der eine Trefferquote von 95 %
**je Trade** plausibel ist, ohne dass sie über unbegrenzte Verluste erkauft wird. Dagegen spricht: Die Kosten einer
Episode (0,42 R) entsprechen 14–42 Funding-Perioden, kurze Episoden verlieren also fast immer. Darum hat S5 eine
Mindesthaltedauer (4.1).

Vorprüfung am 25.10. (nur Funding-Archiv 2020–2024, nur Vorzeichen und Summen, keine Strategie gerechnet, Abschnitt 10):
Nach einer Periode mit Rate > 0,01 % ist die nächste Periode bei BTC und ETH in 99,9 % positiv und in 84 % (BTC) bzw.
87 % (ETH) wieder > 0,01 %. Die 99,9 % sind großteils eine Folge der Binance-Formel (Zinsanteil 0,01 % als Massenpunkt),
kein Hinweis auf einen Vorteil. Jahressummen der Rate: BTC 17,2 / 30,6 / 4,2 / 7,9 / 12,0 % (2020–2024), ETH 27,5 / 37,5 /
0,8 / 8,3 / 13,0 %, SOL −4,0 / 28,6 / −38,0 / 1,3 / 13,7 %. 2022 ist dünn, SOL 2022 stark negativ. Nach Kosten kann S5
daran scheitern. Diese Vorprüfung hat Training **und** Validierung angesehen; θ und die Haltedauer sind dagegen nicht
blind (Abschnitt 10).

### 2.5 Ausgeschlossen

- „Halten bis grün“ ohne Begrenzung: Die Quote entsteht dort nur aus unbegrenzten Verlusten (Masterprompt). S5 begrenzt
  deshalb auch **unrealisierte** Verluste (K11) und die Dauer.
- Maker-Mean-Reversion mit weitem Stop: nach 2.3 Erwartung NICHT BESTANDEN, verbraucht Holdout-Plätze; auf Uzis Wort
  (18:51) nicht aufgenommen.

## 3. Daten und Datenherkunft

| Datensatz | Quelle | Zeitraum | Stand |
|---|---|---|---|
| USD-M Perpetual 1h-Kerzen BTCUSDT, ETHUSDT, SOLUSDT | data.binance.vision, monatliche Archive mit Prüfsumme (`src/research_lab/data/archive.py`) | BTC/ETH ab 2020-01, SOL ab 2020-09 (Warm-up), gezählt ab 2020-10 | geladen (S4) |
| USD-M Funding-Raten (alle 8 h) | wie oben, `Dataset.FUNDING` | wie oben | geladen (S4) |
| Spot 1h-Kerzen BTCUSDT, ETHUSDT, SOLUSDT | wie oben, `Market.SPOT` (Erweiterung auf ETH/SOL: Commit `ca6856f`) | BTC/ETH ab 2020-01, SOL ab 2020-08 (Listing 2020-08-11), Archive bei Binance vorhanden (HTTP-Prüfung 25.10.) | Ladevorgang auf dem Mac läuft (P2) |
| Holdout 2025+ | gesperrt durch `HoldoutLocked` in `data/store.py` | ab 2025-01-01 | nie geladen |

Funding-Zeitpunkte sind 00:00, 08:00 und 16:00 UTC; ein Test belegt Abstand 8 h ± 1 min für alle drei Instrumente
(Abweichungen werden berichtet). Raten werden in ganzzahligen Einheiten von 10⁻⁸ verglichen, nie als Float. Die zum
Zeitpunkt t gezahlte Rate r_t gilt als **ab t bekannt**; S5 nutzt sie frühestens zur Eröffnung der Stundenkerze, die um
t + 1 h beginnt (eine Stunde Sicherheitsabstand). Perp- und Spot-Kerzen werden nach Eröffnungszeit gepaart; fehlt eine
Kerze in einer der beiden Reihen, gilt die Stunde für beide als Lücke. Bekannte Lücken in den SOL-Archiven (2022-02:
72 h, 2022-04: 48 h) werden übernommen; eine Episode, die in eine Lücke läuft, wird zur letzten gemeinsamen Kerze vor
der Lücke mit Schlusskursen geschlossen (`gap`) und zählt als Episode.

### 3.1 Zeitliche Aufteilung

Training 2020-01-01 (SOL: 2020-10-01) bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31, **Holdout 2025-01-01 bis
2026-09-30 (21 Monate, fest, unabhängig vom Laufdatum)**, genau ein Lauf. Episoden gehören zum Abschnitt ihres
Einstiegs (Protokoll 3.2). **Kein Abschnitt rechnet über sein Ende hinaus:** Eine am Abschnittsende offene Episode wird
zur letzten Kerze des Abschnitts mit Schlusskursen geschlossen (`section_end`, Kosten und bis dahin gutgeschriebenes
Funding gebucht) und zählt als Episode. Training und Validierung laden nie Daten ab 2025-01-01.

## 4. Hypothesen-Register (wird mit Version 1.0 eingefroren)

### 4.1 Gemeinsame Regeln aller S5-Varianten

- **Trade = Episode.** Eine Episode beginnt mit dem gleichzeitigen Kauf von q Coins Spot und dem Verkauf von q Coins
  Perpetual und endet mit der gleichzeitigen Auflösung beider Seiten. Je Instrument höchstens eine offene Episode.
- **Nominal und Kapital.** N = 1 (Einheit), q = N / Perp-Einstiegsfill (nicht gerundet). **R = 1 % von N.** Kein
  Hebel: Die Short-Seite ist mit 100 % ihres Nominals besichert (Isolated Margin, 1×). **Gebundenes Kapital je Episode
  ist 2 N** (Spot N + Margin N), bei drei Instrumenten bis 6 N. Ergebnisse in R sind Prozent des Nominals; der Bericht
  nennt zusätzlich die Rendite auf das gebundene Kapital und den USDT-Zins als Vergleich (Opportunitätskosten, kein
  Kriterium).
- **Einstieg.** Zum Funding-Zeitpunkt t mit r_t > θ, ohne offene Episode und mit erfüllter Wiedereinstiegssperre:
  Signal. Fill beider Seiten zur Eröffnung der 1h-Kerze, die um t + 1 h beginnt (Spot-Open für die Long-Seite,
  Perp-Open für die Short-Seite), Slippage gegen sich. Fehlt die Kerze um t + 1 h, verfällt das Signal
  (`invalid_signals`, wird berichtet).
- **Mindesthaltedauer H** (4.2): Vor Ablauf von H Tagen ab Einstiegsfill gibt es keinen regulären Ausstieg.
- **Ausstieg.** Zum ersten Funding-Zeitpunkt t′ ≥ Einstiegsfill + H mit r_t′ ≤ 0 (Rate in 10⁻⁸-Einheiten ≤ 0): Fill
  beider Seiten zur Eröffnung der Kerze um t′ + 1 h. Die auslösende Rate r_t′ wird noch gebucht (sie ist ≤ 0, also
  konservativ). Eine Episode hat **keinen** Zeit-Stop und kein Kursziel, aber eine **Höchstdauer** von 90 Tagen
  (`max_hold`, Fill zur ersten Kerzeneröffnung nach Ablauf).
- **Erzwungene Schließung** (`forced_close`): Sobald das Hoch einer **geschlossenen** Perp-Kerze ≥ 1,8 × Perp-Einstiegsfill
  ist, Fill beider Seiten zur Eröffnung der nächsten Kerze, Perp-Seite mit `stop_slippage`. Sicherung der 1×-Short-Seite
  (vereinfachte Liquidation, rund 20 % Puffer). Fällt ein Funding-Zeitpunkt genau auf den Fill-Zeitpunkt, wird er
  **nicht** gutgeschrieben (zugunsten des Setups wird im Zweifel nicht gebucht).
- **Wiedereinstiegssperre.** Nach jedem Ausstieg (regulär, `max_hold`, `gap`, `section_end`) ist der nächste Einstieg
  frühestens zum **zweiten** Funding-Zeitpunkt nach dem Ausstiegsfill möglich; nach `forced_close` frühestens zum
  **vierten** (≥ 24 h). Das verhindert zerhackte Episoden.
- **Funding-Gutschrift.** Zu jedem Funding-Zeitpunkt t″ mit Einstiegsfill < t″ < Ausstiegsfill, plus t″ = Ausstiegsfill
  nur beim regulären Ausstieg (dort ist r_t″ ≤ 0), erhält die Short-Seite r_t″ × q × Perp-Schluss der Kerze, die um t″
  endet (Näherung für den Mark-Preis; Gutschrift negativ, wenn r_t″ < 0).
- **Netto-Ergebnis** je Episode in N:
  `Funding-Summe + q·(PerpEin − PerpAus) + q·(SpotAus − SpotEin) − 0,0005·q·(PerpEin + PerpAus) − 0,0010·q·(SpotEin + SpotAus)`,
  Fills inklusive Slippage. **Treffer** = Netto-Ergebnis > 0. Ergebnisse werden nach Ausstiegsgrund berichtet
  (`regular`, `max_hold`, `forced_close`, `gap`, `section_end`); alle zählen als Episoden und in K1–K11.
- **Mark-to-Market-Kurve** je Episode, stündlich: aufgelaufenes Funding + q·(PerpEin − PerpSchluss) + q·(SpotSchluss −
  SpotEin) − volle Roundtrip-Kosten. Daraus K4 und K11.
- Kein Nachkauf, keine Teilschließung, keine Umschichtung zwischen Instrumenten. Es gibt kein Raster über Nominal,
  Hebel, Ziel, Stop, Höchstdauer oder Sperrfristen.

### 4.2 Varianten

Zwei geordnete Parameter, keine weiteren: Einstiegsschwelle θ und Mindesthaltedauer H.

| Variante | θ (Einstieg: r_t > θ) | H | Begründung |
|---|---|---|---|
| S5-t01-h7 | 0,01 % (über dem Zinsanteil) | 7 Tage (21 Perioden) | Prämie vorhanden; Haltedauer deckt die Kosten bei ≥ 0,02 % je Periode |
| S5-t01-h21 | 0,01 % | 21 Tage (63 Perioden) | wie oben, Kosten bei ≥ 0,007 % je Periode gedeckt |
| S5-t03-h7 | 0,03 % | 7 Tage | nur bei klarer Prämie einsteigen |
| S5-t03-h21 | 0,03 % | 21 Tage | |

Vier Varianten. Register m: 48 (Startbestand) + 4 = 52; **für alle Rechnungen in S5 gilt fest m = 54** (konservativ,
deckt S4-Nachträge oder zwei weitere Einträge ab) ≤ 60 (Protokoll, Obergrenze). Registriert werden nur Varianten, die
das Gate (6.1) bestehen. Es gibt keine weiteren S5-Varianten.

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

0. **Machbarkeits-Gate vor der Registrierung** (6.1). Nur Varianten, die es bestehen, kommen ins Register.
1. **Training:** E[R] > 0 (Basiskosten), mindestens **n_min** Episoden (6), p < 0,10 gegen den Zufallsvergleich
   (Abschnitt 7, unkorrigiert), Trefferquote Punktwert ≥ 95 % und Untergrenze (Methode K6) ≥ 90 %. Die Vorfilterung
   nach Trefferquote ist hier bewusst und benannt.
2. **Validierung (24 Monate):** mindestens n_min × 24/21 Episoden, E[R] > 0, p < 0,05 (unkorrigiert), Profitfaktor
   > 1,1, K4 und K11 erfüllt, Trefferquote wie Schritt 1, alle Robustheitsregeln (5.4).
3. **Kandidatenliste einfrieren:** höchstens eine Variante je Haltedauer H, gewählt nach dem höchsten E[R] in der
   Validierung (nicht nach der Trefferquote), mit Hash und Protokollversion committen, bevor Holdout-Daten geladen werden.
4. **Holdout,** genau ein Lauf, nur nach Uzis Entscheidung (Abschnitt 8).

### 5.2 Urteil im Holdout

| # | Bedingung | Schwelle |
|---|---|---|
| K1 | Netto-Erwartungswert (Basiskosten) | > 0 R je Episode |
| K2 | schlägt den Zufallsvergleich (Abschnitt 7) **auf E[R]** | Holm-Bonferroni, Familien-α 5 %, m = 54 (verworfene mit p = 1) |
| K3 | Mindeststichprobe (drei Instrumente zusammen) | ≥ **n_min = 80 effektive Episoden** (n / D, Abschnitt 6); darunter **KEIN URTEIL** |
| K4 | maximaler Drawdown der **Mark-to-Market-Kurve** (alle Instrumente, stündlich) | ≤ 20 R (= 20 % von N, ≈ 3,3 % des gebundenen Kapitals bei drei Instrumenten) |
| K5 | Profitfaktor netto | > 1,0 (Basiskosten) |
| K6 | Trefferquote | **Punktwert ≥ 95 %** und einseitige **95-%-Untergrenze ≥ 90 %** (unkorrigiert) nach Clopper-Pearson mit effektivem n_eff = n / D, Treffer k_eff = ⌊k / D⌋, D = Designeffekt aus dem Monatscluster-Schätzer (Varianz des Cluster-Mittels geteilt durch Binomialvarianz, mindestens 1; bei p̂ = 100 % gilt D = 1). Ein Verfahren, keine Alternative |
| K7 | Stress (5.3: Kosten ×2, Funding-Gutschriften ×0,5) | E[R] > 0 |
| K8 | keine versteckten Großverluste (alle Ausstiegsgründe) | mittlerer Verlust ≥ −2,0 R; größter Einzelverlust ≥ −5,0 R; Mittel der schlechtesten 5 % der Episoden ≥ −3,0 R; `forced_close` ≤ 2 % der Episoden |
| K9 | Gewinn je Treffer trägt die Verlierer | mittlerer Gewinn der Treffer ≥ 1,5 × (1 − Trefferquote) / Trefferquote × mittlerer Verlust der Verlierer |
| K10 | Breite | jedes Instrument ≥ 15 % der Episoden; E[R] je Instrument wird nur berichtet |
| K11 | keine versteckten **unrealisierten** Verluste | schlechtester Mark-to-Market-Stand je Episode (MAE) ≥ −3,0 R für ≥ 99 % der Episoden und nie < −6,0 R; Anteil der Episodenstunden unter −1 R ≤ 10 % |

Urteile: **BESTANDEN (Holdout)** (alle K1–K11), **NICHT BESTANDEN**, **KEIN URTEIL** (K3 verfehlt). Masterprompt-
Vokabular: PASS / FAIL / INCONCLUSIVE. „BESTANDEN (Holdout)“ ist nicht das Protokoll-K5 (Papier-Betrieb); das wäre ein
eigenes Paket. Berichtet, aber kein Kriterium: Trefferquote des Zufallsvergleichs, Dauerverteilung der Episoden und
Trefferquote je Dauerklasse, Zeit bis zum ersten positiven Mark-to-Market-Stand, Roll-Carry-Benchmark (7).

### 5.3 Kosten, genau einmal, und Stress

| Posten | Basis | Stress |
|---|---|---|
| Perp-Gebühr je Fill (`CostModel.fee`) | 0,05 % | 0,10 % |
| Spot-Gebühr je Fill (`SPOT_FEE`, neu in `protocol.py`, Änderungsprotokoll-Eintrag nötig) | 0,10 % | 0,20 % |
| Slippage je Fill, beide Seiten (`CostModel.slippage`) | 0,03 % | 0,06 % |
| Slippage bei `forced_close` auf der Perp-Seite (`stop_slippage`) | 0,05 % | 0,10 % |
| Funding-Gutschriften | voll | **× 0,5** (positive Gutschriften halbiert, negative voll) |
| **Roundtrip je Episode** (2 Perp-Fills, 2 Spot-Fills, 4× Slippage) | **≈ 0,42 % von N = 0,42 R** (0,10 + 0,20 + 0,12) | **≈ 0,84 R** |

Protokoll 4.4 streicht im Stress alle Funding-Gutschriften (`CostModel.stressed()` setzt `funding_credits_allowed=False`).
Für eine Strategie, deren einzige Einnahme Funding ist, macht das K7 per Konstruktion unerfüllbar. S5 definiert den Stress
deshalb als Kosten ×2 **und** Gutschriften ×0,5. Das ist eine Abweichung vom Protokoll, die Uzi vor Version 1.0
freigeben muss (Protokoll-Eintrag 1.2, nur für Studien mit Funding als Einnahme); der Bericht weist zusätzlich das Ergebnis
mit Gutschriften = 0 aus (dort ist E[R] zwangsläufig negativ).

Gebühren werden je Bein auf das jeweilige Fill-Nominal berechnet und **genau einmal** abgezogen (Formel 4.1); Slippage
steckt in den Fills und wird nicht noch einmal als Kosten gebucht. Ein Test je Variante belegt vor dem Trainingslauf:
Funding-Summe + Basisergebnis aus den Fills − Gebühren = Netto, und Stress ergibt genau die halbierten Gutschriften bei
doppelten Kosten. Keine Zinsen auf die Spot-Seite, kein Verleih, kein Lending-Ertrag. Spot-Gebühr in der Basiswährung
(Mengenabschlag ≈ 0,1 %) wird als Gebühr auf das Nominal modelliert (Abweichung vernachlässigbar, benannt).

### 5.4 Robustheit (Protokoll 7.3)

- Jahresstabilität: E[R] > 0 in mindestens 60 % der Jahre mit ≥ 5 Episoden (Training + Validierung).
- Walk-Forward: 24 Monate Anpassung / 6 Monate Test. Auswahl je Haltedauer H zwischen ihren zwei θ-Varianten nach E[R],
  in der Anpassung nur Episoden mit Ausstieg bis Fensterende (`known_at`), im Test alle Episoden mit **Signalzeit t**
  im Fenster (`signalled_in`, Protokoll 1.1). Verketteter Test-Erwartungswert > 0 **und** verkettete Test-Trefferquote
  ≥ 90 % (Punktwert; niedriger als 95 %, weil 6-Monats-Fenster wenige Episoden haben). Scheitert der Walk-Forward einer
  Haltedauer, sind beide Varianten dieser Haltedauer für den Holdout gesperrt (Protokoll 7.3).
- Nachbarschaft: Jede Variante braucht E[R] > 0 im Training bei **allen** direkten Nachbarn (gleiches H, anderes θ; gleiches
  θ, anderes H), die das Gate bestanden haben. Hat kein Nachbar das Gate bestanden, entfällt die Regel und das wird berichtet.
- SPA/StepM wird berichtet, ist kein Kriterium (Protokoll-Änderungsprotokoll 23.10.).

## 6. Mindeststichprobe und Power (Planungsrechnung, vor jeder Auswertung)

Lesart K6: Clopper-Pearson, einseitig 95 %, Untergrenze ≥ 90 %. Nachgerechnet (exakt, Binomial):

| n_eff | erlaubte Verlierer | Untergrenze bei 0 Verlierern | Power bei p = 0,97 | p = 0,98 | p = 0,99 |
|---|---|---|---|---|---|
| 60 | 1 | 95,1 % | 46 % | 66 % | 88 % |
| **80** | **3** | 96,3 % | **78 %** | **92 %** | 99 % |
| 100 | 4 | 97,0 % | 82 % | 95 % | 100 % |
| 150 | 8 | 98,0 % | 96 % | 100 % | 100 % |

**n_min = 80 effektive Episoden** (bei D = 1,5: 120 Episoden). Training ≥ 80, Validierung ≥ 92 effektive Episoden.
Zum Vergleich die strenge Lesart (Untergrenze ≥ 95 % auf Niveau 1 − 0,05/54, z = 3,11): Wald-Näherung n_eff ≈ 705 /
211 / 60 für p = 0,97 / 0,98 / 0,99, exakt mit 80 % Power ≈ 1 559 / 620 / 293, Minimum bei null Verlierern 137. Sie ist
mit Carry nicht erreichbar (2.2).

Rechnerische Verträglichkeit mit K1: 120 Episoden kosten 50 R. Bei durchgängiger Investition liefern die Jahressummen aus
2.4 in 21 Monaten rund 25–30 R je Instrument (BTC/ETH), bei drei Instrumenten 50–80 R, in schwachen Jahren wie 2022
deutlich weniger. **K1 und K3 sind zusammen nur bei Funding mindestens auf Historienschnitt erreichbar.** Das ist vorab
bekannt und kein Grund zur Lockerung; Scheitern ist ein gültiges Ergebnis.

Der Designeffekt D wird nicht angenommen, sondern im Zähllauf (6.1) ergebnisblind aus der Episodenzahl je Monat und
Instrument geschätzt (Cluster = Kalendermonat); die Annahme D = 1,5 oben dient nur der Planung.

Nicht gewählt: die einzelne Funding-Periode als Trade-Einheit. Sie würde die Stichprobe verzehnfachen, aber die Perioden
einer Episode sind abhängig, und die Kosten müssten auf Perioden verteilt werden; beides öffnet das Ausreizen der Quote.

### 6.1 Machbarkeits-Gate (vor Registrierung, ergebnisblind)

Episodengrenzen hängen nur von Funding (θ, H, Vorzeichen), Höchstdauer, Lücken und Abschnittsenden ab, nicht vom
Ergebnis; `forced_close` hängt vom Kurs ab und wird im Gate **nicht** angewendet (der Unterschied wird im Bericht
beziffert). Ein Zähllauf auf Training und Validierung zählt je Variante und Instrument die Episoden nach genau den Regeln
aus 4.1 (inklusive Wiedereinstiegssperre, `max_hold`, `gap`, `section_end`), ohne Kurse und ohne R, und rechnet die
Episodendichte je Coin-Monat des **schwächsten Kalenderjahres** auf 63 Holdout-Coin-Monate (21 × 3) hoch.

- Variante ≥ **120** hochgerechnet (= n_min × 1,5 Sicherheitsfaktor) → wird registriert.
- Variante < 120 → wird **nicht** registriert, im Bericht mit Zahl genannt.
- Besteht keine Variante → **S5 ist nicht testbar.** Die Studie endet ohne Register-Eintrag und ohne Trainingslauf.
  Dann bleibt als ehrlicher Weg zu 95 % nur die prospektive Sammlung auf Papier über Jahre oder ein neuer Entwurf mit
  eigener Nummer. Keine Lockerung im selben Entwurf.

Zusätzlich, ebenfalls ohne Kurse: Für jede Episode wird die Funding-Summe aus dem Archiv (Rate × N, ohne Basis) gegen die
Roundtrip-Kosten 0,42 R gestellt. Liegt die Summe über alle Episoden einer Variante unter den Kosten, wird das als
Warnung berichtet (kein Gate, weil es ein Teilergebnis vorwegnimmt; es steht dann in Abschnitt 10 als gesehen).

Die Zählung wird mit Commit und Datensatz-Hash festgehalten, bevor irgendein Ergebnis gerechnet wird.

## 7. Zufallsvergleich (Baseline) und Benchmark

Grundlage Protokoll 7.1, angepasst an Episoden (Paket P4, Code neu):

- **Zufallsvergleich (K2):** zufällige **Einstiege** mit derselben Ausstiegsregel, derselben Mindesthaltedauer und allen
  übrigen Regeln aus 4.1. Jeder von 10 000 Läufen zieht je Instrument genauso viele Einstiegszeitpunkte wie die Variante
  im Abschnitt, gleichverteilt über alle Funding-Zeitpunkte, in zeitlicher Reihenfolge und unter Einhaltung von
  „höchstens eine offene Episode“ und der Wiedereinstiegssperre (ein gezogener Zeitpunkt, der kollidiert, wird neu
  gezogen; maximal 100 Versuche je Episode, sonst entfällt sie und das wird gezählt). Kosten, Gutschriften,
  `forced_close`, Lücken und Abschnittsenden wie bei der Variante. Statistik E[R] gepoolt.
  p = (1 + Läufe mit E[R] ≥ Variante) / 10 001. Seed **20261030**. Nullhypothese: „Der Funding-Filter θ weiß nichts,
  was ein zufälliger Einstiegszeitpunkt mit gleicher Haltelogik nicht auch wüsste.“
- **Roll-Carry-Benchmark (berichtet, kein Kriterium):** dauerhaft investiert ab dem ersten Funding-Zeitpunkt des
  Abschnitts, Ausstieg und Wiedereinstieg nur bei `forced_close`, `gap` und Abschnittsende, dieselben Kosten. E[R] je
  21 Monate und Trefferquote je Monat werden neben der Variante gezeigt.

## 8. Holdout-Freigabe

Der Holdout 2025-01 bis 2026-09 wird nur nach Uzis ausdrücklichem Wort geöffnet, abgefragt per Entscheidungskarte vor dem
Lauf. Die Karte nennt Kandidatenliste (Hash), m, Protokollversion und den Ablauf. Ein Lauf, danach ist der Holdout für S5
und für alle Registereinträge verbraucht; auch ein KEIN URTEIL (K3) verbraucht ihn.

## 9. Arbeitspakete nach Freigabe

| # | Paket | Prüfbefehl |
|---|---|---|
| P2 | Spot 1h BTC/ETH/SOL auf dem Mac laden (Prüfsummen, Lücken berichten); Archivmodul erweitert (`ca6856f`) | `research_lab_fetch --market spot --symbol …` ohne Fehler; Datensatz-Hash im Bericht |
| P3 | Zähllauf 6.1 mit Designeffekt-Schätzung, JSON mit Commit und Hashes | Hochrechnung je Variante ≥ 120? |
| P4 | Code: `hypotheses/s5.py` (Episodenlogik), **neuer Carry-Motor** (zwei Kerzenreihen, Funding nur bis t sichtbar, R = Netto / 0,01 N, Mark-to-Market, Ausstiegsgründe), `SPOT_FEE` und S5-Stress in `protocol.py` (mit Protokoll-Eintrag 1.2), Zufallsvergleich und Roll-Carry nach 7, Tests: Funding erst ab t, Einstieg t + 1 h, Gebühren genau einmal, Stress, `forced_close` ohne Gutschrift am Fill, Sperrfristen, Lücken in einer Reihe, `section_end`, Funding-Zeitstempel, Spot-Mikrosekunden ab 2025 (`parse.py`) | `pytest tests/test_research_lab_s5.py` grün, Cloud-Suite grün |
| P5 | Training und Validierung auf dem Mac (nicht während CI-Jobs), Bericht; Register-Eintrag nur bei Erfolg in beiden | K1–K11 in Training und Validierung |
| P6 | Holdout, genau ein Lauf, nur per Entscheidungskarte | Protokoll R6 |

## 10. Bis zur Erstellung gesehene Daten

- Alles aus S4 Abschnitt 10 sowie die S4-Erkundungen auf 2020–2024 (Trefferquoten und E[R] der zehn 1h-Varianten,
  210 Ziel-/Stop-Zellen). Diese Daten betreffen Richtungs-Einstiege, nicht Funding-Carry.
- Funding-Archiv 2020–2024 (BTC/ETH ab 2020-01, SOL ab 2020-10), Training **und** Validierung, nur: Anteil positiver
  Perioden (BTC 87,6 %, ETH 89,2 %, SOL 77,1 %), bedingte Anteile P(nächste > 0 | aktuelle > 0 / > 0,01 % / > 0,03 %) und
  P(nächste > 0,01 % | …), Jahressummen der Raten (2.4). θ ∈ {0,01 %, 0,03 %} wurde mit Kenntnis dieser Zahlen gewählt
  (nicht blind); H wurde aus den Kosten abgeleitet. **Keine** Episode, kein Kurs, keine Basis, kein Ergebnis einer
  S5-Regel gerechnet.
- Spot-Archive: nur Dateiexistenz bei Binance (HTTP-Status) für ETH 2020-01 und SOL 2020-08.
- Holdout 2025+: nie geladen.

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | ~~Adversariale Prüfung (anderes Modell)~~ erledigt 25.10., Befunde in 0.2 eingearbeitet (Änderungsprotokoll) | erledigt |
| O2 | Spot-Archive geladen, Lücken und Hash berichtet | Mac, P2 |
| O3 | Uzis Wort zu: (a) Lesart K6 (Punktwert ≥ 95 %, Untergrenze ≥ 90 %, unkorrigiert) statt strenger Lesart, (b) S5-Stressregel (Gutschriften ×0,5) als Protokoll-Eintrag 1.2 | Uzi |
| O4 | Freigabe Version 1.0; Registrierung nur der Varianten, die das Gate 6.1 bestehen | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-25 | 0.1 | Entwurf: Funding-Carry, 6 Varianten (θ × Ausstiegsregel), Trade = Episode, R = 1 % Nominal, K1–K10, n_min = 800, Machbarkeits-Gate, Zufallsvergleich mit gleichen Episodendauern | Uzis Ziel 95 % (18:38), Empfehlungen angenommen (18:51) | Abschnitt 10; keine S5-Ergebnisse, kein Holdout |
| 2026-10-25 | 0.2 | Nach adversarialer Prüfung (anderes Modell, 13 Befunde): Stichprobentabelle korrigiert (Wald-Fehler bei p = 0,98/0,99), strenge Lesart als für Carry rechnerisch unerreichbar belegt (137 Episoden bei null Verlierern, 420 R Kosten bei 1 000 Episoden) → K6 jetzt Punktwert ≥ 95 % und CP-Untergrenze ≥ 90 % (unkorrigiert, ein Verfahren, D aus Monatscluster), n_min = 80 effektive Episoden; Stress neu definiert (Protokoll streicht Gutschriften → K7 unerfüllbar), Protokoll-Eintrag 1.2 als offener Punkt; Mark-to-Market-Kurve mit K4 darauf und neuem K11 (MAE) gegen unrealisierte Verluste; Mindesthaltedauer H statt Ausstiegsregel e (Kosten 0,42 R brauchen 14–42 Perioden), Höchstdauer 90 Tage, Wiedereinstiegssperren; `section_end`, Holdout fest 2025-01 bis 2026-09, kein Abschnitt rechnet über sein Ende; Zufallsvergleich mit zufälligen Einstiegen bei gleicher Haltelogik, Roll-Carry-Benchmark; Gate mit Dichte des schwächsten Jahres × 1,5 und Designeffekt-Schätzung; m fest 54; K10 ohne Widerspruch; gebundenes Kapital 2 N; Formel je Bein; Funding-Zeitstempel-Test, ganzzahlige Raten; Walk-Forward-Folge und Nachbarschaft präzisiert; Motor als Neubau benannt | O1 | unverändert, keine S5-Ergebnisse, kein Holdout |
