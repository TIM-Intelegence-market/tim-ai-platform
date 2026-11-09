# S19: Orderflow-Schwellen an BTC messen: Sagen Imbalance 400 %, Cluster 3x, dünnes Extrem 25 % und die Anstrengungs-Schwellen an BTC etwas über die nächste Stunde aus, und wäre ein anderer Wert besser? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S19 (nächste freie Nummer nach S18, 09.11.2026) |
| Version | **0.1, Entwurf.** Kein Code, keine Daten geladen. Vor 1.0: Regeln als Code (`src/research_lab/studies/s19.py`, Skript `scripts/research_lab_s19.py`, Tests), ergebnisblinder Zähllauf, dann Einfrieren auf Uzis Wort |
| Anlass | Master-Analyse 09.11.2026 aus Kundensicht (Broncx), Punkt P8: „Schwellen stammen aus Quellen, nie an BTC gemessen“; Glossar `../../knowledge/ORDERFLOW_BEGRIFFE.md` |
| Geprüfter Code | `src/orderflow_scenario/footprint.py` (F1–F5) und `src/orderflow_scenario/engines/orderflow_interpretation.py` (R1–R4), Konstanten in Abschnitt 2 des Glossars; Regelstand = Commit beim Einfrieren |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nicht geladen. Training bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31 (Abschnitt 3 des Protokolls) |
| Einordnung | **Beobachtungsstudie ohne Trades, ohne Registerplatz** (wie S15/S17, Entscheidung Uzi beim Einfrieren): sie misst nur, ob ein Flag eine Richtungsneigung hat. Kein Setup, kein Edge-Nachweis, keine Holdout-Erlaubnis |

## 1. Fragestellung

TIM setzt sieben Orderflow-Schwellen aus Lehrmaterial: Imbalance ab dem 4-Fachen, Stacked ab
drei, Absorptions-Cluster ab 3 × Stufenmittel, dünnes Extrem bis 25 % des Stufenmittels,
Anstrengung schwer ≥ 1,2 ×, dünn < 0,7 ×, Range schrumpfend < 0,8 ×. Keine davon wurde an
BTC gemessen.

1. **Hat das Flag mit dem heutigen Wert an BTC eine Richtungsneigung?** Nach einem Flag der Art K
   ist der Schluss h Kerzen später häufiger in Richtung R(K) als die Basisrate derselben Woche.
2. **Wäre ein Nachbarwert aus einem vorab festgelegten Raster besser?** Nur dann wird eine Schwelle
   geändert; „besser“ ist in Abschnitt 5 definiert, nicht nachträglich.

Nicht geprüft: Einstieg, Stop, Ziel, Kosten, Kombination mit Level oder HTF-Kontext. Das wäre
eine Strategie-Studie mit eigener Präregistrierung.

## 2. Vorbelastung

- **S2** (Live-Orderflow-Regeln auf 60-Sekunden-Fenstern, beendet NICHT BEURTEILBAR): Das Power-Gate
  scheiterte an der Wochen-Korrelation der Ereignisse. Lehre für S19: Ereignisse clustern in wenigen
  Marktphasen, der Block-Bootstrap läuft über Wochen, und das Gate zählt effektive Wochen, nicht Flags.
- **S8** (lokale Orderflow-Prognose, Sequenzvergleich 28.10.: kein praktischer Zusatznutzen): nutzt
  dieselben Spot-aggTrades 2020–2024 als Minutenbalken, aber keine Footprint-Flags je Preisstufe.
  Training und Validierung dieses Datensatzes sind damit schon einmal angesehen worden, wenn auch mit
  anderen Merkmalen.
- **Gesehen vom Autor:** Live-Footprints im TIM-Chart seit 29.10.2026, die Kontrolle vom 06.11.2026
  (Datenabgleich, keine Trefferquoten) und die Live-Journale seit 01.11. (10 Trades, ohne Footprint).
  Keine Archiv-Statistik zu Imbalances, Clustern oder Extremen. Der Orderflow-Schatten (seit 08.11.,
  PR #154/#155) liefert sein erstes Urteil erst ab 30 Plänen und wurde nicht angesehen.
- **Gegenargument:** Footprint-Flags auf 15-Minuten-Kerzen sind häufig (mehrere je Tag); eine kleine
  Richtungsneigung kann statistisch sicher und praktisch wertlos sein. Deshalb fordert Kriterium 2
  eine Mindestgröße (3 Prozentpunkte), nicht nur p < 0,05.

## 3. Daten

- **Instrument:** BTCUSDT Spot, Binance-aggTrades aus den Tagesarchiven mit Prüfsumme
  (`src/research_lab/data/aggtrades.py`, `AggTradeDayStore`, Holdout-Sperre im Lader). Spot, weil der
  Archiv-Lader und die S8-Minutenbalken dafür bestehen. Der Perp (futures/um) ist beschreibend
  vorgesehen, sobald der Lader ihn vor dem Einfrieren kann; sonst entfällt er, ohne Urteil.
- **Kerzen:** 15m aus den Trades (Eröffnung erster Preis, Hoch/Tief Extrem, Schluss letzter Preis,
  Volumen Summe), UTC. Gegenprobe mit Binance-Spot-Klines je Kerze (Abweichung wird berichtet).
- **Footprint:** je 15m-Kerze Bid/Ask je 5-$-Stufe aus `footprint_from_trades` (derselbe Code wie die
  Engine, Tick 5 $). Kerzen mit weniger als 20 gehandelten Stufen zählen nicht (zu dünn für F4/F5).
- **Zeiträume:** Training 2020-01-01 bis 2022-12-31 (156 Wochen), Validierung 2023-01-01 bis
  2024-12-31 (104 Wochen). Holdout 2025 bleibt zu.
- Tage mit Archiv-Lücke werden ausgelassen und gezählt; eine Kerze zählt nur, wenn ihre h Folgekerzen
  lückenlos vorliegen.

## 4. Flags, Raster und erwartete Richtung (vorab festgelegt)

Je 15m-Kerzenschluss werden die Flags mit jedem Rasterwert berechnet; der heutige Wert ist fett.
Ein Flag zählt nur, wenn es mit dem heutigen Wert derselben Familie **nicht** schon in einer der drei
Kerzen davor stand (Entprellung: ein Ereignis je Lauf).

| Familie | Flag (Code) | Raster | Erwartete Richtung R(K) |
|---|---|---|---|
| I Imbalance | F1 + F2 `stacked_buy` / `stacked_sell` | Faktor ∈ {3, **4**, 5} × Stapel ∈ {2, **3**, 4} | Fortsetzung in Richtung der Imbalance (Bootcamp: Aggression mit Fortsetzungsneigung) |
| A Auktionsrand | F3 `finished_high` / `finished_low` am Extrem in Bewegungsrichtung | keine Zahl, nur heutige Lesart | Umkehr gegen die Bewegung |
| C Cluster | F4 `absorption_cluster` | Faktor ∈ {2, **3**, 4} | Umkehr gegen den Aggressor (passive Seite hält) |
| T Dünnes Extrem | F5 `thin_extreme` | Anteil ∈ {0,20, **0,25**, 0,30} | Umkehr gegen die Bewegung |
| H Absorption (Anstrengung) | R1/R2 `ABSORPTION` | schwer ∈ {1,0, **1,2**, 1,5} | Umkehr gegen den Aggressor |
| E Exhaustion (Anstrengung) | R3/R4 `EXHAUSTION` | dünn ∈ {0,6, **0,7**, 0,8} × schrumpfend ∈ {0,7, **0,8**, 0,9} | Umkehr gegen den Aggressor |

Bewegungsrichtung = Vorzeichen von Schluss minus Schluss vier Kerzen davor; Aggressor = Vorzeichen
des Kerzen-Deltas. Fehlt eines (Null), zählt die Kerze nicht.

Horizonte h ∈ {4, 16} Kerzen (1 h, 4 h). Treffer = Schluss nach h Kerzen liegt in Richtung R(K)
gegenüber dem Schluss der Flag-Kerze; Gleichstand zählt als Fehlschlag.

Basisrate: Anteil der Kerzen derselben ISO-Woche, deren Schluss nach h Kerzen gestiegen ist (für
R = steigt) bzw. gefallen ist (für R = fällt), über alle Kerzen der Woche. Lift = Trefferquote nach
Flag minus Basisrate, in Prozentpunkten.

## 5. Erfolgskriterien

Je Familie, Rasterwert und Horizont eine Hypothese H0: Lift ≤ 0. Statistik: Lift über alle Ereignisse,
Varianz aus einem Block-Bootstrap über ISO-Wochen (Blocklänge 4 Wochen, 9 999 Ziehungen, Seed 19),
p einseitig. Holm-Korrektur über **alle** Hypothesen der Studie zusammen: 9 + 1 + 3 + 3 + 3 + 9 = 28
Flags × 2 Horizonte × 2 Richtungen = 112, Familien-α = 5 %.

**Ein heutiger Wert gilt als bestätigt**, wenn in Training **und** Validierung getrennt:

| # | Kriterium |
|---|---|
| 1 | ≥ 500 Ereignisse je Richtung und ≥ 100 Wochen mit mindestens einem Ereignis |
| 2 | Lift ≥ 3 Prozentpunkte auf h = 4 |
| 3 | Holm-korrigiertes p < 0,05 auf h = 4 |
| 4 | Lift auf h = 16 ≥ 0 (die Neigung kippt nicht) |

**Ein Rasterwert ersetzt den heutigen Wert** nur, wenn er selbst 1–4 erfüllt **und** sein Lift auf
h = 4 in Training und Validierung jeweils mindestens 2 Prozentpunkte über dem des heutigen Werts
liegt. Erfüllen mehrere Rasterwerte das, gewinnt der dem heutigen Wert nächste (keine Randwerte, wenn
die Mitte reicht). Jede andere Konstellation lässt die Schwelle unverändert.

Ergebnis je Familie: „bestätigt“, „bestätigt, Nachbarwert besser“ (mit Wert), „ohne Nachweis“ (keiner
erfüllt 1–4) oder „nicht testbar“ (Gate 5.1). „Ohne Nachweis“ ändert den Code nicht, aber das Glossar
trägt es ein, und Uzi entscheidet, ob die Engine den Beleg weiter wertet.

### 5.1 Machbarkeits-Gate (ergebnisblind, vor jeder Trefferquote)

Zähllauf nur mit Ereigniszahlen und Wochen je Familie, Rasterwert, Richtung und Zeitraum, ohne
Folgeschluss. Eine Familie geht nur in die Auswertung, wenn der heutige Wert Kriterium 1 in Training
und Validierung erfüllt. Das Gate wird nicht gelockert; fällt eine Familie durch, heißt sie „nicht
testbar“ und ihr Raster wird nicht angesehen.

### 5.2 Beschreibend, ohne Urteil

- Mittlere Folge-Log-Rendite in Richtung R(K) in Basispunkten je Flag und Horizont, mit und ohne
  Entprellung.
- Lift je Kalenderjahr (Stabilität), je UTC-Tageszeit in sechs Blöcken (Bezug S17).
- Anteil der Kerzen mit mindestens einem Flag (wie häufig „feuert“ die Engine).
- Perp statt Spot, falls geladen (Abschnitt 3).
- Abweichung der Trade-Kerzen von den Binance-Klines.

## 6. Was nicht geändert wird

- Die Flag-Definitionen (Diagonale 1 Tick, äußere 20 % der Range, Maßstab fünf Kerzen) bleiben; nur
  die Zahlen aus dem Raster variieren. Die Chart-Lesart der Imbalance auf Zeilenbreite wird nicht geprüft.
- Kein Raster außerhalb der Tabelle, kein weiterer Horizont, keine zweite Messgröße als Kriterium.
- Zwischenstände der Trefferquoten werden vor dem vollständigen Lauf nicht angesehen.
- Live-Journale, Orderflow-Schatten, Chart und Engine bleiben bis zum Ergebnis unverändert.

## 7. Ablauf bis 1.0

1. Code: Flags aus `footprint_from_trades` und `OrderflowInterpretationEngine` auf 15m-Kerzen aus dem
   Archiv, Raster als Parameter, Zähllauf (5.1) und Auswertung getrennt, Tests mit synthetischen Trades
   (jedes Flag einmal ausgelöst, Entprellung, Basisrate, Holm-Zahl 112).
2. Zähllauf auf dem Mac (Archive liegen dort, die Cloud erreicht `data.binance.vision` nicht), Bericht
   `../reports/s19_count_<Zeit>.md` nur mit Zahlen.
3. Uzis Wort: Einfrieren als 1.0 mit Commit, Einordnung (Registerplatz ja/nein) ins Protokoll.
4. Ergebnislauf Training, dann Validierung; Bericht nach Abschnitt 5; Glossar nachführen.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-09 | 0.1 | Entwurf aus der Master-Analyse (P8). Kein Code, keine Daten geladen, kein Registereintrag. |
