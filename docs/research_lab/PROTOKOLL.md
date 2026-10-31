# TIM Research Lab – Forschungsprotokoll

| Feld | Wert |
|---|---|
| Version | 1.3 (Änderungsprotokoll am Ende) |
| Status | **FREIGEGEBEN** |
| Erstellt | 2026-09-29 |
| Freigabe | 2026-09-29, Uzi (1.0); 1.1 am 2026-10-22 und 1.2 am 2026-10-25 je mit dem Merge des PR durch Uzi; 1.3 am 2026-10-25 per Entscheidungskarte (S6) |
| Bezug | Bauplan „TIM Research Lab“ (Paket R0), TIM Constitution Band 8 |

Dieses Protokoll wird **vor dem ersten Test** festgeschrieben. Nach der Freigabe
(Version 1.0) darf es nur noch über das Änderungsprotokoll am Ende geändert werden.
Jede Änderung ist dort sichtbar, mit Datum, Grund und der Angabe, welche Daten zu
diesem Zeitpunkt schon angesehen wurden.

Was dieses Protokoll nicht ist: kein Profitversprechen, keine Anlageberatung und
keine Empfehlung für Hebel oder Positionsgrößen mit echtem Geld. Die Risikogröße
unten ist eine Messkonvention für den Backtest.

---

## 1. Fragestellung

Hat eine der unten registrierten Handelsideen für BTC auf Daten, die bei ihrer
Auswahl nie benutzt wurden, einen positiven Erwartungswert nach Kosten, der
zufällige Einstiege schlägt?

Zulässige Endergebnisse je Setup: **BESTANDEN**, **NICHT BESTANDEN** oder
**KEIN URTEIL** (zu wenige Trades). „Kein Vorteil“ ist ein vollwertiges Ergebnis
und wird genauso berichtet wie ein Treffer (Band 8, „Negative Results“).

## 2. Erfolgskriterium (vorab festgelegt)

Ein Setup gilt als profitabel, wenn es **alle fünf** Bedingungen erfüllt:

| # | Bedingung | Gemessen in | Schwelle |
|---|---|---|---|
| K1 | Erwartungswert nach Gebühren, Slippage und Funding | Holdout | > 0 R je Trade |
| K2 | schlägt zufällige Einstiege, korrigiert für alle registrierten Varianten | Holdout | Holm-Bonferroni, Familien-α = 5 %, m = Zahl aller Registereinträge (Abschnitt 7) |
| K3 | Mindestzahl an Trades | Holdout | Short ≥ 200, Mid ≥ 30, Long ≥ 10 |
| K4 | maximaler Drawdown | Holdout | ≤ **20 %** bei 1 % Risiko je Trade |
| K5 | Papier-Betrieb im erwarteten Band | R7, 4–8 Wochen | „bestätigt“ oder „kein Widerspruch“ (Abschnitt 9) |

Unterschreitet ein Setup K3, lautet das Urteil **KEIN URTEIL**, nicht BESTANDEN.
Für M1 mit N = 55 und für M2 ist das im Holdout von rund 20 Monaten wahrscheinlich,
das steht hier vorab fest.
Zusätzlich wird jedes Setup mit verdoppelten Kosten (Abschnitt 4.4) gerechnet.
Das Ergebnis des Stresstests wird immer berichtet. Ein Setup, das unter doppelten
Kosten einen negativen Erwartungswert hat, wird als „kostenempfindlich“ markiert.

## 3. Daten

### 3.1 Quellen

Nur öffentliche Binance-Archive (`data.binance.vision`), als eigene Dateien im Labor.
Die Produktions-DB von TIM wird weder gelesen noch beschrieben.

| Datensatz | Markt | Intervalle | Zweck |
|---|---|---|---|
| Klines BTCUSDT | USD-M Perpetual | 1d, 1h, 15m, 5m | Handelsinstrument für Mid und Short |
| Klines BTCUSDT | Spot | 1d | Signale und Kurse für den Long-Horizont |
| fundingRate BTCUSDT | USD-M Perpetual | je 8 h | Funding-Kosten und Hypothese M2 |
| aggTrades BTCUSDT | USD-M Perpetual | – | optional, nur Stichproben zur Prüfung der Delta-Näherung |

**Abweichung vom Bauplan:** Der Short-Horizont nutzt statt aggTrades die Spalte
„taker buy base volume“ der Klines. Daraus ergibt sich das Delta je Kerze als
`2 · taker_buy_volume − volume`, der CVD als laufende Summe. Das spart mehrere zehn
GB und gibt dem Short-Horizont denselben Zeitraum wie Mid. aggTrades dienen nur
dazu, diese Näherung an einzelnen Tagen zu prüfen.

Jede Datei wird gegen die offizielle `.CHECKSUM` geprüft (Code aus
`src/v2_readiness/backfill.py`). Jede Datensatzversion bekommt einen Hash
(Band 8, „Dataset Rules“). Fehlende Kerzen werden gezählt und gelistet, nicht
aufgefüllt. Läuft ein Trade in eine Lücke, wird er zum letzten Kurs vor der Lücke
geschlossen und gezählt. Verwerfen würde mit späterem Wissen entscheiden und
Ausfälle in Crash-Phasen verschweigen.

**Universum und Survivorship (1.2):** Das Labor rechnet nur auf BTCUSDT (R0–R4) sowie
ETHUSDT und SOLUSDT (Studien S4 und S5); `src/research_lab/protocol.py` (`UNIVERSE`) lässt
nichts anderes zu. Die drei wurden 2026 ausgewählt, also mit dem Wissen, dass sie bis heute
gelistet und liquide sind. Jedes Ergebnis ist deshalb eine Aussage über diese drei Instrumente,
nicht über „Krypto“ oder Altcoins allgemein: Eine Regel, die hier besteht, hätte auf Coins, die
2020 gelistet waren und später verschwanden (etwa LUNA oder FTT), anders aussehen können.
Diese Grenze steht in jedem Bericht (`UNIVERSE_LIMITATION`) und wird bei jedem Urteil mitgenannt.
Vorschlag für ein Universum ohne diesen Fehler, als Entscheid für Uzi und nicht Teil von 1.2:
point-in-time, also alle USD-M-Perpetuals, die zum jeweiligen Signalzeitpunkt bei Binance gelistet
waren, einschließlich später delisteter; ein Delisting schließt offene Trades zum letzten Kurs und
wird gezählt (wie eine Datenlücke in 3.1). Vorher auf dem Mac zu prüfen: ob `data.binance.vision`
die Archive delisteter Symbole weiter vorhält (aus der Cloud nicht erreichbar).

**In R1 zu prüfen (hier nicht verifiziert):** genauer Archivbeginn für Spot
(erwartet August 2017), Perpetual-Klines und fundingRate (erwartet September 2019).
Weicht der Beginn ab, verschiebt sich nur der Anfang des Trainingszeitraums. Die
Grenzen zu Validierung und Holdout bleiben.

### 3.2 Zeitliche Aufteilung

| Abschnitt | Zeitraum | Nutzung |
|---|---|---|
| Training | Datenbeginn bis 2022-12-31 | Hypothesen rechnen, Raster auswerten |
| Validierung | 2023-01-01 bis 2024-12-31 | Kandidaten bestätigen, Auswahl für Holdout |
| Holdout | 2025-01-01 bis Ende des letzten vollständigen Monats vor dem R6-Lauf | genau ein Lauf (R6) |

Datenbeginn je Horizont: Long ab erstem vollständigem Spot-Monat. Long nutzt
durchgehend Spot-Kurse, damit beim Start des Perpetual kein Basis-Sprung in der
Reihe entsteht. Die Kosten werden trotzdem wie beim Perpetual gerechnet
(Abschnitt 4.4). Mid und Short ab erstem vollständigem Perpetual-Monat. M2 braucht
365 Tage Funding-Vorlauf und beginnt deshalb etwa ein Jahr später.

Indikatoren dürfen Daten vor Abschnittsbeginn als Vorlauf nutzen (zum Beispiel
200 Tage für einen Durchschnitt), aber nie Daten nach dem Signalzeitpunkt.
**Abschnittsregel (1.2, strenger):** Ein Trade zählt zu dem Abschnitt, in dem sein
Signal fiel, aber nur, wenn sein Ausstieg nach den Regeln in 4.2 spätestens am
Abschnittsende feststand. Ein am Abschnittsende noch offener Trade bekäme seinen
Ausstiegskurs aus dem nächsten Abschnitt (Trainingsergebnis aus Validierungskursen,
Validierungsergebnis aus Holdout-Kursen); er zählt in keinen Abschnitt, auch dann nicht,
wenn der Backtest ihn am Datenende zwangsschließt. Die Zahl dieser Trades wird je
Abschnitt ausgewiesen („offen T/V“). Ein fester Zeitpuffer zwischen den Abschnitten ist
damit nicht nötig: Der Ausschluss setzt am einzelnen Trade an und ist für jede Haltedauer
exakt. Bis 1.1 zählten solche Trades zu dem Abschnitt ihrer Eröffnung. Im Walk-Forward
(7.3) gilt dieselbe Logik seit 1.1 (`known_at`); Code: `stats.inference.section_trades`,
genutzt im R4-Runner und im Wächter (`stats/guard.py`). Holdout-Daten werden vor R6 nicht
geladen, nicht geplottet und nicht zusammengefasst. Der Loader verweigert sie ohne
Holdout-Freigabe.

### 3.3 Bekannte Grenze des Holdouts

„Unberührt“ heißt: vom Labor nie benutzt. Menschen haben den Markt 2025/2026
trotzdem gesehen. Die Hypothesen L1–S2 sind Standardideen und nicht aus diesem
Zeitraum abgeleitet. Für TIMs eigene Regeln (T1–T3) gilt das nicht sicher, weil sie
2026 entwickelt wurden, also im Holdout-Zeitraum. Ein BESTANDEN dort ist schwächer
belegt und wird so ausgewiesen. Den wirklich frischen Test liefert der
Papier-Betrieb (R7).

## 4. Backtest-Regeln und Kostenmodell

### 4.1 Signal und Einstieg

- Signale entstehen nur auf **geschlossenen** Kerzen.
- Einstieg zum **Eröffnungskurs der nächsten Kerze**.
- Höchstens eine offene Position je Variante. Signale während einer offenen
  Position werden ignoriert und gezählt.

### 4.2 Ausstieg

- Stop, Ziel und Zeit-Stop gelten ab der Einstiegskerze.
- Berühren Stop und Ziel dieselbe Kerze, zählt der **Stop** (konservativ).
- Öffnet eine Kerze jenseits des Stops, wird zum Eröffnungskurs ausgeführt.
- Regelbasierte Ausstiege (etwa Rückkreuzung eines Durchschnitts) werden zum
  Eröffnungskurs der Kerze nach dem Signal ausgeführt.
- Zeit-Stop „n Kerzen“: Ausstieg zum Schlusskurs der n-ten Kerze, die Einstiegskerze
  als erste gezählt.
- Richtungslose oder widersprüchliche Signale (beide Richtungen zugleich) ergeben
  keinen Trade und werden gezählt.

### 4.3 Risikoeinheit R

- 1 R = Abstand von Einstieg zu Anfangsstop. Jede Variante definiert ihren Stop
  (Abschnitt 6).
- Ergebnis je Trade in R, netto nach allen Kosten. Kosten in R =
  Kosten in % × Einstiegskurs / Stopabstand. Enge Stops machen die Kosten in R
  also groß, das ist beabsichtigt.
- Für den Drawdown wird eine Kapitalkurve mit **1 % Risiko je Trade** ohne
  Zinseszins gerechnet (Drawdown in % = größter Rückgang der Summe der R-Ergebnisse
  × 1 %). Das ist eine Messkonvention, keine Größenempfehlung.

### 4.4 Kosten

| Posten | Basis | Stresstest |
|---|---|---|
| Gebühr | 0,05 % je Seite (Taker, USD-M Standardstufe) | 0,10 % je Seite |
| Slippage | 0,03 % je Seite, Stop-Ausführungen 0,05 % | verdoppelt |
| Funding | historische Perpetual-Rate zum jeweiligen Zeitpunkt (00/08/16 UTC), wenn die Position dann offen ist (auch für Long ab Start des Perpetual) | Rate unverändert, aber nie zugunsten des Setups gebucht |
| Funding vor Start des Perpetual (nur Long) | 0,01 % je 8 h als Kosten, für Long und Short | 0,02 % je 8 h |

Gebühren werden als Taker gerechnet, auch wenn ein Limit-Einstieg denkbar wäre.
Die Gebührenhöhe ist beim R1-Datenabruf gegen die aktuelle Binance-Gebührenseite
zu prüfen und bei Abweichung über das Änderungsprotokoll anzupassen, **vor** dem
ersten Test.

## 5. Kennzahlen

Je Variante und je Abschnitt:

- Zahl der Trades, an Datenlücken geschlossenen Trades und ignorierten Signale;
- Erwartungswert in R (Mittelwert), Median, Standardabweichung;
- 95-%-Konfidenzintervall des Erwartungswerts (Block-Bootstrap über
  Kalendermonate, 10 000 Ziehungen);
- Profitfaktor, Trefferquote, durchschnittlicher Gewinn und Verlust in R;
- maximaler Drawdown in R und in % (Abschnitt 4.3), längste Verlustserie;
- Zeit im Markt;
- Erwartungswert je Kalenderjahr;
- p-Wert gegen zufällige Einstiege (Abschnitt 7.1);
- Ergebnis unter Stresskosten.

Für Long zusätzlich als Vergleich (kein Kriterium): Kaufen und Halten im selben
Zeitraum.

## 6. Hypothesen-Register (Startbestand)

Jede Zeile unten ist eine eigene Variante und zählt für die Mehrfachtest-Korrektur,
auch wenn sie im Training verworfen wird. Die Parameterraster sind hier endgültig.
Neue Werte sind neue Registereinträge und nur über das Änderungsprotokoll möglich.

ATR = Average True Range, berechnet nur aus abgeschlossenen Kerzen bis zum Signal.

### Long (Wochen bis Monate, Signale auf Tageskerzen)

| ID | Hypothese | Regel | Raster | Varianten |
|---|---|---|---|---|
| L1 | Trendfolge über gleitendem Durchschnitt | Long, wenn Schluss > SMA(n); flat oder Short, wenn Schluss < SMA(n). Anfangsstop 3 × ATR(20). Nach einem Stop erst beim nächsten Kreuzen wieder einsteigen | n ∈ {100, 150, 200}; Richtung ∈ {nur Long, Long/Short} | 6 |
| L2 | Zeitreihen-Momentum | Wöchentlich (Montag 00:00 UTC): Vorzeichen der Rendite über L Tage bestimmt die Position für eine Woche. Jede Woche ist ein eigener Trade mit vollen Kosten. Anfangsstop 3 × ATR(20). Nach einem Stop erst zur nächsten Wochenentscheidung wieder einsteigen | L ∈ {30, 90, 180}; Richtung ∈ {nur Long, Long/Short} | 6 |

### Mid (Tage, Signale auf Tageskerzen)

| ID | Hypothese | Regel | Raster | Varianten |
|---|---|---|---|---|
| M1 | Donchian-Ausbruch | Tagesschluss über dem Hoch der Tage t−N … t−1 → Long, unter deren Tief → Short. Stop k × ATR(14). Ausstieg bei Tagesschluss jenseits des Gegenkanals über floor(N/2) Tage (t−floor(N/2) … t−1) oder nach 20 Tagen | N ∈ {20, 55}; k ∈ {2, 3} | 4 |
| M2 | Extreme Funding, gegenläufig | Maßgeblich ist der einzelne 8-h-Fundingwert. Signal zum Fundingzeitpunkt: Wert über dem oberen q-Perzentil der Werte aus den 365 Tagen **davor** (aktueller Wert ausgeschlossen) → Short; unter dem unteren → Long. Einstieg zur Eröffnung der nächsten 1h-Kerze. Stop 2 × ATR(14, Tag, letzter abgeschlossener Tag). Ausstieg nach h Tagen | q ∈ {2,5 %, 5 %}; h ∈ {3, 7} | 4 |
| M3 | Wochentags-Effekt | Position von 00:00 bis 24:00 UTC am Wochentag d. Beide Richtungen sind eigene Varianten, damit die Richtung nicht erst aus dem Training abgelesen wird. Stop 1 × ATR(14, Tag) | d ∈ {Mo … So}; Richtung ∈ {Long, Short} | 14 |

### Short (Minuten bis Stunden, Perpetual-Klines)

| ID | Hypothese | Regel | Raster | Varianten |
|---|---|---|---|---|
| S1 | Delta/CVD-Divergenz | Neues N-Kerzen-Hoch, CVD über N Kerzen ohne neues Hoch → Short (spiegelbildlich Long). Stop hinter dem Extrem + 0,5 × ATR(14), Ziel 2 R, Zeit-Stop 4 h | N ∈ {20, 50}; Intervall ∈ {5m, 15m} | 4 |
| S2 | Session-Eröffnungsbereich | 5m-Kerzen. Bereich = Hoch/Tief der ersten r Minuten der Session. Erster 5m-Schluss außerhalb des Bereichs → Einstieg in Ausbruchsrichtung, höchstens ein Trade je Session. Stop an der Gegenseite des Bereichs, Ziel 2 R, Ausstieg spätestens zum Schluss der letzten Session-Kerze. Nur Montag bis Freitag, an Börsenfeiertagen der jeweiligen Börse kein Trade | Session ∈ {London 08:00–16:30 Ortszeit, New York 09:30–16:00 Ortszeit, jeweils mit Sommerzeit}; r ∈ {30, 60} | 4 |

### TIMs eigene Regeln (R5, bestehender Code)

| ID | Hypothese | Regel | Raster | Varianten |
|---|---|---|---|---|
| T1 | BOS (`src/analysis/bos_detector.py`, Standardparameter) | `detect()` wird für jede Kerze t nur mit den Kerzen bis t aufgerufen, nie vektorisiert über die ganze Reihe (sonst gelangen später bestätigte Pivots in frühere Signale; eigener Test in R5). Einstieg in Richtung des Bruchs. Stop 1 × ATR(14), Ziel 2 R, Zeit-Stop 24 Kerzen | Intervall ∈ {15m, 1h} | 2 |
| T2 | Broncx REJECTION (`src/analysis/bronxc_rules.py`) | Gegen den längeren Docht (oberer Docht länger → Short). Bei gleich langen Dochten kein Trade. Stop = Hoch bzw. Tief der Signalkerze ± 0,1 × ATR(14), Ziel 2 R, Zeit-Stop 24 Kerzen | Intervall ∈ {15m, 1h} | 2 |
| T3 | Broncx FAILED_CONTINUATION | Gebrochenes Hoch → Short, gebrochenes Tief → Long. Sind beide gebrochen (Außenstab), kein Trade. Stop = Hoch bzw. Tief der Vorkerze ± 0,1 × ATR(14), Ziel 2 R, Zeit-Stop 24 Kerzen | Intervall ∈ {15m, 1h} | 2 |

ABSORPTION_CONTEXT und WEAK_CONTINUATION werden nicht getestet, weil die Regeln
keine Richtung liefern.
Das wird im R5-Bericht so ausgewiesen.

**Startbestand: m = 48 Varianten** (L 12, M 22, S 8, T 6).
**Obergrenze: 60 Varianten.** Wird sie erreicht, sind weitere Hypothesen erst mit
einem neuen, später liegenden Holdout-Zeitraum zulässig.

Zur Einordnung: Bei m = 48 muss der beste Kandidat im Holdout p < 0,05 / 48 ≈ 0,0010
gegen zufällige Einstiege erreichen. Mit wenigen Trades (vor allem Long) ist das
kaum zu schaffen. Das ist gewollt und der Preis für die Ehrlichkeit der Korrektur.

## 7. Statistik

### 7.1 Vergleich mit zufälligen Einstiegen

Für jede Variante und jeden Abschnitt werden 10 000 Zufallsstrategien erzeugt:
gleiche Zahl an Trades, gleiche Verteilung von Long und Short, gleiche Kosten,
Einstiege gleichverteilt über die erlaubten Kerzen desselben Abschnitts.
Stopabstand (in ATR-Einheiten), Ziel in R und Haltedauer werden aus der Verteilung
der echten Trades der Variante gezogen, weil viele Stops an der Kursstruktur hängen
und nicht an einer festen ATR-Zahl. Überlappung der Zufallstrades ist erlaubt,
sonst lassen sich fast immer investierte Varianten (L1 Long/Short, L2) nicht
nachbilden. Fester, protokollierter Seed.

p-Wert = (1 + Zahl der Zufallsläufe mit Erwartungswert ≥ Setup) / (1 + 10 000).

Einseitiger Test. Zufällige Long-Einstiege in einem steigenden Markt haben selbst
einen positiven Erwartungswert. Wer sie schlägt, zeigt mehr als die Marktdrift.

### 7.2 Mehrfachtest-Korrektur

Holm-Bonferroni mit Familien-α = 5 %. m ist die Zahl **aller** Einträge im Register
zum Zeitpunkt des Holdout-Laufs, auch verworfener und nie in den Holdout gelangter
Varianten (sie gehen mit p = 1 ein). m sinkt nie.

### 7.3 Robustheit (Walk-Forward und Nachbarschaft)

Über Training und Validierung:

- **Jahresstabilität:** Erwartungswert in mindestens 60 % der Kalenderjahre mit
  mindestens 5 Trades > 0. Jahre mit weniger Trades zählen nicht mit.
- **Walk-Forward:** rollierend 24 Monate Anpassung, 6 Monate Test. In jedem
  Anpassungsfenster wird je Hypothese die beste Rastervariante gewählt und nur im
  folgenden Testfenster gemessen. Der verkettete Erwartungswert der Testfenster
  muss > 0 sein. Damit wird das Auswahlverfahren selbst geprüft, nicht nur die
  einzelne Variante. Scheitert der Walk-Forward, sind alle Varianten der
  Hypothese gesperrt.
- **Nachbarschaftsregel:** Die direkten Nachbarn im Raster (nächster Wert je
  geordnetem Zahlenparameter, etwa n, L, N, k, q, h, r) haben im Training ebenfalls
  einen Erwartungswert > 0. Für Kategorien (Richtung, Wochentag, Session,
  Intervall) gibt es keine Nachbarn. Einzelne
  Spitzen im Raster gelten als Zufall.

### 7.4 Prüfung des Wächters selbst (R3)

Auf 200 synthetischen Zufallsreihen ohne eingebauten Vorteil darf der gesamte
Ablauf (Training → Validierung → Holdout mit Korrektur) in höchstens 5 % der Reihen
ein BESTANDEN liefern. Auf 200 Reihen mit eingebautem Vorteil von +0,2 R je Trade
bei ausreichender Tradezahl muss er in mindestens 80 % der Reihen BESTANDEN
liefern.
Erst danach wird der Wächter auf echte Daten angewendet.

## 8. Ablauf und Auswahlregeln

1. **Training.** Alle Varianten rechnen. Weiter kommt eine Variante, wenn
   Erwartungswert > 0, Mindesttrades erreicht (Short ≥ 500, Mid ≥ 50, Long ≥ 20)
   und p < 0,10 gegen Zufall (unkorrigiert, nur Vorauswahl).
2. **Validierung.** Weiter kommt eine Variante, wenn die Hälfte der Mindesttrades
   aus Schritt 1 erreicht ist, Erwartungswert > 0,
   p < 0,05 (unkorrigiert), Profitfaktor > 1,1, Drawdown ≤ Grenze aus K4 und
   alle Robustheitsregeln aus 7.3 erfüllt sind.
3. **Kandidatenliste einfrieren.** Höchstens zwei Varianten je Hypothese (die mit
   dem höchsten Erwartungswert in der Validierung). Die Liste wird mit Hash und
   Protokollversion committet, bevor Holdout-Daten geladen werden.
4. **Holdout (R6), genau ein Lauf.** Urteil je Kandidat nach K1–K4. Der Lauf
   schreibt eine Sperrdatei. Ein zweiter Lauf wird verweigert.
5. **Papier-Betrieb (R7)** nur für BESTANDEN-Kandidaten.

Kommt nach Schritt 2 kein Kandidat durch, lautet das Ergebnis „kein Vorteil in
Training/Validierung gefunden“, und der Holdout bleibt unberührt.

## 9. Papier-Betrieb (K5)

- Signale laufen in TIM als Papier-Signale mit Journal. Es gibt keine Orders.
- **Erwartetes Band:** 5.–95. Perzentil des Erwartungswerts für die tatsächlich
  angefallene Tradezahl, gezogen per einfachem Bootstrap (Trades einzeln) aus den
  Validierungs- und Holdout-Trades der Variante. Einzeln statt in Monatsblöcken,
  weil wenige Papier-Trades keine stabilen Blöcke ergeben.
- **Laufzeit:** mindestens 4 Wochen, verlängert bis höchstens 8 Wochen, solange
  weniger als 20 Trades (Short, Mid) angefallen sind.
- **Bestätigt**, wenn der Live-Erwartungswert im Band liegt und der Drawdown die
  Grenze aus K4 nicht überschreitet.
- **Kein Widerspruch**, wenn nach 8 Wochen weniger als 20 Trades angefallen sind
  (fast immer bei Long, oft bei Mid), der Live-Erwartungswert im Band liegt und der
  Drawdown die Grenze einhält. Das ist keine Bestätigung. Ein solches Setup gilt als
  „profitabel mit schwacher Papier-Evidenz“ und wird so ausgewiesen. Der
  Papier-Betrieb kann dann auf deinen Wunsch weiterlaufen.

## 10. Stoppregeln

- **Verworfen bleibt verworfen:** Scheitert eine Variante im Training oder in der
  Validierung, wird sie nicht umparametriert. Eine neue Parametrierung ist ein
  neuer Registereintrag über das Änderungsprotokoll und erhöht m.
- **Kein Nachbessern am Holdout:** Ein NICHT BESTANDEN im Holdout ist endgültig
  für diese Variante und alle Varianten, die aus ihr abgeleitet werden.
- **Datenfehler nach dem Holdout:** Ein zweiter Lauf ist nur zulässig, wenn ein
  Datenfehler (nicht ein Strategieproblem) nachgewiesen und im Änderungsprotokoll
  beschrieben ist. Kandidatenliste und Code bleiben bis auf die Korrektur gleich.
- **Obergrenze:** Bei 60 Registereinträgen ist Schluss für diesen Holdout.
- **Papier-Stopp:** Liegt der Live-Erwartungswert nach mindestens 20 Trades unter
  dem 5. Perzentil des Bands oder überschreitet der Drawdown die Grenze aus K4,
  wird das Setup sofort gestoppt.
- **Kein echtes Geld** vor Abschluss von R7 und einem eigenen, freigegebenen
  Bauplan dafür.

## 11. Reproduzierbarkeit

Jeder Lauf speichert Datensatz-Hashes, Commit, Protokollversion, Parameter,
Kostenmodell und Seeds (Band 8, „Reproducibility“). Gleiche Eingabe ergibt
dasselbe Ergebnis mit demselben Hash.

## 12. Offene Punkte vor der Freigabe

| # | Punkt | Wer |
|---|---|---|
| O1 | ~~Drawdown-Grenze für K4~~ erledigt: 20 % bei 1 % Risiko je Trade | Uzi |
| O2 | Datenweg: (a) Domains in der Umgebung freigeben oder (b) Download auf dem Mac | Uzi |
| O3 | Archivbeginn und Gebührenstufe gegen die Quellen prüfen (Abschnitte 3.1, 4.4). Teilweise erledigt: Spot-Klines beginnen am 2017-08-17 (Probe 2026-09-29), erster vollständiger Spot-Monat ist damit 2017-09. USD-M-Klines (1d, 1h, 15m, 5m) und fundingRate beginnen im Monatsarchiv mit 2020-01 (2019-09 bis 2019-12 liefern 404, Probe 2026-09-29). Offen: Gebührenstufe | R1 |

## Änderungsprotokoll

Nur anhängen, nie überschreiben. Nach Beginn von R4 sind Änderungen an Datensplit,
Kriterien und Raster nur noch erlaubt, wenn sie strenger machen.

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-09-29 | 0.1 | Entwurf erstellt, nach Gegenprüfung präzisiert (M3 beide Richtungen, m = 48) | R0 | keine Labordaten |
| 2026-09-29 | 1.0 | Freigegeben; Drawdown-Grenze K4 = 20 % bei 1 % Risiko je Trade festgelegt | Freigabe durch Uzi | keine Labordaten |
| 2026-09-29 | 1.0 | Klarstellung zu 7.4, keine Regeländerung: Die Wächter-Prüfung läuft mit 99 statt 10 000 Zufallsläufen (Laufzeit; die p-Untergrenze 0,01 liegt unter jeder dort genutzten Holm-Schwelle), m = 4 und ohne Walk-Forward und Nachbarschaftsregel, weil die synthetischen Varianten kein Parameterraster haben. Ergebnis: 0 von 200 Zufallsreihen BESTANDEN, 190 von 200 Reihen mit +0,2 R BESTANDEN | R3 | nur synthetische Daten |
| 2026-09-29 | 1.0 | Befund, keine Regeländerung: Probe-Download (USD-M 1h 2024-01: 744/744 Kerzen, Checksumme PASS; fundingRate 2024-01 PASS; Spot 1d 2017-08/09 PASS). Spot-Archiv beginnt 2017-08-17 | R1 | 2024-01 USD-M, 2017-08/09 Spot (nur Vollständigkeit geprüft, keine Auswertung) |
| 2026-09-29 | 1.0 | Umsetzung R4, Klarstellungen ohne Änderung an Split, Kriterien oder Raster: (a) 7.1 wird aus Laufzeitgründen als Monte-Carlo-Pool gerechnet: je Variante und Abschnitt werden mindestens 50 × n (mindestens 5 000) Zufallstrades nach den Regeln von 7.1 simuliert, jeder der 10 000 Läufe zieht seine n Trades aus diesem Pool. Das nähert frische Zufallstrades je Lauf an; die Näherung ist nicht strenger und wird im Bericht genannt. (b) T1 ruft `detect()` je Kerze mit den letzten 300 Kerzen bis t auf (Laufzeit; weiterhin nur Kerzen bis t). (c) S2-Feiertage regelbasiert für NYSE und LSE samt einmaliger Schließtage; verkürzte Handelstage werden als volle Tage behandelt. (d) M2: Die Funding-Rate eines Abrechnungszeitpunkts gilt ab diesem Zeitpunkt als bekannt, das Signal fällt auf die 1h-Kerze, die dort schließt | R4 | keine Labordaten ausgewertet |
| 2026-09-29 | 1.0 | Befund nach 3.1, keine Regeländerung: Das Binance-Monatsarchiv für USD-M (Klines 1d/1h/15m/5m und fundingRate) beginnt mit 2020-01, nicht 2019-09. Wie in 3.1 vorgesehen verschiebt sich nur der Trainingsbeginn für Mid und Short auf 2020-01-01; Validierungs- und Holdout-Grenzen bleiben. Tagesarchive werden nicht ergänzt (Funding fehlt dort). Alle USD-M-Monate 2020-01 bis 2024-12 vollständig, Checksummen PASS | R4 | USD-M 2020-01 bis 2024-12 und Spot 2017-08 bis 2024-12 geladen und auf Vollständigkeit geprüft, keine Auswertung |
| 2026-10-22 | 1.1 | **Methodenkorrektur 7.3 Walk-Forward (strenger), Paket T03 des Verbesserungsplans:** Die Wahl der besten Rastervariante am Ende eines Anpassungsfensters nutzte bisher jeden Trade, dessen Einstieg im Fenster lag, auch wenn er erst nach dem Fensterende geschlossen wurde. Damit floss das spätere Ergebnis offener Trades in eine Entscheidung ein, die zu diesem Zeitpunkt fiel (Zukunftsinformation, Codex-Befund F01). Neu: In die Anpassung zählen nur Trades, deren Signal im Fenster lag **und** deren Ausstieg spätestens am Fensterende bekannt war (`known_at`). Ins Testfenster zählen Trades mit Signal im Testfenster (`signalled_in`, Signalzeit statt Einstiegszeit, wie in 3.2 und im R4-Runner). Ein am Fensterende noch offener Trade zählt in keines der beiden. Regressionstest: zwei bis zum Fensterende byte-gleiche Verläufe mit unterschiedlichem späteren Ergebnis müssen dieselbe Wahl ergeben. Betroffen ist allein die Robustheitsregel Walk-Forward; Split, Kriterien, Raster und Holdout-Grenze sind unverändert. Der R4-Bericht vom 29.09. (`reports/r4_2026-09-29T2219Z.md`) wurde mit Version 1.0 gerechnet und bleibt unverändert erhalten; seine Walk-Forward-Werte gelten als durch diesen Befund eingeschränkt (siehe `reports/METHODENBEFUND_2026-10-22_walk_forward.md`). Kein Kandidat hing allein am Walk-Forward, das Gesamtergebnis „kein Vorteil in Training/Validierung“ bleibt bestehen. Holdout nicht geladen | T03 | Training/Validierung bis 2024-12 (R4), Holdout nicht geladen |
| 2026-10-23 | 1.1 | **Zusatzauswertung, keine Regeländerung:** Der R4-Bericht bekommt einen Glückstest über alle Varianten gemeinsam (`src/research_lab/stats/snooping.py`): Hansens SPA-Test (studentisiert, p-Werte unten/konsistent/oben) und das schrittweise Verfahren StepM nach Romano-Wolf (α = 5 %, mit der konsistenten SPA-Zentrierung, also Step-SPA nach Hsu, Hsu und Kuan 2010, wie in arch), beide mit stationärem Bootstrap über Tagesreihen. Vorab festgelegt: Benchmark 0 R pro Tag (nicht handeln), Trade am Schlusstag gebucht, Tage ohne Trade 0 R, Blocklänge 10 Tage, 10 000 Ziehungen, Seed = Lauf-Seed + 100 (Training) bzw. + 101 (Validierung), Training im gemeinsamen Fenster ab dem spätesten Datenbeginn. Nur Training und Validierung, der Holdout wird dafür nicht geladen. Das Ergebnis ändert kein Urteil und keine Kandidatenliste; ob es künftig ein Kriterium wird, entscheidet Uzi vor dem nächsten Register | Zweiter Glückstest, der die Abhängigkeit zwischen verwandten Varianten berücksichtigt (Holm in 7.2 nimmt Unabhängigkeit an) | keine neuen Labordaten ausgewertet |
| 2026-10-25 | 1.2 | **Abschnittsregel 3.2 (strenger) und Universum/Survivorship in 3.1 (Grün-Programm, Sicht Forschung, PR #429):** (a) Ein Trade zählt nur dann zu dem Abschnitt seines Signals, wenn sein Ausstieg spätestens am Abschnittsende feststand; am Abschnittsende offene oder am Datenende zwangsgeschlossene Trades zählen in keinen Abschnitt und werden je Abschnitt gezählt ausgewiesen. Bis 1.1 flossen so Validierungskurse in Trainingsergebnisse (Trainingsentscheid mit Zukunftsinformation); zwischen Validierung und Holdout schnitt der Runner die Daten ab, wodurch offene Trades künstlich zum Grenzkurs geschlossen wurden. Umsetzung `stats.inference.section_trades`, R4-Runner (`_split`, Spalte „offen T/V“ im Bericht), Wächter (`_stage`). Betroffen sind nur Trades über eine Grenze, bei Zeit-Stops bis 20 Tageskerzen also höchstens wenige je Variante; der R4-Bericht vom 29.09. bleibt unverändert erhalten und gilt als durch diesen Befund eingeschränkt, das Gesamtergebnis „kein Vorteil“ hängt an keinem Grenz-Trade. Ein fester Puffer wird nicht eingeführt (Ausschluss je Trade ist exakt). (b) Universum BTCUSDT/ETHUSDT/SOLUSDT als Survivorship-Grenze festgehalten (`protocol.UNIVERSE`, `UNIVERSE_LIMITATION` in jedem Bericht); Vorschlag point-in-time-Universum mit delisteten Coins liegt bei Uzi. Split-Grenzen, Kriterien, Raster und Holdout-Grenze unverändert; Holdout nicht geladen | Grün-Programm Sicht Forschung (Uzi: Survivorship und Leaky Validation prüfen) | Training/Validierung bis 2024-12 (R4, S4-Zähllauf), Holdout nicht geladen |
| 2026-10-25 | 1.3 | **Studienbezogene Ausnahmen für S6 (Maker-Mean-Reversion, `studien/S6_WINRATE_95_MAKER_MEAN_REVERSION_PRAEREGISTRIERUNG.md`), freigegeben von Uzi am 25.10. 23:45 Ortszeit per Entscheidungskarte; gelten nur für Studien mit Durchhandel-Fill-Regel, Post-only-Regel und Latenzprüfung an aggTrades:** (A1) 4.4: Limit-Fills (Einstieg, Ziel) rechnen mit der Maker-Gebühr `MAKER_FEE` = 0,02 % (Stress 0,04 %) statt Taker; Stop, Zeitstop, Lücke und Abschnittsende bleiben Taker mit Slippage; jeder Bericht weist zusätzlich alle Kennzahlen mit dem Protokoll-Kostenmodell (alles Taker) aus. (A2) 3.2 (Abschnittsregel 1.2): Ein am Abschnittsende offener Trade wird zur letzten Kerze des Abschnitts zum Schlusskurs geschlossen (`section_end`, Taker) und zählt, statt in keinen Abschnitt zu zählen; bei 240-Minuten-Zeitstop betrifft das höchstens einen Trade je Instrument und Abschnitt, der Anteil wird berichtet; kein Abschnitt liest Daten des nächsten. (A3) 8/K3: Zusätzlich zu ≥ 500 Trainings- und ≥ 200 Holdout-Trades mindestens 160 effektive Trades (n_eff = ⌊n / D⌋, Designeffekt D aus dem Tagescluster über alle Instrumente) im Training und Holdout, 183 in der Validierung (strenger). (A4) 7.1: Der Zufallsvergleich wird volatilitäts-gematcht (Vergleichsminuten aus demselben Instrument, Abschnitt und σ₃₀-Dezil, gleiche Ausstiege und Kosten), Pool-Methode wie R4(a); der ungematchte Vergleich nach 7.1 wird zusätzlich berichtet. (A5) 3.1: `gap` schließt wie bisher zur letzten Kerze vor der Lücke; zusätzlich Bericht mit Schluss zur ersten Kerze nach der Lücke. Ferner festgehalten: Trefferquoten-Kriterium K6 für S6 = Punktwert ≥ 95 % und einseitige 95-%-Clopper-Pearson-Untergrenze ≥ 90 % mit effektiven Zahlen; Uzi hat die geringe Power von K2 bei 160 Trades zur Kenntnis genommen (S6 Abschnitt 6). Register: sechs S6-Varianten eingetragen (m = 54 von 60). Datensplit, Holdout-Grenze, Holm-Korrektur und Stoppregeln unverändert | S6 Version 1.0 | S6: Fills und Fill-Tage 2020–2024 (Gate), kein Ausstieg, kein R; Holdout nicht geladen |
| 2026-10-26 | 1.3 | **Einordnung nach Abschnitt 10, keine Regeländerung:** S7 (`studien/S7_3_4R_TRENDFOLGE_AUSBRUCH_PRAEREGISTRIERUNG.md`) scheiterte am 26.10. in der Validierung nur an K4 (Drawdown 30 R > 20 R); beide S7-Varianten bleiben `failed_validation`. Die Nachfolgestudie S7b (`studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md`, höchstens eine offene Position über BTC/ETH/SOL, Uzis Wahl per Karte 12:34 Ortszeit) ist **keine Neuparametrierung der verworfenen Varianten, sondern ein eigener, offen als Ableitung deklarierter Registereintrag** (zwei Varianten, Register 56 → 58, Holm weiter m = 60); ihre Vorbelastung durch die gesehenen S7-Ergebnisse steht in S7b Abschnitt 2. Die Portfolio-Regel (`engine.run_portfolio`) wirkt nur auf die Trade-Auswahl; Split, Kriterien, Raster, Mindestzahlen und Holdout-Grenze sind unverändert. Der Holdout-Lauf von S7b würde nach Abschnitt 8 und 10 den Holdout für den gesamten Registerzeitraum verbrauchen | S7b Entwurf 0.2 | S7: Training/Validierung bis 2024-12 (alle vier Varianten); S7b: Signalzahlen ohne R (Zähllauf 6.1); Holdout nicht geladen |
| 2026-10-26 | 1.3 | **Einordnung, keine Regeländerung:** Studie S8 (lokale BTC-Orderflow-Prognose, `studien/S8_ORDERFLOW_PROGNOSE_PRAEREGISTRIERUNG.md`) läuft als **eigene Familie außerhalb dieses Holdout-Registers**, entschieden von Uzi am 26.10. 20:49 Ortszeit per Entscheidungskarte. S8 belegt keine Registerplätze (m bleibt 58 von 60), lädt den Archiv-Holdout ab 2025-01-01 nie und kann aus ihm keine Bestätigung ziehen. Training (bis 2022) und Validierung (2023–2024) gelten wie in 3; eine Bestätigung ist nur über einen eigenen, vor Datenbeginn registrierten prospektiven Test auf neuen Live-Daten möglich (Zeitgrenzen, Fallzahl/Power-Gate und Stoppregeln in der S8-Registrierung). S8-Kandidaten erhalten keine Holdout-Erlaubnis und keine Zulassung als Setup-Evidenz über dieses Register | Register 58/60; ein prospektiver Test ist für eine Live-Prognose der passende Nachweis | keine (S8 Entwurf 0.2, keine Archivdaten geladen) |
| 2026-10-31 | 1.3 | **Einordnung, keine Regeländerung:** Der Forschungsbereich (`FORSCHUNGSBEREICH.md`, Code `src/research_lab/workshop/`, freigegeben von Uzi am 31.10. 14:02 Ortszeit) sammelt und prüft Ideen in `IDEEN.jsonl`, bevor daraus Studien werden. Eine Idee ist kein Registereintrag und verbraucht keinen Registerplatz (m bleibt unverändert); Registereinträge entstehen weiter nur über eine Präregistrierung nach diesem Protokoll. Die Ideen-Prüfung lädt keine Daten und weist Ideen mit Archivzeitraum ab 2025-01-01 als gesperrt aus. Split, Kriterien, Raster und Holdout-Grenze unverändert | Forschungsbereich F0–F2 | keine Labordaten |
