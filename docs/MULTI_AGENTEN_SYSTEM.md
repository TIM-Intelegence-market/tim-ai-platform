# Multi-Agenten-System für TIM (Entwurf)

Stand 10.11.2026, **ENTWURF 0.1**. Gebaut sind P1 (Übergabezettel, Abschnitt 9), P2 (Neustart-Budget des
Watchdogs, Abschnitt 10), P3 (Review-Gate, Abschnitt 11), P4 (Vorfall an Worker, Abschnitt 15, noch aus), P5 (Hermes-Evals, Abschnitt 13), P6 („Wartet auf Uzi“, Abschnitt 12) und P7 (PS5-Rückweg, Abschnitt 14). Auftrag: Uzi, „Go“,
„go P1“, „go p2“ und „go mach alle ps fertig“ am 10.11.2026.

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
| Dienst steht | Watchdog | Watchdog (nur Neustart) | **3** Neustarts in 30 min, ein vierter wäre nötig: Halt ohne weitere Neustarts, bis eine Prüfung ohne neustartbaren Fehler kommt (gebaut, P2) |
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
| 1 | Der Übergabezettel `TIM_HANDOVER_V1` ist gebaut (P1), aber noch kein Worker liest ihn. `TIM_QWEN_TASK_V1`, das Bugfixer-Modell und `agents/contract.py` bestehen daneben weiter. | Übergaben zwischen Rollen laufen über Uzi oder den Koordinator |
| 2 | Vorfall-Issues mit geprüfter Code-Diagnose können an den Worker gehen (P4), der Schalter ist aber aus, bis der Login der Reporter-App am Mac eingetragen ist. | Bis dahin werden Fehler gemeldet und erst nach Uzis Anstoß repariert |
| 3 | Reviewer-Pflicht gibt es jetzt als Check `Review gate` (P3), aber nicht als Pflicht-Check im Ruleset. | Ein PR ohne Zettel kann technisch weiter gemergt werden; der Check zeigt es rot |
| 4 | Kein gemeinsamer Versuchszähler. Die Pipeline kennt nur `agent:retry` (einmal). | Abbruchgrenzen aus Abschnitt 4 sind nicht durchgesetzt |
| 5 | Hermes-Evals liegen jetzt im Repo (P5, 14 Fälle, letzter Mac-Lauf 10.11. 11:17: 14/14). Der Lauf braucht Hermes am Mac und läuft nicht in CI; die Pflicht vor einer Änderung ist eine Regel, kein Schalter. | Ein Prompt-Wechsel ohne Lauf fällt nur im Review auf |
| 6 | Der Runner kann Jobs auf der PS5 rechnen und das Bündel mit Hash zurückholen (P7), aber kein Zeitplan startet das. | Durchlauf A braucht weiter einen Anstoß, aber keine Mac-Sitzung mit Auftragstext mehr |
| 7 | „Wartet auf Uzi“ steht im Tagesbericht (P6), aber ohne offene PRs und Karten. | Offene PRs sieht Uzi weiter nur in GitHub und im Thread |
| 8 | Server-Worker (Qwen 30B) im Probelauf, wöchentliche Reflexion nicht installiert (ungeprüft, Stand Anfang November). | zwei gebaute Teile laufen nicht |

## 8. Nächste Schritte (jeder wartet auf „go“)

| Paket | Inhalt | Prüfung |
|---|---|---|
| P1 **gebaut** | Übergabezettel als ein Schema im Issue-Body (Rolle, Eingang, Ausgang, Nachweis, Versuchszähler). Nur Doku und Prüfer, kein Verhalten. | `pytest tests/agents/test_handover.py` |
| P2 **gebaut** | Abbruchgrenze dort, wo sie fehlte: Neustart-Budget im Watchdog. Der Qwen-Worker hatte seine Grenze schon (Abschnitt 10). | `pytest tests/test_watchdog_restart_budget.py` |
| P3 **gebaut** | Reviewer als Pflichtschritt vor „merge-fertig“ für kritische Pfade (Journal, Kostenmodell, `src/database/`). | Check `Review gate`, `pytest tests/agents/test_review_gate.py` |
| P4 **gebaut, aus** | Vorfall-Issue mit geprüfter Code-Diagnose (`incident:code`) geht in die Worker-Triage; SAFETY, Betrieb, Netz, Selbsttest nie. | `pytest tests/test_triage_incidents.py` |
| P5 **gebaut** | Hermes-Evals ins Repo holen (ohne Schlüssel) und als Pflichtlauf vor jeder Prompt- oder Modelländerung festlegen. | `pytest tests/agents/test_hermes_evals.py`; am Mac `python -m src.agents.hermes_evals` |
| P6 **gebaut** | „Wartet auf Uzi“ als ein Abschnitt im Hermes-Tagesbericht. Offene PRs fehlen (kein Netz im Bericht), siehe Abschnitt 12. | `pytest tests/test_waiting_on_uzi.py` |
| P7 **gebaut** | PS5-Ergebnis kommt als Bündel mit Hash zurück, der Researcher prüft es mit `verify`. | `pytest tests/test_research_runner_ps5.py` |

Empfohlene Reihenfolge: P1, P2, P3 (machen die Kette sicher), dann P4 und P6 (machen sie selbstlaufend), zuletzt
P5 und P7. P1 bis P3 sind klein und ändern nichts am Live-Betrieb.

## 9. Übergabezettel `TIM_HANDOVER_V1` (P1)

Code `src/agents/handover.py`, Tests `tests/agents/test_handover.py`. Der Zettel steht als ein Block im Issue- oder
PR-Text. Der Prüfer liest ihn und sagt gültig oder ungültig. Kein Worker liest ihn bisher, es ändert sich also kein
Verhalten.

````text
```json TIM_HANDOVER_V1
{
  "schema": "TIM_HANDOVER_V1",
  "task_id": "github-issue-42",
  "issue_number": 42,
  "from_role": "ENGINEER",
  "to_role": "TESTER",
  "input": "Issue #42 mit Vertrag",
  "output": "Draft-PR mit Reparatur",
  "evidence": [{"kind": "link", "ref": "PR #43"}],
  "attempt": 1,
  "max_attempts": 3,
  "gate": "NONE"
}
```
````

Regeln des Prüfers:

- Genau diese elf Felder, kein weiteres. Genau ein Zettel je Text, höchstens 12 000 Zeichen.
- Rollen: PM, RESEARCHER, DATA_STEWARD, ENGINEER, TESTER, REVIEWER, DEVOPS, SECURITY, DOCS. Absender und Empfänger
  sind verschieden.
- Nachweis: 1 bis 20 Einträge der Art `test`, `log`, `number`, `hash`, `link`, `file`. Pflichtart je Absender:
  Researcher `file`, Data Steward `hash`, Engineer `link`, Tester `test`, Reviewer `link`, DevOps `log`.
- Versuche: `attempt` höchstens `max_attempts`, `max_attempts` höchstens 3 (ein erster Versuch und zwei
  Reparaturen). Ein Zettel über der Grenze ist ungültig. Durchgesetzt im Worker wird das erst mit P2.
- `gate` nennt die Freigabe, die der Empfänger noch braucht: `NONE`, `F1_GO`, `F2_MERGE`, `F3_RULE_UPDATE`,
  `F4_LIVE`, `F5_HOLDOUT`. Der Zettel erteilt nie selbst eine Freigabe; ein Feld wie `approved_by` wird abgewiesen.

Prüfen einer Datei: `python -m src.agents.handover DATEI` (Ende 0 gültig, 1 ungültig).

## 10. Abbruchgrenzen im Bestand (P2)

Bestandsaufnahme vor dem Bau, was schon durchgesetzt war:

| Stelle | Grenze | Stand |
|---|---|---|
| Mac-Qwen-Worker (`src/local_first/issue_triage.py`) | 2 Versuche je Vertrag, Fehlertexte am Issue, dann `agent:blocked` mit Kommentar; erst Label entfernen gibt neue Versuche frei | **war schon da**, unverändert. Strenger als Abschnitt 4 (dort 1 + 2); bleibt so. |
| Triage | 2 Aufrufe je Issue-Fassung, 30 je Tag | war schon da |
| Issue-Pipeline (`agent:retry`) | ein erneuter Lauf je Freigabe durch einen Menschen | war schon da |
| Watchdog (`scripts/tim_watchdog.py`) | 3 rote Prüfungen und 5 min Abkühlzeit je Neustart, **aber keine Obergrenze** | **gefehlt**, jetzt gebaut |

Neu im Watchdog:

- Höchstens 3 Neustarts in 30 Minuten (`--restart-max 3`, `--restart-window 1800`, das sind die Standardwerte;
  die Plist bleibt unverändert).
- Wäre ein vierter nötig, hält der Watchdog an: kein Neustart mehr, Ereignis `WATCHDOG_RESTART_HOLD` (ERROR) im
  `watchdog.jsonl`, Feld `restart_hold: true` in `watchdog_status.json` und `watchdog_recovery_state.json`.
- Der Halt endet nicht mit der Zeit, sondern erst, wenn eine Prüfung keinen neustartbaren Fehler mehr zeigt.
  Danach gilt wieder das Budget aus dem 30-Minuten-Fenster.
- Nebenbefund behoben: Die Abkühlzeit galt bisher nur eine Prüfung lang, weil der Zeitpunkt des letzten Neustarts
  im nächsten Durchlauf nicht mehr gespeichert wurde. Er bleibt jetzt erhalten. Folge: höchstens ein Neustart je
  5 Minuten, wie es in der Plist steht.

Offen: Der Halt erscheint in den Watchdog-Dateien und im Log, aber noch nicht als eigene Meldung an Uzi (gehört zu
P6, Abschnitt „wartet auf Uzi“ im Tagesbericht).

## 11. Review-Gate (P3)

Code `src/agents/review_gate.py`, Workflow `.github/workflows/review-gate.yml`, Tests `tests/agents/test_review_gate.py`.

- Ändert ein PR einen kritischen Pfad, braucht sein Text einen gültigen Übergabezettel `TIM_HANDOVER_V1` mit
  `from_role` REVIEWER und der PR-Nummer als `issue_number`. Sonst wird der Check `Review gate` rot.
- Kritisch: `.github/`, `ops/`, `scripts/timctl`, `scripts/tim_watchdog.py`, `src/database/`, `src/tim_incident/`,
  `src/task_governance/`, Journal-Logik `src/dashboard/plan_journal.py`, Kostenmodell `src/research_lab/exit_variants.py`,
  Holdout-Sperre `src/research_lab/protocol.py`, Lernregister `src/research_lab/learning/`, `REGISTER.jsonl`,
  `PROTOKOLL.md` und die beiden Agenten-Prüfer selbst.
- Der Reviewer ist ein Agent, der die Änderung nicht geschrieben hat (Skill `adversariale-pruefung`). Eine zweite
  Person wird nicht erzwungen, so hat Uzi es am 26.10.2026 entschieden (R2). Der Check ist deshalb kein
  Pflicht-Check im Ruleset; Uzis „merge“ bleibt die einzige Freigabe.
- Grenze: Der Check prüft nur, dass ein Zettel da ist, nicht wer ihn geschrieben hat.
- Läuft auf einem GitHub-Rechner, nie auf dem Mac- oder Server-Runner, weil das Repo öffentlich ist. Der Prüfer
  läuft aus dem Basis-Stand, damit ein PR den eigenen Check nicht abschwächen kann; umbenannte Dateien zählen mit
  altem und neuem Pfad.

## 12. Wartet auf Uzi (P6)

Code `src/dashboard/waiting_on_uzi.py`, eingehängt in den Tagesbericht um 8 und 22 Uhr (`daily_report.facts`).
Gelesen werden nur TIM-eigene Dateien:

- Watchdog hat die Neustarts angehalten (P2, `watchdog_recovery_state.json`).
- F11-Filter mit Urteil „bestanden“, bereit für Uzis Entscheidung (`data/research/self_improve/log.jsonl`); eine
  gebrochene Hash-Kette wird ebenfalls gemeldet.
- Orderflow-Schatten und Hermes-Zweitmeinung, sobald 30 Pläne geschlossen sind und das Urteil fällig ist.

Eine unlesbare Datei wird genannt, nicht still ausgelassen. Offene PRs und Entscheidungskarten stehen nicht drin,
weil der Bericht kein Netz nutzt und keinen GitHub-Zugang hat.

## 13. Hermes-Evals (P5)

Code `src/agents/hermes_evals.py`, Fälle `src/agents/hermes_eval_cases.json` (14: fünf Fakten, zwei fehlende Daten,
sechs Ablehnungen inklusive Prompt-Injection, eine englische Frage), Tests `tests/agents/test_hermes_evals.py`.
Übernommen vom Mac (`Documents/TIM/hermes-evals`, Lauf 10.11.2026 11:17: 14/14).

- Lauf am Mac: `python -m src.agents.hermes_evals` (alle) oder mit Fall-Namen. Fragt Hermes per `hermes -z`, liest die
  Werkzeug-Spur aus `~/.hermes/logs/agent.log` und vergleicht Zahlen mit `live_status.json`.
- Berichte enthalten Antworten mit Kontozahlen. Das Repo ist öffentlich, deshalb schreibt der Lauf nach
  `~/Library/Application Support/TIM/hermes-evals/reports` (oder `TIM_HERMES_EVAL_REPORTS`), nie ins Repo.
- Regel: vor und nach jeder Änderung an Hermes (Prompt, SOUL.md, Modell, Werkzeuge) laufen lassen und beide
  Berichte behalten. Weniger bestandene Fälle stoppen die Änderung, bis der Grund geklärt ist.
- Gegenüber der Mac-Fassung behoben: Fehlt ein Wert in `live_status.json`, stürzte der Lauf ab (`None` formatiert);
  jetzt ist es ein benannter Fehlschlag. Eine einzelne Zeile „OK“ mitten in einer Ablehnung zählt jetzt auch als
  behauptete Aktion, vorher nur am Anfang der Antwort.

## 14. PS5-Rückweg (P7)

Die Forschungswerkstatt (`src/research_lab/workshop/runner.py`) hatte schon einen SSH-Weg zum Server. Er kann jetzt
auch die PS5 hinter Warpgate: eigener Port, Schlüsseldatei (nur der Pfad), Python aus dem venv, Kopie per `scp`
(die PS5 hat kein `rsync`). Ein Job wird mit `submit --host ps5` angelegt und gerechnet mit

`python -m src.research_lab.workshop run --pending --host ps5 --ssh uzi:ps5-research@<warpgate-host> --ssh-port 2222
--ssh-key ~/.ssh/tim_uzi --remote-dir ~/tim-research/code --remote-python ~/tim-research/.venv/bin/python --copy scp`

Das Ergebnis kommt als Bündel mit Manifest und Inhalts-Hash in die Werkstatt, `verify --bundle` prüft es.

- Nebenfund behoben: Ob die PS5 denselben Code-Stand hat wie der Auftrag, wurde erst nach dem Rechnen verglichen.
  Jetzt bricht der Lauf vorher ab (Exit 97, „commit-mismatch“), statt Stunden auf altem Code zu rechnen.
- Der Warpgate-Nutzer enthält einen Doppelpunkt (`uzi:ps5-research`). `scp` hätte `uzi` als Rechner gelesen; der
  Nutzer geht deshalb als `-o User=…` an ssh, rsync und scp.
- Noch nicht an der echten PS5 geprüft: der erste Lauf mit `scp` (Pfad wird ohne `~` relativ zum Home-Verzeichnis
  geholt). Kennt der Mac seinen eigenen Code-Stand nicht, fällt die Vorab-Prüfung weg; die Prüfung nach dem Lauf
  bleibt.
- Nicht gebaut: ein Zeitplan, der das selbst startet. Ein langer Lauf würde den 15-Minuten-Agenten am Mac blockieren,
  und ein neuer LaunchAgent ist eine Änderung am Betrieb. Beides nur mit Uzis Wort.

## 15. Vorfall an Worker (P4)

`src/local_first/issue_triage.py`: Ein Vorfall-Issue der Reporter-App kommt in die Worker-Triage nur, wenn es
`incident` und `incident:code` trägt und keins von `incident:safety`, `incident:ops`, `incident:network`,
`incident:unknown`, `selftest`, `checkup:pause-qwen`, `checkup:silence`. `incident:code` setzt der Checkup nur
nach einer geprüften Diagnose, deren Stellen alle unter `src/` liegen und nicht in `src/tim_incident/` oder
`src/database/` (`code_label` in `src/tim_incident/github.py`). Danach gilt alles wie bei jedem Issue: Triage,
Vertrag, zwei Versuche, PR gate, Merge nur nach Uzis „merge“.

- Aus, bis `TIM_TRIAGE_INCIDENT_AUTHORS` den Login der Reporter-App (`<app-slug>[bot]`) nennt. Der Login steht
  absichtlich nicht im Repo. Andere Logins als `…[bot]` zählen dort nicht. Einschalten ist eine Änderung am Mac und
  braucht Uzis Wort.
- Ungeprüft: ob der Mac-Worker die Vorfall-Issues in seiner Issue-Liste sieht (gleiches Repo angenommen).
- Die Labels werden nur bei der Triage geprüft. Kommt `incident:safety` erst nach `status:ready` dazu, hält das den
  Worker nicht an; dafür bleibt `agent:blocked` oder das Label entfernen. Teilaufgaben aus `agent:split` erbt der
  Filter nicht.
- `gh` meldet die App als `app/<slug>`; das zählt nur mit `is_bot`, und wird zu `<slug>[bot]` umgeschrieben.

## Nicht Teil dieses Entwurfs

Auto-Merge, Erweiterung des Echtgeld-Tests, Öffnen des Holdouts, neue Rechte für Worker oder Hermes, Änderungen
an Diensten auf Mac, Server oder PS5.
