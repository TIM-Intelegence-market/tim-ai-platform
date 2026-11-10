# Multi-Agenten-System für TIM (Entwurf)

Stand 10.11.2026, **ENTWURF 0.1**, nichts davon ist gebaut oder eingeschaltet. Auftrag: Uzi, „Go“ am 10.11.2026.
Grundlage ist der Stand in diesem Repo (`platform-main`, 496f0a4) und die Projektnotizen. Der laufende Zustand
auf Mac, Server und PS5 wurde für diesen Entwurf **nicht** neu gemessen; wo ein Stand nur aus Notizen stammt,
steht „ungeprüft“ dabei.

Ziel: Eine Aufgabe läuft von der Idee bis zum fertigen Ergebnis durch, ohne dass Uzi eingreift. Er wird nur an
den festen Freigabepunkten gebraucht, oder wenn das System abbricht und meldet.

## 1. Feste Regeln (kein Agent ändert sie)

| Regel | Durchgesetzt durch |
|---|---|
| „go“ = bauen, „merge“ = mergen, beides nur von Uzi | Ruleset `platform-main`, Worker ohne Merge-Recht (`CI.md`) |
| Echtgeld nur im Kraken-Test mit seinen Limits | Live-Code liegt außerhalb des Repos, Limits und STOP-Datei dort |
| Holdout ab 2025-01-01 gesperrt | `src/research_lab/protocol.py`, Lernregister weist ab |
| Keine Keys oder Passwörter in Chat, Repo, Logs | Schlüsselbund, Redaktion in `src/tim_incident/`, Secret-Scanning |
| Studie wird vor dem Lauf eingefroren, Training vor Validierung, echte Gebühren | `docs/research_lab/PROTOKOLL.md`, `REGISTER.jsonl` (Hash-Kette) |
| Worker ändern keine gesperrten Pfade | `PR gate` (fail-closed) |

Freigabepunkte, an denen das System immer anhält:

- **F1 „go“**: Bauauftrag oder Studie (Präregistrierung wird damit eingefroren).
- **F2 „merge“**: jeder PR.
- **F3 Regel-Update**: bestandene Studie oder Filter wird Regel, nur per Karte nach prospektivem Test.
- **F4 Live-Eingriff**: Live-Code einspielen, Trader nach STOP wieder einschalten, Dienst-Konfiguration ändern.
- **F5 Holdout**: nur mit Uzis ausdrücklichem Wort.

## 2. Rollen

| Rolle | bekommt | entscheidet | gibt weiter | heute in TIM | Gerät |
|---|---|---|---|---|---|
| **PM** | Uzis Auftrag, Vorfall-Issue, Idee | Zerlegung in Pakete, Reihenfolge, wer dran ist, Abbruch | Issue mit Übergabezettel an die nächste Rolle | Koordinator im Projekt, Issues mit `status:*` (`docs/ISSUE_WORKFLOW.md`) | Cloud |
| **Researcher** | Idee, Journale, Schatten-Ergebnisse | Hypothese, Studien-Entwurf, Urteil BESTANDEN / NICHT BESTANDEN / KEIN URTEIL | Präregistrierung (an F1), danach Bericht mit Zahlen | Forschungswerkstatt `src/research_lab/workshop/` (Stufe 1), Studien S1–S20 | PS5 rechnet, Mac nur Live-Anteile |
| **Data Steward** | Datenbedarf der Studie, Sammler-Status | ob die Daten vollständig und sauber genug sind (sonst kein Lauf) | Datensatz-Hash, Lückenliste, Freigabe „Daten ok“ | Prüfsummen, Coverage-Dienste, `com.tim.data-issue-reporter` | Server (Kopie), Mac (Sammler) |
| **Engineer** | Issue mit Vertrag (erlaubte Pfade, Tests) | Umsetzung innerhalb des Vertrags | Branch und Draft-PR | Qwen-Worker am Mac (`TIM_QWEN_TASK_V1`), Issue-Pipeline Codex → Claude, Threads | Mac, Qwen 30B über Server |
| **Tester** | PR-Stand | grün oder rot, sonst nichts | Check-Ergebnis am Commit | `test` und `PR gate` auf Runner `mac-mini-tim`, volle Suite in der Cloud | Mac-Runner |
| **Reviewer** | grüner PR, Auftrag, Diff | bestätigte Fehler ja/nein (getrennt von Fehlalarmen) | Befundliste am PR | Skill `adversariale-pruefung`, `src/agents/review.py`; **kein Pflichtschritt** | Cloud |
| **DevOps** | Merge auf `platform-main`, Health-Daten | Nachziehen, Zurückrollen, Neustart im erlaubten Rahmen | Deploy-Stand, Health-Status | `com.tim.dashboard-refresh` (Nachzug mit Rollback), `com.tim.watchdog`, Checkup auf dem Server | Mac, Server |
| **Security** | jeder PR, jeder Vorfall | blockieren bei Secret, gesperrtem Pfad, Rechte-Ausweitung | Block mit Grund | `PR gate`, Secret-Scanning/CodeQL, Klasse SAFETY im Checkup | GitHub, Server |
| **Docs** | gemergter PR, Studienbericht | was in Systemstand und Logbuch gehört | aktualisierte Doku im selben oder nächsten PR | `docs/SYSTEMSTAND.md`, `LOGBUCH.json`, Projektnotizen | Cloud |
| **Hermes** (Beobachter, keine eigene Rolle) | Pläne, Orderflow-Lage, Status | nichts, schreibt nur Kommentar | Zweitmeinung je Plan, Tagesbericht 8 und 22 Uhr | `src/dashboard/plan_opinion.py`, `daily_report.py` | Mac |

Grundsatz: Wer baut, prüft nicht. Tester und Reviewer sind nie dieselbe Instanz wie der Engineer, und kein
Agent gibt sich selbst frei.

## 3. Zwei Durchläufe

### A. „Neue Orderflow-Strategie testen“

1. **PM** legt ein Issue an (Ziel, Abnahme, Grenzen).
2. **Researcher** schreibt die Präregistrierung: Frage, Daten, Kosten mit echten Gebühren, Schwellen, Zahl der Varianten.
3. **Data Steward** prüft Zeitraum und Lücken, liefert Datensatz-Hash. Reicht ein Zeitraum ins Holdout: Abbruch.
4. **F1**: Uzi sagt „go“. Die Studie wird im Register eingefroren.
5. **Engineer** baut den Studien-Code, **Tester** und **Reviewer** prüfen, **F2**: „merge“.
6. **Researcher** lässt auf der PS5 rechnen (Training, dann Validierung) und schreibt den Bericht.
7. Bestanden: 30 Tage Schattenbetrieb (prospektiv, jedes Fenster genau einmal). Nicht bestanden: Bericht, Ende.
8. **F3**: Erst nach bestandenem Schatten kommt eine Karte „Regel übernehmen ja/nein“. Übernahme läuft wieder über 5.
9. **Docs** trägt Ergebnis in Logbuch und Systemstand ein.

Uzi wird höchstens dreimal gebraucht: „go“, „merge“, Karte.

### B. „Fehler im Live-Betrieb beheben“

1. **DevOps** erkennt: Watchdog, Checkup oder roter `test` auf `platform-main` öffnen genau ein Issue je Ursache.
2. **PM** stuft ein: Daten/Anzeige (weiter mit 3) oder Echtgeld/Sicherheit (sofort Meldung an Uzi, kein Reparaturversuch).
3. **Engineer** stellt den Fehler nach (Test, der rot ist) und baut die Reparatur. Reparaturen gelten als von Uzi
   beauftragt, solange sie nur Daten, Anzeige und Tests betreffen; alles andere wartet auf **F1**.
4. **Tester**, **Reviewer**, **Security** wie in A.
5. **F2**: „merge“. **DevOps** zieht den Mac nach und prüft https://tim-online.online/chart.
6. Vorfall-Issue schließt erst, wenn die Ursache im Health-Status weg ist, nicht beim Merge.

## 4. Fehlerbehandlung

| Fehler | erkennt | repariert | Abbruch und Meldung an Uzi |
|---|---|---|---|
| Test rot im PR | Tester | Engineer | nach **2** Reparaturversuchen am selben Fehler: `status:blocked`, Meldung mit Log |
| Infrastruktur (Runner weg, Netz) | Tester | niemand, ein erneuter Lauf | zweiter Fehlschlag: Meldung, kein dritter Lauf |
| Reviewer findet bestätigten Fehler | Reviewer | Engineer | zweite Review-Runde mit bestätigtem Fehler: Meldung |
| Gesperrter Pfad, Secret im Diff | Security (`PR gate`) | niemand automatisch | sofort |
| Dienst steht | Watchdog | Watchdog (nur Neustart) | **3** Neustarts in 30 min ohne GREEN: keine weiteren Neustarts, Meldung |
| Deploy scheitert | Nachzug-Agent | rollt zurück | sofort, mit `timctl`-Grund |
| Datenlücke | Data Steward | Nachhol-Dienst | Lücke nach einem Nachhol-Lauf noch offen: Meldung; Studien auf dem Zeitraum ruhen |
| Echtgeld: Lesefehler, fremde Position | Live-Trader | niemand | STOP-Datei wie heute; wieder ein nur auf Uzis Wort (**F4**) |
| Holdout-Zugriff, gebrochene Hash-Kette | Register | niemand | sofort, Forschung fällt auf Stufe 0 (`FORSCHUNGSBEREICH.md`) |
| Agent überschreitet Budget oder Zeit | PM | niemand | sofort; Aufgabe wird nicht still neu gestartet |

Regeln dazu: Jeder Versuch wird am Issue gezählt, nicht im Kopf des Agenten. Ein Agent darf den Zähler nicht
zurücksetzen. Eine Meldung an Uzi enthält immer: was kaputt ist, was versucht wurde, Beleg, eine empfohlene
Entscheidung. Kein Test wird übersprungen oder abgeschaltet, um grün zu werden.

## 5. Selbstverbesserung

Das System lernt, indem es **Vorschläge** erzeugt. Regeln, Risikogrenzen und Kostenmodell ändert nur ein PR nach
Uzis Karte und „merge“.

| Quelle | was daraus wird | Sperre |
|---|---|---|
| Plan-Journale 15m/1h | F11 `self_improve.py`: vier feste Filter, 30 Tage beobachten, ein Urteil je Fenster | Schwellen fest im Code, Ergebnis nur „bereit für Uzis Entscheidung“ |
| Orderflow-Schatten | Vergleich Schatten-Ausstieg gegen Journal nach 30 geschlossenen Plänen | zeichnet nur auf, filtert nichts |
| Hermes-Zweitmeinung | Trefferquote DAFÜR/DAGEGEN nach 30 Plänen | reiner Kommentar |
| Wöchentliche Reflexion | höchstens ein Vorschlag je Woche als Frage ans Research Lab | DB-Verbindung nur lesend, `automatic_rule_change` immer `false` |
| Lernschleife L1 | Herausforderer gegen Champion, Wechsel nur bei `ELIGIBLE` und Karte, nur Papier | Lernregister rechnet das Urteil selbst |
| Agenten-Tests (Hermes-Evals) | fester Testkatalog, Ergebnis je Prompt- oder Modellstand | vorhanden am Mac, noch nicht im Repo, siehe Lücke 5 |
| Abgebrochene Aufgaben | monatliche Liste „woran scheitern die Agenten“ als Issue-Vorschläge | PM schreibt nur Vorschläge |

Agenten-Prompts und Modellwahl gelten wie Code: Änderung per PR, vorher Agenten-Test, danach „merge“.

## 6. Nachweis je Übergabe

| Übergabe | Nachweis |
|---|---|
| PM → jede Rolle | Issue mit Ziel, Abnahme, Grenzen, einem Status-Label |
| Researcher → F1 | Präregistrierung als Datei, Eintrag in `REGISTER.jsonl` mit Hash |
| Data Steward → Researcher | Datensatz-Hash, Zahl und Liste der Lücken, Prüfsummen ok |
| Engineer → Tester | Draft-PR, Diff nur in erlaubten Pfaden |
| Tester → Reviewer | Checks `test` und `PR gate` grün am aktuellen Commit, volle Suite mit Zahlen |
| Reviewer → F2 | Befundliste am PR, bestätigte Befunde behoben |
| DevOps nach Merge | Commit auf dem Mac = Commit auf `platform-main`, Watchdog GREEN, Chart-Seite lädt |
| Researcher → F3 | Bericht mit Trades, Erwartungswert nach Kosten, Drawdown, Stresstest doppelte Kosten |
| Schatten → F3 | Fenster-Start, Zahl neuer Trades, Intervall, ein Urteil |
| Vorfall geschlossen | Erholungskommentar mit Health-Wert, nicht nur gemergter PR |

## 7. Was es schon gibt, was fehlt

Vorhanden: Issue-Worker (Mac, Qwen), Issue-Pipeline (Codex → Claude → Draft-PR), `PR gate`, Runner, Watchdog,
Checkup mit Vorfall-Issues, Nachzug mit Rollback, Forschungswerkstatt mit Register, Orderflow-Schatten, F11,
Hermes-Zweitmeinung und Tagesbericht, Agenten-Vertrag `src/agents/contract.py`.

| # | Lücke | Folge heute |
|---|---|---|
| 1 | Kein einheitlicher Übergabezettel. Worker nutzt `TIM_QWEN_TASK_V1`, Bugfixer ein eigenes Modell, `agents/contract.py` ein drittes. | Übergaben zwischen Rollen laufen über Uzi oder den Koordinator |
| 2 | Vorfall-Issue geht nicht von selbst an den Engineer. | Fehler werden gemeldet, aber erst nach Uzis Anstoß repariert |
| 3 | Reviewer ist kein Pflichtschritt (Review-Pflicht aus, CODEOWNERS nur geplant). | „merge-fertig“ ohne unabhängige Prüfung möglich |
| 4 | Kein gemeinsamer Versuchszähler. Die Pipeline kennt nur `agent:retry` (einmal). | Abbruchgrenzen aus Abschnitt 4 sind nicht durchgesetzt |
| 5 | Hermes-Evals gibt es seit 10.11.2026 (14 Tests, laut Projekt-Thread alle grün, hier ungeprüft), aber nur am Mac unter `Documents/TIM/hermes-evals`, nicht im Repo und nicht an einen Ablauf gebunden. | Kein Lauf in CI, kein Pflichtlauf vor einem Prompt- oder Modellwechsel |
| 6 | Rückweg PS5 → Bericht ist Handarbeit (Mac-Sitzung mit Auftragstext). | Durchlauf A hält nach dem Rechnen an |
| 7 | Keine eine Stelle für „wartet auf Uzi“. | Offene Freigaben liegen in Threads, PRs und Karten verteilt |
| 8 | Server-Worker (Qwen 30B) im Probelauf, wöchentliche Reflexion nicht installiert (ungeprüft, Stand Anfang November). | zwei gebaute Teile laufen nicht |

## 8. Nächste Schritte (jeder wartet auf „go“)

| Paket | Inhalt | Prüfung |
|---|---|---|
| P1 | Übergabezettel als ein Schema im Issue-Body (Rolle, Eingang, Ausgang, Nachweis, Versuchszähler). Nur Doku und Prüfer, kein Verhalten. | Test: gültiger und ungültiger Zettel |
| P2 | Versuchszähler und Abbruchgrenzen aus Abschnitt 4 im Worker. Geschützter Pfad, also Owner-PR. | Test: dritter Versuch wird abgewiesen und meldet |
| P3 | Reviewer als Pflichtschritt vor „merge-fertig“ für kritische Pfade (Journal, Kostenmodell, `src/database/`). | PR ohne Befundliste gilt nicht als merge-fertig |
| P4 | Vorfall-Issue bekommt bei Klasse Daten/Anzeige automatisch den Worker-Vertrag; Echtgeld und SAFETY nie. | Probelauf mit `checkup:selftest` |
| P5 | Hermes-Evals ins Repo holen (ohne Schlüssel) und als Pflichtlauf vor jeder Prompt- oder Modelländerung festlegen. | Lauf vor und nach einer Prompt-Änderung, Ergebnis als Datei |
| P6 | „Wartet auf Uzi“ als ein Abschnitt im Hermes-Tagesbericht (offene go, merge, Karten). | Bericht zeigt bekannte offene PRs |
| P7 | PS5-Ergebnis kommt als Datei mit Hash zurück und wird vom Researcher abgeholt. | Ein Studienlauf ohne Mac-Sitzung |

Empfohlene Reihenfolge: P1, P2, P3 (machen die Kette sicher), dann P4 und P6 (machen sie selbstlaufend), zuletzt
P5 und P7. P1 bis P3 sind klein und ändern nichts am Live-Betrieb.

## Nicht Teil dieses Entwurfs

Auto-Merge, Erweiterung des Echtgeld-Tests, Öffnen des Holdouts, neue Rechte für Worker oder Hermes, Änderungen
an Diensten auf Mac, Server oder PS5.
