# Plan: Selbstverbessernde Trading-KI mit Orderflow und Optionsflow

Stand 13.11.2026. **Plan-Dokument, kein Code.** Nichts hier ändert Live-Verhalten, Regeln, Journale oder Scores.
Anlass: Uzi am 13.11.2026: „selfimproving Trading KI, die Orderflow und Optionsflow kann“.
Regeln: Echtgeld gesperrt, keine Orders, keine Keys im Repo, Holdout 2025 nur mit Uzis ausdrücklichem Wort,
Merge nur auf Uzis (oder Chris') Wort. Die Parallelarbeit „Orderflow-Engine bis 50 USD pro Tag“ wird nur
referenziert, nicht dupliziert.

## 1. Ziel, Erfolgskriterium, Nicht-Ziele

- **Ziel:** Ein System, das Orderflow- und Optionsflow-Merkmale zusammen auswertet und seine eigenen
  Regeln nach festen Prüfregeln verbessert, ohne dass es sich selbst in Live-Code oder Echtgeld schreibt.
- **Erfolgskriterium (ehrlich):** Nicht „die KI lernt“, sondern: eine vorab registrierte Regel besteht
  Validierung 2024 und danach einen Vorwärtslauf im Papier (mind. 30 Tage, ≥ 100 Trades) **nach** Bitunix-Kosten.
  Bis dahin ist die Antwort auf „hat sie einen Edge“ nein.
- **Nicht-Ziele:** Live-Orders, Selbständerung des Live-Codes, automatische Regeländerung, neue Pipeline
  neben dem vorhandenen Gedächtnis, Holdout-Nutzung ohne Freigabe.

## 2. Was TIM schon hat (wiederverwenden)

| Baustein | Ort im Repo | Rolle im neuen Plan |
|---|---|---|
| Orderflow-Engine OF2 (M1–M7), Footprint, Kosten-Gate | `src/research_lab/of2`, `docs/research_lab/studien/OF2_*` | Orderflow-Seite der Merkmale |
| OFX-Suche (Parameterraum, Sieb, Dauerlauf PS5/PS4) | `src/research_lab/ofx` | Suchmaschine; Optionsmerkmale als weitere Dimension |
| Research Engine, Protokoll 1.3, Register, Präregistrierung | `src/research_lab/protocol.py`, `docs/research_lab/PROTOKOLL.md`, `REGISTER.jsonl` | Pflichtweg jeder Idee |
| Gedächtnis G1–G3 (Aussagenliste, Status, Begründung je Plan) | `src/research_lab/gedaechtnis.py`, `begruendung.py`, `docs/research_lab/gedaechtnis/` | Speicher der „Erkenntnisse“; Fehlerfinder G4 ist die Selbstkritik |
| Lernschleife L1, Werkstatt, Selbstverbesserung, Trade-Reflexion | `src/research_lab/learning`, `workshop/self_improve.py`, `workshop/trade_reflection.py` | Gerüst der Wochenschleife, nur Vorschläge |
| Gamma/GEX, Walls, Flip, Max Pain, Expected Move (Deribit, 5-min-Log seit 04.11.) | `src/options_gamma`, `src/dashboard/gamma_data.py`, `GEX_WAND_REAKTION_ENTWURF.md` | Optionsflow-Stufe 0, **Bestand statt Fluss** |
| Schatten-Score (Trades, Footprint neben Live-Score) | Journal, PR #255 | Ort, an dem neue Signale zuerst nur mitlaufen |
| Binance-Metrics (OI, Top-Trader, Taker-Verhältnis), S28 | `S28_*` | Vorbild für „Positionierung als Merkmal“ |
| Kosten, Walk-forward, Bootstrap/Verschiebungstest, Holm | S24–S28 Code unter `src/research_lab/studies` | Prüfwerkzeug unverändert übernehmen |

Regel: Kein neues Modell, wenn ein vorhandener Baustein es mit einer Zusatzspalte erledigt.

## 3. Optionsflow: Datenquellen

Wichtig: Gamma/GEX aus dem Deribit-Bestand ist **Positionierung**, kein **Fluss**. Optionsflow heißt hier:
einzelne Optionstrades (Größe, Seite, Strike, Verfall, Aggressor), Blocktrades, Änderung von Open Interest,
Put/Call-Verhältnis, Implied Vol / Skew über die Zeit. Dafür braucht es Historie.

| Quelle | Inhalt | Kosten | Historie | Bewertung |
|---|---|---|---|---|
| Deribit öffentliche API (`get_book_summary_by_currency`, `get_last_trades_by_currency_and_time`, Websocket `trades.option.*`, DVOL) | Bestand, Trades, Index | kostenlos, ohne Key | Bestand nur aktuell; Trades-Abfrage reicht begrenzt zurück (Umfang vor Nutzung messen) | **Start**: Recorder ab sofort, wie beim Gamma-Log |
| Binance European Options (`eapi`, Websocket) | Trades, Ticker, OI, Mark/IV | kostenlos live | Tardis führt Daten ab 15.06.2023 | zweite Quelle, kleiner Markt, Plausibilitätsabgleich |
| Tardis.dev | Deribit-Optionen komplett (Trades, Quotes, Ticker mit Greeks, Mark-IV), Daten ab 30.03.2019 bzw. Quotes/Ticker ab 01.10.2019; Binance-Optionen ab 15.06.2023 | bezahlt (Preis hier **nicht geprüft**, vor Entscheidung auf der Seite nachsehen); gratis nur jeweils der 1. Tag eines Monats | ja | beste Trainingshistorie; Trainings-/Validierungsfenster 2020–24 abdeckbar |
| Amberdata, Laevitas, CoinAPI, Kaiko | Optionstrades, Flow, Skew | bezahlt, Preise nicht geprüft | ja | nur Alternative, falls Tardis nicht reicht |
| Deribit Insights / Reports | Marktberichte | frei | Text, keine Rohdaten | nur als Gegenprobe, nicht als Trainingsdaten |

Konsequenz: **Ohne bezahlte Historie ist Training 2020–23 mit echten Optionstrades nicht möglich.** Kostenlos geht nur
Vorwärtsaufzeichnung (Recorder), und die liefert frühestens nach Monaten genug Stichprobe. Die gratis Monatsersten
(Tardis) taugen für Datenvertrag und Parser-Tests, nicht für Statistik. Bezahlung ist Uzis Entscheidung; vorher keine Konten, keine Keys.

Datenregeln: Zeitstempel in UTC, Quelle und Abrufzeit je Zeile, Rohdaten unverändert ablegen, abgeleitete Spalten getrennt,
keine Zukunftsinformation (Merkmal zum Zeitpunkt t nur aus Daten ≤ t, Optionsbestand mit Schnappschuss-Zeit).
Dateien unter `data/options/` bleiben außerhalb des Repos (Größe, Lizenz der Anbieter).

## 4. Wie „selbstverbessernd“ sicher geht

Selbstverbesserung heißt hier: **das System schlägt vor, prüft und verwirft; ein Mensch aktiviert.**

1. **Nur Papier und Schatten.** Die Schleife darf nur Forschungsläufe, Papier-Journal und Schatten-Score schreiben.
   Kein Zugriff auf Live-Pfade, Kraken/Bitunix-Schlüssel, Stop-Dateien oder Risikolimits.
2. **Feste Fenster.** Training 2020–2023, Validierung 2024, Holdout 2025 **nur** mit Uzis ausdrücklichem Wort, einmalig,
   nie in der Suche. Für Optionsmerkmale gilt das gleiche Fenster; reicht die Historie nicht, gilt
   „nicht prüfbar“, nicht „kürzeres Fenster nehmen“.
3. **Vorab-Registrierung.** Jede Kandidatenregel wird vor dem ersten Blick auf Validierung eingefroren
   (Protokoll 1.3, Studien-Nummer, Code-Stand). Änderung = neue Version.
4. **Mehrfachtest-Korrektur.** Zählung aller je geprüften Kandidaten im Register; Holm über die Familie, Bootstrap
   und Verschiebungstest wie S24. Das Register von 58 Hypothesen (laut Gedächtnis-Plan) ist der Nenner; jede neue
   Optionsfamilie erhöht ihn. Training mehrfach benutzen ist erlaubt, Validierung nur einmal pro Version.
5. **Kosten zuerst.** Bitunix-Taker 0,06 %, Schlupf, Funding, bei Optionsmerkmalen zusätzlich: Merkmal-Verzögerung
   (Daten kommen mit Latenz) und realistische Ausführung zum nächsten Kurs, nicht zum Signalkurs.
6. **Mindeststichprobe.** < 100 Trades = „nicht prüfbar“ (wie S31b). Kein Urteil aus kleinen Zahlen.
7. **Gedächtnis statt Parallel-Ablage.** Jede Erkenntnis wird eine Aussage in `aussagen.jsonl` mit Status
   belegt / hinweis / ungeprüft / widerlegt. Der Fehlerfinder (G4) sucht Widersprüche zwischen Code und Status.
   Widerlegtes bleibt als Negativwissen stehen.
8. **Keine Selbständerung des Live-Codes.** Die KI darf Patches **vorschlagen** (Branch, PR), nie mergen oder deployen.
   Merge nur auf Wort von Uzi oder Chris, gemäß `CI.md` und `PR gate`.
9. **Rückfall und Verfall.** Eine übernommene Regel hat ein Ablaufdatum und wird bei Verschlechterung im Papier
   automatisch auf „Schatten“ zurückgestellt (nur Papier, kein Live-Eingriff).
10. **Adversariale Prüfung** (Skill `adversariale-pruefung`) vor jedem Statuswechsel auf „belegt“.
11. **Kein LLM als Entscheider.** Sprachmodelle dürfen Hypothesen formulieren und Berichte schreiben; die Zahl
    entscheidet die feste Prüfregel, nicht das Modell.

Wochenschleife (Vorschlag): Sonntagsbericht → Fehler im Gedächtnis (max. 3) → neue Hypothesen aus Journal und
Optionsmerkmalen → Registrierung → Trainingslauf PS5 → ggf. einmalige Validierung → Ergebnis ins Gedächtnis → Vorschlag an Uzi.

## 5. Ehrliche Einschätzung der Chance

- Die eigenen Studien S24 (alle Indikatoren, 34.848 Trades Validierung), S26 (Aufwand gegen Ergebnis) und S27 (größere
  Trades) endeten mit **„NO ROBUST EDGE PROVEN“**. In S24 sortierte das Regressionsmodell zwar signifikant
  (Abstand 0,135 R, Holm bestanden), aber auch die beste Gruppe verlor nach Kosten im Mittel 0,38 R je Trade.
  S27 zeigt: weitere Stopps senken den Kostenanteil (−0,10 R statt −0,44 R), lassen aber keinen Vorteil übrig.
  S31b: Orderflow-Regeln auf BTC 2020–22 liefern zu wenige Trades (< 100) für ein Urteil. S28 (Positionierung)
  ist vorbereitet, Ergebnis lag mir hier nicht vor. S29/S30 sind nach Projektnotizen noch nicht abgeschlossen oder hier nicht im Repo.
- Optionsflow ist neu für TIM, aber kein Freifahrtschein. Bekannte Gründe, warum er helfen könnte: Positionierung
  und Hedging-Fluss (Gamma) wirken auf kurze Sicht auf den Kurs; große Optionstrades enthalten teils Information.
  Gründe, warum es trotzdem scheitern kann: öffentlicher Flow ist breit bekannt und schnell eingepreist; Aggressor-Seite
  bei Optionen ist oft unsicher; Deribit-Liquidität konzentriert sich auf wenige Verfälle; Historie ist kurz oder teuer;
  jede neue Merkmalsfamilie vergrößert das Mehrfachtest-Problem.
- **Meine Einschätzung (Schätzung, nicht gemessen):** Die Chance, dass Optionsflow allein nach Kosten einen belegten Edge
  auf BTC liefert, ist klein. Realistischer ist ein Nutzen als **Filter/Regime** (z. B. Gamma-Regime, Skew-Extreme,
  Blocktrade-Richtung) für die Orderflow-Setups. Selbst das ist nur Hypothese.
- Das Ziel „Ø 50 USDT/Tag netto“ ist ein Richtwert, kein Plan-Erfolgskriterium. Eine selbstverbessernde Schleife
  erzeugt keinen Edge, der in den Daten nicht steckt; sie findet nur schneller, ob einer da ist.
- Wert auch bei Misserfolg: saubere Negativergebnisse im Gedächtnis, eine fertige Optionsdaten-Pipeline, ein Test,
  ob Optionsmerkmale Orderflow-Trades verbessern.

## 6. Pakete (klein, in Reihenfolge, jedes nur auf „go“)

| Nr | Paket | Ergebnis | Prüfbefehl / Nachweis | Abhängigkeit |
|---|---|---|---|---|
| A0 | Dieses Dokument lesen, Entscheidung zu Daten (nur Aufzeichnen oder Tardis kaufen) | Uzis Wort | Antwort auf die Fragen in Abschnitt 7 | – |
| A1 | **Optionsfluss-Recorder** (Deribit-Trades, OI, DVOL; später Binance) read-only, Rohdaten + Zeitstempel, Lücken-/Duplikat-Check | Dauerdatei außerhalb Repo | Test mit Fixture; 24-h-Lauf ohne Lücke > 60 s | keine |
| A2 | **Datenvertrag Optionsflow** (Spalten, Zeitregel, Latenz, Aggressor-Logik) + Parser-Tests mit Gratis-Monatsersten (Tardis) | Doku + Tests | `pytest tests/…options_flow` grün | A1 optional |
| A3 | **Merkmale** (Put/Call-Flow, Netto-Prämie, Blocktrade-Richtung, Skew, Gamma-Regime aus vorhandenem Log) als Spalten im vorhandenen Merkmalsraum | Spalten, keine Regel | Test „kein Blick in die Zukunft“ | A2 |
| A4 | **Studie S-Optionen, Präregistrierung 1.0**: Verbessern Optionsmerkmale die OF2-/S24-Trades nach Kosten? Training 2020–23 | Präregistrierung, Zähllauf (ergebnisblind) | Zähllauf-Bericht mit n | A3 + Historie (Tardis) |
| A5 | **Schatten-Spalte**: Optionsmerkmale laufen im Schatten-Score/Papier-Journal mit, ohne Wirkung | Journal-Feld | Journal enthält Feld, Score unverändert | A3 |
| A6 | **Wochenschleife** auf Gedächtnis (G4 Fehlerfinder + Hypothesenliste), nur Bericht/Vorschläge | Sonntagsbericht-Abschnitt | Lauf ohne Schreibzugriff auf Live-Pfade (Test) | G3/G4 aus Gehirn-Plan |
| A7 | Validierung 2024 **einmalig**, nur wenn A4 Training ≥ 100 Trades zeigt | Ergebnisdatei | Protokoll-Eintrag | A4, Uzis Wort |
| A8 | Vorwärtslauf Papier ≥ 30 Tage | Journal-Auswertung | Bericht mit n und Kosten | A5, A7 bestanden |
| A9 | Holdout 2025, einmalig | Ergebnis | – | **nur Uzis ausdrückliches Wort** |

A1 und A2 sind die einzigen Pakete ohne Datenkauf. A4–A9 hängen an der Historie.

## 7. Offene Fragen an Uzi

1. Nur aufzeichnen (kostenlos, Stichprobe erst in Monaten) oder Tardis-Historie bezahlen (Preis vorher prüfen, Konto/Key nur von Uzi)?
2. Start mit A1/A2 (Recorder + Datenvertrag)? Der Recorder läuft am Mac/Server als Dauerdienst, das ist ein neuer Dienst und braucht dein Wort.
3. Soll Optionsflow zuerst als **Filter** für Orderflow-Setups getestet werden (meine Empfehlung) oder als eigene Strategie?

## 8. Grenzen dieses Dokuments

- Quellenlage zu Anbietern: Verfügbarkeit ab-Datum von der Tardis-Dokumentation (Deribit ab 30.03.2019, Binance Optionen ab 15.06.2023).
  Preise, Lizenzbedingungen und Deribit-Rückblick der öffentlichen Trades-API sind **nicht geprüft**.
- Ergebnisse S24–S28, S31b stammen aus den Berichten im Projektordner und aus dem Repo; nicht neu gerechnet.
- Status von S29/S30 und der Parallelarbeit „Orderflow-Engine bis 50 USD pro Tag“ nicht eingesehen; dort nachlesen, nichts doppeln.
