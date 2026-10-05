# Vollautomatischer Merge: Plan, Stand und Garantien

**Status: vorbereitet, nicht aktiv und nicht bereit für Auto-Merge.** Zielentscheidung des Inhabers: Ein Issue wird automatisch
analysiert, von Claude Code umgesetzt, als PR geprüft und nach bestandenen Schutzregeln ohne menschliches Review nach `platform-main`
gemerged. Das ersetzt die bisherige Regel (b) „Mensch genehmigt, GitHub merged“ **erst bei der Aktivierung**. `CI.md` und `CLAUDE.md`
sind deshalb absichtlich unverändert und beschreiben weiter Regel (b).

Weiterführend: [Identitäten und Schlüssel](AUTO_MERGE_IDENTITIES.md) · [Schutzregeln und 403-Beleg](AUTO_MERGE_RULESET.md) ·
[Bootstrap, Dry-Run, Pilot, Aktivierungsvorschau](AUTO_MERGE_ROLLOUT.md).

**Offene harte Voraussetzungen, solange eine davon offen ist, gilt „nicht bereit“:** (1) HTTP 403 für Rulesets, (2) keine getrennten
Worker- und Merger-Identitäten, (3) der Gate-Workflow lief noch nie in GitHub Actions, (4) Runner-Patch P6 ist nicht in PR #146.

## 1. Fakten und Annahmen

| Aussage | Beleg |
|---|---|
| PR #146: Draft, Head `71ada63`, `TIM full suite`, `test`, `codeql` grün, enthält den `local_env`-Filter | GitHub-API gelesen |
| PR #147: Draft, Head `023ccec` (Gate); PR #149: Draft, Head `692e278` (Bytecode-Fix) | GitHub-API gelesen |
| Rulesets und `rules/branches/platform-main` antworten mit HTTP 403: „Upgrade to GitHub Pro or make this repository public“ | **am 2026-10-04 selbst per lesendem GET verifiziert, vor dem Umzug in die Organisation**; danach nicht neu geprüft, Details in `AUTO_MERGE_RULESET.md` |
| Repository wurde am 2026-10-04 von `uezeyiraydin-cell` in die Organisation `TIM-Intelegence-market` verschoben; es ist privat, `owner.type: Organization` | am 2026-10-05 selbst gelesen (GitHub-Suche, Repository-ID unverändert 1316019774) |
| `allow_auto_merge: false` | vor dem Umzug selbst gelesen, danach nicht neu geprüft |
| Der Issue-Runner nutzt das `gh`-Konto des Inhabers; ohne Patch P6 gibt es keine Worker-Identität | Code in #146 |
| Das Konto hatte vor dem Umzug GitHub Free | Folgerung aus dem 403-Text, **nicht direkt gelesen**; der Plan der Organisation ist unbekannt |
| Für private Repositories einer Organisation braucht es für Rulesets den Organisationsplan GitHub Team (GitHub Pro gilt nur für persönliche Konten) | nach meinem Kenntnisstand, **nicht verifiziert** (`docs.github.com` ist im Entwicklungscontainer gesperrt); Preis und Umfang ebenso |
| Merges mit `github.token` lösen keine Folge-Workflows aus | dokumentiertes GitHub-Verhalten nach meinem Kenntnisstand, im Pilot zu bestätigen |
| Das Merge-API-Verhalten bei verschobenem Base (HTTP 405 bei strikter Aktualität) | nach meinem Kenntnisstand, nicht selbst getestet |
| Der Commit-Status `pr-gate/head` entsteht auf der Head-SHA und gilt als Pflicht-Check | **ungeklärt**, zeigt erst der erste Lauf nach dem Bootstrap-Merge |

## 2. Architektur (Vertrauensgrenzen)

```
Issue ──► Runner (lokal, Worker-Identität, Patch P6) ──► Draft-PR (Branch claude/issue-N-…, Autor = Worker)
                                                              │
   GitHub-Rulesets auf platform-main (noch nicht möglich: 403):
     A "merge conditions", KEIN Bypass-Akteur: PR erforderlich, 0 Reviews, strikte Pflicht-Checks
       test · TIM full suite · pr-gate/head, kein Force-Push, kein Löschen
     B "restrict updates", Merger-App als einziger Bypass-Akteur: nur die Merger-App darf aktualisieren
                                                              │
 Controller-Workflow (aus platform-main, Merger-App-Token) ◄── liest nur: Autor-Login, Branch, Repo, Head-SHA,
   1. Policy (.github/auto-merge-policy.json, aus Base)           Checks/Status dieser SHA, Gate-Ergebnis
   2. Gate neu ausführen auf exakt dieser SHA                     NIE: PR-Text, Labels, Kommentare
   3. Merge per API mit sha=<geprüfte SHA> (GitHub lehnt bei verschobenem Head selbst ab)
```

**Der Controller blockiert bei:** unbekanntem Autor, Fork, falscher Basis oder Branch, `mergeable` ungleich `true`,
`mergeable_state` ungleich `clean`, Branch hinter `platform-main` (vor der Prüfung **und** noch einmal unmittelbar vor dem Merge),
fehlendem, laufendem oder nicht erfolgreichem Check (jeder Check auf der SHA muss `success` sein), Pflicht-Check, der nicht von der
erwarteten Workflow-Datei, dem erwarteten Ereignis, derselben Head-SHA und demselben Repository stammt (gleichnamige Jobs aus anderen
Workflows machen ihn mehrdeutig und blockieren), fehlendem oder unechtem `pr-gate/head`-Status (genau einer, `success`, Ersteller
`github-actions[bot]`, Lauf von `pr-gate.yml` auf `pull_request_target`), Gate-Verstoß oder -Absturz, SHA-Wechsel, jedem API-Fehler,
Rulesets, die nicht exakt der Policy entsprechen (beide Rulesets samt Bypass-Konfiguration, siehe Ruleset-Dokument), und fehlendem App-Token. Ein Draft-PR wird zuerst auf „ready“ gesetzt und erst beim
**nächsten** Lauf neu geprüft und gemerged.

Der kombinierte Status-Endpunkt liefert den Ersteller nicht mit. Der Controller liest deshalb zusätzlich die detaillierte,
paginierte Status-Historie und ergänzt nur den neuesten Status jedes Kontexts mit derselben ID, demselben Ergebnis und
derselben Ziel-URL. Abweichungen zwischen den Antworten oder ein fehlender Ersteller blockieren. Ältere Statusmeldungen
(z. B. `pending` vor `success`) werden nicht als aktuelle Meldungen bewertet.

**Das Gate** (Pfade, Modi, Größe) gilt für Branches `claude/issue-N-…`: erlaubt nur `src/`, `tests/`, `docs/`; gesperrt `.github/`,
`scripts/`, `config/`, `CI.md`, `CLAUDE.md`, Abhängigkeitslisten, `conftest.py`, `sitecustomize.py` u. a.; **bestehende Tests nur
ergänzbar**; neue Dateien unter `tests/` nur als `test_*.py` (keine `conftest.py`, `__init__.py`, Plugins, Konfigurationsdateien, Daten,
keine Module, die Standardnamen überdecken, keine `.pth`/`.pyc`/`.so`); keine Symlinks, Submodule, Rechtewechsel; höchstens 40 Dateien
und 1 MB je Datei.

**Wiederholung und Fehler:** Der Controller hält keinen Zustand und bewertet jeden Lauf neu; ein echter Lauf mergt **genau einen** PR
(`max_merges_per_run` muss bei echten Merges 1 sein), und die Rulesets werden unmittelbar vor diesem Merge erneut gelesen. Ein neuer Push ändert die SHA und startet die Prüfung von vorn. Ein PR, der nach einem anderen Merge hinter
`platform-main` liegt, bleibt blockiert, bis der Runner ihn aktualisiert hat (`--maintain`, Patch P6). Der Runner nimmt einen
abgebrochenen Lauf an der ersten unerledigten Stelle wieder auf, ohne Claude erneut zu starten.

## 3. Pakete und Stand

| Paket | Inhalt | Stand |
|---|---|---|
| Controller, Policy, Workflow (inaktiv) | `scripts/auto_merge_controller.py`, `.github/auto-merge-policy.json`, `.github/workflows/auto-merge-controller.yml` | erledigt (PR #150) |
| Gate-Härtung | geschützte Tests, Test-Hilfsdateien, Größenlimit, Status `pr-gate/head` | erledigt (PR #150) |
| Identitäten, Ruleset, Rollout, Garantien | diese Dokumente und `docs/rulesets/platform-main-merge-conditions.json` sowie `platform-main-restrict-updates.json` | erledigt als Entwurf |
| Runner-Patch P6 für PR #146 (Worker-Identität, Wiederaufnahme, Branch-Pflege) | als separate Patch-Datei geliefert | **offen: nicht in #146 angewendet** |
| GitHub-Plan, Ruleset, Apps, Negativversuche (**zuerst in einem privaten Testrepository mit identischen Regeln**, im Produktionsrepository danach nur lesend) | `AUTO_MERGE_RULESET.md` (Abschnitt 4), `rulesets/test-repo/README.md`, `AUTO_MERGE_IDENTITIES.md` | **offen, Inhaber** |
| Bootstrap-Merges #149, #147, #150, #146 | Reihenfolge in `AUTO_MERGE_ROLLOUT.md` | **offen, Inhaber** |
| Erster echter Gate-Lauf, Dry-Run-Matrix, Ende-zu-Ende-Pilot | Tabellen in `AUTO_MERGE_ROLLOUT.md` | **offen** |
| Aktivierung, `CI.md`/`CLAUDE.md` umstellen | nur als Vorschau, nicht angewendet | erst nach Ihrem ausdrücklichen Go |

## 4. Garantie-Matrix

**A = durch GitHub erzwungen · B = nur durch den Controller (Code und Tests) geprüft · C = noch nicht geprüft oder nicht vorhanden.**
Heute ist **keine** Garantie der Schutzregel-Klasse durch GitHub erzwungen, weil Rulesets für dieses Repository 403 liefern.

| Garantie | Mechanismus | Kat. |
|---|---|---|
| Der gemergte Head ist der geprüfte Head | Merge-API-Parameter `sha=`: GitHub lehnt bei verschobenem Head ab (wirkt nur im Merge-Aufruf des Controllers) | **A** |
| Der Gate-Workflow läuft aus dem Base-Stand und hat nur `contents: read`, `statuses: write` | GitHub-Semantik von `pull_request_target` und `permissions` | **A** (Wirkung in Actions noch nie beobachtet, also zugleich **C**) |
| Kein Weg nach `platform-main` ohne PR und grüne Pflicht-Checks, **auch nicht für die Merger-App** (Ruleset A hat keinen Bypass-Akteur) | GitHub-Ruleset „merge conditions“ | **C** (403, Ruleset fehlt) |
| Die Konfiguration beider Rulesets samt Bypass-Akteuren entspricht der Policy | Controller liest sie zu Beginn des Laufs **und unmittelbar vor jedem einzelnen Merge erneut**; ein echter Lauf mergt genau einen PR (`--verify-rulesets` auch einzeln, lesend) | **B** |
| Der Branch ist aktuell (Base-Race) | Ruleset „strikt“; zusätzlich prüft der Controller zweimal | Ruleset **C**, Controller **B** |
| Nur die Merger-Identität kann mergen, der Worker nicht | Ruleset „restrict updates“ (Regel `update`, Merger-App als einziger Bypass-Akteur, **nur dort**) | **C** |
| Worker hat kein Recht auf Workflows, Admin, Maintain | App-Rechte; der Runner prüft `admin`/`maintain` vor jeder Aktion | App **C**, Runner **B** |
| Worker und Merger sind getrennt vom Inhaber | zwei GitHub Apps | **C** (nicht eingerichtet, Runner nutzt noch das `gh` des Inhabers) |
| Worker ändert weder Gate, Workflows, Policy, Controller noch bestehende Tests; keine Test-Hilfsdateien | Pfad-Gate im PR-Diff, vom Controller selbst erneut ausgeführt | **B** (ohne Ruleset für andere Schreibberechtigte nicht durchgesetzt) |
| Checks stammen vom erwarteten Workflow, Ereignis, Head und Repository; Gate-Status stammt von `github-actions[bot]` | Controller | **B** |
| Unbekannter Zustand, fehlender Check, SHA-Wechsel, API-Fehler, fehlende Regeln, kein App-Token blockieren | Controller, 239 Tests | **B** |
| PR-Text, Labels und Branch-Namen begründen keine Berechtigung | Controller (Test mit gefälschten Labels und Text) | **B** |
| Controller und Policy sind inaktiv | `enabled: false`, `dry_run: true`, keine Worker, Workflow manuell, Job nur auf `platform-main` | **B** |
| Runner, Codex und Claude können weder die `gh`-Anmeldung des Inhabers noch einen Merger-Schlüssel lesen | getrennter macOS-Benutzer (Voraussetzung, [`AUTO_MERGE_IDENTITIES.md`](AUTO_MERGE_IDENTITIES.md) §5) und Isolationsprüfung 4a im Pilot; **noch nicht eingerichtet, nicht belegt** | **C**, bis 4a bestanden |
| Folge-Workflows nach einem Controller-Merge laufen | App-Token statt `github.token` | **C** |
| Fachliche Richtigkeit; Worker-Code (Quellcode und neue Testmodule) läuft in den Checks und könnte Ergebnisse beeinflussen | nicht durch Pfadregeln erzwingbar | **C**, nicht erzwingbar |

## 5. Aktivierung

Siehe [`AUTO_MERGE_ROLLOUT.md`](AUTO_MERGE_ROLLOUT.md) (Abschnitt 5, Aktivierungsvorschau). Reihenfolge in Kurzform: Plan oder
Sichtbarkeit entscheiden, Apps und Rulesets anlegen, getrennten macOS-Benutzer für den Runner einrichten, Negativversuche im Testrepository belegen (danach nur lesende Prüfungen im Produktionsrepository), Bootstrap-Merges, erster echter Gate-Lauf, Dry-Run-Matrix,
Isolationsprüfung 4a und Ende-zu-Ende-Pilot, dann die Aktivierungsänderung zur Freigabe vorlegen. **Stopp-Schalter:** `enabled: false` in der Policy, den
`schedule`-Trigger entfernen oder den Bypass der Merger-App im Ruleset „restrict updates“ entziehen.
