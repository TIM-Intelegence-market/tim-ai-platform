# S12: Trifft die geschätzte Liquidations-Heatmap echte Liquidationen? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S12 (S11 ist laut Logbuch vergeben: von Uzi am 28.10. abgelehnte Variante ohne Filter) |
| Version | **1.0 – ZUR FREIGABE.** Sammler L1–L3 gebaut, Probelauf seit 31.10.2026 (zählt nicht zur Studie), kein Ergebnis |
| Anlass | Uzi 31.10.2026 („go“ auf die Empfehlung N1). Grundlage: Auswertung des Berichts „Orderflow verstehen und prüfen“ (Deep Research, 28.10.2026), `/mnt/project-files/analysen/orderflow-research-2026-10-28/bewertung.md` |
| Protokoll | `../PROTOKOLL.md`; eigene **prospektive** Familie wie S8 und L1 (kein Archiv, kein Holdout berührt) |
| Art | Kalibrierung eines Anzeigemodells. **Keine Handelsregel, kein Signal, kein Echtgeld** |

## 1. Fragestellung

Die Liquidations-Heatmap im Control Center (`src/liquidation_map/heatmap.py`, PR #24) ist eine Schätzung aus dem
Open Interest (OI) und den Kerzen von Binance-Futures. Sie nimmt halb Long, halb Short und eine feste Hebel-Mischung
an. Ob sie dort liegt, wo wirklich liquidiert wird, hat TIM nie gemessen.

**Einzige geprüfte Behauptung:** Die OI-basierte Schätzung sagt den Ort gemeldeter Liquidationen in den nächsten
6 Stunden besser voraus als dieselbe Schätzung ohne OI-Information (reine Preis-Schätzung, Abschnitt 4.3).

Das folgt der Regel aus dem Bericht: Eine Orderflow- oder Derivate-Information zählt nur, wenn sie gegenüber
derselben Methode ohne diese Information etwas hinzufügt.

**Nicht geprüft:** ob Liquidationen den Preis anziehen („Magnet“), ob nach Liquidationswellen eine Richtung folgt,
ob man damit handeln kann. Das wären eigene Studien mit eigener Präregistrierung und frühestens nach S12 sinnvoll.

## 2. Was TIM schon hat und Vorbelastung

- Heatmap-Modell und Abruf: `src/liquidation_map/heatmap.py`, `src/dashboard/liquidation_data.py` (30-min-Perioden,
  500 Perioden, Binance `/futures/data/openInterestHist` und `/fapi/v1/klines`).
- OpenMarket liefert `LIQUIDATION_AGG` (Summen je Intervall und Seite, ohne Preis, Herkunft nicht dokumentiert,
  `src/market_data/providers/openmarket/context_schemas.py`). Für eine Prüfung **nach Preisstufe** reicht das nicht.
- Perp-aggTrades und OI-Z-Score sammelt seit F5 `src/dashboard/perp_flow.py`; S12 nutzt diese Daten nicht.
- **Vorbelastung:** Uzi und die Threads haben die Heatmap im Chart gesehen (seit 28.10.). Gemeldete Liquidationen
  hat TIM nie gespeichert; ein Ergebnis kennt niemand.

## 3. Daten (alles öffentlich, kein Schlüssel, kein Konto)

### 3.1 Gemeldete Liquidationen

| Quelle | Rolle | Stream | Bekannte Grenze |
|---|---|---|---|
| Binance USD-M Futures | **primär** (gleiche Börse wie die Heatmap) | `btcusdt@forceOrder`, Basis laut Doku am 31.10. `wss://fstream.binance.com/market/ws/` | Je Symbol nur die **letzte** Liquidation je 1000 ms (Doku: „only the latest one liquidation order within 1000ms will be pushed“). Untererfassung bei Wellen |
| Bybit V5 linear | Robustheit (andere Börse) | `allLiquidation.BTCUSDT`, 500 ms | Preisfeld `p` ist der **Bankruptcy Price**, nicht der Ausführungspreis; `S = Buy` heißt: Long wurde liquidiert. Endpunkt `wss://stream.bybit.com/v5/public/linear` liefert im Probelauf Daten |

Seiten-Konvention, im Probelauf am 01.11.2026 an echten Ereignissen geprüft: Liquidierte Longs liegen unter,
liquidierte Shorts über dem Kurs. Binance: SELL 77 917–78 035, BUY 78 114 USDT. Bybit: Buy 77 679–77 873,
Sell 78 458–78 470 USDT (Ausgabe von `sides`, 09:00–12:00 Ortszeit).

- Binance: Zwangs-**SELL** schließt einen Long → Zelle „long“ der Heatmap; Zwangs-**BUY** → „short“. Preis = `ap`
  (Durchschnittspreis), Menge = `z` (ausgeführt), Zeit = `T`.
- Bybit: `S = Buy` → „long“, `S = Sell` → „short“; Preis = `p`, Menge = `v`, Zeit = `T`.

Ereignisse und Duplikate:

- Binance: gezählt wird nur eine Nachricht mit `X = FILLED`. Nachrichten mit anderem Status werden gezählt und
  berichtet, aber nicht ausgewertet. Gleiche Nachrichten (gleiches `T`, `S`, `ap`, `z`) zählen einmal.
- Bybit: gleiche Einträge (gleiches `T`, `S`, `v`, `p`) zählen einmal.

Notional je Ereignis = Preis × Menge in USDT.

Bekannte Verzerrung, die beide Modelle gleich trifft: Liquidiert wird nach dem **Mark Price**, gemeldet wird der
Ausführungs- bzw. Bankruptcy-Preis. Beide können einige Zeilen vom geschätzten Niveau entfernt liegen. Weil TIM und
Baseline dieselbe Schrittweite und dieselben Ereignisse nutzen, trifft die Verschiebung beide. Weil die Modelle
unterschiedliche Abstandsprofile haben können, ist eine einseitige Wirkung aber nicht ausgeschlossen. Deshalb gibt
es die Sekundäranalyse mit ±1 Zeile Toleranz (4.4).

### 3.2 Eingefrorene Heatmap-Stände

Viermal am Tag, zu den Fensteranfängen t ∈ {00:00, 06:00, 12:00, 18:00 UTC}, holt der Sammler um **t + 120 s**
OI-Historie und Kerzen genau wie `liquidation_data.fetch_heatmap` (BTCUSDT, 30 min, 500 Perioden) und speichert die
**rohen Antworten**. Vor dem Rechnen werden Kerzen mit Eröffnung > t − 1800 s (die laufende) und OI-Stände mit
Zeitstempel > t − 1800 s verworfen. Grund: Ob ein OI-Zeitstempel den Stand zu diesem Zeitpunkt oder am Ende seiner
30-min-Periode meint, ist nicht dokumentiert; die strengere Lesart schließt einen Blick in die Zukunft in beiden
Fällen aus. Im Probelauf (01.11.2026, Abruf 07:02 Ortszeit für t = 06:00 UTC) war der jüngste Stempel ohnehin
t − 1800 s, es geht also nichts verloren. Liegen OI-Zeitstempel nicht auf dem 30-min-Raster, ist der Stand ungültig
(gezählt, nicht repariert). Ältere OI-Stempel ohne passende Kerze sind normal (Binance liefert die OI-Historie eine
Periode früher beginnend) und werden von `build_heatmap` übergangen. Scheitert der Abruf, wird jede Minute neu versucht; ein Stand, der später als t + 15 min geholt
wurde, ist ungültig (der Mac kann schlafen oder offline sein). Gespeichert werden Rohantworten, Ergebnis von `build_heatmap`, `input_hash` und Code-Commit. So lässt sich
jeder Stand später exakt nachrechnen (Binance hält die OI-Historie nur 30 Tage).

### 3.3 Ablage und Qualität

- Tagesdateien (UTC), append-only, eine Zeile je Eintrag (unkomprimiert, damit ein Absturz höchstens eine Zeile
  kostet), mit Tagesmanifest (Zeilen, Prüfsumme, Verbindungen, Lücken, defekte Zeilen) unter
  `data/research_lab/liquidations/` auf dem Mac. Nicht in der Runtime-Datenbank, solange S12 Labor ist.
- Je Nachricht: Rohtext unverändert, `receive_ns`, `session_id`, `payload_sha256`.
- Binance-forceOrder hat keine Sequenznummer. Lücken sind deshalb **Verbindungslücken**: jede Verbindung schreibt
  `connect` und `disconnect` (mit Grund), ein gescheiterter Versuch `connect_failed`; das Tagesmanifest listet die
  Lücken mit Beginn und Ende. Ein Feed ohne Nachricht ist **kein** Wert null, sondern nur dann null, wenn die
  Verbindung nachweislich stand.
- „Verbunden“ heißt: Jede Minute geht ein Websocket-Ping hinaus; nur wenn das Pong binnen 10 s kommt, wird `alive`
  geschrieben, sonst endet die Verbindung. Zwischen zwei Lebenszeichen derselben Verbindung (jede Nachricht und jedes
  `alive`) dürfen höchstens 75 s liegen. Längere Pausen und alles nach einem `disconnect` zählen als Lücke. Lehnt
  Bybit das Abo ab, endet die Verbindung ebenfalls.
- Ein Fenster ist **gültig**, wenn der primäre Feed ≥ 99 % der 6 Stunden verbunden war, der Heatmap-Stand vollständig
  ist (`periods_with_oi` ≥ 450 und in beiden Modellen je Seite ≥ 10 aktive Zeilen, 4.2) und mindestens ein Long- oder Short-Ereignis vorkam. Ungültige Fenster werden gezählt und
  mit Grund berichtet, nie aufgefüllt.

## 4. Messung

### 4.1 Fenster

Je Fensteranfang t ein Fenster [t, t + 6 h). Die Fenster überlappen nicht. Der Heatmap-Stand von t sieht nichts
aus dem Fenster.

### 4.2 Trefferanteil

Für Modell m, Fenster t und Seite s ∈ {long, short}:

1. Die Auswertung rechnet beide Modelle mit demselben Algorithmus wie `build_heatmap` nach, aber **ohne die
   Anzeige-Filter** `MIN_SHARE` (Untergrenze 2 %) und `MAX_CELLS` (400 Zellen). Diese Filter dienen nur der
   Darstellung und würden die Zahl der verfügbaren Zeilen je Modell ungleich machen.
2. Aus dem Stand von t nur die **aktiven** Zellen (`end = None`) der Seite s nehmen, und zwar Long-Zellen mit
   `price + step ≤ last` und Short-Zellen mit `price > last` (dieselben Filter wie `analysis` in `build_heatmap`).
3. Die **10 stärksten Zeilen** (nach `usd`, Gleichstand: näher am Preis zuerst) bilden die Vorhersage V(m, t, s).
4. Jedes gemeldete Ereignis der Seite s im Fenster wird mit `heatmap._row(Preis, step)` (Schrittweite des Stands)
   einer Zeile zugeordnet.
5. T(m, t, s) = Notional der Ereignisse in V(m, t, s) / Notional aller Ereignisse der Seite s im Fenster.
   Eine Seite ohne Ereignis fällt für dieses Fenster in beiden Modellen weg.
5. T(m, t) = notional-gewichtetes Mittel über die vorhandenen Seiten.

### 4.3 Die beiden Modelle

- **TIM:** `build_heatmap` unverändert mit den eingefrorenen Eingaben.
- **Preis-Baseline:** derselbe Aufruf mit denselben Kerzen, aber OI an **genau denselben Zeitstempeln** wie die
  echten OI-Daten ersetzt durch `oi_base[ts] = 1 + Rang(ts)` (jede Periode gleich viel neues OI, nie Abbau).
  `periods_with_oi` muss in beiden Modellen gleich sein, sonst ist der Stand ungültig. Hebel-Mischung, Seitenanteil, Schrittweite,
  Sweep-Regel und Top-10 bleiben gleich. Damit unterscheidet sich nur die OI-Information.

### 4.4 Zusätzlich berichtet (nicht entscheidend)

- Zufallsvergleich mit gleichem Abstand: Für jede der 10 TIM-Zeilen im Abstand d Zeilen vom Preis wird eine
  Zufallszeile derselben Seite gleichverteilt aus [d − 5, d + 5] gezogen, ohne Doppelte (Seed 20261031, 999 Ziehungen
  je Fenster). Berichtet wird der Anteil der Fenster, in denen TIM über dem Median der Ziehungen liegt.
- Toleranz: dieselbe Rechnung mit V erweitert um je eine Nachbarzeile (±1 Zeile) in beiden Modellen.
- Ungewichtet: Anteil der **Ereignisse** statt des Notionals in V, damit wenige große Liquidationen nicht alles
  bestimmen.
- Dieselbe Auswertung mit Bybit-Ereignissen (andere Börse, Bankruptcy Price).
- Anteil der Ereignisse, die überhaupt in **irgendeiner** aktiven Zelle liegen (Abdeckung der Karte).
- Getrennt nach Regime: ruhige und hektische Fenster (Fenster-Spanne unter/über dem Median aller gültigen Fenster).

## 5. Entscheidungsregel (vorab)

D(t) = T(TIM, t) − T(Baseline, t) je gültigem Fenster.

**Bestanden**, wenn beides gilt:

1. Mittelwert von D > 0 mit einseitigem 95-%-Konfidenzintervall, dessen Untergrenze > 0 liegt. Methode:
   Moving-Block-Bootstrap über Kalendertage (UTC), Blocklänge 7 Tage, ein Tag wird mit allen seinen gültigen
   Fenstern gezogen, B = 9 999, Seed 20261031, Perzentil-Intervall (5-%-Quantil der Bootstrap-Mittelwerte);
2. Mittelwert von D ≥ 0,05 (5 Prozentpunkte; kleiner gilt als praktisch bedeutungslos).

**Nicht bestanden** in jedem anderen Fall. Kein zweiter Versuch mit anderen Parametern (andere Top-N, andere
Fensterlänge, andere Hebel) unter dem Namen S12; das wäre eine neue Studie mit offener Vorbelastung.

**Folgen:**

- Bestanden: Die Heatmap darf im Control Center als „mit echten Liquidationen geprüft“ beschrieben werden. Sie bleibt
  Anzeige, kein Signal.
- Nicht bestanden: Vorschlag an Uzi, die Heatmap im Chart als „nicht besser als reine Preisschätzung“ zu
  kennzeichnen oder abzuschalten. Umsetzung nur nach Uzis Wort.

## 6. Dauer und Machbarkeits-Gate (ergebnisblind)

- Start: 00:00 UTC des ersten vollständigen Tages, an dem Sammler und Heatmap-Stände laufen, nachdem Uzi Version 1.0
  freigegeben hat. Der Startzeitpunkt wird vor dem ersten Fenster in diese Datei eingetragen.
- Laufzeit: **genau 56 Tage** ab Start (224 Fenster), Ende = Start + 56 Tage, 00:00 UTC.
- **Gate nach 14 Tagen**, ohne D zu rechnen: Gezählt werden nur gültige Fenster (Abschnitt 3.3). Hochgerechnet auf
  8 Wochen müssen ≥ 150 gültige Fenster herauskommen.
  - Erfüllt: weiterlaufen bis 8 Wochen.
  - Nicht erfüllt: Die Entscheidung fällt am selben Gate (Tag 14): **einmal** auf genau 84 Tage verlängern, wenn die
    Hochrechnung auf 84 Tage ≥ 150 ergibt. Sonst endet S12 sofort als „nicht beurteilbar“. Später wird nicht mehr
    verlängert.
- Eine Power-Rechnung gibt es nicht. Sie bräuchte die Streuung von T oder D, und die ließe sich nur messen, indem
  man echte Ereignisse gegen die Stände rechnet. Das wäre eine Teil-Entblindung. Das Gate zählt deshalb nur
  Fallzahlen.
- Zwischenergebnisse für D werden nicht angesehen. Ausgewertet wird einmal am Ende.

## 7. Arbeitspakete (erst nach Uzis Freigabe der Version 1.0)

| Paket | Inhalt | Prüfung |
|---|---|---|
| L1 | Sammler für Binance forceOrder und Bybit allLiquidation, Rohablage, Lücken, Tagesmanifest; launchd auf dem Mac | Tests mit Beispielnachrichten aus der Doku, Lückentest; 24 h Probelauf |
| L2 | Heatmap-Stände 4× täglich mit Rohantworten und `input_hash`, Nachrechnen bit-genau | Test: gespeicherter Stand = neu gerechneter Stand |
| L3 | Zählskript fürs Gate (nur Gültigkeit, kein D) | Test mit synthetischen Daten |

**Stand 31.10.2026 (Uzis Wahl „Sammler bauen“):** L1–L3 gebaut in `src/research_lab/liquidations/`
(`events`, `store`, `collector`, `snapshots`, `gate`, CLI `python -m src.research_lab.liquidations`), Tests in
`tests/test_research_lab_s12_liquidations.py`, launchd-Vorlage `launchd/com.tim.s12-liquidations.plist.template`.
`build_heatmap` hat dafür die Parameter `min_share` und `max_cells` bekommen (Standard unverändert, Anzeige gleich).
Daten liegen unter `~/Library/Application Support/TIM/research-lab/liquidations/`. L4 folgt erst nach dem Gate.

| Paket | Inhalt | Prüfung |
|---|---|---|
| L4 | Auswertung (Abschnitte 4 und 5) | Tests nur mit synthetischen Daten, bis zum Ende keine echte Auswertung |

Alles läuft auf dem Mac, nur lesend gegenüber den Börsen, ohne Konto. Die Runtime und das Control Center werden
nicht verändert.

## 8. Bis zur Erstellung gesehene Daten

Die Heatmap ist seit 28.10.2026 im Chart sichtbar. Die API-Dokumentationen von Binance (forceOrder) und Bybit
(allLiquidation) wurden am 31.10.2026 nachgelesen. Probelauf seit 31.10.2026 16:48 Ortszeit: gesehen wurden nur
die Ausgaben von `sides` (12 Ereignisse, Seite, Preis, Menge), `verify` (3 Stände OK), das Manifest vom 31.10.
(Zeilen, Abdeckung) und die Zeitstempel eines Stands. Kein Ereignis wurde gegen Heatmap-Zeilen gerechnet; D ist
unbekannt. Daten des Probelaufs zählen nicht zur Studie.

## 9. Offene Punkte vor Version 1.0

1. ~~Seiten-Konvention~~ erledigt 01.11. (Abschnitt 3.1).
2. ~~OI-Zeitstempel~~ erledigt 01.11.: Regel OI ≤ t − 1800 s (Abschnitt 3.2), unabhängig von der Bedeutung.
3. ~~Bybit-Endpunkt~~ erledigt: liefert im Probelauf.
4. Offen: Uzis Freigabe von Version 1.0. Danach wird der Sammler auf den Stand 1.0 gebracht; der Start (Abschnitt 6)
   wird hier eingetragen.

## Änderungsprotokoll

| Datum | Version | Änderung | Gesehene Daten |
|---|---|---|---|
| 2026-10-31 | 0.1 | Entwurf: Frage, Daten, Messung, Entscheidungsregel, Gate, Pakete | keine Liquidationsdaten |
| 2026-10-31 | 0.2 | Nach adversarialer Prüfung: Anzeige-Filter aus der Auswertung, Baseline auf echten OI-Zeitstempeln, `_row` für Ereignisse, Seitenfilter wie `analysis`, Duplikate/`FILLED`, Abruf t + 120 s, abstandsgleicher Zufallsvergleich, ±1-Zeile- und ungewichtete Sekundärmaße, Moving-Block-Bootstrap 7 Tage, feste Start-/Endzeit und Verlängerungsregel, keine Power-Rechnung (Entblindung) | keine Liquidationsdaten |
| 2026-10-31 | 0.3 | Umbenannt von S11 in S12 (S11 im Logbuch vergeben, `next_study_id`) | keine Liquidationsdaten |
| 2026-10-31 | 0.4 | L1–L3 gebaut; Abrufregel (Wiederholung, ungültig nach t + 15 min) und Definition „verbunden“ (Ping/Pong je Minute, Lebenszeichen ≤ 75 s) nach zweiter adversarialer Prüfung; offener Punkt OI-Zeitstempel | keine Liquidationsdaten |
| 2026-11-01 | 1.0 | Nach Probelauf: Seiten bestätigt, OI nur bis t − 1800 s, Raster-Prüfung statt Kerzen-Abgleich (der alte Abgleich erklärte jeden echten Stand für ungültig), offene Punkte 1–3 erledigt | Probelauf-Ausgaben wie Abschnitt 8, kein D |
