# TIM Core Research: Bestandsaufnahme Orderflow, Optionsflow, Gamma

Stand: `platform-main` = HEAD 5670267 (nur lesend; `git fetch origin` ausgeführt, nichts geschrieben).
Grenze: `TRADING_AUTHORIZED=NO`. Dieses Dokument enthält keine Handelsfreigabe und keine neuen Rechenergebnisse.
Kennzeichnung: BELEG = im Repo gelesen (Datei/Zeile). VERMUTUNG = nicht belegt. Testzahlen sind grob per `grep -c "def test_"`, nicht per pytest-Lauf.

## 1. Bestand je Engine

| Engine | Modul (LOC) | Was es berechnet | Tests (grob) |
|---|---|---|---|
| Orderflow live | `src/orderflow/` (6 Dateien, 803): `live_state.py`, `metrics.py`, `observations.py`, `validation*.py` | Fenster 1/5/15 min, Delta, Tages-CVD, Absorption, buy_share; `metrics.py` verlangt Trade-ID und `buyer_is_maker` (Z. 37) | 19 Dateien `tests/test_orderflow*`, 194 Tests; `test_perp_flow*` 27 |
| Orderflow Szenario | `src/orderflow_scenario/` (37 Dateien, 8065): Footprint, Engines, Backtest, Governance | Szenario-/Planlogik (nicht im Forschungsplan, nur erwähnt) | in den 194 enthalten (VERMUTUNG: teils) |
| Orderflow Forschung | `src/research_lab/of2` (14, 2600), `ofx` (7, 615), `orderflow_ml` (Bars), `s31` | Footprint, Delta, Absorption, Parameterrasterlauf (OFX ca. 32.100 Konfigurationen laut Plan Abschn. 9) | of2 79 Tests, ofx 18 |
| Fusion (S40-Gerüst) | `src/research_lab/fusion/`: `of_features.py`, `historisch.py`, `walkforward.py`, `datenreife.py` | Merkmale F1-F10 als reine Funktionen, historischer Lader mit Holdout-Sperre, purged Walk-forward, Ridge, Clark-West | `test_fusion_*` 25 Tests, `test_s40*` 23 |
| Optionsflow | `src/research_lab/options_flow/` (6, 774): `recorder.py`, `contract.py`, `features.py`, `features_q.py` | Deribit-Optionstrades, R1-R6, V1-V3, Q-Merkmale; Merkmal zu t nur mit `recv_ms <= t` (`features.py:4,25`) | `test_research_lab_options_flow*` 3 Dateien, 26 |
| Gamma | `src/options_gamma/` (7, 940): `gex.py`, `models.py`, `greeks.py`, `snapshot.py`, `recorder.py` | GEX je Strike, Flip, Wände, Max Pain; `models.py`: M0-M4, Spot/Forward (Black-76), Vanna, Charm, Sensitivität | `test_options_gamma*` 25, `test_gamma*` 32 |
| Gamma-Zonen / Forward | `src/dashboard/gamma_zones.py`, `gamma_data.py`, `src/research_lab/forward/gamma_callwall.py` | Gamma-Level gegen Orderbuch-Wände; S41-Beobachtung | `test_research_forward_gamma_callwall` 6 |
| Liquidationen / Depth | `src/liquidation_map`, `research_lab/liquidations` (1068), `depth` (803), `orderbook` (600) | Heatmap, L2-Replay, Wände | `test_liquidation*` 4 Dateien |
| Prüfwerkzeug | `research_lab/stats` (1149), `protocol.py`, `konsolidierung/` | Bootstrap, Holm, Deflated Sharpe, Kosten, Holdout-Sperre | 97 Dateien mit `research_lab` im Namen |

Gesamt: 549 Testdateien, 6249 `def test_` im Repo. BELEG: Property-Tests (Bibliothek `hypothesis`) kommen in `tests/` nicht vor (grep ohne Treffer). Es gibt nur `test_orderflow_known_side_properties.py` auf Branch `-a`, nicht auf main.

Pläne: `docs/research_lab/of_optionen_gamma/FORSCHUNGSPLAN.md` (Entwurf 0.1, 368 Z., Stand 23.11.) und `LITERATUR_EVIDENZ.md` (140 Z.). BELEG: Der Plan nennt sich selbst "keine Testergebnisse". Seine Pakete P0-P4 sind auf main inzwischen gebaut (`fusion/*`, `options_gamma/models.py`, `features_q.py`).

## 2. Studienurteile

Alle Urteile stammen aus Berichten im Repo. BELEG, soweit Datei genannt.

| Studie | Urteil | Beleg |
|---|---|---|
| S40 (Orderflow/Optionsflow historisch, 1.0 eingefroren 24.11., Merge f733f90) | Alle 12 Haupttests im Training nicht bestanden; Validierung entfällt, 2023-24 ungesehen, 2025 unberührt. Kleinster Holm-p 0,066 (T3 ETH 1h), IC des größeren Modells in 11 von 12 kleiner als Kursmodell. Offener Punkt: T9 gleicher IC für A1 und A5 auf 1h | `studien/S40_BERICHT.md` |
| S40 Datenreife | Alle Märkte und Deribit 2020-01 bis 2024-12 gültig (60/60 bzw. SOL 52/52) | `studien/S40_DATENREIFE.md` |
| S41 (Call-Wall als Widerstand, vorwärts, eingefroren 24.11.) | Läuft; Start 25.11., Urteil erst ab 30 entschiedenen Ereignissen, sonst nach 120 Tagen NICHT_BESTANDEN_ZEIT. Erkundung (17/18 gehalten) ausdrücklich kein Beleg | `studien/S41_...PRAEREGISTRIERUNG.md` |
| S39 (Bewegung Fortsetzung/Umkehr) | Kein Typ belegt, drei Typen unter n=20 | `studien/S39_BERICHT.md` |
| S35a (Level plus Orderflow) | Nicht bestanden, alle 12 Konfigurationen, Training | `studien/S35A_ZAEHLLAUF_ERGEBNIS.md` |
| S34 (LVN/VWAP-Fade) | Nicht bestanden | `studien/S34_ZAEHLLAUF_ERGEBNIS.md` |
| S32 (Orderbuch-Ungleichgewicht) | Nicht bestanden: Kosten 13-18 bp größer als enger Stop (laut Zitat in S42/S43 auf Branch efoijz) | `reports/s32_s32r_ergebnis_2026-11-23.md` (Inhalt nicht gelesen) |
| S42/S43 (Orderbuch, große Ranges / Limit-Einstieg), S44 (Ausbruch folgen) | Auf platform-main nicht vorhanden. Auf Branch `origin/claude/project-thread-efoijz`: S42/S43 "1.0 eingefroren 25.11.", S44 "Entwurf 0.1". Branch gehört zu PR #398 (Chris, offen, geprüft 26.11.) | `git ls-tree origin/claude/project-thread-efoijz` |
| OF2, OFX, S31/S31b | Laut FORSCHUNGSPLAN Abschn. 1 Nr. 5 "alle nicht bestanden oder nicht belegt" (Zusammenfassung des Plans, Einzelurteile nicht neu geprüft) | `FORSCHUNGSPLAN.md` |
| Gamma-Wände (Altstudie) | Training 58/88 gegen 81 % Kontrolle, 2024 19/31 gegen 50 %, Richtung kippt: kein stabiler Vorteil | `FORSCHUNGSPLAN.md` Abschn. 1 Nr. 5 |

"Sicht 5" (Forschung) steht in `docs/audits/GRUEN_PLAN_11_SICHTEN.md`: Grün heißt dort "offene Frage mit vorab registrierter Studie geprüft", nicht "profitabel". Den Stand von Sicht 5 selbst habe ich nicht vertieft.

Studienregister und Freeze-Regeln: `docs/research_lab/PROTOKOLL.md` (Version 1.3), `REGISTER.jsonl` (116 Zeilen; laut S40 58 von 60 Plätzen belegt, `MAX_REGISTER_ENTRIES = 60`, `protocol.py:86`, deshalb werden S34-S40 per PR eingefroren, nicht eingetragen), `konsolidierung/STUDIENREGISTER.md` und `EVIDENZMATRIX.md` (Datensatz-Familien OF-MIN, LEVEL-INTRADAY mit überlappenden Zeiträumen, "nicht unabhängig"), `gedaechtnis/`. Holdout: `protocol.py:25` `HOLDOUT_START_MS` = 2025-01-01, `split_of` Z. 41-43.

## 3. Point-in-Time und Lookahead

Vorhandener Schutz (BELEG):
- Holdout-Sperre im Code: `protocol.py:25,41-43`; `fusion/historisch.py:54,65,86,106` (Dateien ab 2025 ungeöffnet übersprungen, Zeilen gezählt und verworfen); `studies/s40_daten.py:69,127,234,345` (HoldoutRefused); `walkforward.py:22` (Abbruch bei Zeile/Ziel ab 2025).
- `recv_ms`-Regel: `options_flow/features.py:4,25`; historische Zeilen bekommen `recv_ms = ts + 2000 ms` (S40-Präreg. Abschn. 4).
- Merkmale nur aus Bars mit `known_ms <= t`, Ziel ab erster Bar zu/nach t (S40 Abschn. 5); Tests `test_fusion_of_features.py:53` (`test_no_look_ahead`), `test_fusion_scaffold.py:95,106,190`.
- Aggressorseite im Fusion-Lader strikt +1/-1, sonst ValueError (`fusion/of_features.py:53-54`).
- `dvol_change` nutzt nur Kerzen mit Stempel <= t (`options_flow/features.py:102-120`, Test `test_research_lab_options_flow_features.py:66`).

Bekannte Lücken auf platform-main (alle bestätigt, Stand HEAD 5670267):

| Lücke | Status auf main | Stelle | Fix liegt in |
|---|---|---|---|
| Unbekannte Handelsseite = Kauf (Paket B) | OFFEN | `src/orderflow/live_state.py:93` `buy = not bool(trade.buyer_is_maker) if trade.buyer_is_maker is not None else True`; `src/dashboard/perp_flow.py:298` `seller_aggressive = bool(row["m"])` (None/Text würde zur Seite) | Commit b0ab1372 u. a. auf `origin/claude/project-thread-7aqprg-b` (+ Folgecommits bis 86dd94f0) |
| Live-Lage ohne Point-in-Time (Paket A) | OFFEN | `live_state.py:167` setzt `as_of` = Erzeugungszeit; kein `pit_contract`, Datei existiert auf main nicht (`git ls-files` leer) | `-a` (neue `src/orderflow/pit_contract.py`, 191 Z., plus `test_pit_contract.py`); auch `-pit` |
| Gamma-Zonen ohne Options-Frische (Paket C) | OFFEN | `src/dashboard/gamma_zones.py:83-104` prüft nur Orderbuch-Alter (`STALE_AFTER` Z. 37, Z. 94), nicht das Alter des Gamma-Standes; `gamma_data.py:192-198` `with_age` misst ab `as_of` (Empfangszeit), nicht ab Quellzeit des OI | `-c` (`source_times`, `UNKNOWN_GAMMA_TIME`, Ruleset gamma-orderbuch/1.2) |
| `dvol_change` evtl. Look-ahead | VERMUTUNG, nicht belegt | `features.py:113`: `row[0] <= t_ms` nimmt den Schlusskurs einer Kerze, deren Stempel <= t. Ist der Stempel der Kerzenbeginn, fließt Information bis `ts + Auflösung` ein. Auflösung 60 s laut `OPTIONSFLOW_DATENVERTRAG.md:19`. Auf main hat die Funktion keinen Aufrufer in `src/` (grep), also derzeit kein wirksamer Leck, aber V1 aus dem Regelkatalog würde sie nutzen | Vol-Plan `-vol` (`PAKETE_V0_V5_DETAIL.md` Z. 27: "bis belegt gesperrt") |
| OI-Datenalter | OFFEN | Plan Abschn. 3: Deribit-OI evtl. 8 h verzögert (laut Tardis-Doku, unbestätigt). `fusion/datenreife.py` hat einen OI-Alter-Test (`test_fusion_scaffold.py:37`), aber kein Beleg zur echten Verzögerung | keiner |
| `quotes_from_book_summary` | Inverse/USDC-Kontraktgröße nicht gelesen | `snapshot.py:50-75` setzt kein `multiplier` (Default 1,0 aus `gex.py:33`); Plan Abschn. 6.1 will USDC-Größe aus API | keiner |

Hinweis: Die Feature-Branches basieren auf einem älteren main-Stand (Diff `origin/platform-main..-a` löscht u. a. S32/S32-R-Dateien). Bei einem Merge ist ein Rebase nötig, sonst gehen diese Dateien verloren. VERMUTUNG, dass dies nur ein Diff-Artefakt der Basis ist; Merge-Basis nicht geprüft.

## 4. Datenqualität

- Die Wurzel-Dokumente `TIM_COVERAGE_GAP_REGISTER.md`, `TIM_COVERAGE_VALIDATION.md`, `TIM_GAP_CLASSIFICATION_REGISTER.md` betreffen **BTCUSDT-1m-Spot-Kerzen** vom 22./23.07.2026 (`[2026-07-22T20:14Z, 2026-07-23T14:27Z)`): 1093 erwartet, 663 beobachtet, 430 fehlend, **60,659 % Abdeckung**, 33 Lücken (CG-001..033), alle `DOWNLOAD_FAILED`/`REQUIRES_EXTERNAL_SOURCE`, Register-Status OPEN, Wiederherstellung nicht freigegeben. BELEG. Sie sagen nichts über Optionsflow, Gamma oder Perp-Trades und sind für diese Engines nur indirekt relevant (Transportzuverlässigkeit, `TIM_TRANSPORT_RELIABILITY_REPORT.md`).
- Für die Engines maßgeblich ist der Forschungsplan Abschn. 3 und 12: Gamma-Log seit 04.11.2026 (17.11.: 4.032 Zeilen, Lücken bis 2,4 h), Optionsflow seit 13.11. mit Unterbrechung bis 21.11. (TCC), Orderbuch seit 17.11. Laufstatus der Recorder wurde dort selbst "heute nicht geprüft" (Plan Abschn. 12). Ich habe keine Mac-Daten gesehen.
- Historische Daten (S40): 481 MB, Lücke = mehr als 10 min ohne Nachricht, Monat gültig bei Lückenanteil unter 2 % (`S40_DATENREIFE.md`). Kein gültiger Monat fehlt. Das Ergebnis ist ein Befund über das Archiv, nicht über den eigenen Recorder.
- Für S41 sind die eigenen Gamma-Stände entscheidend; die Erkundung (04.-24.11.) stammt aus einer einzigen Fallphase (78k nach 61k), Selektionsrisiko laut S41 selbst.

## 5. Lücken gegen die Gates (Kurzfassung aus Issue #372, wie vorgegeben)

Status nur nach Repo-Lage auf main. Gate-Texte aus Issue #372.

### G1 Orderflow
| Kriterium | Status | Beleg |
|---|---|---|
| Mathematische Definitionen | VORHANDEN | `FORSCHUNGSPLAN.md` Abschn. 4 (F1-F10), Code `fusion/of_features.py` |
| Versionierte Schwellen | TEILWEISE | `live_state.THRESHOLDS` ist "unkalibrierte Startwerte" (Docstring); S40-Schwellen eingefroren per Präreg. |
| Synthetische Positiv-/Negativfälle | TEILWEISE | `test_fusion_of_features.py` (Positivfälle F1-F10), `test_compare_finds_planted_orderflow_effect_only`; für `live_state` nur Einzelfälle |
| Property-Tests | FEHLT | keine `hypothesis`-Tests auf main |
| Identische Replay-Hashes | TEILWEISE | `metrics.py:94` `source_hash`, `gex.py:77` `chain_input_hash`; Replay-Gegenproben nur auf `-integ-abe` (nicht main) |
| Kein Lookahead | TEILWEISE | Forschungspfad gut abgesichert (siehe oben); Live-Pfad: Lücken A und B offen |

### G2 Options/Gamma
| Kriterium | Status | Beleg |
|---|---|---|
| Referenzrechnungen | TEILWEISE | `test_options_gamma_models.py:23` (M0 = gex.py), Finite-Differenzen für Vanna/Charm (Z. 84); keine unabhängige externe Referenz |
| Einheiten | VORHANDEN | Docstring `gex.py:8-10`, `models.py` (USD je 1 %, Vanna je Volpunkt, Charm je Tag) |
| Verfall | TEILWEISE | abgelaufene Quotes werden übersprungen (`snapshot.py:63`, `gex.py:65`); Verfallstag-Effekt (G7, Q10) ungerechnet |
| Inverse Kontrakte | FEHLT | Plan Abschn. 6.1: Delta-Prämienanpassung "OFFEN"; USDC-Größe nicht gelesen (`snapshot.py:50-75` ohne multiplier) |
| Dealer-Annahmen explizit | VORHANDEN | `gex.py:3-6`, `models.py` M0-M4, `assumption_independent` (Z. 251) |
| Keine Gamma-Zone allein aus Depth | TEILWEISE | `gamma_zones.py` verlangt Gamma-Level plus stehende Wand, aber ohne Gamma-Frische (Lücke C) |

### G5 Validierung
| Kriterium | Status | Beleg |
|---|---|---|
| Präregistrierter Test | VORHANDEN | S40 1.0, S41 1.0 (eingefroren, Code-SHA im Bericht) |
| OOS-Netto mit Unsicherheit | TEILWEISE | S40 bewertet IC/Clark-West, bewusst keine Handelsmetrik; Netto-E[R] mit Intervall nur bei S35a/S34 (Bootstrap) |
| Kosten | TEILWEISE | `protocol.py:72` `STRESS_COSTS`; S40 ohne Kosten (Prognosestudie) |
| Robustheit | TEILWEISE | Jahresregel in S40, leave-one-year-out in S34; Schwellen ±25 % und Ablation laut Plan Abschn. 8.7 nicht für Gamma/Fusion gerechnet |
| Holdout gesperrt | VORHANDEN | siehe Abschn. 3 |
| Gamma-Studie mit Daten | FEHLT | nur 04.11. bis heute eigene Aufzeichnung; Plan Abschn. 8: kleine Effekte "nicht prüfbar" |

## 6. Priorisierte Offline-Forschungsaufgaben

Alle ohne Orders, ohne Produktions- oder Mac-Dienständerung, ohne Holdout 2025. Reihenfolge nach Nutzen für G1/G2/G5.

1. **A1: Live-Lücken A/B/C in main klären (Merge-Reihenfolge, Rebase).** Ziel: dass Orderflow-Seite UNKNOWN und PIT-Vertrag auf main liegen, bevor weitere Live-Auswertung Daten für Studien liefert. Daten: keine, nur Code/Tests. Prüfbefehl: `pytest tests/test_orderflow_live_state.py tests/test_perp_flow.py tests/test_pit_contract.py tests/test_gamma_zones.py -q` auf dem gemergten Stand. Abhängigkeit: Branches `-b`, `-a`, `-c` (Reihenfolge b, a, c; `-integ-abe` als Prüfstand). Risiko: Branches haben ältere Basis (Verlust von S32-Dateien beim Merge, VERMUTUNG); ein Review pro Paket vorher.
2. **A2: Property-Tests für G1 (Seite, Delta/CVD-Invarianten, Zukunftspermutation).** Ziel: Lücke "Property-Tests FEHLT" schließen: `delta = buy - sell`, UNKNOWN verändert weder Delta noch CVD, Merkmal bei t unverändert bei Änderung der Daten nach t. Daten: synthetisch. Prüfbefehl: neuer Testlauf `pytest tests/test_orderflow_known_side_properties.py -q` (auf `-a` vorhanden, erst nach A1 sinnvoll). Abhängigkeit: A1, `hypothesis` als Abhängigkeit in `requirements*.txt` (Entscheidung nötig). Risiko: neue Abhängigkeit; sonst gering.
3. **A3: dvol_change-Zeitstempel belegen.** Ziel: Kerzenbeginn gegen Kerzenende der Deribit-Antwort anhand bereits aufgezeichneter Rohdateien (nur lesen) feststellen und `dvol_change` auf `ts + Auflösung <= t` umstellen oder freigeben. Daten: Recorder-Rohdateien `SUMMARY`/DVOL auf Kopie. Prüfbefehl: ein Test mit laufender gegen abgeschlossene Kerze (wie `-vol` V1 vorsieht) plus `pytest tests/test_research_lab_options_flow_features.py -q`. Abhängigkeit: Plan auf `-vol` (nur Planung). Risiko: Rohdaten nur am Mac; ohne sie bleibt es VERMUTUNG.
4. **A4: Gamma-Referenzrechnung und inverse/USDC-Kontrakte (G2).** Ziel: unabhängige Referenz (z. B. feste Zahlentabelle aus dokumentierter Formel, kein Netz) für Gamma, Delta-Prämienanpassung inverser Optionen und USDC-Kontraktgröße; `multiplier` im Snapshot-Parser. Daten: synthetische Kette `tests/fixtures/options_gamma/` (laut Plan). Prüfbefehl: `pytest tests/test_options_gamma.py tests/test_options_gamma_models.py -q`. Abhängigkeit: keine offenen PRs; `gex.py` bleibt unverändert (Planregel). Risiko: Deribit-Dokumentation nur ohne Netz nicht prüfbar, Annahmen als OFFEN markieren.
5. **A5: S40-Nacharbeit ohne neue Tests (T9-Auffälligkeit).** Ziel: Klären, ob A5 auf 1h die Optionsmerkmale wirklich nutzt (A1 und A5 gleicher IC auf vier Stellen). Daten: `s40_train.json` am Mac (nicht im Repo); Alternative: Test auf synthetischen Daten, dass A5 sich von A1 unterscheidet, wenn Optionsmerkmale vorhanden sind. Prüfbefehl: `pytest tests/test_s40.py -q` plus Diagnose ohne Neuberechnung des Urteils. Abhängigkeit: keine. Risiko: ein Fehler würde S40-Urteil nicht kippen (11 von 12 Tests IC kleiner), wohl aber die Aussagekraft von T9-T12; Änderung am eingefrorenen Code nur als neue Version.
6. **A6: Datenreife-Bericht für eigene Aufzeichnung (Gate G-A).** Ziel: Lücken (> 10 min), Duplikate, Uhrzeitversatz und OI-Datenalter je Recorder zählen, ohne Ergebnisse anzusehen. Daten: Kopien von `gamma_levels.jsonl`, Optionsflow-Dateien, Orderbuch-Archiv. Prüfbefehl: `python -m src.research_lab.fusion.datenreife ...` (CLI laut `test_fusion_scaffold.py:37`, genaue Argumente prüfen). Abhängigkeit: Zugriff auf Mac-Kopien durch die Eigentümer. Risiko: Zahlen aktuell unbekannt; Ergebnis kann "nicht prüfbar" lauten.
7. **A7: S41 vorbereiten und überwachen (nur lesend).** Ziel: Zähler gegen die Schwelle 30 Ereignisse und die Frist 120 Tage führen; keine Regeländerung. Daten: `data/options/gamma_levels.jsonl`. Prüfbefehl: `python -m src.research_lab.forward.gamma_callwall --log data/options/gamma_levels.jsonl` plus `pytest tests/test_research_forward_gamma_callwall.py -q`. Abhängigkeit: Paket C (Frische), sonst zählen veraltete Gamma-Stände. Risiko: Ereignisse klumpen; nur 6 Tests.
8. **A8: S42/S43/S44 Einordnung nach Merge.** Ziel: S42/S43 (eingefroren) und S44 (Entwurf) in Studienregister und `EVIDENZMATRIX` (Familie, Mehrfachtest-Zähler für Deflated Sharpe) eintragen. Daten: Branch `efoijz`. Prüfbefehl: `pytest tests/test_research_lab_s44.py -q` (auf dem Branch). Abhängigkeit: PR #398 (Chris, offen). Risiko: gleiche 55 Tage mehrfach genutzt (laut S42/S43-Text), Familie "nicht unabhängig".

Nicht empfohlen: weitere Orderflow-Richtungsstudien auf 1-4 h (S40, S35a, S39 stützen dies nicht), Datenkauf, Holdout-Freigabe, jede Handelsnutzung.

## 7. Offene Unsicherheiten dieser Bestandsaufnahme
- Keine pytest-Läufe; Testzahlen sind Zeilenzählungen.
- Gate-Texte G1/G2/G5 wurden gegen Issue #372 abgeglichen; PR #398 = Branch efoijz bestätigt.
- Studienurteile S32, OF2, OFX, S31 nur aus Sekundärangaben; Berichte nicht einzeln gelesen.
- Zustand der Recorder auf Mac/PS5 unbekannt.
