# Subagenten-Plan für TIM

Stand 15.11.2026, **ENTWURF 0.1** (Auftrag: Uzi, 15.11.2026). Ergänzt `docs/MULTI_AGENTEN_SYSTEM.md`: Dort stehen die
Rollen der ganzen Kette, hier stehen fünf konkrete Subagenten mit Grenzen, die man in einer Sitzung aufrufen kann.
Die Definitionen liegen unter `.claude/agents/`.

## 1. Grundsätze

- **Nur prüfen und berichten.** Alle fünf Subagenten sind lesend. Keiner baut Code, rechnet Studien, merged, schreibt
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

Grenze der Technik: Die Werkzeugliste in der Definition (`tools:`) begrenzt, was ein Subagent aufrufen kann. Bei
`Bash` lässt sich „nur lesend“ dort nicht erzwingen; es ist eine Anweisung im Prompt. Deshalb haben nur Reviewer und
Wächter `Bash`, der Studien-Prüfer, Daten-Steward und Journal-Auswerter nicht.

## 2. Übersicht

| # | Agent | Modell / Effort | Werkzeuge | Läuft |
|---|---|---|---|---|
| 1 | `studien-pruefer` | Opus, hoch | Read, Grep, Glob | vor jedem Einfrieren (F1) und vor jedem Bericht „BESTANDEN“ |
| 2 | `pr-reviewer` | Sonnet, mittel | Read, Grep, Glob, Bash (nur `git`/`gh`-Lesen) | je PR, bevor Uzi „merge“ sagt |
| 3 | `mac-server-waechter` | Sonnet, niedrig | Read, Grep, Glob, Bash (nur Lesen) | nach Anstoß, höchstens alle 30 Minuten; nach jedem Merge einmal |
| 4 | `daten-steward` | Sonnet, mittel | Read, Grep, Glob | vor jeder Studie (Datensatz-Hash) und bei Verdacht |
| 5 | `journal-auswerter` | Sonnet, niedrig | Read, Grep, Glob | wöchentlich (Sonntag Abend) |

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
- **Berechtigung:** lesend. `Bash` nur für `git diff`, `git log`, `git show` und lesende `gh`-Aufrufe. Kein Push,
  kein Merge, kein Kommentar im PR (das macht der Aufrufer, wenn Uzi es will).
- **Modell:** Sonnet, mittlerer Effort. Bei kritischen Pfaden (siehe Review-Gate-Liste) empfiehlt der Reviewer selbst
  eine zweite Prüfung mit Opus.
- **Akzeptanzkriterien:** Befunde mit Datei und Zeile, je Befund `bestätigt`, `plausibel` oder `Fehlalarm`.
  Eine Zeile „Tests gelesen: ja/nein, ausgeführt: ja/nein“. Kein „sieht gut aus“ ohne Beleg.
- **Abschlussnachweis:** Befundliste im Thread; bei kritischen Pfaden ein gültiger `TIM_HANDOVER_V1`-Zettel
  (`from_role` REVIEWER, `issue_number` = PR-Nummer, `gate` F2_MERGE), den der Aufrufer in den PR-Text setzt.
- **Wann:** Pro PR, sobald `test` und `PR gate` grün sind und bevor Uzi „merge“ bekommt. Nicht bei reinen
  Doku-PRs unter 50 Zeilen ohne Pfadbezug, außer Uzi will es.
- **Nicht-Ziele:** Code selbst reparieren, Auto-Merge auslösen, Review-Kommentare auf GitHub posten.

## 5. Mac-/Server-Wächter

- **Ziel:** Einen kurzen Lagebericht liefern: läuft alles, was laufen soll.
- **Scope:** Dienste und Recorder am Mac (Watchdog-Status, Journal-Dienste, Bitunix-Recorder), Server tim-core-01,
  PS4/PS5 (Läuft der Wächter-Job, ist die Zeit der letzten Ausgabe plausibel), `https://tim-online.online/chart`
  (HTTP 200, Daten nicht veraltet), Stand des Mac-Checkouts gegen `platform-main` nach einem Merge, Kraken-STOP-Datei
  nur als „vorhanden/nicht vorhanden“ (Inhalt nie lesen).
- **Berechtigung:** nur lesend. `Bash` für Status-Abfragen (`curl -I`, `git rev-parse`, `launchctl list`, Log-Zeitstempel,
  `df`). Kein Neustart, kein `kill`, keine Konfig-Änderung, kein Einspielen von Code (F4 bleibt bei Uzi). Zugriff auf Mac und
  Server nur über die schon freigegebenen Geräte-Werkzeuge; was die Sitzung nicht erreicht, steht als „nicht erreichbar“
  im Bericht.
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
- **Berechtigung:** nur lesend (Read, Grep, Glob) auf Repo-Dateien und bereitgestellte Prüfsummen und Lückenlisten.
  Kein Zugriff auf Datenbanken, kein Nachladen, kein Löschen.
- **Modell:** Sonnet, mittlerer Effort.
- **Akzeptanzkriterien:** Zahl und Liste der Lücken (Start, Ende, Länge), Zahl der Duplikate, Zahl der
  Zeitstempel-Fehler, jeweils je Quelle und Zeitraum. Der Zeitraum endet vor 2025-01-01, sonst Abbruch mit
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
- **Berechtigung:** nur lesend (Read, Grep, Glob) auf Journal-Dateien im Repo oder bereitgestellte Auszüge.
- **Modell:** Sonnet, niedriger Effort.
- **Akzeptanzkriterien:** Jede Zahl nennt ihre Quelle und das Fenster. Kleine Stichproben werden als solche
  markiert (unter 30 Trades: kein Urteil). Kein Satz „Edge belegt“ ohne die Voraussetzungen aus dem Protokoll
  (`docs/research_lab/PROTOKOLL.md`). Fehlende Tage stehen als Lücke, nicht als null Trades.
- **Abschlussnachweis:** Wochenbericht von höchstens einer Seite, bei Fund (Journal nicht fortgeschrieben, Filter
  bestanden/gebrochen) ein Satz an Uzi. Der Bericht ist kein Regel-Update (F3).
- **Wann:** Sonntag Abend, einmal pro Woche. Kein Zeitplan wird ohne Uzis „go“ eingerichtet; bis dahin auf Anfrage.
- **Nicht-Ziele:** Trades bewerten wie ein Urteil, Regeln ändern, Echtgeld-Empfehlungen.

## 8. Zusammenspiel

```text
Idee -> [Daten-Steward] -> Präregistrierung -> [Studien-Prüfer] -> F1 "go" (Uzi)
PR grün -> [PR-Reviewer] -> F2 "merge" (Uzi) -> [Wächter] Mac-Stand + /chart
Woche -> [Journal-Auswerter] -> Uzi
```

Kein Subagent ruft einen anderen auf. Der Aufrufer (Thread oder Koordinator) verbindet sie. So bleibt Dateibesitz
klar und der Verbrauch sichtbar.

## 9. Was nicht dazugehört

- Kein Dauerlauf ohne Anstoß, kein Zeitplan ohne Uzis „go“.
- Studien, neuer Code, Backfills und Reparaturen: Threads, nicht Subagenten.
- Anbindung an das Review-Gate als Pflicht im Ruleset: bleibt Uzis Entscheidung (R2, 26.10.2026).

## 10. Einführung und Prüfung

1. Merge dieses PR (Uzi „merge“). Danach stehen die fünf Definitionen in `.claude/agents/`.
2. Probelauf je Agent an einem bekannten Fall (zum Beispiel Studien-Prüfer an S36, PR-Reviewer an einem
   gemergten Doku-PR, Wächter einmal am Mac). Maßstab: findet er einen absichtlich eingebauten Fehler, bleibt er in
   seinen Grenzen (kein Schreiben), nennt er Unerreichbares als „nicht geprüft“.
3. Verbrauch je Modell mit `/usage` ansehen; ist ein Agent zu teuer, Effort oder Umfang senken.
4. Erst nach erfolgreichem Probelauf Zeitpläne (Journal-Auswerter, Wächter) vorschlagen.

Prüfbefehl für den PR: `python -m pytest tests/agents -q` (Doku und Agent-Dateien ändern keinen Code) und das Lesen der
fünf Dateien auf Frontmatter (`name`, `description`, `tools`, `model`).

## Herkunft

Eigener Entwurf für TIM nach `docs/MULTI_AGENTEN_SYSTEM.md` und dem Aufbau von `.claude/agents/explore.md`
(Opus plant, Sonnet baut, Haiku sucht). Keine fremden Prompts übernommen.
