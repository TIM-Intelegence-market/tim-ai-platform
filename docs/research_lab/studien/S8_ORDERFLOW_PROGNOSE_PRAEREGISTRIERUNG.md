# S8: Lokale BTC-Orderflow-Prognose (Trade-only) – Präregistrierung

**Status: ENTWURF 0.2, nicht registriert.** Kein Registereintrag, keine Auswertung, keine Ergebnisse.
Grundlage: Uzis Bauplan „TIM: Bauplan für lokale BTC-Orderflow-KI“ (26.10.2026), Pakete P0 und P1.
Dieser Entwurf hält Fragestellung, Daten, Merkmale, Zielwert und Datensplit fest, **bevor** ein Ergebnis
angesehen wird. Er ändert weder das Protokoll (1.3) noch S2.

## 1. Forschungsfrage und Begriffe

Frage: Sagt ein Modell aus Trade-Merkmalen (aggTrades BTCUSDT Spot) die Richtung der Preisänderung über die
nächsten fünf Minuten besser vorher als die registrierten Referenzen (Klassen-Basisrate, einfache Delta-Richtung)?

Getrennt gehalten werden:

- **Richtungsprognose**: Wahrscheinlichkeiten für aufwärts / abwärts / neutral; Gegenstand von S8.
- **Datenfehler**: fehlende, veraltete oder lückenhafte Daten. Sie führen zu einem fehlenden Wert mit Grund,
  nie zu „neutral“.
- **Handelsentscheidung**: nicht Teil von S8. Trade-only-Archive enthalten keinen Spread und keine Fills;
  S8 misst Preisreaktionen, keinen Nettoertrag. Eine Abwärtsprognose im Spotmarkt ist kein ausführbarer Short.

Instrument: Binance Spot BTCUSDT. Entscheidung einmal je abgeschlossener Minute, Horizont 5 Minuten.

## 2. Daten und Wissenszeit

- Quelle: tägliche Binance-aggTrades-Archive (data.binance.vision), geprüft gegen die offizielle Prüfsumme.
  Eigener Tagesspeicher `data/research_lab/orderflow_ml/` (nicht in Git), getrennt vom S2-Speicher.
- **Die S2-Preisdateien (`data/research_lab/aggtrades/px/`) werden nicht geöffnet** (S2 Abschnitt 8). Der
  optionale Abgleich mit S2 liest nur die Zähldateien `agg/`.
- Keine Abfrage der Runtime-Datenbank, kein Import aus dem Runtime-Pfad.
- Zeitbasis: Archive tragen die Börsen-Ereigniszeit, nicht die damalige lokale Empfangszeit. Offline-Merkmale
  sind deshalb eine **Ereigniszeit-Näherung** (`exchange_event_time_proxy`). Eine spätere Live-Prüfung (P4)
  muss Balken aus dem bilden, was bis t tatsächlich angekommen war.
- Einheiten: Mengen in 1e-8 BTC, Preise und Quote-Volumen in 1e-8 USDT als ganze Zahlen; „Trades“ meint
  aggTrade-Ereignisse, nicht einzelne Börsen-Fills.

## 3. Datensplit (Protokoll 1.3, unverändert)

| Abschnitt | Zeitraum (UTC) | Verwendung |
|---|---|---|
| Training | 2020-01-01 bis 2022-12-31 | Modelltraining, innere Validierung für frühes Stoppen |
| Validierung | 2023-01-01 bis 2024-12-31 | Modellvergleich (äußerer Block) |
| Holdout | ab 2025-01-01 | **gesperrt**, kein Bestandteil von S8; Code verweigert jeden Holdout-Tag vor dem Abruf |

Purging: Eine Entscheidung entfällt, wenn t + 5 Minuten hinter dem Abschnittsende liegt (kein Trainingslabel
liest einen Validierungspreis). Merkmale dürfen in die Vergangenheit über die Abschnittsgrenze zurückblicken.
Für Walk-forward innerhalb eines Abschnitts (P3) gilt dasselbe Purging an jeder Blockgrenze; zusätzlich ein
Abstand von 5 Minuten (Horizont). Keine zufällige Aufteilung benachbarter Minuten.

## 4. Merkmale (Version 1.1.0) – Datenwörterbuch

Entscheidungszeit t = Ende der Minute. Alle Merkmale lesen nur Minuten bis t, höchstens bis zum Beginn des
Vortags zurück. Die ersten 120 Minuten nach einer Datenlücke (fehlender Tag) gelten als Aufwärmphase und werden
ausgeschlossen. Kerzenkontext nur aus bei t **geschlossenen** Uhrstunden.

| Merkmal | Definition |
|---|---|
| `delta_norm_1` | (Kauf-BTC − Verkauf-BTC) / Gesamt-BTC der Entscheidungsminute; aggressorseitig |
| `cvd_norm_5` | Summe Delta / Summe Volumen über die letzten 5 Minuten (−1..1) |
| `cvd_norm_15` | wie cvd_norm_5 über 15 Minuten |
| `cvd_norm_60` | wie cvd_norm_5 über 60 Minuten |
| `cvd_btc_5` | rollierendes CVD in BTC über 5 Minuten |
| `cvd_btc_15` | rollierendes CVD in BTC über 15 Minuten |
| `cvd_btc_60` | rollierendes CVD in BTC über 60 Minuten |
| `buy_count_share_5` | Anteil aggressiver Käufe an aggTrade-Ereignissen, 5 Minuten |
| `trades_5` | Zahl der aggTrade-Ereignisse (nicht Einzel-Fills), 5 Minuten |
| `trade_rate_5_vs_60` | trades_5 / (aggTrades der letzten 60 Minuten / 12) |
| `volume_btc_5` | Volumen in BTC, 5 Minuten |
| `volume_usdt_5` | Volumen in USDT (Σ Preis × Menge), 5 Minuten |
| `volume_rel_5_vs_60` | volume_btc_5 / (BTC-Volumen 60 Minuten / 12) |
| `mean_trade_btc_5` | mittlere aggTrade-Größe in BTC, 5 Minuten |
| `largest_trade_btc_5` | größter aggTrade in BTC, 5 Minuten |
| `large_trade_share_5` | Anteil aggTrades ≥ 1 BTC, 5 Minuten |
| `ret_1` | ln(letzter Preis bei t / letzter Preis 1 Minute vorher) |
| `ret_5` | ln-Preisänderung über 5 Minuten bis t |
| `ret_15` | ln-Preisänderung über 15 Minuten bis t |
| `ret_60` | ln-Preisänderung über 60 Minuten bis t |
| `vol_60` | Wurzel des Mittels der quadrierten 1-Minuten-ln-Renditen der letzten 60 Minuten (nicht zentriert) |
| `range_15` | ln(Hoch / Tief) der letzten 15 Minuten |
| `pos_in_range_60` | (Preis − Tief60) / (Hoch60 − Tief60); fehlt bei Hoch = Tief |
| `prev_hour_ret` | ln-Rendite der letzten bei t geschlossenen Uhrstunde (UTC) |
| `prev_hour_dist_high` | ln(Preis bei t / Hoch dieser geschlossenen Stunde) |
| `prev_hour_dist_low` | ln(Preis bei t / Tief dieser geschlossenen Stunde) |
| `hour_utc` | Stunde von t in UTC (0..23) |
| `weekday` | Wochentag von t in UTC (0 = Montag) |
| `vp_prev_poc_dist` | ln(Preis bei t / POC des Volumenprofils des Vortags, Mitte der Preisstufe) |
| `vp_prev_va_pos` | (Preis − VAL) / (VAH − VAL) der Value Area (70 %) des Vortags; < 0 darunter, > 1 darüber |
| `vp_prev_va_width` | ln(VAH / VAL) der Value Area des Vortags |
| `vp_dev_poc_dist` | ln(Preis bei t / POC des laufenden Tagesprofils bis t) |
| `vp_dev_va_pos` | Lage des Preises in der Value Area des laufenden Tagesprofils bis t |
| `tpo_prev_poc_dist` | ln(Preis bei t / TPO-POC des Vortags, 30-Minuten-Perioden) |
| `tpo_prev_va_pos` | Lage des Preises in der TPO-Value-Area (70 %) des Vortags |

**Volume Profile und TPO (seit 1.1.0, auf Uzis Wunsch vom 26.10. vor jeder Auswertung ergänzt):** Der Exporter
zählt das aggressive Volumen je Minute und Preisstufe. Die Stufenbreite gilt für einen ganzen UTC-Tag und ist die
größte Zahl der Form 1/2/5 × 10^k USDT, die 0,1 % des ersten Trades des Tages nicht übersteigt (bei 30 000 USDT also
20 USDT). Regeln: POC = Stufe mit dem größten Wert (Gleichstand: tiefere Stufe); Value Area = vom POC aus jeweils die
größere Nachbarstufe hinzunehmen (leere Stufen zählen 0, Gleichstand: obere), bis ≥ 70 % erreicht sind; TPO = 48
Perioden à 30 Minuten, jede markiert die Stufen von ihrem Tief bis Hoch einmal. Vortagsprofile nur, wenn der ganze
Vortag vorliegt; das laufende Tagesprofil nutzt nur Minuten bis t. Die Merkmale sind Bezugsabstände, keine
Handelsregeln (kein „POC-Magnet“ o. ä. als Hypothese).

Qualitätsspalten je Zeile: `stale_ms` (Alter des letzten Trades bei t), `empty_minutes_60` (Minuten ohne Trade
in den letzten 60), `warm`, `complete`.

## 5. Zielwert (Label-Version 1.0.0)

- Startpreis: letzter Trade bis t. Zielpreis: letzter Trade bis t + 5 Minuten.
- Ist der Start- oder Zieltrade älter als 60 s, fehlt das Label mit Grund (`stale_start`, `stale_target`);
  ebenso `beyond_data` (Folgetag fehlt), `no_volatility`, `purged_section_end`.
- Schwelle, nur aus bei t Bekanntem: `max(k · vol_60 · √5, Kostenboden)` mit **k = 0,5** und
  **Kostenboden = 0,16 %** (Protokoll-Taker-Kosten hin und zurück: 2 × (0,05 % Gebühr + 0,03 % Slippage)).
  Klasse aufwärts, wenn ln(Ziel/Start) > Schwelle; abwärts, wenn < −Schwelle; sonst neutral.
- k und Kostenboden werden hier **ohne Blick auf Ergebnisse** vorgeschlagen und vor der Registrierung
  festgeschrieben. Jede spätere Änderung erzeugt eine neue Konfigurations-ID und zählt als weiterer Versuch.

## 6. Geplante Auswertung (P3, Vorschlag zur Freigabe)

- Referenzen: Klassen-Basisrate (aus dem Training), Delta-Richtung (`cvd_norm_5` > 0 → aufwärts, < 0 → abwärts).
- Kandidaten: multinomiale logistische Regression; CatBoost (≤ 500 Iterationen, Tiefe 4, Lernrate 0,05,
  2 Threads, fester Seed), genau eine Konfiguration.
- Primärmetrik: Log-Loss auf der Validierung; daneben Brier-Score, Güte je Klasse, Kalibrierung,
  Enthaltungsanteil, Stabilität über Monatsblöcke. Konfidenzintervalle per Block-Bootstrap über Tage.
- **Vor jeder Auswertung offen und von Uzi festzulegen:** kleinster interessierender Effekt
  (Log-Loss-Verbesserung gegenüber der Basisrate), Fallzahl-/Power-Gate mit Tages-Cluster, Stoppregeln.
  Ohne bestandenes Gate gilt wie bei S2: „nicht beurteilbar“.

## 7. Einordnung im Register (entschieden)

**Uzi, 26.10.2026, 20:49 Ortszeit, per Entscheidungskarte: „Eigene Familie, prospektiv“.** S8 läuft außerhalb des
Holdout-Registers (Protokoll-Änderungsprotokoll, Eintrag vom 26.10.); es belegt keine Plätze (m bleibt 58 von 60)
und lädt den Archiv-Holdout ab 2025 nie. Training und Validierung dienen der Modellwahl; eine Bestätigung ist nur
über einen eigenen prospektiven Test auf neuen Live-Daten möglich. Dessen Startzeit, Dauer, Fallzahl-/Power-Gate,
kleinster interessierender Effekt und Stoppregeln werden in Version 1.0 dieser Registrierung festgelegt, **bevor**
die prospektiven Daten beginnen. S8-Ergebnisse sind keine Setup-Evidenz nach dem bestehenden Register.

## 8. Werkzeug (Stand dieses Entwurfs)

`src/research_lab/orderflow_ml/` (Tests: `tests/test_research_lab_s8_export.py`):

```
python -m src.research_lab.orderflow_ml fetch  --from 2020-01-01 --to 2024-12-31   # Archive laden, prüfen, reduzieren
python -m src.research_lab.orderflow_ml export --from 2020-01-01 --to 2024-12-31   # Merkmale, Labels, Split-Manifest, Bericht
python -m src.research_lab.orderflow_ml replay --decision 2021-03-01T12:00:00Z --export-dir <Export>
python -m src.research_lab.orderflow_ml crosscheck-s2 --s2-root data/research_lab/aggtrades  # nur agg/
```

Der Export schreibt Merkmale und Labels in getrennte Dateien, dazu `split_manifest.json` (Konfiguration und
Hash, Code-Commit, Eingangs-, Merkmals- und Label-Hash, Zählungen je Abschnitt) und `quality_report.md`.
Der Bericht ist ergebnisblind: Er zählt Ausschlussgründe und Label-*Status*, keine Klassenverteilung.

Abnahme P1 (Bauplan) und Nachweis in den Tests: Volumen je Preisstufe summiert sich zum Minutenvolumen, POC/Value
Area/TPO an Handbeispielen, laufendes Profil kausal; gleiche Eingaben → gleiche Hashes; spätere Daten ändern keine
frühere Merkmalszeile (abgeschnittene und manipulierte Zukunft, auch im Preisstufen-Profil); doppelte Trades, Id-Lücken, Zeitrücksprünge,
leere Minuten, fehlende Tage und Trades außerhalb des UTC-Tags werden erkannt; Replay vom Archiv bis zum Label
stimmt mit dem Export überein; Holdout-Tage werden vor dem Abruf verweigert.

Reproduzierbarkeit: Ganzzahlige Größen sind exakt. Fließkommamerkmale (ln, Wurzel) sind auf derselben Plattform
bitgleich; zwischen macOS und Linux kann die letzte Stelle abweichen. Maßgeblich ist deshalb der Export-Hash
des Mac-Laufs, der im Split-Manifest steht.

Laufzeit (gemessen in der Cloud, synthetisch): Reduktion ≈ 1 s je Million aggTrades ohne CSV-Lesen, Export
≈ 0,1 s je Tag. Der Abruf von rund 1 827 Archivtagen (je 100–300 MB) dauert auf dem Mac Stunden; der Lauf ist
noch nicht erfolgt.

## 9. Abweichungen vom Bauplan

- Branch `claude/…` statt `codex/…` (Cloud-Thread); Arbeit in der Cloud, nicht in `~/TIM-live`.
- Keine neue uv-Umgebung: Der Exporter braucht nur die Standardbibliothek. CatBoost/scikit-learn kommen erst
  mit P3, dann in `requirements-research.txt`-ähnlicher, getrennter Liste.
- Der Bauplan nennt die S2-Zähler als mögliche Quelle; sie reichen nicht (keine Preise). S8 reduziert die
  Rohdaten selbst neu, statt S2-`px/` zu öffnen.
- Volatilität `vol_60` ist nicht zentriert (Wurzel der mittleren quadrierten Rendite); so festgelegt, damit
  der Wert ohne Mittelwertschätzung auskommt.

## 10. Bestand und Lücken (P0, gegen `platform-main` e7f14f1)

| Baustein | Im Repo | Für S8 |
|---|---|---|
| aggTrades live | `src/data_ingestion/binance_ws.py` | P4: Balken aus Live-Trades mit `reduce_trades` bilden |
| aggTrades Archiv | `src/research_lab/data/aggtrades.py` (S2: Zähler + `px/`) | `read_rows` wiederverwendet; `px/` bleibt zu |
| Prüfsummen | `src/v2_readiness/backfill.py` | wiederverwendet |
| Holdout-Sperre | `HoldoutLocked`, `protocol.HOLDOUT_START_MS` | wiederverwendet |
| Live-Metriken | `src/orderflow/metrics.py` (Delta, CVD, Größen) | gleiche Aggressor-Definition (Käufer ist Maker → Verkauf) |
| Feature-/Dataset-Verträge | `src/tim_v2/features`, `src/tim_v2/dataset` | später: S8-Merkmale dort als `FeatureDefinition` eintragen |
| Register | `docs/research_lab/REGISTER.jsonl`, m = 58/60 | S8 außerhalb, siehe Abschnitt 7 |
| Trainer, Modellartefakt | fehlt | P3 |
| Prognosejournal, Anzeige | fehlt (Plan-Journal als Vorlage) | P4 |
| Orderbuch-Collector | fehlt | P2, Vertrag: `S8_DEPTH_DATENVERTRAG_ENTWURF.md` |
| Ressourcenmessung Mac | nicht gemessen | vor P2/P3 auf dem Mac |

## Änderungsprotokoll

| Datum | Version | Änderung | Bis dahin gesehene Daten |
|---|---|---|---|
| 2026-10-26 | 0.1 | Entwurf: Frage, Daten, Split, Merkmale 1.0.0, Label 1.0.0, Werkzeug, offene Entscheidungen | keine Archivdaten geladen, keine Outcomes; nur synthetische Testdaten |
| 2026-10-26 | 0.2 | Merkmale 1.1.0 mit Volume Profile und TPO (Uzis Wunsch, 20:02 Ortszeit); Balkenversion 1.1.0 mit Profildatei; Abschnitt 7: Uzis Entscheid „Eigene Familie, prospektiv“ (Karte 20:49 Ortszeit), Protokoll-Einordnung; Registerstand 58/60 | unverändert: keine Archivdaten, keine Outcomes |
