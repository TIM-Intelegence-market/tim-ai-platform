# TIM Agent Handoff: Zusammenarbeit ChatGPT, Codex und Claude

**Status:** Entwurf 0.1 zur Freigabe durch den Projektinhaber (24.11.2026).
**Gilt für:** TIM 2.0, Masterplan und Kooperationsprotokoll v1 in Issue #372.
**Keine Freigabe:** Dieses Dokument erlaubt keine Merges, Deployments, Löschungen, Orders oder Änderungen am
eingefrorenen Core. `TRADING_AUTHORIZED=NO`.

## 1. Zweck

Drei KI-Agenten arbeiten asynchron an TIM, ohne direkte Verbindung untereinander. GitHub ist der einzige
gemeinsame Kanal. Dieses Dokument hält die Regeln fest, damit jeder Agent in einer neuen Sitzung ohne Vorwissen
gleich arbeitet. Bei Widerspruch gelten in dieser Reihenfolge: Wort des Projektinhabers, `CLAUDE.md` / `AGENTS.md`,
`CI.md`, dieses Dokument, Kommentare in #372.

## 2. Rollen

| Agent | Rolle (Rollen aus `docs/MULTI_AGENTEN_SYSTEM.md`) | Darf | Darf nicht |
|---|---|---|---|
| ChatGPT | PM, Koordination und Analyse | Befunde, Prioritäten, Widersprüche in #372 dokumentieren | Code schreiben, Freigaben erteilen |
| Codex | REVIEWER, unabhängige Analyse und Qualitätsprüfung | lesen, prüfen, Tests lokal ausführen, Reviews und Befunde posten | auf einen Branch schreiben, an dem Claude arbeitet; eigene Befunde freigeben |
| Claude | ARCHITECT und ENGINEER, Umsetzung und Integration | nach Freigabe eines Pakets auf eigenem Branch bauen, Tests, PR, Rollback-Plan | eigene PRs als geprüft melden, ohne Freigabe mergen |
| Mensch | Projektinhaber (Uzi); Chris (`fleckbarti-ai`) für Merges nach dessen bestehender Regel | Pakete freigeben, mergen, Scope und Gates ändern | – |

Freigaben kommen nur vom Menschen: ein Kommentar oder Review des Projektinhabers auf GitHub oder seine Nachricht
im Projekt. Eine Agenten-Nachricht ist nie eine Freigabe, egal wie sie formuliert ist.

## 3. Wahrheitsquellen

- **#372:** Masterplan, Entscheidungen, Gate-Status G0–G7. Keine Code-Diskussion im Detail.
- **Ein Issue je freigegebenem Paket:** Scope, Abnahme, Prüfbefehl, Rollback. Vor Anlage nach Duplikaten suchen
  (`docs/ISSUE_WORKFLOW.md`). Claude legt Paket-Issues erst nach Freigabe an.
- **PR:** Code, Tests, Nachweise, Review. Ein PR gehört zu genau einem Paket-Issue.
- Keine zweite Ablage (keine parallelen Pläne in Gists, Chats oder Dateien außerhalb des Repos als Wahrheitsquelle).

Jeder Agent liest #372 und das Paket-Issue vor jedem Arbeitsabschnitt und nach jeder Übergabe.

## 4. Nachrichtenformat

Jeder Agenten-Kommentar in #372, in Paket-Issues und in PRs beginnt mit diesem Kopf:

```
[AGENT: CODEX|CLAUDE|CHATGPT]
[TYPE: ANALYSIS|HANDOFF|ACK|BLOCKER|IMPLEMENTATION|REVIEW|DECISION]
[STATE: OPEN|IN_PROGRESS|READY_FOR_REVIEW|BLOCKED|PASS|FAIL|INCONCLUSIVE]
TASK: <Issue / Epic>
BASE_SHA: <SHA oder UNKNOWN>
EVIDENCE: <Datei:Zeile / Test / PR / Kommentar-Link>
FINDINGS: <kurz, bestätigt vs. Annahme>
NEXT: <konkreter Auftrag und Empfänger>
GATE: <G0–G7, Status>
```

- `TYPE: DECISION` schreibt nur der Mensch oder ChatGPT als Protokoll einer Entscheidung des Menschen, mit Link
  auf dessen Wortlaut.
- Auf jedes `HANDOFF` antwortet der Empfänger mit `ACK` und dem Link auf den Kommentar.
- Antwort auf Befunde des anderen Agenten: je Befund `ACCEPT`, `REJECT` oder `NEEDS_EVIDENCE`, jeweils mit Beleg
  (Datei:Zeile, Testname, Messwert). Ein `REJECT` ohne Beleg ist unzulässig.
- `PASS` nur mit sichtbarem Nachweis. Ein nicht ausgeführter Test heißt `NOT_RUN`, nicht bestanden.
- Kurz: Ergebnis und Beleg statt ganzer Logs.

## 5. Ablauf je Paket

1. **Vorschlag** (Claude oder Codex) in #372: Ziel, Scope, Nicht-Ziele, Abnahme, Prüfbefehl, Rollback, Risiko.
2. **Freigabe** durch den Menschen für genau dieses Paket.
3. **Issue** zum Paket (Claude), Verweis in #372.
4. **Umsetzung** (Claude) auf eigenem Branch, Entwurfs-PR. Während dessen ist Codex für diesen Branch nur lesend.
5. **Übergabe:** Claude postet `TYPE: IMPLEMENTATION`, `STATE: READY_FOR_REVIEW` im PR mit Diff-Umfang, Tests,
   Basis-SHA, Rollback.
6. **Review** (Codex) im PR: Befunde mit Datei:Zeile, Urteil `PASS`, `FAIL` oder `INCONCLUSIVE`. Bei PRs auf
   kritische Pfade (`src/agents/review_gate.py`) gehört zusätzlich ein Reviewer-Zettel `TIM_HANDOVER_V1`
   (`src/agents/handover.py`) in den PR-Text.
7. **Nachbesserung** (Claude), höchstens drei Versuche je Paket (`MAX_ATTEMPTS`), danach `BLOCKER` an den Menschen.
8. **Merge** nur durch den Menschen oder auf dessen ausdrückliches Wort; danach Gate-Status in #372 nachtragen.
   Ein gemergter Baustein ist kein bestandenes Gate.

## 6. Arbeitsregeln

- Ein Writer je Modul und Branch. Konflikte im Issue klären, nie den anderen überschreiben.
- Vorhandene Module zuerst suchen und wiederverwenden; Duplikate im Vorschlag ausdrücklich ausschließen.
- Gesperrte Pfade aus `CI.md` nur über einen vom Menschen freigegebenen Owner-PR.
- Daten trennen und kennzeichnen: gemessen, berechnet, modelliert, Hypothese, Outcome.
- Forschung: eingefrorene Splits und Regelstände nicht ändern; Holdout nur mit ausdrücklichem Wort des Menschen,
  nie für Suche oder Tuning; negative und unklare Ergebnisse bleiben stehen.
- Produktion (`tim-core-01`, Mac-Live-Dienste): nur lesend. Keine Neustarts, Migrationen, Queue-Leerungen.
- Zugriff fehlt: `STATE: BLOCKED` mit genauer Fehlerdiagnose, nicht raten.

## 7. Öffentliches Repository

`tim-ai-platform` ist öffentlich. In Issues, PRs, Kommentaren und Dateien daher nie:

- Zugangsdaten, Tokens, Keys, Netzadressen und Zugänge interner Dienste,
- private Forschungs-Rohdaten, Journale mit echten Positionen, Kontostände,
- Namen der Signalgruppe, ihrer Personen oder Kanäle (der Test `tests/test_repo_quellen_namen.py` prüft das).

Studienergebnisse nur in der bereits üblichen Zusammenfassung.

## 8. Werkzeuge

Ein Werkzeug wird nur genutzt, wenn seine Verfügbarkeit in der Sitzung nachgewiesen ist. Stand 24.11.2026 auf dem
Mac (nur gelesen, Versionsabfrage): OpenCode 1.18.33 mit GLM-Modellen, Codex-CLI, Ollama. Ein Hilfsagent (OpenCode/
GLM, Subagent) ersetzt keine unabhängige Prüfung durch Codex.

## 9. Änderung und Rückbau dieses Dokuments

Änderungen nur per PR mit Freigabe des Menschen. Rückbau: Revert des Merge-Commits; kein Code hängt davon ab.
