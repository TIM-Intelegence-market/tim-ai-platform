# Vollautomatischer Merge: Plan, Stand und Aktivierung

**Status: vorbereitet, nicht aktiv.** Zielentscheidung des Inhabers: Ein Issue wird automatisch analysiert, von Claude Code
umgesetzt, als PR geprüft und nach bestandenen Schutzregeln ohne menschliches Review nach `platform-main` gemerged.
Das ersetzt die bisherige Regel (b) „Mensch genehmigt, GitHub merged“ **erst bei der Aktivierung** (Schritt 8).
`CI.md` und `CLAUDE.md` sind deshalb absichtlich unverändert und beschreiben weiter Regel (b). Das Gate-Regelwerk in
`CI.md` kennt die Erweiterungen dieses PRs (geschützte bestehende Tests) noch nicht.

## 1. Fakten und Annahmen

| Aussage | Beleg |
|---|---|
| PR #146: Draft, Head `71ada63`, mergeable `clean`, `TIM full suite`, `test`, `codeql` grün | GitHub-API gelesen am 2026-10-04 |
| PR #147: Draft, Head `023ccec`, `test`, `codeql` grün; `PR gate` lief noch nie in Actions | GitHub-API gelesen |
| PR #149: Draft, Head `692e278`, grün | GitHub-API gelesen |
| Der Issue-Runner arbeitet mit dem lokalen `gh` des Nutzers; es gibt kein eigenes Worker-Token | Code in #146 (`Pipeline.github`) |
| Branch-Protection und Rulesets liefern im privaten Repo HTTP 403; `allow_auto_merge` ist `false` | **Angabe des Inhabers, nicht selbst geprüft** |
| Das Konto ist ein persönliches Konto ohne bezahlten Plan | **Annahme** (aus dem 403 und dem Kommentar „User plan account“ in `CODEOWNERS`) |
| Welcher GitHub-Plan Rulesets für private Repos freischaltet | **nicht verifiziert** (`docs.github.com` ist im Entwicklungscontainer gesperrt), siehe Abschnitt 4 |
| Ein `pull_request_target`-Check zählt als Pflicht-Check für den PR-Commit | **ungeklärt**, zeigt erst der erste Lauf nach dem Bootstrap-Merge |

## 2. Architektur (Vertrauensgrenzen)

```
Issue ──► Runner (lokal, Worker-Identität) ──► Draft-PR (Branch claude/issue-N-…)
                                                   │
        GitHub Ruleset (erzwingt PR, Pflicht-Checks, aktueller Branch, nur Merger darf mergen)
                                                   │
 Controller-Workflow (läuft aus platform-main, Merger-Identität) ◄── liest nur: Autor, Branch, Repo, Head-SHA,
   1. Policy (.github/auto-merge-policy.json, aus Base)                Checks dieser SHA, Gate-Ergebnis
   2. Gate neu ausführen auf exakt dieser SHA (scripts/pr_gate.py)     NIE: PR-Text, Labels, Kommentare
   3. Merge per API mit `sha=<geprüfte SHA>`  (GitHub lehnt bei verschobenem Head selbst ab)
```

Der Worker ändert weder Gate, Workflows, Policy noch den Controller: Das Pfad-Gate (`.github/`, `scripts/`, `config/`,
`CI.md`, `CLAUDE.md`, Abhängigkeitslisten, `conftest.py` …) lehnt solche PRs ab, und bestehende Tests sind **nur noch
ergänzbar, nicht änderbar oder löschbar** (`add_only_prefixes`). Der Controller-Job läuft nur auf `platform-main`.

**Der Controller blockiert bei:** unbekanntem Autor, Fork, falschem Basis- oder Branch-Namen, `mergeable` ungleich `true`,
`mergeable_state` ungleich `clean`, Branch hinter `platform-main` (`behind_by` ungleich 0), fehlendem, laufendem oder nicht
erfolgreichem Check (jeder Check auf der SHA muss `success` sein), Pflicht-Check von einer anderen App als `github-actions`,
Gate-Verstoß oder Gate-Absturz, SHA-Wechsel zwischen Prüfung und Merge, jedem API-Fehler und jeder Antwort ohne erwartete
Felder. Ein Draft-PR wird zuerst auf „ready“ gesetzt und erst beim nächsten Lauf neu geprüft und gemerged.

**Wiederholung:** Der Controller hält keinen Zustand. Jeder Lauf bewertet alles neu, es wird höchstens
`max_merges_per_run` (1) PR gemerged. Ein neuer Push ändert die SHA und startet die Prüfung von vorn. Ein PR, der nach
einem anderen Merge hinter `platform-main` liegt, bleibt blockiert, bis der Branch aktualisiert wurde (Paket P4).

## 3. Pakete und Stand

| Paket | Inhalt | Stand |
|---|---|---|
| P1 | Plan und Garantie-Matrix (dieses Dokument) | erledigt |
| P2 | Controller, Policy, Workflow, inaktiv: `scripts/auto_merge_controller.py`, `.github/auto-merge-policy.json`, `.github/workflows/auto-merge-controller.yml` | erledigt, 125 Tests (Controller und Gate) |
| P3 | Gate: bestehende Tests geschützt (`add_only_prefixes`) | erledigt |
| P4 | Runner (PR #146, Codex-Branch): eigenes Worker-Token und Identitätsprüfung, Branch aktuell halten, sichere Wiederholung | **offen**, nur mit echtem `gh` im Pilot prüfbar |
| P5 | GitHub-Einstellungen und Plan (Abschnitt 4) | **offen, Inhaber** |
| P6 | Manuell geprüfte Bootstrap-Merges von #147, #146 und diesem PR | **offen, Inhaber** |
| P7 | Pilot erst mit `dry_run`, dann echt, mit Beleg der Garantien | **offen** |
| P8 | `CI.md` und `CLAUDE.md` auf die neue Regel umstellen | erst bei Aktivierung |

## 4. Was auf GitHub fehlt

Zu klären ist **eine Entscheidung des Inhabers**: privat mit passendem Plan, öffentlich oder bis dahin Draft-PRs.

- **Plan (nach meinem Kenntnisstand, bitte auf den von Ihnen verlinkten GitHub-Seiten prüfen):** Rulesets und Branch-Protection
  für *private* Repositories brauchen bei einem persönlichen Konto GitHub Pro, bei einer Organisation GitHub Team oder
  Enterprise Cloud. Mit GitHub Free sind sie nur für öffentliche Repositories verfügbar. Der HTTP-403-Text von GitHub nennt
  den fehlenden Plan normalerweise ausdrücklich; bitte den genauen Wortlaut prüfen. Ich habe den 403-Block nicht umgangen und
  keine Admin-Zugangsdaten benutzt.
- **Ruleset auf `platform-main`** (nach Planwechsel): Pull Request erforderlich (Anzahl Freigaben 0), erforderliche Status-Checks
  `PR gate`, `test`, `TIM full suite` mit „Branch muss aktuell sein“, Force-Push und Löschen gesperrt, **Updates nur für die
  Merger-Identität** (Bypass-Liste nur diese), keine Admin-Ausnahme.
- **Merger-Identität:** empfohlen eine GitHub App mit `contents: write` und `pull-requests: write` (nicht der Mensch, nicht
  der Worker). Der Controller nutzt bis dahin `github.token`. Merges mit `github.token` lösen keine Folge-Workflows aus
  (zum Beispiel `ci.yml` bei `push` auf `platform-main`); ein App-Token behebt das.
- **Worker-Identität:** ein eigenes Konto oder eine App mit fein abgestuftem Token nur für dieses Repository, das nicht der
  Inhaber ist. Ohne das könnte jeder PR des Inhabers mit passendem Branch-Namen als Worker-PR gelten.
- **Repository-Variable oder Secret:** nur nötig, wenn die App-Variante gewählt wird (App-ID, privater Schlüssel).

## 5. Garantie-Matrix: was GitHub heute erzwingt und was nicht

| Garantie | Durchsetzung | Heute |
|---|---|---|
| Controller und Policy sind inaktiv (`enabled: false`, `dry_run: true`, keine Worker, Workflow nur manuell, Job nur auf `platform-main`) | Code und Test `test_the_shipped_policy_is_inert` | **ja** |
| Jeder unbekannte Zustand, fehlende Check, SHA-Wechsel oder API-Fehler blockiert den Merge | Controller-Code, 125 Tests; zusätzlich `sha=` im Merge-Aufruf | **ja** (wirkt erst bei Aktivierung) |
| Der Worker kann Gate, Workflows, Policy, Controller oder bestehende Tests im PR nicht ändern | Pfad-Gate im PR-Diff | **nur im Code**; ohne Ruleset nicht erzwungen |
| Es gibt keinen Weg nach `platform-main` ohne PR und grüne Pflicht-Checks | GitHub-Ruleset | **nein** (403) |
| Der geprüfte Stand ist der gemergte Stand (Branch aktuell) | Controller prüft `behind_by`; Ruleset „aktuell“ | **nur im Controller** |
| Nur der Controller kann mergen, der Worker nicht | Ruleset „Updates einschränken“ mit Merger-Bypass | **nein** |
| Worker- und Merger-Identität sind vom Menschen getrennt | eigenes Konto beziehungsweise App | **nein** (Runner nutzt das `gh` des Inhabers) |
| Fachliche Richtigkeit der Änderung | nicht erzwingbar | **nie**: ein grüner Test beweist sie nicht, ein Worker könnte neue, schwache Tests ergänzen |

## 6. Aktivierung (erst nach P5, P6 und einem Pilot-Beleg)

1. Plan/Sichtbarkeit entscheiden, Ruleset und Identitäten anlegen (Abschnitt 4) und die 403-Sperre als aufgehoben prüfen.
2. #147 manuell geprüft nach `platform-main` mergen (Bootstrap), dann #146 und diesen PR.
3. Ersten echten Lauf des `PR gate` beobachten: Fetch im privaten Repo, Zuordnung zum Pflicht-Check. Falls der Check nicht für die
   PR-SHA zählt, `PR gate` aus `required_checks` der Policy streichen (der Controller führt das Gate selbst aus) oder einen
   Commit-Status ergänzen.
4. In `.github/auto-merge-policy.json` `worker_logins` setzen und `enabled: true` lassen, `dry_run: true`; den Controller manuell
   (`workflow_dispatch` auf `platform-main`) starten und die Entscheidungen im Log lesen.
5. Pilot (Dry-Run): Der Runner erzeugt einen **Draft-PR**. Der Controller meldet dafür zuerst `would-mark-ready` (nicht
   `would-merge`) und ändert im Dry-Run nichts; der PR bleibt Draft. Erst ein **Ready-PR** kann `would-merge` ergeben. Für den
   Pilot setzt der Inhaber den Pilot-PR von Hand auf „Ready“ und startet den Controller ein zweites Mal; im echten Betrieb
   markiert der Controller den PR selbst als „ready“ (`marked-ready`) und merged erst im **nächsten** Lauf nach erneuter
   Prüfung. Manipulierte Test-PRs (Workflow-Änderung, geänderter bestehender Test, gefälschtes Label) müssen `blocked` melden.
6. Erst dann: `dry_run: false` in einem überprüften Commit und den `schedule`-Trigger im Workflow einkommentieren.
7. LaunchAgent der Pipeline erst nach dem erfolgreichen Pilot starten (`production`).
8. `CI.md` und `CLAUDE.md` auf die neue Regel umstellen und die Garantie-Matrix mit dem beobachteten Stand aktualisieren.

**Stopp-Schalter:** `enabled: false` in der Policy, den `schedule`-Trigger entfernen oder das Ruleset-Bypass des Mergers
entziehen. Jeder der drei stoppt weitere Merges.
