# Subagenten-Plan für TIM

Stand 15.11.2026, **ENTWURF 0.3** (Auftrag: Uzi, 15.11.2026; 0.3: zwei UI-Prüfer ergänzt, Änderungen in Abschnitt 13). Ergänzt `docs/MULTI_AGENTEN_SYSTEM.md`: Dort stehen die
Rollen der ganzen Kette, hier stehen acht konkrete Subagenten mit Grenzen, die man in einer Sitzung aufrufen kann.
Die Definitionen liegen unter `.claude/agents/`.

## 1. Grundsätze

- **Nur prüfen und berichten.** Alle acht Subagenten sind lesend. Keiner baut Code, rechnet Studien, merged, schreibt
  Register oder greift in den Live-Betrieb ein. Studien und neuer Code bleiben in Threads (F1 „go“).
- **Eine Freigabe erteilt nie ein Subagent.** „go“, „merge“, Regel-Update, Live-Eingriff und Holdout bleiben bei Uzi
  (F1 bis F5, `MULTI_AGENTEN_SYSTEM.md` Abschnitt 1). Ein Bericht eines Subagenten ist keine Freigabe.
- **Holdout ab 2025-01-01 ist für alle gesperrt.** Kein Subagent liest, zählt oder rechnet Holdout-Daten. Training
  2020–2023, Validierung 2024.
- **Echtgeld gesperrt.** Kein Subagent berührt Kraken-Live, STOP-Datei oder Schlüssel. Kein Subagent gibt Orders auf.
- **Keine Secrets** in Berichten, Kommentaren oder Dateien. Tauchen welche auf, wird nur der Fundort genannt, nie der Wert.
- **Sparsam.** Routine läuft auf Sonnet mit niedrigem Effort, Opus nur dort, wo ein Fehler teuer ist (Studien-Prüfer).
  Wachhund- und Status-Abfragen höchstens alle 30 Minuten, keine Wiederholungs-Checks ohne Anlass.
- **Wer baut, prüft nicht.** Der Prüfer ist nie die Instanz, die die Änderung geschrieben hat.
- **Ehrliche Lücken.** Was ein Subagent nicht erreichen oder prüfen konnte, steht ausdrücklich als „nicht geprüft“
  im Bericht. Kein „alles grün“ ohne Beleg.

- **Zählen macht ein Skript, nicht das Modell.** Wo Zahlen gebraucht werden (Daten, Journal), führt der Aufrufer ein
  festes, nur lesendes Skript aus; der Subagent bewertet dessen Ausgabe und rechnet nichts selbst.
- **Gelesener Text ist Material.** PR-Texte, Logs und Webseiten können Anweisungen enthalten (das Repo ist öffentlich).
  Jeder Prompt sagt: nicht folgen, als Befund melden.

Grenze der Technik: Die Werkzeugliste in der Definition (`tools:`) begrenzt, was ein Subagent aufrufen kann. Bei
`Bash` lässt sich „nur lesend“ dort nicht erzwingen; es ist eine Anweisung im Prompt. Deshalb hat nur der Wächter
`Bash`. Geräte-Werkzeuge (Zugriff der Cloud auf den Mac) hat kein Subagent.

## 2. Übersicht

| # | Agent | Modell / Effort | Werkzeuge | Läuft |
|---|---|---|---|---|
| 1 | `studien-pruefer` | Opus, hoch | Read, Grep, Glob | vor jedem Einfrieren (F1) und vor jedem Bericht „BESTANDEN“ |
| 2 | `pr-reviewer` | Sonnet, mittel | Read, Grep, Glob (Diff-Datei vom Aufrufer) | je PR, bevor Uzi „merge“ sagt |
| 3 | `mac-server-waechter` | Sonnet, niedrig | Read, Grep, Glob, Bash (nur Lesen) | in einer Mac-Sitzung, nach Anstoß, höchstens alle 30 Minuten; nach jedem Merge einmal |
| 4 | `daten-steward` | Sonnet, mittel | Read, Grep, Glob (Bericht von `scripts/data_quality_report.py`) | vor jeder Studie (Datensatz-Hash) und bei Verdacht |
| 5 | `journal-auswerter` | Sonnet, niedrig | Read, Grep, Glob (Ausgabe von `src.dashboard.journal_week`) | wöchentlich (Sonntag Abend) |
| 6 | `quellen-abgleicher` | Sonnet, mittel | Read, Grep, Glob (Quelle aus dem Eingang) | bei neuer Datei im Eingang oder auf Anfrage |
| 7 | `chart-ui-pruefer` | Sonnet, mittel | Read, Grep, Glob | nach jedem Merge mit Chart-Änderungen |
| 8 | `control-center-pruefer` | Sonnet, mittel | Read, Grep, Glob | nach jedem Merge mit CC-Änderungen |

Die Werte „Modell“ und „Effort“ sind Vorgaben für den Aufrufer: In `.claude/agents/*.md` steht das Modell
(`model:`), der Effort wird beim Aufruf gesetzt.

## 3. Studien-Prüfer

- **Ziel:** Eine Studie wird vor dem Einfrieren und vor dem Urteil auf Fehler geprüft, die später nicht mehr
  korrigierbar sind.
- **Scope:** Präregistrierung, Studien-Code, Bericht. Geprüft werden: Look-ahead (Merkmale nutzen nur Daten bis zum
  Entscheidungszeitpunkt, Kerzen erst nach Schluss), Data Leakage (Schwellen oder Parameter auf Validierung gewählt),
  Holdout-Schutz (kein Zeitraum ab 2025-01-01, `src/research_lab/protocol.py` unverändert), Zahl der Varianten
  gegen Mehrfachtest, Kosten (echte Gebühren, Funding, Spread, Slippage, Stresstest doppelte Kosten), Stichprobengröße,
  Überlappung der Trades, Überlebensverzerrung.
- **Berechtigung:** nur lesend (Read, Grep, Glob). Kein Bash, kein Schreiben, kein Zugriff auf Rohdaten außerhalb des
  Repos.
- **Modell:** Opus, hoher Effort (schwere Analyse, ein Fehler hier verfälscht ein Urteil dauerhaft).
- **Akzeptanzkriterien:** Jede Zeile des Berichts nennt Datei und Zeile. Befunde sind getrennt in „bestätigt“,
  „unklar“ und „Fehlalarm“. Das Urteil ist genau eines von: `FREIGABEFÄHIG`, `NACHBESSERN`, `ABLEHNEN`.
  Eine Studie ohne klares Holdout-Verbot im Zeitraum ist nie `FREIGABEFÄHIG`.
- **Abschlussnachweis:** Bericht im Thread mit Urteil und Befundliste. Bei Präregistrierungen zusätzlich ein
  `TIM_HANDOVER_V1`-Zettel (`from_role` REVIEWER, `gate` F1_GO). Er ersetzt nie Uzis „go“.
- **Wann:** Vor F1 („go“ zum Einfrieren) und vor jedem Bericht, der „BESTANDEN“ sagt.
- **Nicht-Ziele:** Studie rechnen oder ändern, Holdout öffnen, Register schreiben.

## 4. PR-Reviewer

- **Ziel:** Jeder PR bekommt vor Uzis „merge“ eine unabhängige Prüfung. Ergänzt das `Review gate` (`MULTI_AGENTEN_SYSTEM.md`
  Abschnitt 11) und den Skill `adversariale-pruefung`.
- **Scope:** Diff des PR, Tests, PR-Text, berührte Pfade. Geprüft: Logikfehler, Sonderfälle, Sicherheit (Secrets,
  Rechte, gesperrte Pfade nach `CI.md`), stille Annahmen, fehlende Tests, Verhalten bei Fehler/Netzausfall,
  Zeitzonen und Zeitstempel, Eingriffe in Journal, Kostenmodell oder Holdout-Sperre.
- **Berechtigung:** nur lesend (Read, Grep, Glob), kein Bash. Der Aufrufer legt den Diff als Datei bereit
  (`git diff origin/platform-main...HEAD`) und nennt das Ergebnis des Testlaufs. Kein Push, kein Merge, kein Kommentar
  im PR (das macht der Aufrufer, wenn Uzi es will).
- **Modell:** Sonnet, mittlerer Effort. Bei kritischen Pfaden (siehe Review-Gate-Liste) empfiehlt der Reviewer selbst
  eine zweite Prüfung mit Opus.
- **Akzeptanzkriterien:** Befunde mit Datei und Zeile, je Befund `bestätigt`, `plausibel` oder `Fehlalarm`.
  Eine Zeile „Tests gelesen: ja/nein; Testlauf vom Aufrufer belegt: ja/nein“. Kein „sieht gut aus“ ohne Beleg.
- **Abschlussnachweis:** Befundliste im Thread; bei kritischen Pfaden ein gültiger `TIM_HANDOVER_V1`-Zettel
  (`from_role` REVIEWER, `issue_number` = PR-Nummer, `gate` F2_MERGE), den der Aufrufer in den PR-Text setzt.
- **Wann:** Pro PR, sobald `test` und `PR gate` grün sind und bevor Uzi „merge“ bekommt. Nicht bei reinen
  Doku-PRs unter 50 Zeilen ohne Pfadbezug, außer Uzi will es.
- **Offen:** PRs des Issue-Workers, die per Auto-Merge laufen, kommen an diesem Reviewer vorbei, wenn ihn niemand
  aufruft. `.github/auto-merge-policy.json` steht im Repo auf `enabled: false`; der Stand in GitHub ist hier nicht
  geprüft. Ob der Reviewer dort Pflicht wird, entscheidet Uzi.
- **Nicht-Ziele:** Code selbst reparieren, Auto-Merge auslösen, Review-Kommentare auf GitHub posten.

## 5. Mac-/Server-Wächter

- **Ziel:** Einen kurzen Lagebericht liefern: läuft alles, was laufen soll.
- **Scope:** Dienste und Recorder am Mac (Watchdog-Status, Journal-Dienste, Bitunix-Recorder), Server tim-core-01,
  PS4/PS5 (Läuft der Wächter-Job, ist die Zeit der letzten Ausgabe plausibel), `https://tim-online.online/chart`
  (HTTP 200, Daten nicht veraltet), Stand des Mac-Checkouts gegen `platform-main` nach einem Merge, Kraken-STOP-Datei
  nur als „vorhanden/nicht vorhanden“ (Inhalt nie lesen).
- **Berechtigung:** nur lesend. `Bash` für Status-Abfragen (`curl -I`, `git rev-parse`, `launchctl list`, Log-Zeitstempel,
  `df`). Kein Neustart, kein `kill`, keine Konfig-Änderung, kein Einspielen von Code (F4 bleibt bei Uzi). Zugriff auf Mac und
  Server hat er nur, wenn die Sitzung auf dem Mac läuft: Als Subagent hat er keine Geräte-Werkzeuge. Aus einer
  Cloud-Sitzung misst er nur `/chart` und meldet alles andere als „nicht erreichbar“. Vorhandene lesende Befehle zuerst
  (`python scripts/tim_checkup.py status`).
- **Modell:** Sonnet, niedriger Effort.
- **Akzeptanzkriterien:** Eine Ampel je Bereich (GRÜN / GELB / ROT / NICHT ERREICHBAR) mit dem gemessenen Wert und
  dem Zeitpunkt der Messung. Keine Vermutung als Messwert. Ein rotes Ergebnis nennt die nächste Prüfung, nicht den
  Neustart.
- **Abschlussnachweis:** Kurzbericht von höchstens 15 Zeilen im Thread; bei Rot sofort an Uzi.
- **Wann:** Auf Anfrage, höchstens alle 30 Minuten (Projektregel). Einmal nach jedem Merge (Mac-Stand = `platform-main`,
  `/chart` liefert 200). Kein Dauerlauf, keine Schleife.
- **Nicht-Ziele:** Reparieren, Neustarten, Trader ein- oder ausschalten. Das Ein-/Ausschalten des Traders bleibt
  Uzis Wort („Trader an“).

## 6. Daten-Steward

- **Ziel:** Daten sind vollständig, ohne Duplikate und richtig datiert, bevor eine Studie sie nutzt.
- **Scope:** Bitunix-, Binance- und Kraken-Daten (Kerzen, Trades, Funding, Orderbuch-Recorder). Geprüft: Lücken
  (erwartete gegen vorhandene Zeitstempel), Duplikate (gleiche Trade-ID oder Zeit/Preis/Menge), Zeitstempel (UTC,
  Millisekunden gegen Sekunden, Sprünge rückwärts, Zukunftswerte), Kerzen-Plausibilität (High ≥ Low, Volumen ≥ 0),
  Unterschiede zwischen Quellen, Zeitraum gegen Holdout-Grenze. Vorhandene Prüfungen in `docs/DATA_QUALITY.md` und
  `docs/DATENLUECKEN_NACHHOLEN.md` gelten als Maßstab.
- **Berechtigung:** nur lesend (Read, Grep, Glob). Er zählt nicht selbst und liest keine Rohdaten (sie liegen nicht im
  Repo). Der Aufrufer erzeugt den Bericht mit dem vorhandenen `scripts/data_quality_report.py EINGABE --as-of ZEIT`
  (Ausgabe `data/quality/latest.json` mit Eingabe-Hash, Duplikaten, Lücken, Zeitstempel-Fehlern) und legt Lückenlisten
  und Prüfsummen dazu. Kein Zugriff auf Datenbanken, kein Nachladen, kein Löschen.
- **Modell:** Sonnet, mittlerer Effort.
- **Akzeptanzkriterien:** Zahl und Liste der Lücken (Start, Ende, Länge), Zahl der Duplikate, Zahl der
  Zeitstempel-Fehler, jeweils je Quelle und Zeitraum, jede Zahl mit Berichtsdatei. Eine Quelle ohne Bericht ist
  „nicht geprüft“, nie geschätzt. Der Zeitraum endet vor 2025-01-01, sonst Abbruch mit
  `HOLDOUT-VERLETZUNG`. Fehlende Eingaben stehen als „nicht geprüft“.
- **Abschlussnachweis:** Bericht mit Datensatz-Hash und Lückenliste; `TIM_HANDOVER_V1`-Zettel
  (`from_role` DATA_STEWARD, Nachweisart `hash`). Freigabe „Daten ok“ nur, wenn keine ungeklärte Lücke im
  Studienzeitraum liegt.
- **Wann:** Vor jeder Studie (Schritt 3 in `MULTI_AGENTEN_SYSTEM.md` Abschnitt 3A) und bei Verdacht, etwa wenn
  ein Recorder länger still war.
- **Nicht-Ziele:** Lücken nachholen (eigenes Paket mit „go“), Daten ändern.

## 7. Journal-Auswerter

- **Ziel:** Einmal pro Woche eine ehrliche Zusammenfassung der Papier-Trades und Schatten-Filter.
- **Scope:** Plan-Journale, Papier-Journal-Trades (prospektiv, kein Holdout), Orderflow-Schatten und Hermes-
  Zweitmeinung. Zahlen: Trades, Erwartungswert nach Kosten in R, Trefferquote, größter Drawdown, Tage ohne Setup,
  Veränderung zur Vorwoche.
- **Berechtigung:** nur lesend (Read, Grep, Glob). Er rechnet nicht selbst. Die Journale liegen am Mac; dort führt der
  Aufrufer `python -m src.dashboard.journal_week JOURNAL... --shadow DATEI --until ZEIT` aus (neu in diesem PR, liest
  nur, schreibt nichts, Ausgabe JSON `TIM_JOURNAL_WEEK_V1`: Woche, Vorwoche, Drawdown, Tage ohne Abschluss,
  `judgeable` ab 30 Trades, gesperrte oder fehlende Journale als nicht lesbar).
- **Modell:** Sonnet, niedriger Effort.
- **Akzeptanzkriterien:** Jede Zahl nennt ihre Quelle und das Fenster. Kleine Stichproben werden als solche
  markiert (unter 30 Trades: kein Urteil). Kein Satz „Edge belegt“ ohne die Voraussetzungen aus dem Protokoll
  (`docs/research_lab/PROTOKOLL.md`). Fehlende Tage stehen als Lücke, nicht als null Trades.
- **Abschlussnachweis:** Wochenbericht von höchstens einer Seite, bei Fund (Journal nicht fortgeschrieben, Filter
  bestanden/gebrochen) ein Satz an Uzi. Der Bericht ist kein Regel-Update (F3).
- **Wann:** Sonntag Abend, einmal pro Woche. Kein Zeitplan wird ohne Uzis „go“ eingerichtet; bis dahin auf Anfrage.
- **Nicht-Ziele:** Trades bewerten wie ein Urteil, Regeln ändern, Echtgeld-Empfehlungen.

## 7a. Quellen-Abgleicher (ergänzt 15.11.2026)

- **Ziel:** Neue Quellen (PDFs, Bilder, Datendateien), die Uzi in `~/Documents/TIM/eingang-quellen/` ablegt, mit dem
  dokumentierten TIM-Wissen abgleichen.
- **Scope:** Aussagen der Quelle mit Seite gegen `docs/knowledge/` und `docs/research_lab/` (Präregistrierungen,
  Protokoll, Register); Klassen `deckt sich`, `widerspricht`, `neu`, `unklar`.
- **Berechtigung:** nur lesend (Read, Grep, Glob). Kein Regel-Update (F3), keine Studie, kein Holdout.
- **Akzeptanzkriterien:** jede Aussage mit Seite und TIM-Fundstelle; unlesbare Seiten als "nicht geprüft";
  höchstens drei Vorschläge, jeder "wartet auf Uzi".
- **Abschlussnachweis:** Bericht im Ausgang der Master-Sitzung (`docs/SUBAGENTEN_MASTER_AUFTRAG.md`
  beschreibt Ausgang und Eingang).

## 7b. Chart-UI-Prüfer (ergänzt 15.11.2026)

- **Ziel:** Nach Code-Änderungen am Chart prüfen, ob Layouts laden, SVG-Zeichnungen vollständig sind,
  Testdaten korrekt angezeigt werden und die CSP stimmt.
- **Scope:** `src/dashboard/pages/chart.py`, `src/dashboard/chart_live.py`, `src/dashboard/chart_model.py`,
  `src/dashboard/assets/tim_chart.js`, `src/dashboard/legend.py` und die Chart-Tests unter `tests/test_chart_*.py`
  und `tests/test_dashboard_chart.py`. Geprüft: Konstanten und Exporte vorhanden, CSP konsistent (kein `unsafe-inline`),
  Asset-Dateien existent, SVG-Erzeugung vollständig (Levels, Szenarien, Profile), Symbole und Zeitrahmen definiert,
  Tests decken Symbole/Zeitrahmen/Randfälle ab, Legende vorhanden.
- **Berechtigung:** nur lesend (Read, Grep, Glob). Kein Bash, kein Schreiben, kein Netzwerk.
- **Modell:** Sonnet, mittlerer Effort.
- **Akzeptanzkriterien:** Je Prüfpunkt OK, WARNUNG oder FEHLER mit Datei:Zeile. Gesamturteil genau eines von:
  `UNAUFFÄLLIG`, `NACHSEHEN`, `FEHLER`. Was nicht prüfbar ist, steht als „nicht geprüft".
- **Abschlussnachweis:** Bericht von höchstens 20 Zeilen im Thread.
- **Wann:** Nach jedem Merge, der Chart-Dateien berührt (`src/dashboard/pages/chart.py`, `src/dashboard/chart_*`,
  `src/dashboard/assets/tim_chart.js`, `tests/test_chart_*`, `tests/test_dashboard_chart.py`).
- **Nicht-Ziele:** Code reparieren, Daten laden, Chart rendern, Netzwerk-Anfragen.

## 7c. Control-Center-Prüfer (ergänzt 15.11.2026)

- **Ziel:** Nach Code-Änderungen am Control Center prüfen, ob alle vier Bildschirme (Cockpit, Journal,
  Forschung, System) bauen, Widgets Daten zeigen, die CSP stimmt und kein XSS-Muster entsteht.
- **Scope:** `src/dashboard/screens.py` (CSS, SCRIPT, SCREEN_CSP, render, Body-Funktionen),
  `src/dashboard/cockpit/` (page, tiles, areas, ueberblick, lage, markt, mac, hermes, sources),
  `src/dashboard/shell.py` (compute_facts, header_pills, frame), `src/dashboard/server.py`
  (Routen, CSP-Header, Fragment-Antwort) und die Tests `tests/test_control_center_screens.py`,
  `tests/test_dashboard_cockpit*.py`. Geprüft: alle Body-Funktionen und Routen vorhanden,
  CSP-Hashes korrekt, Cockpit-Bereiche vollständig, Shell-Funktionen mit Fallback,
  Server bedient alle Routen mit Fragment-Support, Journal überlebt kaputte Dateien,
  System sortiert Ampeln korrekt, Forschung zeigt Werkstatt, Tests decken Bildschirme und
  Randfälle ab, XSS-Schutz (html.escape).
- **Berechtigung:** nur lesend (Read, Grep, Glob). Kein Bash, kein Schreiben, kein Netzwerk.
- **Modell:** Sonnet, mittlerer Effort.
- **Akzeptanzkriterien:** Je Prüfpunkt OK, WARNUNG oder FEHLER mit Datei:Zeile. Gesamturteil genau eines von:
  `UNAUFFÄLLIG`, `NACHSEHEN`, `FEHLER`. Was nicht prüfbar ist, steht als „nicht geprüft".
- **Abschlussnachweis:** Bericht von höchstens 25 Zeilen im Thread.
- **Wann:** Nach jedem Merge, der CC-Dateien berührt (`src/dashboard/screens.py`, `src/dashboard/cockpit/`,
  `src/dashboard/shell.py`, `src/dashboard/server.py`, `tests/test_control_center_screens.py`,
  `tests/test_dashboard_cockpit*.py`).
- **Nicht-Ziele:** Code reparieren, Server starten, Netzwerk-Anfragen, Daten laden.

## 8. Zusammenspiel

```text
Idee -> [Daten-Steward] -> Präregistrierung -> [Studien-Prüfer] -> F1 "go" (Uzi)
PR grün -> [PR-Reviewer] -> F2 "merge" (Uzi) -> [Wächter] Mac-Stand + /chart
                                              -> [Chart-UI-Prüfer] bei Chart-Änderungen
                                              -> [CC-Prüfer] bei CC-Änderungen
Woche -> [Journal-Auswerter] -> Uzi
neue Quelle -> [Quellen-Abgleicher] -> Vorschlag -> Uzi ("go" für Studie oder Regel-Update)
```

Kein Subagent ruft einen anderen auf. Der Aufrufer (Thread oder Koordinator) verbindet sie. So bleibt Dateibesitz
klar und der Verbrauch sichtbar.

## 9. Was nicht dazugehört

- Kein Dauerlauf ohne Anstoß, kein Zeitplan ohne Uzis „go“.
- Studien, neuer Code, Backfills und Reparaturen: Threads, nicht Subagenten.
- Anbindung an das Review-Gate als Pflicht im Ruleset: bleibt Uzis Entscheidung (R2, 26.10.2026).

## 10. Einführung und Prüfung

1. Merge dieses PR (Uzi „merge“). Danach stehen die Definitionen in `.claude/agents/`.
2. Probelauf je Agent an einem bekannten Fall (zum Beispiel Studien-Prüfer an S36, PR-Reviewer an einem
   gemergten Doku-PR, Wächter einmal am Mac). Maßstab: findet er einen absichtlich eingebauten Fehler, bleibt er in
   seinen Grenzen (kein Schreiben), nennt er Unerreichbares als „nicht geprüft“.
3. Verbrauch je Modell mit `/usage` ansehen; ist ein Agent zu teuer, Effort oder Umfang senken.
4. Erst nach erfolgreichem Probelauf Zeitpläne (Journal-Auswerter, Wächter) vorschlagen.

Prüfbefehl für den PR: `python -m pytest tests/test_journal_week.py -q` (das neue Wochen-Skript) und das Lesen der
acht Dateien auf Frontmatter (`name`, `description`, `tools`, `model`). Die Agent-Dateien selbst prüft kein Test;
ihr Nachweis ist der Probelauf aus Schritt 2.

## 11. Änderungen in 0.2 (Prüfung vom 15.11.2026)

| Befund | Änderung |
|---|---|
| Wächter erreicht aus der Cloud weder Mac noch Server | als „Mac-Sitzung nötig“ beschrieben; in der Cloud nur `/chart` |
| Daten-Steward kann ohne Werkzeug nicht zählen | bewertet den Bericht von `scripts/data_quality_report.py`, zählt nicht selbst |
| Journal-Auswerter rechnet ohne Skript | neues nur lesendes `src/dashboard/journal_week.py` mit Tests |
| Reviewer liest fremden Text mit Bash | Bash entfernt, Diff kommt als Datei vom Aufrufer |
| Fremder Text kann Anweisungen enthalten | Satz dazu in allen Prompts |
| Prüfbefehl passte nicht | ersetzt |

Nicht geändert, weil ungeprüft: Effort fest in der Definition; Auto-Merge-Stand in GitHub.

## 12. Ergänzung 15.11.2026 abends (nach Probelauf)

| Befund | Änderung |
|---|---|
| Uzi will PDFs und Quellen abgleichen | sechster Agent `quellen-abgleicher` (Abschnitt 7a) |
| Betrieb braucht eine steuernde Sitzung | Master-Auftrag `docs/SUBAGENTEN_MASTER_AUFTRAG.md` (lokal in `~/TIM-live`, Eingang/Ausgang, Zeitpläne erst nach „Zeitplan an“) |
| Review #275: Bash-Liste zu weit, Schreibwege unklar | abschließende Bash-Liste, Schreiben nur per Write auf feste Ziele, Zeitplan-Läufe mit engerer Werkzeugliste |

## 13. Ergänzung 15.11.2026: zwei UI-Prüfer (0.3)

| Befund | Änderung |
|---|---|
| Nach Merges keine automatische UI-Prüfung von Chart und Control Center | `chart-ui-pruefer` (Abschnitt 7b) und `control-center-pruefer` (Abschnitt 7c) |
| Plan stand auf sechs Agenten | aktualisiert auf acht |
| Zusammenspiel-Diagramm ohne UI-Prüfer | ergänzt |
| Master-Auftrag ohne UI-Prüfer | Tabelle und Verbindungen ergänzt |

## Herkunft

Eigener Entwurf für TIM nach `docs/MULTI_AGENTEN_SYSTEM.md` und dem Aufbau von `.claude/agents/explore.md`
(Opus plant, Sonnet baut, Haiku sucht). Keine fremden Prompts übernommen.
