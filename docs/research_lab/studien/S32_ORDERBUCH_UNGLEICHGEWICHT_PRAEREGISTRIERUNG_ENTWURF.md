# S32: Orderbuch-Ungleichgewicht („Pfad des geringsten Widerstands“): Sagt ein dünnes Buch auf einer Seite die nächste Bewegung bei BTC voraus, und reicht das nach Kosten? (Präregistrierung, Entwurf 0.1)

| Feld | Wert |
|---|---|
| Studie | S32 (nächste freie Nummer nach S31/S31b, 12.11.2026) |
| Version | **0.1, Entwurf.** Nur Text, noch kein Code, kein Datenabruf, kein Lauf |
| Anlass | Barti 12.11.2026: Setup aus dem Video „The Only Orderflow Guide You'll Ever Need“ (6:22–9:55, S&P-Future): in einer engen Range läuft der Preis in Richtung der Buchseite mit weniger wartender Liquidität. Frage: lässt sich das in TIM einbauen? |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kosten aus `src/research_lab/protocol.py` |
| Daten | Binance USDⓈ-M BTCUSDT Perpetual: Orderbuch-Änderungen (L2) und Trades von Tardis.dev, **nur die kostenlosen Tage (jeweils der 1. eines Monats)**, Abschnitt 3 |
| Holdout | ab 2025-01-01, wird nicht geladen. Training 2020-06 bis 2022-12, Validierung 2023–2024 |
| Einordnung | Beobachtungsstudie mit gedachten Trades, ohne Registerplatz. Auch bei Bestehen kein Filter für S7b oder Engine, nur Schattenbetrieb (Abschnitt 9) |

## 1. Was das Video behauptet und was davon messbar ist

- Aggressive Marktorders sind Druck, wartende Limit-Orders sind Widerstand. Die dünnere Buchseite bricht leichter.
- Liegt der Preis in einer Range nahe einer verteidigten Grenze und ist die Gegenseite deutlich dünner, folgt eine
  Bewegung zur dünnen Seite. Im Beispiel 2–3 Ticks (ES, Tick 0,25 Punkte bei 6.840).
- Der Trader nennt keine Schwellen. Das Beispiel ist im Nachhinein ausgewählt.

Messbar ist: Buchungleichgewicht zum Zeitpunkt t, Range-Lage zum Zeitpunkt t, Preisweg danach. Nicht messbar mit
L2-Aggregaten: wer die Orders stellt, ob sie zurückgezogen werden (Pulling/Spoofing), Icebergs.

## 2. Die Kostenfrage vorab (Arithmetik, keine Messung)

Das ist der wichtigste Punkt und der Grund für die Bauart dieser Studie.

| | ES (Video) | BTCUSDT Perp in TIM |
|---|---|---|
| Tick | 0,25 Punkte ≈ 0,37 bp bei 6.840 | 0,1 USDT ≈ 0,01 bp bei rund 100.000 USD |
| Bewegung im Beispiel | 2–3 Ticks ≈ 0,7–1,1 bp | „2–3 Ticks“ wären bei BTC bedeutungslos, daher alles in bp |
| Kosten hin und zurück | Spread 1 Tick + Gebühr ≈ 0,5 bp (grobe Schätzung) | **Basis 16 bp** (Taker 5 bp + Slippage 3 bp je Seite), **Stress 32 bp**; nur Maker beidseitig 4 bp, aber ohne sichere Ausführung |

Folge: Eine Bewegung in der Größe des Videos deckt bei TIM-Kosten nicht einmal ein Zehntel der Kosten. Eine
Wette „zuerst +k bp oder zuerst −k bp“ mit Trefferquote p bringt netto k·(2p−1) − Kosten. Mit k = 20 bp und
16 bp Kosten braucht sie **p ≥ 90 %**, mit Stresskosten ist sie unmöglich. Die Forschungsliteratur
(z. B. Cont/Kukanov/Stoikov 2014 zu Order Flow Imbalance, Gould/Bonart 2016 zu Queue Imbalance) findet das
Vorhersage-Signal recht verlässlich, aber für Bewegungen in der Größe des Spreads und für Sekunden.

Darum trennt S32 zwei Fragen: **Gibt es das Signal bei BTC überhaupt (H1)?** und **Reicht es nach TIM-Kosten
für einen Trade (H2)?** Ehrliche Erwartung: H1 ja, H2 nein.

## 3. Daten

Vorhandenes in TIM reicht nicht:

| Quelle | Inhalt | Warum nicht |
|---|---|---|
| `agg_trades`/`venue_trades` (tim-core-01), aggTrades-Archive | Trades mit Aggressor-Seite | kein Orderbuch |
| Binance-Archiv `bookDepth` | Tiefe in Bändern ±1 bis ±5 % | erst ab 2023-01 (kein Training), Bänder viel zu grob (1 % = 100 bp) |
| Bitunix-Recorder (seit 12.11.2026) | Trades + `depth_book1` | nur beste Stufe, keine Historie |
| S8/P2-Depth-Datenvertrag | Binance Spot diff-depth | Entwurf, kein Collector |

Geplante Quelle: **Tardis.dev, kostenlose Tage.** Laut Tardis-Doku (gelesen 12.11.2026) sind die Tagesdateien
des 1. Tags jedes Monats ohne API-Schlüssel herunterladbar. Binance USDⓈ-M liegt ab 2019-11-17 vor, Typen
`incremental_book_L2` und `trades`. Tiefe ab 2020-01-07 als `depth@0ms`, Anfangszustand aus einem REST-Snapshot
(Top 1000 Stufen), Sequenzprüfung mit Neustart bei Lücke. Vor 2020-05-14 meldet Tardis Lücken und
Latenzspitzen, darum beginnt S32 erst danach.

| Abschnitt | Tage | Anzahl |
|---|---|---|
| Training | 1. Tag jedes Monats, 2020-06-01 bis 2022-12-01 | 31 |
| Validierung | 1. Tag jedes Monats, 2023-01-01 bis 2024-12-01 | 24 |
| Holdout | ab 2025 | gesperrt, wird nicht abgerufen |

Offen vor dem Abruf (nicht geprüft): Nutzungsbedingungen der kostenlosen Dateien (die Doku-Seiten nennen keine
Einschränkung, die AGB sind nicht gelesen), Größe je Tag. Rohdaten kommen nie ins Repo; nur abgeleitete
Sekundenwerte und Ergebnisse. Erster Schritt ist ein einzelner Tag zum Messen der Größe (Abschnitt 8).

Vorbelastung: Keine TIM-Studie hat bisher Orderbuchdaten gesehen. Trade-basierter Orderflow ist gesehen (S2, S8,
S19, S21, OF2: alle ohne belegten Vorteil). Der 1. eines Monats ist kein zufälliger Tag (Monatswechsel,
Funding-Zeitpunkte wie sonst); das wird als Grenze berichtet, nicht korrigiert.

## 4. Buchzustand und Merkmale (fest, keine Variation)

- Buch je Sekunde aus allen Nachrichten mit Börsenzeit ≤ t nachgebaut. Ungültiges Buch (Sequenzlücke,
  gekreuztes Buch, Snapshot fehlt) = Sekunde ungültig, kein Signal. Erste 60 s nach einem Neuaufbau ungültig.
- Mitte m = (bester Bid + bester Ask) / 2.
- **Ungleichgewicht I5** = Summe Bid-Menge im Band [m − 5 bp, m) geteilt durch Summe Ask-Menge im Band
  (m, m + 5 bp]. Ein Band in bp statt N Stufen, weil BTC-Stufen von 0,1 USDT einzeln fast leer sind.
- **Ungleichgewicht L5** = Bid-Menge der besten 5 Stufen / Ask-Menge der besten 5 Stufen (am nächsten am Video).
- Signal **long**, wenn I5 ≥ 3; **short**, wenn I5 ≤ 1/3. Eine Schwelle, keine Suche. L5 nur in H1b.
- **Range-Lage (H3):** Fenster 15 min vor t. Range = Hoch − Tief der Mitte. Untere Grenze „verteidigt“, wenn
  die Mitte im Fenster mindestens 2-mal bis auf 2 bp an das Tief kam und sich danach jeweils um mindestens
  5 bp entfernte. Long-Lage: Mitte im unteren Viertel der Range und untere Grenze verteidigt. Short
  spiegelbildlich. Range enger als 10 bp oder weiter als 60 bp: keine Range-Lage.
- Abkühlung: höchstens ein Ereignis je 300 s (gleich dem Horizont), damit sich die Ergebnisfenster nicht
  überlappen. Das erste Signal im Fenster zählt.
- Sitzungsetikett (nur beschreibend): Asien 00–07, London 07–13:30, New York 13:30–20, Rest 20–24 UTC.

## 5. Fragestellung

| | Frage | Messung | Bestehen |
|---|---|---|---|
| H1 | Zeigt I5 die Richtung an? | Vorzeichen der Mitte-Änderung von t+1 s bis t+30 s (gleich = ausgelassen) | Trefferquote > 50 % in Training **und** Validierung, untere Grenze 95-%-Intervall > 50 % (Block-Bootstrap über Tage) |
| H1b | Dasselbe mit L5 | wie H1 | nur beschreibend, zählt nicht für Holm |
| H2 | Reicht es für einen Taker-Trade? | Einstieg Taker am besten Ask (long) bzw. Bid (short) bei t+1 s; Ziel +20 bp, Stop −20 bp, Zeitstopp 300 s; Netto mit Basiskosten (16 bp hin und zurück) | mittleres Netto > 0 in Training **und** Validierung, untere Intervallgrenze > 0; Stresskosten berichtet |
| H3 | Hilft die Range-Lage? | H2 nur für Ereignisse mit Range-Lage in Signalrichtung, gegen H2 ohne Range-Lage | Netto > 0 wie H2 **und** besser als H2 ohne Filter in beiden Abschnitten |

- Eine Sekunde Verzögerung bildet ab, dass TIM nicht in Tokio steht. Ausstieg bei Ziel/Stop: erster Trade
  durch den Preis; Stop-Slippage 5 bp wie im Protokoll.
- Mehrfachtests: Holm über H1, H2, H3 (m = 3). Für den Deflated Sharpe zählen H2 und H3 als **2 neue Versuche**
  (64 → 66).
- Mindestmenge je Abschnitt: 300 Ereignisse (H1, H2), 100 (H3). Darunter „nicht prüfbar“.
- Maker-Variante (Einstieg als Limit an der eigenen Seite, 2 bp Gebühr je Seite): **nur beschreibend**, weil die
  Ausführung aus L2-Aggregaten nicht sicher bestimmbar ist (Platz in der Warteschlange unbekannt).

## 6. Auswertung

Je Abschnitt: Ereigniszahl (long/short, je Sitzung), Trefferquote H1 mit Intervall, Netto-bp H2/H3 mit Basis-
und Stresskosten, nötige Trefferquote zum Ausgleich der Kosten, Zufallsvergleich (gleiche Sekunden, zufällige
Richtung), Ergebnis je Tag (zeigt, ob einzelne Tage alles tragen). Bericht unter `../reports/` mit
STATUS/CHANGES/TESTS/EVIDENCE/BLOCKERS/NEXT_ACTION.

## 7. Nicht Teil von S32

Andere Schwellen, Bänder oder Horizonte (wären neue Versuche), Spot-Buch, andere Börsen, Liquidationen,
Kombination mit S7b, Echtgeld, Live-Orders.

## 8. Ablauf und Prüfbefehle

1. Barti und Uzi lesen den Entwurf. Änderungen nur jetzt, vor jedem Datenkontakt.
2. Machbarkeit Daten (braucht Bartis Go): AGB der kostenlosen Tardis-Dateien lesen; **einen** Trainingstag
   (2020-06-01) laden, Größe und Rechenzeit messen, Buchnachbau gegen die Trades prüfen (kein Trade außerhalb
   des besten Bids/Asks ± 1 Tick). Noch keine Signale ansehen.
3. Code `src/research_lab/studies/s32.py` mit Tests (Buchnachbau, Lücken, Range-Lage, Holdout-Sperre),
   `evaluate` gesperrt bis 1.x.
4. Zähllauf (PS5): nur Ereigniszahlen je Abschnitt. Uzis Wort und Bartis Go → Einfrieren als 1.0.
5. Auswertung einmal, Ergebnis ohne Nachbessern.

## 9. Was bei Bestehen folgt

Auch bei Bestehen kein Einbau als Handelsregel. Nächster Schritt wäre ein Schattenlauf mit eigenem Recorder
(Binance `btcusdt@depth20@100ms` oder der S8/P2-Vertrag) und eigenen, vorab registrierten Zeitgrenzen, denn
55 Tage sind wenig und der Holdout bleibt zu. Besteht nur H1, ist die nützliche Form eher ein **Einstiegs-Timing
für bestehende Setups** (z. B. Limit statt Market, wenn das Buch gegen den Einstieg steht) als ein eigenes Setup;
das wäre eine eigene Studie.
