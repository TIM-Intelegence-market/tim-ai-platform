# Studie S4: Strategie mit Trefferquote ≥ 75 % und positivem Netto-Erwartungswert (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Status | **ENTWURF 0.2, nicht freigegeben.** Nichts ist gerechnet. Version 1.0 erst nach Uzis Freigabe; danach nur noch Änderungen über das Änderungsprotokoll unten, und nach dem ersten Trainingslauf nur noch strengere. |
| Erstellt | 2026-10-25, Masterprompt Phase D/E (Trading-Forschungsziel B) |
| Protokollbezug | `../PROTOKOLL.md` Version 1.1: Datensplit 3.2, Backtest 4.1–4.3, Kosten 4.4, Zufallsvergleich 7.1, Holm 7.2, Robustheit 7.3 (Walk-Forward mit `known_at`), Ablauf 8, Stoppregeln 10 |
| Kostenmodell | ausschließlich `CostModel` / `BASE_COSTS` / `STRESS_COSTS` aus `src/research_lab/protocol.py` (kein eigenes Modell) |
| Name | S3 ist in `S2_ORDERFLOW_REGELN_PRAEREGISTRIERUNG.md` für die Strategie-Folgestudie zu S2 reserviert, darum S4 |
| Daten bis dahin gesehen | siehe Abschnitt 10 |

Was dieses Dokument nicht ist: kein Profitversprechen, keine Anlageberatung, keine Freigabe für Papier- oder Echtgeldbetrieb.
Das Ergebnis darf und wird wahrscheinlich **NICHT BESTANDEN** oder **KEIN URTEIL** lauten (Abschnitt 2).

---

## 1. Fragestellung

Gibt es unter den unten vorab festgelegten Regeln eine Strategie, die auf Daten, die bei ihrer Auswahl nie benutzt
wurden, **gleichzeitig**

1. eine Netto-Trefferquote von mindestens 75 % hat,
2. einen positiven Netto-Erwartungswert und einen Profitfaktor über 1 nach realistischen Kosten hat,
3. zufällige Einstiege mit derselben Stop-/Ziel-Geometrie schlägt,
4. einen begrenzten Drawdown und keine versteckten Großverluste hat,
5. Walk-Forward, Jahresstabilität und Kostenstress übersteht?

Eine hohe Trefferquote allein ist kein Erfolg. Sie wird nie isoliert optimiert (Abschnitt 5.3).

## 2. Ausgangslage (aus bereits vorliegenden Ergebnissen, nicht neu gerechnet)

**R4 (29.09.2026, Protokoll 1.0, 48 Varianten):** keine Kandidaten. Die höchste Trefferquote im Training war
57,7 % (M2-q0.05-h7, 26 Trades), in der Validierung 51,9 %. Keine einzige Variante kam auf 60 %. Die Varianten mit
dem höchsten Erwartungswert (L1) hatten Trefferquoten von 11–27 %: Sie lebten von wenigen großen Gewinnen.
Alle Short-Varianten (S1, S2, T1–T3) waren netto negativ, weil Kosten enge Stops auffressen.
Quelle: `../reports/r4_2026-09-29T2219Z.json`, Feld `win_rate`.

**Glückstest G4 (24.10.2026):** SPA p ≈ 0,46 (Training) / 0,43 (Validierung), StepM keine Variante. Bestätigt: kein Edge.

**Plan-Journal (live, 24.10.):** Struktur-Regel mit 0,15 % Stop hatte Kosten von 1,2 R je Trade. Die
Kosten-Schwelle 0,25 R (PR #408) ist eine Anzeige, kein Filter.

**Folgerung vorab:** Eine Trefferquote von 75 % bei positivem Netto-Erwartungswert ist nur mit einem Ziel möglich,
das kleiner als der Stop ist, und nur mit einem Stop, der weit genug entfernt ist, dass die Kosten in R klein
bleiben. Das zeigt die folgende Rechnung (Kosten aus `BASE_COSTS`: Gewinnfall 0,16 % je Runde, Stopfall 0,18 %).

### 2.1 Gewinnschwelle der Trefferquote (Netto)

Trefferquote, ab der der Netto-Erwartungswert über 0 liegt, für Ziel T (in R) und Stopabstand d (in % vom Einstieg):

| Ziel T | d = 0,50 % | d = 0,72 % | d = 1,00 % | d = 1,50 % | d = 2,00 % |
|---|---|---|---|---|---|
| 0,33 R | 99,3 % | 92,1 % | 87,4 % | 83,4 % | 81,3 % |
| 0,50 R | 88,3 % | 81,8 % | 77,6 % | 74,0 % | 72,2 % |
| **0,75 R** | 76,0 % | 70,3 % | **66,7 %** | 63,5 % | 61,9 % |
| 1,00 R | 66,7 % | 61,6 % | 58,4 % | 55,6 % | 54,2 % |

Formel: Gewinn = T − 0,0016/d, Verlust = 1 + 0,0018/d, Schwelle = Verlust / (Gewinn + Verlust).

Lesart: Mit Ziel 0,5 R ist eine Trefferquote von 75 % bei üblichen Stops ungefähr **die Gewinnschwelle**, also kein
Vorteil. Mit Ziel 0,75 R und Stop ≥ 1 % liegt die Schwelle bei rund 67 %. Darum legt diese Studie **für alle
Varianten T = 0,75 R** fest und verlangt Kosten ≤ 0,25 R je Stopfall (Stop ≥ ~0,72 % entfernt).
Ziel 1 R wird nicht registriert: Zufällige Einstiege treffen dort ohne Drift nur ~50 %, 75 % wäre ein
Vorsprung von 25 Prozentpunkten, für den es keinen Hinweis gibt.

### 2.2 Was zufällige Einstiege mit derselben Geometrie liefern

Ohne Drift trifft ein Ziel von 0,75 R vor einem Stop von 1 R in etwa 1 / 1,75 ≈ 57 % der Fälle (brutto, vor Kosten).
Eine Trefferquote von 75 % bedeutet also rund **18 Prozentpunkte über Zufall**. Das ist der eigentliche Anspruch.
**Vorab-Erwartung: wahrscheinlich NICHT BESTANDEN.** Das wird hier festgehalten, damit ein
Nullergebnis nicht als Überraschung umgedeutet wird.

## 3. Daten und Datenherkunft

| Punkt | Festlegung |
|---|---|
| Quelle | nur öffentliche Binance-Archive `data.binance.vision`, Download auf Uzis Mac (Cloud blockiert die Domain), `scripts/research_lab_fetch.py` |
| Instrumente | USD-M Perpetual **BTCUSDT, ETHUSDT, SOLUSDT** (Universum fest, keine Auswahl nach Ergebnis) |
| Datensätze | Klines 1d, 1h (Signale und Ausführung), fundingRate (Funding-Kosten); Delta-Näherung aus `taker_buy_base_volume` wie R4 (`2 · taker_buy − volume`) |
| Prüfung | `.CHECKSUM` je Datei, Datensatz-Hash je Instrument und Abschnitt, Lückenliste (nicht auffüllen; Trade in Lücke → Schluss zum letzten Kurs, gezählt, Protokoll 3.1) |
| Produktions-DB | wird weder gelesen noch beschrieben. Live-Daten (Orderflow seit Juli 2026, Plan-Journal) sind **kein** Bestandteil |
| Holdout-Sperre | `src/research_lab/data/store.py` verweigert Monate ab 2025-01 ohne `HoldoutPermission` aus `stats.register.claim_holdout` |

**Offen vor Freigabe (O1):** Archivbeginn für ETHUSDT und SOLUSDT USD-M prüfen (erwartet 2020-01 bzw. 2020-09).
Abstimmung mit dem Thread „25.10. Multi-Coin-Architektur isoliert entwerfen“: Diese Studie braucht nur
Archivdateien im Labor, keine Änderung an TIMs Live-Symbolen. Liegen ETH/SOL zur Freigabe nicht vor, wird **vor**
dem Trainingslauf festgelegt, ob S4 nur mit BTC läuft (dann ist KEIN URTEIL laut Abschnitt 6 sehr wahrscheinlich).
Diese Entscheidung fällt nie nach Einsicht in Ergebnisse.

### 3.1 Zeitliche Aufteilung (unverändert aus Protokoll 3.2)

| Abschnitt | Zeitraum (UTC) | Nutzung |
|---|---|---|
| Training | Datenbeginn je Instrument bis 2022-12-31 | Regeln rechnen, Vorauswahl |
| Validierung | 2023-01-01 bis 2024-12-31 | Bestätigung, Kandidatenliste einfrieren |
| Holdout | 2025-01-01 bis Ende des letzten vollständigen Monats vor dem Lauf | **genau ein Lauf, nur mit Uzis ausdrücklichem Wort** |

**Holdout-Budget:** Protokoll 6 erlaubt höchstens 60 Registereinträge für diesen Holdout. Belegt sind 48. S4
registriert **10** Varianten (Abschnitt 4), danach m = 58. Zwei Plätze bleiben frei. Wird die Obergrenze erreicht,
ist für weitere Hypothesen ein neuer, späterer Holdout nötig (Protokoll 10).

**Bekannte Grenze:** Menschen (und TIMs Regeln seit 2026) haben den Markt 2025/2026 gesehen. Die Hypothesen unten
sind Standardideen der Marktstruktur und nicht aus diesem Zeitraum abgeleitet. Den wirklich frischen Test liefert
erst ein vorab registrierter Papier-Betrieb (Protokoll 9), der hier nicht beantragt wird.

## 4. Hypothesen-Register (eingefroren mit Version 1.0)

### 4.1 Gemeinsame Regeln aller S4-Varianten

- Signale nur auf **geschlossenen 1h-Kerzen**; Einstieg zur Eröffnung der nächsten 1h-Kerze (Protokoll 4.1).
- Jede Signalfunktion wird für Kerze t nur mit Kerzen bis t aufgerufen. Tageswerte (Regime) nur aus Tageskerzen,
  die spätestens mit Schluss(t) geschlossen sind.
- ATR = ATR(14) auf 1h als einfacher Mittelwert der True Range (`src/research_lab/backtest/indicators.atr`), nur aus
  abgeschlossenen Kerzen bis einschließlich t.
- **Ziel 0,75 R**, Anfangsstop je Hypothese, **Zeit-Stop 24 Kerzen** (Ausstieg zum Schluss der 24. Kerze).
- **Kostentor (fest, kein Rasterwert):** Ein Signal wird nur gehandelt, wenn die geschätzten Stopfall-Kosten
  ≤ 0,25 R sind (Formel wie `src/dashboard/plan_cost_check.py`, also Stop ≥ ~0,72 % entfernt). Preisbasis ist
  **Schluss(t)** als Einstiegsschätzung und der Stop aus der Regel, weil die Eröffnung von t+1 zum Signalzeitpunkt
  unbekannt ist. Das Tor wird beim Fill nicht erneut geprüft. Sonst kein Trade,
  gezählt als `skipped_cost`. Der Wert 0,25 R wird hier **vor** dem Bericht der Kosten-Schwellen-Studie (B3) festgelegt
  und danach nicht angepasst.
- Höchstens eine offene Position je Variante und Instrument. Signale während einer offenen Position werden
  ignoriert und gezählt.
- Stop und Ziel in derselben Kerze → **Stop** (konservativ, drückt die Trefferquote). Der Anteil solcher Kerzen
  wird berichtet. Gap über den Stop → Ausführung zur Eröffnung mit Stop-Slippage.
- Kein Nachkaufen, kein Verschieben des Stops weg vom Kurs, keine Teilgewinne, kein Pyramidisieren, konstantes Risiko
  von 1 R je Trade.
- Widersprüchliche Signale (Long und Short zugleich) → kein Trade, gezählt.
- Ein Trade ist **Treffer**, wenn sein Netto-Ergebnis nach allen Kosten > 0 R ist. Brutto-Trefferquote und die Anteile
  Ziel / Stop / Zeit-Stop werden zusätzlich berichtet.
- Swing-Hoch/-Tief über N Kerzen = Maximum der Hochs bzw. Minimum der Tiefs der Kerzen t−N … t−1.
- Regime „Trend auf“: Rendite der letzten 20 geschlossenen Tageskerzen ≥ +5 %; „Trend ab“: ≤ −5 %; sonst
  „Seitwärts“ (gleiche Definition wie S2, Abschnitt 5). Fehlen die 21 Schlusskurse: Regime unbekannt, kein Trade.

### 4.2 Varianten

| ID | Hypothese und ökonomische Begründung | Regel | Raster | Var. |
|---|---|---|---|---|
| H1 | **Liquidity Sweep & Reclaim.** Stop-Orders sammeln sich jenseits offensichtlicher Hochs/Tiefs (Osler 2003, Stop-Loss-Clustering). Werden sie abgeholt und schließt der Kurs zurück im Bereich, war der erzwungene Fluss absorbiert; kurzfristige Rückkehr in den Bereich ist plausibel. | Long: Tief(t) < Swing-Tief(N) (Kerzen t−N … t−1) und Schluss(t) > Swing-Tief(N) und Schluss(t) in der oberen Kerzenhälfte. Short spiegelbildlich. Stop = Extrem der Kerze t ∓ 0,25 × ATR | N ∈ {24, 72} | 2 |
| H2 | **Sweep mit Absorption (Delta/CVD).** Wie H1, aber der Sweep wurde gegen aggressive Gegenseite gehalten: Beim Long-Sweep war das Kerzen-Delta negativ (Verkäufer aggressiv, trotzdem Rückeroberung), beim Short-Sweep positiv. | H1 mit N = 24, zusätzlich Delta(t) mit Gegenvorzeichen; Stärke s: „Vorzeichen“ oder „\|Delta(t)\| ≥ 80. Perzentil der \|Delta\| der 720 Kerzen davor“ | s ∈ {Vorzeichen, P80} | 2 |
| H3 | **Regime-Mean-Reversion.** In Seitwärtsphasen sind Ausschläge oft Liquiditätsnachfrage, deren Preisdruck sich auflöst (Grossman-Miller 1988, Inventarrisiko der Market Maker). | Nur Regime „Seitwärts“. Long: Schluss(t) ≤ SMA24(Schluss) − k × ATR; Short spiegelbildlich. Stop = Extrem der Kerze t ∓ 1,0 × ATR | k ∈ {2, 3} | 2 |
| H4 | **Trend-Rücksetzer mit CHoCH (Multi-Timeframe).** Zeitreihen-Momentum auf Tagesbasis (Moskowitz, Ooi, Pedersen 2012) plus Kauf eines liquiditätsgetriebenen Rücksetzers, sobald die 1h-Struktur wieder dreht. | Nur in Trendrichtung („Trend auf“ → nur Long). Rücksetzer: max Hoch(t−24 … t−1) − min Tief(t−6 … t−1) ≥ d × ATR. Einstiegssignal (CHoCH-Näherung): drei aufeinanderfolgend fallende Hochs Hoch(t−4) > Hoch(t−3) > Hoch(t−2) > Hoch(t−1) und Schluss(t) > Hoch(t−1). Stop = min Tief(t−6 … t) − 0,25 × ATR. Short spiegelbildlich | d ∈ {1,5; 2,5} | 2 |
| H5 | **Session-Sweep der Asia-Spanne.** Zu Beginn liquider Sessions werden die Extreme der ruhigen Asia-Session häufig abgeholt und wieder verlassen (intraday Saisonalität von Volumen und Volatilität in Krypto). Gegenstück zu S2 (Ausbruch), nicht dessen Umkehrung, weil Stop und Ziel anders liegen. | Asia-Spanne = Hoch/Tief der 1h-Kerzen mit Eröffnung 00:00 … 06:00 UTC desselben Tages. Im Fenster w (Kerzen nach Eröffnungszeit): Hoch(t) > Spannen-Hoch und Schluss(t) ≤ Spannen-Hoch in derselben Kerze → Short; spiegelbildlich Long. Stop = Extrem der Kerze ∓ 0,25 × ATR. Höchstens ein Trade je Tag und Instrument, Ausstieg spätestens 20:00 UTC. Alle sieben Wochentage (Krypto) | w ∈ {London: Eröffnung 07:00 … 10:00 UTC, New York: Eröffnung 13:00 … 16:00 UTC} | 2 |

**S4-Bestand: 10 Varianten**, Register danach m = 58. Feste UTC-Zeiten ohne Sommerzeit (anders als S2), damit
keine Kalenderlogik als Freiheitsgrad dient.

Bewusst nicht registriert: Funding-Extreme (M2 schon gescheitert), BOS-Detektor (T1 gescheitert), Ziel 0,5 R
(Abschnitt 2.1: kein Vorteil möglich), Ziel ≥ 1 R (Abschnitt 2.1), Orderflow-Live-Regeln (S2, eigene Studie).

## 5. Erfolgskriterien (vorab, alle müssen erfüllt sein)

### 5.1 Ablauf wie Protokoll 8

1. **Training** (Vorauswahl): E[R] > 0, mindestens 500 Trades (über alle drei Instrumente, wie Protokoll 8 für Short), p < 0,10 gegen Zufall
   (unkorrigiert), Netto-Trefferquote ≥ 75 %.
2. **Validierung**: mindestens 250 Trades, E[R] > 0, p < 0,05 (unkorrigiert), Profitfaktor > 1,1, Drawdown ≤ 20 %,
   Netto-Trefferquote ≥ 75 %, alle Robustheitsregeln (5.4).
3. **Kandidatenliste einfrieren**: höchstens eine Variante je Hypothese, mit Hash und Protokollversion committen,
   bevor Holdout-Daten geladen werden.
4. **Holdout**, genau ein Lauf, nur nach Uzis Entscheidung (Abschnitt 8).

### 5.2 Urteil im Holdout

| # | Bedingung | Schwelle |
|---|---|---|
| K1 | Netto-Erwartungswert (Basiskosten) | > 0 R je Trade |
| K2 | schlägt zufällige Einstiege (Protokoll 7.1, gleiche Geometrie, gleiche Kosten, gleiche Instrumente) | Holm-Bonferroni, Familien-α 5 %, **m = 58** (alle Registereinträge, verworfene mit p = 1) |
| K3 | Mindeststichprobe (alle drei Instrumente zusammen) | ≥ 600 Trades; darunter **KEIN URTEIL** |
| K4 | maximaler Drawdown | ≤ 20 % bei 1 % Risiko je Trade (Protokoll 4.3) |
| K5 | Profitfaktor netto | > 1,0 (Basiskosten) |
| K6 | Netto-Trefferquote | Punktwert ≥ 75 % **und** untere einseitige 95-%-Grenze (Monatsblock-Bootstrap, 10 000 Ziehungen) ≥ 70 %. Diese Grenze ist **nicht** für Mehrfachtests korrigiert; die Korrektur trägt K2 |
| K7 | Kostenstress (`STRESS_COSTS`) | E[R] > 0 (strenger als Protokoll 2, dort nur Markierung) |
| K8 | keine versteckten Großverluste | mittlerer Verlust ≥ −1,30 R; größter Einzelverlust ≥ −3,0 R; Mittel der schlechtesten 5 % der Trades ≥ −1,5 R |
| K9 | Trefferquote über Zufall | Netto-Trefferquote − Netto-Trefferquote der Zufallseinstiege aus K2 ≥ 10 Prozentpunkte |
| K10 | Breite | E[R] > 0 bei mindestens 2 von 3 Instrumenten (je Instrument nur beschreibend getestet) |

Urteile: **BESTANDEN** (alle K1–K10), **NICHT BESTANDEN**, **KEIN URTEIL** (K3 verfehlt oder Daten-/Power-Gate offen).
Im Masterprompt-Vokabular: PASS / FAIL / INCONCLUSIVE.

### 5.3 Schutz gegen das Ausreizen der Trefferquote

- Ziel 0,75 R ist für alle Varianten fest, Stop je Hypothese fest. Kein Raster über Ziel, Stop oder Zeit-Stop.
- K8 verhindert, dass eine hohe Trefferquote mit seltenen Großverlusten erkauft wird.
- K9 verhindert, dass die Trefferquote nur aus der Geometrie stammt.
- Netto statt brutto: Zeit-Stop-Ausstiege knapp über Einstieg zählen nur als Treffer, wenn sie nach Kosten > 0 sind.
- Gebühren werden **genau einmal** abgezogen: Im Labormotor (`src/research_lab/backtest/engine.py`) stecken Slippage
  in den Ausführungspreisen und Gebühren einmal in `fees = fee × (entry + exit)`. Vor dem Trainingslauf belegt ein
  Test je Variante, dass `brutto − Gebühr − Funding = netto` gilt und die Slippage nicht zusätzlich als Kosten gebucht
  wird.

### 5.4 Robustheit (Protokoll 7.3, Version 1.1)

- Jahresstabilität: E[R] > 0 in mindestens 60 % der Jahre mit ≥ 5 Trades (Training + Validierung, wie Protokoll 7.3).
- Walk-Forward: 24 Monate Anpassung / 6 Monate Test, Auswahl je Hypothese zwischen ihren zwei Varianten, nur
  Trades mit Ausstieg bis Fensterende in der Anpassung (`known_at`), Test nach Signalzeit (`signalled_in`).
  Verketteter Test-Erwartungswert > 0 **und** verkettete Test-Trefferquote ≥ 75 %.
- Nachbarschaft: Die jeweils andere Rastervariante hat im Training E[R] > 0. Gilt für die geordneten Parameter
  N (H1), s (H2, Vorzeichen < P80), k (H3) und d (H4). Für H5 (w = Session, Kategorie) entfällt die Regel.
- SPA/StepM (`src/research_lab/stats/snooping.py`) über alle 58 Varianten wird berichtet, ist aber laut
  Änderungsprotokoll vom 23.10. kein Kriterium, solange Uzi das nicht entscheidet.

## 6. Mindeststichprobe und Power (Planungsrechnung, vor jeder Auswertung)

Vereinfachtes Modell: Trades unabhängig, Designeffekt 1,5 für zeitliche Häufung (gleiche Tage über drei Instrumente).
Normalnäherung, einseitig, Power 80 %. Streuung je Trade aus der Geometrie: Gewinn ≈ +0,59 R, Verlust ≈ −1,18 R
(d = 1 %), bei 75–80 % Treffern σ ≈ 0,71–0,77 R; gerechnet mit σ = 0,75 R.

| Frage | Annahme | nötige Trades |
|---|---|---|
| Trefferquote > 70 %, wahr 80 % (K6, unkorrigiert) | α = 5 % | ~180 |
| Trefferquote > 70 %, wahr 80 % (korrigiert) | α = 5 % / 58 | ~470 |
| Trefferquote > 75 %, wahr 80 % (strengere Lesart) | α = 5 % | ~660 |
| E[R] > 0, wahr +0,15 R | α = 5 % / 58 (K2) | ~590 |
| E[R] > 0, wahr +0,10 R | α = 5 % / 58 | ~1 330 |
| E[R] > 0, wahr +0,05 R | α = 5 % / 58 | ~5 300 |

Darum K3 = 600 Trades. Ein wahrer Vorteil unter ~0,15 R je Trade ist mit dem Holdout von ~21 Monaten
voraussichtlich nicht nachweisbar; dann lautet das Urteil ehrlich KEIN URTEIL oder NICHT BESTANDEN.

**Power-Gate vor dem Trainingslauf:** Ein reiner Zähllauf auf Training und Validierung zählt nur Signale und
Kostentor-Ausfälle je Variante, **ohne** Ergebnisse (kein Ausstieg, kein R). Weil ohne Ausstiege die Sperre „eine
Position je Variante und Instrument“ nicht anwendbar ist, werden zwei Zahlen berichtet: Obergrenze = alle Signale,
Untergrenze = Signale mit mindestens 24 Kerzen Abstand zum zuletzt gezählten (eine Position dauert höchstens
24 Kerzen). Maßgeblich ist die Untergrenze: Hochgerechnet auf 21 Monate muss sie ≥ 600 Holdout-Trades erwarten lassen. Varianten darunter bleiben registriert (sie zählen für m),
laufen aber mit dem vorab vermerkten Hinweis „voraussichtlich KEIN URTEIL“. Die Zählung wird mit Commit und
Datensatz-Hash festgehalten, bevor der Trainingslauf startet.

## 7. Zufallsvergleich (Baseline)

Grundlage Protokoll 7.1, mit diesen vorab festgelegten Anpassungen (der heutige Code in
`src/research_lab/stats/random_entry.py` kann sie noch nicht, Paket P2):

- je Variante, Abschnitt und Instrument 10 000 Zufallsläufe, gleiche Tradezahl, gleiche Long/Short-Verteilung,
  fester Seed **20261025**;
- **erlaubte Einstiegskerzen** sind nur die Kerzen, an denen der Kontextfilter der Hypothese gilt: H3 Regime
  „Seitwärts“, H4 Regime in Traderichtung, H5 das Sessionfenster w und höchstens ein Trade je Tag; H1/H2 alle Kerzen
  mit gültiger ATR;
- **Stopabstand in Prozent vom Einstieg**, gezogen aus der Verteilung der echten Trades derselben Variante (die
  alle das Kostentor bestanden haben). Damit besteht jeder Zufallstrade das Tor, es wird nichts verworfen oder
  neu gezogen, und ruhige Phasen werden nicht aussortiert;
- Ziel 0,75 R und **fester Zeit-Stop 24 Kerzen** (nicht die Haltedauer der echten Trades), Stop zuerst bei
  gleicher Kerze, gleiche Kosten;
- die Funktion liefert neben dem p-Wert die **Netto-Trefferquote der Zufallsläufe** (Mittel über die Läufe) für K9.

Zusätzlich beschreibend: Kaufen und Halten je Instrument.

## 8. Holdout-Freigabe

- Vor jedem Holdout-Lauf fragt Claude Uzi **per Entscheidungskarte**. Ohne Uzis ausdrückliches Wort wird der Holdout
  weder geladen noch geplottet noch zusammengefasst.
- Voraussetzungen für die Frage: Version 1.0 freigegeben, Kandidatenliste committet, Wächter-Test (Protokoll 7.4)
  mit den S4-Regeln auf synthetischen Reihen bestanden, Zähllauf und Trainings-/Validierungsbericht committet.
- Kommt nach der Validierung kein Kandidat durch, bleibt der Holdout zu und das Ergebnis lautet „kein Vorteil in
  Training/Validierung“. Dann wird Uzi nicht nach dem Holdout gefragt.
- Große Läufe auf dem Mac nur mit Uzis Ja und nie während eines CI-Testjobs.

## 9. Arbeitspakete nach Freigabe

| Paket | Inhalt | Prüfung |
|---|---|---|
| P1 | Signalfunktionen H1–H5 in `src/research_lab/hypotheses/` (nur stdlib), Kostentor, Netto-Treffer | Tests: Look-ahead (Ergebnis für t ändert sich nicht, wenn Kerzen nach t verändert werden), Kosten genau einmal, Stop-zuerst, Kostentor-Grenze 0,25 R |
| P2 | Zufallsbaseline nach Abschnitt 7 und Multi-Instrument-Lauf im Runner (gepoolte Statistik, Block-Bootstrap über Kalendermonate gemeinsam für alle Instrumente) | Test mit synthetischen Reihen; Wächter-Test 7.4 mit S4-Geometrie |
| P3 | Download ETH/SOL auf dem Mac (Uzis Ja), Prüfsummen, Lückenbericht | Vollständigkeitsbericht je Monat, Holdout-Monate gesperrt |
| P4 | Zähllauf (Abschnitt 6) | Zählbericht mit Hash committet |
| P5 | Training/Validierung, Register-Einträge (`--commit-register`), Bericht | Bericht + Register im PR, Merge nur auf Uzis „merge“ |
| P6 | Holdout, genau einmal | nur nach Entscheidungskarte (Abschnitt 8) |

## 10. Bis zur Erstellung gesehene Daten

- Alle R4-Ergebnisse (48 Varianten, Training und Validierung, inklusive Trefferquoten) und der Glückstest G4.
- S2-Entwurf und deskriptive Live-Trefferquoten der Orderflow-Regeln (Juli–Oktober 2026).
- Plan-Journal-Trades seit 24.10.2026 (zwei geschlossene Trades, beide Stop).
- **Nicht** gesehen: S4-Regeln auf irgendwelchen Daten, ETH/SOL-Archive, der Bericht der Kosten-Schwellen-Studie
  (B3), Holdout-Daten ab 2025-01.
- Bekannt ist der allgemeine Marktverlauf 2025/2026 (Abschnitt 3.1, Grenze).

## 11. Offene Punkte vor Version 1.0

| # | Punkt | Wer |
|---|---|---|
| O1 | Archivbeginn ETHUSDT/SOLUSDT USD-M prüfen; BTC-only oder drei Instrumente festlegen | Mac-Lauf + Uzi |
| O2 | Lesart des 75-%-Kriteriums (K6) bestätigen | Uzi |
| O3 | Unabhängige Methodenprüfung: erste Runde eingearbeitet (0.2); zweite Prüfung durch eine andere Person/Modell (z. B. Codex oder Chris) | offen |
| O4 | Freigabe Version 1.0 und Registrierung der 10 Varianten (Änderungsprotokoll in `../PROTOKOLL.md`) | Uzi |

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-25 | 0.1 | Entwurf | Masterprompt Phase D/E | Abschnitt 10; keine S4-Ergebnisse, kein Holdout |
| 2026-10-25 | 0.2 | Nach adversarialer Prüfung: Mindesttrades wie Protokoll 8 (500/250), Jahresstabilität ≥ 5 Trades, Kostentor auf Schluss(t), H4/H5 eindeutig, ATR benannt, Nachbarschaft je Parameter, σ aus Geometrie (K3 = 600), K6 als unkorrigiert gekennzeichnet, Zähllauf mit Unter-/Obergrenze, Zufallsbaseline mit Filtern, %-Stop und festem Zeit-Stop | Review O3 (erste Runde) | unverändert, keine S4-Ergebnisse |
