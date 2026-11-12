# G1 Inventur TIM-Gehirn – Mac-Teil (12.11.2026)

Nur gelesen. Stand ~/TIM-live: Working Tree bzw. origin/platform-main (lokal). Zahlen sind aus den Dateien gezählt. „nicht gefunden“ heißt: an den genannten Orten nicht vorhanden.

## 1. Wissensordner

| Pfad (unter ~/Documents/TIM) | Art | Größe/Anzahl | Datum | Inhalt | Live-Zugriff |
|---|---|---|---|---|---|
| wissen/mega-orderflow-2026-11-07.md | eigene Verdichtung | 896 KB | 07.11. | Broncx Bootcamp + Trading University: 74 Regeln (R01–R74), 34 Modelle, Master-Tabelle Abschnitt 17, alle als „unvalidiert“ markiert | unbekannt (kein Verweis im Code gefunden) |
| wissen/of2-p0-kalibrierung-2026-11-07.md | eigene Messung | 35 KB | 07.11. | TIMs eigene Häufigkeiten von Imbalances (OF2-Kalibrierung P0) | unbekannt |
| wissen/plan-tim-gehirn-2026-11-12.md | Plan | 5 KB | 12.11. | Entwurf TIM-Gehirn (Überzeugungsregister, Engine als Prüfer, P0–P4) | nein |
| wissen/g1-inventur-mac-2026-11-12.md | diese Datei | – | 12.11. | – | nein |
| analysen/ | – | nicht gefunden | – | – | – |
| reel-auswertung-2026-11-01/ | Reel-Texte | 157 Dateien, 652 KB | 01.11. | 153 Texte, davon ca. 12 Trading-Reels (Skydweller, ProfitPro, DeepCharts, QuantLab u. a.), Rest kein Trading | unbekannt |
| reel-auswertung-2026-11-02-quantfinancetogo/ | Video-Texte | 58 Dateien, 452 KB | 02.11. | 53 Videos „Quant Finance from Scratch“ (Data-Snooping, 200-Tage-Linie als Vola-Regime) | unbekannt |
| GoatHub-Verlauf/ | Kanal-Verlauf + Auswertungen | 121 Dateien, 6,7 MB | 28.10. | Rohabschriften und auswertungen/ (KERN_DER_GRUPPE, education-durchgang, drei-kanaele/ERGEBNIS: Calls mit zu kleiner Stichprobe) | ja, indirekt: src/knowledge/goathub*.py (GoatHub-Wissen), Pfad nicht geprüft |
| goathub-pdfs/ | Lehrmaterial | 2 Dateien, 420 KB | 27.10. | HTF-to-Entry (BOS/CHoCH) | unbekannt |
| indikator-pruefung-2026-11-04/ | Prüfprotokoll | 51 Dateien, 10 MB | 04.11. | Indikator-Prüfung (Screenshots/Protokoll), keine Überzeugungen | unbekannt |
| tim-broncx-feed/data/telegram/ | Signale | 2 Dateien, 244 KB | 07.11. | SMC-Signale #SMC001–005, 4 von 5 unausgeführt verfallen | ja: launchd com.tim.broncx-discord-feed; src/knowledge/broncx_feed.py |
| telegram-reader/ | Code + Daten | 1422 Dateien, 30 MB | 08.11. | Telegram-Leser (Code, Sitzungsdaten nicht geöffnet) | unbekannt |

Das Überzeugungsregister (Entwurf v0, scratchpad, noch nicht abgelegt) erfasst aus diesen Quellen 90 externe Aussagen:

| Bereich | Aussagen |
|---|---|
| Orderflow | 20 |
| Struktur | 16 |
| Profil | 12 |
| Risiko | 11 |
| Liquidität | 6 |
| Psychologie | 6 |
| Makro | 5 |
| Funding | 5 |
| Volatilität | 5 |
| Sonstiges | 4 |

## 2. Obsidian-Vault und tim-graph

**Vault:** `~/Documents/TIM/TIM OBSIDIAN/` (Standard laut `src/obsidian_vault/schema.py:11`, überschreibbar mit TIM_OBSIDIAN_VAULT). Er enthält 116 Notizen und wurde zuletzt am 11.11. 16:01 geändert. 8 Notizen sind in den letzten 2 Tagen hinzugekommen oder geändert worden.
- Claude Memory/: 17 Notizen
- TIM/: 98 Notizen

| Ordner unter TIM/ | Notizen |
|---|---|
| 00 Inbox | 0 |
| 01 Home | 4 |
| 10 Architektur | 9 |
| 20 Incidents | 4 |
| 30 Missionen | 11 |
| 40 Systeme | 7 |
| 50 Daten & QA | 8 |
| 60 Agenten & Tools | 13 |
| 70 Entscheidungen | 2 |
| 75 Research | 8 |
| 80 Runbooks | 8 |
| 90 Berichte | 17 (davon Automatisch/) |
| 95 Archiv | 0 |
| 99 Vorlagen | 7 |

- **Inhalt:** Betrieb, Architektur, Missionen und Runbooks. Trading-Überzeugungen kommen praktisch nicht vor.
- **Altbestand:** Daneben liegt `TIM OBSIDIAN alt 2026-10-01/`.
- **Befüllung:** Der launchd-Job `com.tim.obsidian-refresh` läuft stündlich (StartInterval 3600) über `src/obsidian_vault/auto_refresh.py`. Er schreibt u. a. „90 Berichte/Automatisch/TIM Stand automatisch.md“ und „PRs 2026-Wxx“.

**tim-graph:**
- **Speicher:** `~/Documents/TIM/worktrees/mcp-clients/.runtime/graph/graph.sqlite`. Status ok, schema 1.0.0, read_only_tim=true.
- **Größe:** 13 753 Knoten und 30 237 Kanten.

| Knotentyp | Anzahl |
|---|---|
| Function | 4201 |
| Test | 3837 |
| Method | 2539 |
| File | 1000 |
| Module | 1000 |
| Class | 900 |
| Column | 92 |
| ObsidianNote | 80 |
| Service | 56 |
| Tool | 16 |
| Table | 10 |
| Agent | 8 |
| Gate | 6 |
| Mission | 5 |
| Incident | 1 |
| Database | 1 |
| Repository | 1 |

| Kantentyp | Anzahl |
|---|---|
| DEFINES | 12 477 |
| CALLS | 11 016 |
| TESTS | 3284 |
| IMPORTS | 1585 |
| CONTAINS | 1102 |
| REFERENCES | 508 |
| READS | 120 |
| WRITES | 75 |
| DOCUMENTED_BY | 37 |
| DEPENDS_ON | 20 |
| REQUIRES | 6 |
| USES_TOOL | 6 |
| RELATED_TO | 1 |

- **Abfrage:** über den MCP-Server `tim-graph` (graph_search, graph_impact, graph_dependencies, graph_agent_context usw.) und über den Skill tim-cli.
- **Auffällig:** File und Module stehen auf genau 1000. Das sieht nach einer Kappung beim Indexieren aus.
- **Fehlende Knotentypen:** Es gibt keine Knoten für Studien, Hypothesen, Überzeugungen oder Trades. Forschungswissen fehlt im Graph vollständig.

## 3. Trade-Reflexion, Journal-Lehren, Wochenbericht, Ideen

### Trade-Reflexion
- **Datei:** `~/TIM-live/data/research/trade_reflections.jsonl` (72 KB, 11.11. 15:59, Regeln `trade-reflection/1.0`, `src/research_lab/workshop/trade_reflection.py`).
- **Umfang:** 71 reflektierte Trades vom 24.10. bis 11.11.2026, zusammen +7,31 R netto.
- **Herkunft nach Journal:** tim_plan_journal 31, short 25, mid 14, struct 1.
- **automatic_rule_change:** immer false.

| Lehre | Trades | Summe netto R |
|---|---|---|
| AGAINST_TREND (gegen TIMs Marktzustand) | 23 | +0,68 |
| (keine Lehre) | 21 | +7,82 |
| COSTS_ATE_PROFIT (Kosten fraßen Gewinn) | 13 | −0,09 |
| WRONG_AT_ONCE (lief sofort gegen Plan) | 12 | −13,13 |
| INVALIDATED (Schluss jenseits Ungültigkeit) | 8 | −4,27 |
| FULL_TARGET (alle drei Ziele) | 6 | +12,13 |
| STOP_BY_WICK (Stop nur per Docht) | 3 | −3,49 |
| GAVE_BACK (≥1 R im Plus, ohne Gewinn) | 2 | −0,09 |
| TIMEOUT | 2 | −0,90 |
| DATA_GAP | 2 | −2,36 |

Ein Trade kann mehrere Lehren tragen. Die Summen überlappen sich deshalb.

### Journal-Review
- `src/research_lab/journal_review.py` (journal-review/1, MIN_CLUSTERS 30, Cluster-Block-Bootstrap) schreibt Vorschläge.
- Eine eigene Lehren-Datei davon wurde unter data/research nicht gefunden.

### Wochenberichte
- **Dateien:** `data/research/reports/` enthält nur woche_2026-W45.md/.json. Daneben liegen forschung_2026-09.md und forschung_2026-10.md.
- **Gesamtbild:** Der letzte Bericht (W45) nennt 31 geschlossene Papier-Trades in der Woche mit +5,07 R nach Kosten und 61 Trades insgesamt.

| Journal | Woche | Gesamt |
|---|---|---|
| TIM 30m | −0,48 R | 27 Trades, +1,02 R |
| 15m | +1,98 R | 21 Trades, +3,86 R |
| 1h | +3,56 R | 12 Trades, +5,15 R |
| Struktur 30m | – | 1 Trade, −2,20 R |

- **Kein Filter bestanden:**
  - „gegen Marktzustand auslassen“: Der Rückblick spricht dagegen, die gestrichenen Trades lagen bei +2,72 R.
  - „Kosten > 0,15 R auslassen“: wird bis 01.12. beobachtet.
  - Grade C und fehlende Bestätigung: würden fast alle Trades streichen.
- **Läufer-Schatten (MID 1h):** 0 von 30 Trades mit TP2.

### Ideen
- **Datei:** `data/research/IDEEN.jsonl` mit 12 Zeilen: 5 vom Typ add (Ideen) und 7 vom Typ status (Statuswechsel).
- **Status:** ready 4, study_draft 2, waiting_budget 1.
- **Die 5 Ideen, jüngste zuerst:**
  1. 06.11. Trade-Reflexion tim_plan_journal_short: AGAINST_TREND
  2. 03.11. Trade-Reflexion tim_plan_journal: INVALIDATED
  3. 03.11. Trade-Reflexion tim_plan_journal: AGAINST_TREND
  4. 01.11. Kosten in R nach Tageszeit (wurde S17)
  5. 31.10. Funding-Extreme als Kontraindikator (wurde S16)

Es gibt also nur 5 Ideen, nicht 10.

## 4. Plan-Journale (`~/TIM-live/data/journal/`, Stand 12.11. vormittags)

Die Summen sind aus den Journal-Dateien selbst gebildet, jeweils roh und nach den Ausschlüssen in `src/dashboard/plan_journal_corrections.json`.

| Journal | Pläne | Zeitebene | geschlossen | netto R roh | nach Ausschluss | erster / letzter Plan |
|---|---|---|---|---|---|---|
| tim_plan_journal | 74 | 30m 72, 15m 2 | 52 | −27,61 | 31 Trades, +0,92 | 24.10. / 11.11. |
| tim_plan_journal_short | 44 | 15m | 25 | +3,61 | 25, +3,61 | 27.10. / 11.11. |
| tim_plan_journal_mid | 17 | 1h | 14 | +4,97 | 14, +4,97 | 27.10. / 10.11. |
| tim_plan_journal_level | 9 | 30m | 9 | −20,47 | 8, −17,71 | 25.10. / 26.10. |
| tim_plan_journal_struct | 6 | 30m 5, 15m 1 | 6 | −8,21 | 1, −2,20 | 24.10. / 25.10. |
| tim_plan_journal_perp_short | 3 | 15m | 2 | −0,16 | 2, −0,16 | 10.11. / 11.11. |
| tim_plan_journal_perp_mid | 1 | 1h | 1 | +1,00 | 1, +1,00 | 10.11. |
| tim_plan_journal_long, _vp, _xmr_15m, _xmr_1h | 0 | – | 0 | 0 | – | – |

- **Zeitebenen:** 30m 86, 15m 50, 1h 18. Ein 1d-Journal gibt es nicht.
- **Ausschlüsse:** plan_journal_corrections.json enthält 27 Einträge, jeder einzeln von Uzi freigegeben, z. B. „PHANTOM_INVALID_ON_ARRIVAL“.
- **Hinweis:** Das Hauptjournal kippt durch die Ausschlüsse von −27,61 R auf +0,92 R. Die Ausschlüsse bestimmen also fast das ganze Ergebnis.

## 5. Ergebnisse, die nur am Mac oder auf der PS5 liegen (nicht im Repo)

| Was | Ort | Stand |
|---|---|---|
| S22 Zähl- und Ergebnislauf | ~/Documents/TIM/results/s22/ (4 Dateien, u. a. s22_evaluate_2026-11-11T1841Z.json) | NICHT BESTANDEN. Im Repo ist kein Ergebnisbericht vorhanden. |
| S21 count/evaluate | ~/Documents/TIM/s21_*.json | Kopie. Der Bericht s21_ergebnis ist im Repo. |
| S19 Ergebnis | PS5 ~/tim-research/results/s19/s19_evaluate_20261110T1025Z.json/.md | Im Repo nicht gefunden. |
| S24, S26, S27 Ergebnisse | – | nicht gefunden (weder am Mac noch im Repo) |
| S25 | Repo: s25_count_2026-11-11T2059Z, s25_run_2026-11-12T0926Z. Mac: s25-zaehllauf/klines5m.tar (66 MB, Daten) | Ergebnis im Repo |
| OFX-Kandidaten | PS5 ~/tim-research/results/ofx/lauf1 und lauf2 | lauf1: 377 Konfigurationen, 0 bestanden, gestoppt am 10.11. lauf2: 8644 Konfigurationen, 0 bestanden, läuft noch (letzte Zeile 12.11. 10:48). Eine kandidaten.jsonl gibt es nicht, state.json meldet „kandidaten: 0“. |
| Bitunix-Aufzeichnung | ~/Documents/TIM/bitunix-check/rec/status.json | Die Datei meldet state „running“ (pid 88747; BTC/ETH/SOL; 78 267 Trades, 141 734 Depth-Updates, 3 Lücken). Die Datei wurde zuletzt am 11.11. um 23:03 geschrieben, und Prozess 88747 läuft nicht mehr. Die Aufzeichnung steht also seit etwa 23:03, der Status ist veraltet. |
| Forward-Journale | ~/TIM-live/data/research/forward/OF/status.json und S7b/status.json | OF: 0 Trades seit 11.11. (Mindestens 100 nötig). S7b: läuft seit 01.11., bisher 1 Treffer in S7b-D20-T3. |
| Kronos S18 | ~/Documents/TIM/kronos-s18/ (probe_result_cpu/mps.json, launchd com.tim.s18-kronos) | Probe-Ergebnisse, kein Studienergebnis gefunden |

## 6. Live-Regeln, die die Runtime benutzt

Die Liste ist aus dem Code gelesen (origin/platform-main lokal). Zeilennummern mit „~“ sind ungefähr. Alle 64 Annahmen haben den Evidenzstatus **ungeprüft**: Keine Live-Regel verweist auf eine bestandene Studie. `RULE_EQUIVALENCES` in `setup_evidence.py` ist leer.

**Bestimmen Einstieg, Stop und Ziel der Pläne:**
- `src/dashboard/level_plans.py`
- `vp_plans.py`
- `plan_journal.py`: _active_stop, judge_trade, swing_stop, drop_lost_levels, invalid_on_arrival
- `plan_cost_check.py`
- `exit_shadow.py` und `orderflow_shadow.py`
- `src/orderflow_scenario/engines/trade_plan.py`
- `src/orderflow/live_state.py`: THRESHOLDS

**Feature-Schalter (Env), Namen ohne Werte von Secrets:**
- In der launchd-Runtime: `TIM_ENABLE_OLLAMA=false`, `TIM_OMNIROUTE_ENABLED=true`, `TIM_OLLAMA_MODEL=qwen2.5:7b`.
- Im Code: `TIM_OFSC_MODE`, `TIM_RUNTIME_CANDLES`, `TIM_RUNTIME_ENV`, `TIM_DASHBOARD`, `TIM_MACRO_CALENDAR`, `TIM_BAROMETER_JSON`, `TIM_GRAPHIFY_VIEW`, `TIM_TRADING_TEAM_STATE`, `TIM_HERMES_*`, `TIM_OBSIDIAN_VAULT`.
- Einzelwerte habe ich nicht weiter verfolgt.

| ID | Bereich | Annahme | Stelle | Wert |
|---|---|---|---|---|
| LIVE-CHART-01 | chart_urteil | Ein Long am 1D-VAL (Short am 1D-VAH) innerhalb 0,15 % ist ein Pluspunkt, am gegenüberliegenden Value-Rand oder am 1D-POC ein Minuspunkt. | `src/dashboard/chart_verdict.py:judge R1 (Z.144-157)` | NEAR_PCT=0.15 %; +1/-1 Punkt |
| LIVE-CHART-02 | chart_urteil | Eine 1h- bzw. 4h-Marktstruktur (BOS/MSS) in Trade-Richtung verbessert den Trade, dagegen verschlechtert ihn; beide Zeitrahmen zählen je einen Punkt. | `src/dashboard/chart_verdict.py:judge R2 (Z.158-165)` | STRUCTURE_TFS=(1h,4h); je TF +1/-1; Pivotbreite chart_live.STRUCTURE_PIVOT=3 |
| LIVE-CHART-03 | chart_urteil | Ein Stop hinter dem Strong Low/High der 1h-Struktur (bei 1h-Trend in Trade-Richtung) macht den Trade besser. | `src/dashboard/chart_verdict.py:judge R3 (Z.166-170)` | +1 Punkt |
| LIVE-CHART-04 | chart_urteil | Liegen zwischen Einstieg (+0,25 R) und erstem Ziel ein 1D/1W-Level, naked POC oder ein BOS-Ziel der Gegenrichtung, ist das ein Hindernis gegen den Trade. | `src/dashboard/chart_verdict.py:judge R4 (Z.171-185)` | OBSTACLE_MIN_R=0.25; MAJOR_GROUPS=(day,week,naked); -1 Punkt (nur einmal, egal wie viele Hindernisse) |
| LIVE-CHART-05 | chart_urteil | Ein Einstieg direkt (0,30 %) an einer ungebrochenen 1h-Trendlinie in Trade-Richtung stützt den Trade, direkt an einer Gegen-Trendlinie bremst ihn. | `src/dashboard/chart_verdict.py:judge R5 (Z.186-194)` | LINE_PCT=0.30 %; TREND_TF=1h; Pivotbreite chart_live.TREND_PIVOT=5; +1/-1 |
| LIVE-CHART-06 | chart_urteil | Absorption an einem Level nahe dem Einstieg (Stütze) stützt den Trade, Absorption auf dem Weg zum Ziel bremst ihn. | `src/dashboard/chart_verdict.py:judge R6 (Z.199-208)` | Stütze: Level innerhalb 2*NEAR_PCT=0,30 % unter/über Einstieg; +1/-1 je Level |
| LIVE-CHART-07 | chart_urteil | Eine Orderflow-Welle in Plan-Richtung ohne Exhaustion bestätigt den Trade, eine Welle dagegen spricht gegen ihn. | `src/dashboard/chart_verdict.py:judge R7 (Z.209-214) -> orderflow_shadow.gate` | +1 / -1 Punkt |
| LIVE-CHART-08 | chart_urteil | Tages-CVD und Perp-Delta 15m beide in Plan-Richtung stützen den Trade, beide dagegen sprechen gegen ihn. | `src/dashboard/chart_verdict.py:judge R8 (Z.215-222)` | +1/-1; kein Punkt bei Uneinigkeit oder 0 |
| LIVE-CHART-09 | chart_urteil | Ein Netto-Punktestand von mindestens +2 bedeutet NEHMEN, von höchstens -2 AUSLASSEN, sonst NEUTRAL; alle Regeln wiegen gleich viel. | `src/dashboard/chart_verdict.py:TAKE_AT/SKIP_AT (Z.38), judge Z.223-226` | TAKE_AT=+2; SKIP_AT=-2; Gewichte alle 1 |
| LIVE-CHART-10 | chart_urteil | Das Chart-Urteil gilt nur, wenn die Orderflow-Lage höchstens 10 Minuten vom Planzeitpunkt entfernt ist. | `src/dashboard/chart_verdict.py:orderflow_view/LAGE_MAX_AGE (Z.31,66-72)` | LAGE_MAX_AGE=10 min |
| LIVE-CHART-11 | chart_urteil | Das Vortages-Value (VAH/VAL/POC) und die Level-Auswahl der Chart-Lage bilden den Chart zutreffend ab (Wertefläche 70 %, Kerzen-Näherung wenn keine echten Trades). | `src/dashboard/chart_model.py:VALUE_AREA_SHARE (Z.28); chart_verdict.chart_lage (Z.82-118)` | VALUE_AREA_SHARE=0.70; PROFILE_TARGET_BINS=60 |
| LIVE-GRADE-01 | grade | Ein bestätigtes Szenario (CONFIRMED) ist wertvoller als ein unbestätigtes: +2 Punkte (von max. 5). | `src/orderflow_scenario/engines/trade_plan.py:grade_scenario (Z.213)` | +2 Punkte |
| LIVE-GRADE-02 | grade | Ein Szenario-Score von mindestens 0,45 ist ein Qualitätsmerkmal des Setups: +1 Punkt. | `src/orderflow_scenario/engines/trade_plan.py:GRADE_SCORE_THRESHOLD (Z.42), grade_scenario` | 0.45; +1 |
| LIVE-GRADE-03 | grade | Ein Reward/Risk (Ziel 1) von mindestens 2,0 macht ein Setup besser: +1 Punkt. | `src/orderflow_scenario/engines/trade_plan.py:GRADE_RR_THRESHOLD (Z.43), grade_scenario` | 2.0; +1 |
| LIVE-GRADE-04 | grade | Fehlen Gegenbelege (evidence_against), ist das Setup besser: +1 Punkt; Gegenbelege schließen A aber nicht aus (4 von 5 Punkten reichen). | `src/orderflow_scenario/engines/trade_plan.py:grade_scenario` | +1; A ab 4 Punkten, B bei 3, sonst C; A+ nie |
| LIVE-GRADE-05 | grade | Der Evidenzstatus eines Setup-Typs ist INSUFFICIENT_EVIDENCE, solange keine geprüfte Regel-Äquivalenz zu einer im Hypothesenregister geführten Strategie besteht. | `src/research_lab/setup_evidence.py:RULE_EQUIVALENCES (Z.33), evidence_status` | RULE_EQUIVALENCES={} (leer) |
| LIVE-GRADE-06 | grade | Ein Plan darf nur dann als PAPER_TRADE gelten, wenn Evidenz PASSED_HOLDOUT, Ausführung PAPER_APPROVED, Pipeline TRADE_PLAN und Szenario CONFIRMED sind. | `src/dashboard/plan_journal.py:journal_gate (Z.287-310)` | 4 Gates, alle nötig |
| LIVE-GRADE-07 | grade | Pläne nur auf Symbolen mit Registerforschung (BTCUSDT) erben einen Evidenzstatus; andere Symbole (z.B. XMR) bekommen SYMBOL_NOT_RESEARCHED. | `src/dashboard/plan_journal.py:EVIDENCE_SYMBOLS (Z.126), with_evidence (Z.1057)` | frozenset({BTCUSDT}) |
| LIVE-OF-01 | orderflow | Ein Delta gegen die Kursbewegung bei nicht dünnem Volumen bedeutet Absorption durch passive Gegenseite; bei dünnem Volumen (<0,7x) bedeutet es stattdessen Erschöpfung des Aggressors. | `src/orderflow_scenario/engines/orderflow_interpretation.py:evaluate (Z.~250-290)` | THIN_VOLUME_RATIO=0.7 |
| LIVE-OF-02 | orderflow | Schweres Volumen (>=1,2x Mittel der 5 Vorkerzen) bei einseitigem Delta und flachem Preis (<0,1 %) ist Absorption. | `src/orderflow_scenario/engines/orderflow_interpretation.py:HEAVY_VOLUME_RATIO (Z.46), evaluate` | HEAVY_VOLUME_RATIO=1.2; EFFORT_BASELINE_CANDLES=5; Flat-Schwelle 0,1 % (Z.193) |
| LIVE-OF-03 | orderflow | Eine Bewegung mit Delta bei dünnem Volumen (<0,7x) und schrumpfender Range (<0,8x) zeigt, dass dem Zug der Treibstoff ausgeht (Exhaustion). | `src/orderflow_scenario/engines/orderflow_interpretation.py:SHRINKING_RANGE_RATIO (Z.48)` | SHRINKING_RANGE_RATIO=0.8 |
| LIVE-OF-04 | orderflow | Footprint: Ein Ask/Bid-Verhältnis von mindestens 4 an einem Preislevel ist ein Imbalance; drei aufeinanderfolgende bilden einen Stack und bedeuten lebendigen Zug. | `src/orderflow_scenario/footprint.py:IMBALANCE_RATIO/STACK_MIN (Z.43-44)` | IMBALANCE_RATIO=4; STACK_MIN=3 |
| LIVE-OF-05 | orderflow | Footprint-Absorption: Ein Level mit mindestens dem 3-fachen mittleren Levelvolumen ist Absorptions-Cluster; Randlevel <=25 % des Mittels in den äußeren 20 % der Range zeigen Erschöpfung. | `src/orderflow_scenario/footprint.py:CLUSTER_RATIO/THIN_EXTREME_RATIO/EDGE_FRACTION (Z.45-47)` | CLUSTER_RATIO=3; THIN_EXTREME_RATIO=0.25; EDGE_FRACTION=0.2 |
| LIVE-OF-06 | orderflow | Der Marktzustand (Trend, Ausbruch, Akzeptanz, Sweep, Pin-Bar-Erschöpfung) lässt sich aus Pivot-Struktur und festen Kerzenschwellen bestimmen. | `src/orderflow_scenario/engines/market_state.py:evaluate (Z.140-232)` | Expansion Vol-Ratio>=1,5; Kompression<=0,7; Akzeptanz Vol-Ratio>=0,9; Pin-Bar Body<15 % der Range und Vol-Ratio>=1,3; PIVOT_WINDOW=2; Range über 20 Kerzen; Konfidenz 0,75 (x0,6 bei Konflikt) |
| LIVE-OF-07 | orderflow | Ein Breakout-Szenario ist relevant, wenn der Kurs 0,5 % unter bis 2 % über dem Range-Hoch (20 Kerzen) liegt, ein Reclaim-/Rejection-Szenario in vergleichbaren Fenstern am Range-Tief. | `src/orderflow_scenario/engines/scenario_generator.py:generate (Z.137-154), BREAKOUT_EDGE_WINDOW (Z.348)` | near_range_high [0,995;1,02]xHoch; near_range_low [0,98;1,005]xTief; Kante 1 % |
| LIVE-OF-08 | orderflow | Anfangs-Scores der Szenarien (A 0,38, B 0,34, C 0,28, D 0,35, E 0,30, Broncx-Level 0,30) und Normierung auf Summe 0,9 spiegeln relative Wahrscheinlichkeiten. | `src/orderflow_scenario/engines/scenario_generator.py:generate (Z.201,244,287,308,326,420; Normierung Z.334-343)` | 0.38/0.34/0.28/0.35/0.30/0.30; Summe 0,9 |
| LIVE-OF-09 | orderflow | Der Szenario-Score erhöht sich um feste Zuschläge: Marktzustand passt +0,12, aggressive Seite passt +0,08 (dagegen -0,06), je Beleg dafür +0,04 (max 3), dagegen -0,05 (max 2), bestätigte Absorption/Exhaustion +0,06, OI-Akkumulation +0,03, Positionierungshinweis +-0,03, Datenqualität skaliert 0,5-1,0. | `src/orderflow_scenario/engines/probability.py:_score (Z.~45-90)` | Basis 0,30; +0,12/+0,08/-0,06/+0,04xn/-0,05xn/+0,06/+0,03/+-0,03 |
| LIVE-OF-10 | orderflow | Ein Szenario wird CONFIRMED, sobald alle seine Pflichtbestätigungen erfüllt sind; eine einzige spezifische Invalidierung macht es INVALIDATED. | `src/orderflow_scenario/engines/confirmation.py:_next_state (Z.~45-60)` | alle mandatory_confirmations nötig; keine Gewichtung optional |
| LIVE-OF-11 | orderflow | Broncx' Richtung verschiebt Szenario-Scores um höchstens +-0,08 und seine Level nahe dem Kurs (1 %) werden zu Szenarien (max 2, Abstand >0,2 % zu eigenen Triggern); er zählt nie als Bestätigung. | `src/orderflow_scenario/external_context.py:EXTERNAL_WEIGHT (Z.47); scenario_generator.EXTERNAL_LEVEL_WINDOW (Z.350)` | EXTERNAL_WEIGHT=0.08; Fenster 1 %; Duplikat 0,2 %; MAX 2; Alter <=24 h |
| LIVE-OF-12 | orderflow | Funding >=0,02 %/8h ist erhöht, >=0,05 % extrem; Liquidationsanteil >=65 % ist dominant; OI-Änderung <0,5 % ist flach; Orderbuch-Imbalance >=0,15 ist spürbar; Gamma-Flip innerhalb 0,3 % ist AT_FLIP. | `src/orderflow_scenario/positioning.py (Z.52-57, 676)` | FUNDING_ELEVATED_8H=0.0002; EXTREME=0.0005; LIQUIDATION_DOMINANCE=0.65; OPEN_INTEREST_FLAT=0.005; ORDERBOOK_IMBALANCE_NOTABLE=0.15; GAMMA_NEAR=0.003 |
| LIVE-OF-13 | orderflow | Live-Orderflow-Lage: Eine Welle hat Richtung, wenn /Delta5m//Volumen5m >=0,15; Stärke 0-3 aus Tempo gegen die letzten 20 Minuten mit Grenzen 1,0/1,6/2,5. | `src/orderflow/live_state.py:THRESHOLDS, _wave (Z.40-47,193-216)` | direction_share=0.15; tempo_strength=(1.0,1.6,2.5) |
| LIVE-OF-14 | orderflow | Exhaustion einer Welle liegt vor, wenn die letzte Minute <50 % des 3-Minuten-Spitzenvolumens hat oder das Delta kippt, und der 1m-Range <30 % der 5m-Range ist (Stillstand). | `src/orderflow/live_state.py:_wave (Z.193-216)` | fade_ratio=0.5; stall_range_share=0.3 |
| LIVE-OF-15 | orderflow | Absorption an einem Level liegt vor, wenn es berührt, nicht durchbrochen wird und sein 15m-Volumen >=3x das Median-Levelvolumen ist; Imbalance bei Ask/Bid >=3. | `src/orderflow/live_state.py:_levels (Z.222-256)` | absorption_volume_factor=3.0; imbalance_ratio=3.0; Toleranz 2 Ticks; Reichweite 0,6 % |
| LIVE-OF-16 | orderflow | Eine Orderflow-Welle in Plan-Richtung ohne Exhaustion ist BESTAETIGT, eine Gegenwelle GEGEN; der Schatten würde bei Gegenwelle der Stärke >=2 oder eigener Exhaustion aussteigen. | `src/dashboard/orderflow_shadow.py:gate/should_exit (Z.81-97), AGAINST_STRENGTH=2` | AGAINST_STRENGTH=2; TARGET_TRADES=30 |
| LIVE-OF-17 | orderflow | Beobachtungsregeln (z.B. Kaufvolumen >=2x Vorfenster und Kauf-Anzahl >=1,5x) zeigen aggressive Käufer-/Verkäuferaktivität; mindestens zwei Klauseln je Regel. | `src/orderflow/observations.py:OrderflowObservationEngine.evaluate (Z.~38-60)` | Faktoren 2/1,5/3/2, Ratio >=3 |
| LIVE-OF-18 | orderflow | Ein 5/15/30-Minuten-Preisverlauf mit Seitwärtsschwelle 0,10 % misst, ob eine Orderflow-Beobachtung richtig lag. | `src/orderflow/validation.py:HORIZONS/SIDEWAYS_THRESHOLD_PERCENT (Z.15-16)` | HORIZONS=(5,15,30) min; SIDEWAYS=0,10 % |
| LIVE-KOSTEN-01 | kosten | Gebühr 0,05 % und Slippage 0,03 % je Seite (0,05 % bei Stop-Ausführung) bilden die Handelskosten realistisch ab. | `src/dashboard/plan_journal.py:FEE_PER_SIDE/SLIPPAGE_PER_SIDE/STOP_SLIPPAGE (Z.100-103), costs_r (Z.567); src/research_lab/protocol.py:CostModel (Z.50-56)` | fee=0.0005; slippage=0.0003; stop_slippage=0.0005 |
| LIVE-KOSTEN-02 | kosten | Ein Plan ist nur handelbar, wenn die geschätzten Round-Trip-Kosten bis zum Stop höchstens 0,25 R betragen; teurere Pläne werden nicht ins Journal geschrieben. | `src/dashboard/plan_cost_check.py:COST_LIMIT_R (Z.40); plan_journal.drop_costly (Z.402)` | COST_LIMIT_R=0.25 |
| LIVE-KOSTEN-03 | kosten | Der Kostenpreis (Break-even plus Kosten) entspricht fill*(1+0,05 %+0,03 %)/(1-0,05 %-0,05 %), ~0,18 % über dem Einstieg bei BTC. | `src/dashboard/plan_journal.py:cost_stop_level (Z.590)` | aus FEE/SLIPPAGE/STOP_SLIPPAGE |
| LIVE-KOSTEN-04 | kosten | Das Orderflow-Modul rechnet 6 bp Taker, 2 bp Maker, 2 bp Slippage und verwirft Trades, bei denen Gebühren >25 % des Gewinns auffressen. | `src/orderflow_scenario/config.py:default_config fee_model (Z.183); engines/risk.py (Z.129-131)` | taker 6, maker 2, slippage 2 bp; Kosten/Reward <=0,25 |
| LIVE-KOSTEN-05 | kosten | Limit-Füllungen (Maker 0,02 %) gelten nur in Studien mit Trade-Through-Fill-Regel und Latenzprüfung; sonst bleibt alles Taker. | `src/research_lab/protocol.py:MAKER_FEE (Z.76)` | MAKER_FEE=0.0002 |
| LIVE-AUSF-01 | ausfuehrung | Ein Plan mit TIM/1-Regeln hat Stop 0,5 % (Trend/Breakout) oder 1 % (sonst) unter/über der Einstiegszone und Ziele bei 1,5R/2R/3R. | `src/orderflow_scenario/engines/trade_plan.py:_stop_long/_stop_short (Z.180-190), TARGET_R (Z.37)` | Stop 0,995/0,99 bzw. 1,005/1,01; TARGET_R=(1.5,2,3) |
| LIVE-AUSF-02 | ausfuehrung | Management: Je ein Drittel Ausstieg bei Ziel 1, 2 und 3; bei Berührung von Stop und Ziel in derselben 1m-Kerze zählt der Stop zuerst. | `src/dashboard/plan_journal.py:THIRD (Z.89), evaluate (Z.773); trade_plan.partial_take_profit_plan` | THIRD=1/3 |
| LIVE-AUSF-03 | ausfuehrung | Struktur-Pläne (struct/1): Ein Stop 0,05 % hinter dem nächsten 30m-Swing und Ziele an Liquiditätsorten (Level, Swings) sind besser als feste Prozente; erstes Ziel mindestens 1,5 R. | `src/dashboard/structure_plan.py:MIN_FIRST_R/STOP_BUFFER/MERGE_GAP/SWING_WIDTH (Z.22-26)` | MIN_FIRST_R=1.5; STOP_BUFFER=0.0005; MERGE_GAP=0.0005; SWING_WIDTH=2 |
| LIVE-AUSF-04 | ausfuehrung | Level-Pläne (level/1): Kaufen am nächsten Hauptlevel (Vortag/Vorwoche VAH/VAL/POC, naked POC) unter dem Kurs, Verkaufen am nächsten darüber, wenn das Risiko zum Swing klein ist. | `src/dashboard/level_plans.py:CLUSTER_GAP/ZONE_PAD/MAX_DISTANCE/MAX_RISK/MAX_PLACES (Z.39-43)` | Cluster 0,15 %; Zone +0,05 %; Distanz <=3 %; Risiko <=2 %; 3 Orte je Richtung |
| LIVE-AUSF-05 | ausfuehrung | Volume-Profile-Pläne (vp/1): Berührt eine 30m-Kerze Vortages-VAH/VAL/POC und schließt zurück auf Handelsseite, ist das ein Einstieg mit Ziel am nächsten naked POC (Mindest-R 1,0). | `src/dashboard/vp_plans.py:MIN_R/HOUR_DAYS/WALL_NEAR_PCT/TRADED/PICKY (Z.44-50)` | MIN_R=1.0; HOUR_DAYS=14; WALL_NEAR_PCT=0.3; Kontexte HIGHER/LOWER/INSIDE gehandelt |
| LIVE-AUSF-06 | ausfuehrung | Ein Stop auf Break-even plus Kosten nach TP1 (oder nach TIMs Urteil SICHERN) schützt Gewinn besser als der alte Stop auf Einstieg. | `src/dashboard/plan_journal.py:_active_stop (Z.609), judge_trade (Z.650), STOP_RULE_COST` | COST_STOP_MIN_GAP_R=0.1; FALLBACK_HOURS=4; FALLBACK_MFE_R=0.75 |
| LIVE-AUSF-07 | ausfuehrung | TIM sichert, wenn Struktur seit dem Fill die Richtung bestätigt hat (BOS/MSS dafür) oder die These schwächer wird (BOS dagegen, Marktzustand dagegen, bestätigtes Gegenszenario). | `src/dashboard/plan_journal.py:judge_trade (Z.650-690), VERDICT_RULESET` | Gründe: structure_confirms_*, structure_against_*, market_state_against, opposite_scenario_* |
| LIVE-AUSF-08 | ausfuehrung | Ein geschützter Stop folgt dem letzten bestätigten 30m-Swing in Gewinnrichtung (wenn Schluss >=0,1 R darüber) wie bei einem Orderflow-Trader. | `src/dashboard/plan_journal.py:swing_stop (Z.693)` | COST_STOP_MIN_GAP_R=0.1; PIVOT_WINDOW=2 |
| LIVE-JOURNAL-01 | journal | Ein Limit-Plan verfällt nach 24 h ohne Fill (30m), Haltedauer max 48 h; Horizonte 15m: 12/24 h, 1h: 24/72 h, 1d: 7/21 Tage. | `src/dashboard/plan_journal.py:PENDING_HOURS/MAX_HOLD_HOURS/HORIZON_HOURS (Z.87-88,134)` | 24/48 h; (12,24); (24,72); (168,504) |
| LIVE-JOURNAL-02 | journal | Nach einem Stop an einem Level gilt das Level als verloren; neue Pläne am gleichen Level warten auf einen Schluss jenseits der Zone (Horizont-Journale zusätzlich auf 4 Schlüsse). | `src/dashboard/plan_journal.py:drop_lost_levels (Z.442), LOCK_TOLERANCE/LOCK_MIN_CLOSES (Z.161-162)` | Toleranz 0,1 %; Mindestsperre 4 Schlüsse |
| LIVE-JOURNAL-03 | journal | Pläne, deren Stop oder Invalidierung beim Aufnahme-Schluss schon überschritten ist, sind nicht handelbar und werden nicht notiert. | `src/dashboard/plan_journal.py:invalid_on_arrival (Z.500)` | Schluss jenseits Stop/Invalidierung |
| LIVE-JOURNAL-04 | journal | Keine neuen Einstiege im NY-Open-Block (15 min vor bis 30 min nach 9:30 New York). | `src/dashboard/chart_model.py:NY_OPEN_LOCAL/NY_OPEN_BLOCK (Z.39-40); plan_journal ny_open_windows` | (-15 min, +30 min) |
| LIVE-JOURNAL-05 | journal | Kerzen mit mehr als 60 Minuten Alter (30m-Journal) gelten als veraltet, dann werden keine neuen Pläne aufgenommen. | `src/dashboard/plan_journal.py:STALE_AFTER (Z.128); level_plans/vp_plans STALE_SECONDS=3600` | 60 min |
| LIVE-JOURNAL-06 | journal | Ein BTC-Short ist auf Binance Spot nicht ausführbar (kein Margin-Modell), XMR-Perp-Short schon; Tick 0,01 und Los 0,00001 bzw. 0,001. | `src/dashboard/plan_journal.py:INSTRUMENT_SPECS (Z.119-124)` | short_executable False/True; Ticks |
| LIVE-JOURNAL-07 | journal | Ein Score-Bucket mit höherem Score hat höhere Trefferquote (der Score ist kalibriert); wird erst ab 30 Plänen beurteilt. | `src/dashboard/plan_journal.py:SCORE_BUCKETS/SCORE_MIN_PLANS (Z.873-874)` | Buckets 0-0,4/0,4-0,5/0,5-0,6/0,6+; min 30 |
| LIVE-JOURNAL-08 | journal | Perp-Journale auf Binance-USD-M-Kerzen mit Volumenprofil aus echten Perp-Trades bilden das Handelskonto (Kraken-Perps) besser ab als Spot-Journale. | `src/dashboard/perp_journal.py (Z.1-30)` | Pfade perp_short/mid, xmr_15m/1h |
| LIVE-JOURNAL-09 | journal | Das Trader-Journal bucht einen Trade nur als TRADE, wenn alle vier Broncx-Gate-Fragen mit Ja beantwortet sind, sonst NO_TRADE. | `src/dashboard/trader_journal.py:GATE (Z.44-49)` | 4 Fragen, 1 Nein = NO_TRADE |
| LIVE-JOURNAL-10 | journal | Eine Volatilitätsgewichtung (SIGMA_REF/sigma, begrenzt auf 0,5-2,0) auf Basis der GARCH(1,1)-4h-Prognose macht die Papier-Größe besser. | `src/research_lab/vol_4h.py:W_MIN/W_MAX/SIGMA_REF/PARAMS (Z.44-53)` | W_MIN=0.5; W_MAX=2.0; SIGMA_REF BTC 0,9787; PARAMS BTC (0.0126,0.0628,0.9371) |
| LIVE-REFL-01 | reflexion | Käufer-Aktivität, steigendes CVD und extremes Kaufverhältnis bedeuten 'Preis steigt' (Verkäufer-Pendants 'fällt', Frequenz/Großtrade 'bewegt sich'); das ist die feste Lesart der Reflexion. | `src/reflection/scorecard.py:READING (Z.29-38)` | 8 Beobachtungstypen -> UP/DOWN/MOVE; Horizonte 5/15/30 min |
| LIVE-REFL-02 | reflexion | Eine Beobachtungsregel gilt als belegt, wenn der einseitige Binomialtest gegen die Basisrate nach Holm-Korrektur p<0,05 erreicht und mindestens 30 Fälle vorliegen. | `src/reflection/scorecard.py:MIN_SAMPLE/ALPHA (Z.39-41); report.py:STATUS` | MIN_SAMPLE=30; ALPHA=0.05; Holm; Wilson 95 % |
| LIVE-SONST-01 | sonstiges | Risikostufen der Orderflow-Risk-Engine: STANDARD 0,5 % Konto-Risiko, CONSERVATIVE 0,25 %, AGGRESSIVE 1 %; Hebel max 10x; Tagesverlust 3 %, Woche 6 %, 3 Verluste in Folge stoppen. | `src/orderflow_scenario/config.py:default_config (Z.167-182), MAX_LEVERAGE (Z.26)` | 0,25/0,5/1 %; 10x; 3 %/6 %/3 Verluste; Positionsanteil 10 %; Liquidationspuffer 5 %; min. Datenqualität 0,5; required_grade B |
| LIVE-SONST-02 | sonstiges | Datenqualität: Jede fehlende Eingabe senkt das Vertrauen um 0,12, jedes Problem um 0,08, jede Schätzung um 0,02 (Basis 0,9); unter 0,5 wird kein Plan zugelassen. | `src/orderflow_scenario/engines/data_quality.py (Z.115-125)` | Basis 0,9; 0,12/0,08/0,02; Faktoren 0,7/0,5; Screenshot-Konfidenz <0,6 |
| LIVE-SONST-03 | sonstiges | Konfidenz der Orderflow-Interpretation startet bei 0,55 und steigt mit Anzahl Beobachtungen (+0,05 je), Bestätigungen (+0,10-0,15) und Kategorien (+0,02, max 0,08). | `src/orderflow_scenario/engines/orderflow_interpretation.py (Z.475-502)` | 0.55 Basis; Zuschläge s. Z.476-493 |

**Auffälligste Annahmen (alle ungeprüft):**
1. **Chart-Urteil:** Alle Regeln haben das Gewicht 1. Die Schwellen liegen bei TAKE_AT +2 und SKIP_AT −2. R2 zählt 1h und 4h doppelt. Fehlt eine frische Orderflow-Lage, gilt dieselbe Schwelle mit weniger Regeln. S22 hat 2023–2024 nicht bestanden: R5 wirkt verkehrt, R3 sagt nie „dagegen“, R4 nie „dafür“.
2. **Szenario-Score:** Grade A/B/C hängt am Score ≥ 0,45, und dieser Score ist ausdrücklich `UNCALIBRATED_CONFIDENCE` aus gesetzten Startwerten und Zuschlägen.
3. **Orderflow-Schwellen:** Die Schwellen in `live_state.THRESHOLDS` (Welle, Absorption 3x, Imbalance 3, fade 0,5) sind laut Docstring „unkalibrierte Startwerte“. Sie tragen R6–R8.
4. **Kosten:** Das Kostenlimit 0,25 R filtert Pläne aktiv. Die Kostensätze sind uneinheitlich: Journal 0,05 % + 0,03 %, Orderflow 6/2/2 bp, Orderflow-Schatten 5 bp.
5. **Sichern und Nachziehen:** Diese Logik (be_cost/1, verdict/1, Sicherheitsnetz 4 h / 0,75 R, Swing-Trail) bestimmt das Netto-R des ganzen Journals.

## Nicht gelesen bzw. offen
- Rohabschriften in GoatHub-Verlauf/kanaele und rohfassungen: nur über die Auswertungen erfasst.
- Die Inhalte von telegram-reader: Code und Sitzungsdaten habe ich bewusst nicht geöffnet.
- Die PDFs selbst.
- `src/orderflow_scenario/engines/pipeline.py` und das Innere von `chart_live.market_structure` habe ich nicht in Regeln zerlegt.
- Ob OF2/OFX live Entscheidungen tragen: offen. Im Live-Pfad ist nur `research_lab/forward/of_paper.py` sichtbar.
- Die Werte der Env-Schalter im Code (nur die Namen erfasst).
- Keine Secrets, kein Keychain und keine .env gelesen.
