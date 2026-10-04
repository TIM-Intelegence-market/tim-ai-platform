# Auto-Merge: Bootstrap, Dry-Run-Test, Pilot und Aktivierungsvorschau

**Nichts davon ist ausgeführt.** Jeder Schritt mit „Inhaber“ ist Ihre Handlung; Claude merged keinen Bootstrap-PR und ändert keine
Repository-Einstellung.

## 1. Reihenfolge und Abhängigkeiten der PRs

| Schritt | PR | Abhängigkeit | Wer | Hinweis |
|---|---|---|---|---|
| 1 | #149 Bytecode-Fix | keine | Inhaber | unabhängig, grün; erst danach ist `test_complete_engine_repair_evidence_allows_fixed` stabil |
| 2 | #147 Gate (Bootstrap) | keine | Inhaber, **manuell geprüft** | `pull_request_target` nutzt die Workflow-Datei des Base-Branches; erst nach dem Merge kann der Workflow in Actions laufen |
| 3 | #150 Controller (gestapelt auf #147) | Schritt 2 | Inhaber, **manuell geprüft** | vorher auf den neuen `platform-main` bringen (siehe unten), damit keine Gate-Datei doppelt eingeführt wird |
| 4 | #146 Runner (Codex-Branch) | Runner-Patch P6 zuerst anwenden | Codex/Inhaber | liefert den Check `TIM full suite`; ohne ihn blockiert der Controller dauerhaft |
| 5 | erster echter Gate-Lauf, Dry-Run-Matrix, Pilot | Schritte 1 bis 4 | Inhaber | Abschnitte 2 bis 4 |
| 6 | GitHub-Plan, Rulesets, Identitäten, Negativversuche **zuerst im Testrepository** | Entscheidung zum Plan | Inhaber | siehe `AUTO_MERGE_RULESET.md` (Abschnitt 4), `rulesets/test-repo/README.md` und `AUTO_MERGE_IDENTITIES.md` |
| 7 | Aktivierung | alles oben belegt | Inhaber, nach ausdrücklichem Go | Abschnitt 5 |

**#150 nach dem Merge von #147 auf den neuen Stand bringen.** #150 liegt auf dem Branch von #147 (Head `023ccec`). Wurde #147 per
*Squash* oder *Rebase* gemerged, stehen dessen Commits nicht mehr als dieselben auf `platform-main`; ein einfacher Merge würde die
Gate-Dateien doppelt und mit Konflikten einführen. Deshalb nur die Commits von #150 übertragen:

```bash
git fetch origin
git checkout claude/auto-merge-controller
git rebase --onto origin/platform-main 023ccec      # nur die Commits nach #147 mitnehmen
git push --force-with-lease origin claude/auto-merge-controller
# Basis des PR in GitHub auf platform-main umstellen, Tests und CI erneut laufen lassen
```

Wurde #147 per Merge-Commit gemerged, genügt `git merge origin/platform-main`. In beiden Fällen: erst die Tests
(`python -m pytest tests/test_pr_gate.py tests/test_auto_merge_controller.py -q`) und die CI abwarten, dann mergen.
Der Rebase überschreibt Verlauf auf dem eigenen Branch von #150 und braucht deshalb Ihre ausdrückliche Freigabe.

## 2. Erster echter Gate-Lauf (nach Schritt 2 und 3)

Mit einem harmlosen Test-PR von einem Branch `claude/issue-<N>-gate-pilot` gegen `platform-main`. Belegen und mit Actions-Link
eintragen:

| Frage | Erwartung | Beleg (Link) |
|---|---|---|
| Läuft `git fetch refs/pull/N/head` im privaten Repo mit den Standard-Zugangsdaten? | Schritt „Fetch PR head…“ grün | offen |
| Entspricht der gegatete Stand genau `github.event.pull_request.head.sha`? | Ausgabe ohne „PR head moved“ | offen |
| Steht der Commit-Status `pr-gate/head` auf der **Head-SHA** des PR (Erst `pending`, dann `success`), erstellt von `github-actions[bot]`? | `GET /repos/{repo}/commits/{sha}/status` zeigt genau einen Eintrag, Ersteller `github-actions[bot]`, `target_url` auf den Gate-Lauf | offen |
| Zählt `pr-gate/head` als Pflicht-Check des PR (sobald das Ruleset existiert)? | PR zeigt den Kontext als erforderlich und erfüllt | offen |
| Wird `test` an die Head-SHA gebunden und trägt der Lauf Pfad `.github/workflows/ci.yml`, Ereignis `pull_request`? | `GET /repos/{repo}/actions/runs/{id}` passt | offen |

## 3. Controller im Dry-Run (manuell, `enabled: true`, `dry_run: true`, `require_rulesets: false`)

Der Workflow liest Policy und Gate immer aus `platform-main`. Für den Dry-Run ist deshalb eine **eigene, geprüfte Änderung** an
`.github/auto-merge-policy.json` auf `platform-main` nötig: `enabled: true`, `dry_run: true`, `worker_logins` auf den Login der
Worker-Identität, `require_rulesets: false` (solange es kein Ruleset gibt). Das ist ungefährlich, weil `dry_run: true` bleibt: Der
Code verweigert eine Policy, die echte Merges erlaubt, ohne dass `require_rulesets`, `require_app_token` und eine `merger_app_id` gesetzt sind (getestet), und
ein Dry-Run schreibt nichts außer dem Log. Start über „Actions → Auto-merge controller → Run workflow“ auf `platform-main`. Danach die
Änderung zurücknehmen oder durch die Aktivierungsänderung (Abschnitt 5) ersetzen. Für jeden Fall Ergebnis und Actions-Link eintragen:

| Nr. | Fall | So erzeugen | Erwartetes Ergebnis | Tatsächlich | Link |
|---|---|---|---|---|---|
| 1 | zulässiger Draft-PR | Worker-PR, alle Checks grün | `would-mark-ready` | offen | offen |
| 2 | Ready-PR | Fall 1 von Hand auf „Ready“ | `would-merge` | offen | offen |
| 3 | geänderter Head | nach dem Start der Prüfung einen Commit auf den PR-Branch pushen | `blocked` (Head ändert sich oder Check noch laufend) | offen | offen |
| 4 | veralteter Base-Stand | `platform-main` weiterlaufen lassen, PR nicht aktualisieren | `blocked` („not up to date“) | offen | offen |
| 5 | manipulierte Test-Hilfsdatei | PR mit neuer `tests/conftest.py` | `blocked` („gate: … protected path“) | offen | offen |
| 6 | geänderter bestehender Test | PR, der eine vorhandene Testdatei ändert | `blocked` („existing files here are protected“) | offen | offen |
| 7 | fehlender Pflicht-Check | PR, dessen `test` noch fehlt oder dessen `TIM full suite` fehlschlägt | `blocked` | offen | offen |
| 8 | falscher Autor | PR vom Inhaber auf Branch `claude/issue-<N>-x` | nicht bewertet (keine Worker-PR) | offen | offen |
| 9 | Fork | PR aus einem Fork mit passendem Branch-Namen | nicht bewertet oder `blocked` („not in this repository“) | offen | offen |
| 10 | API-Fehler | in Actions nicht gefahrlos erzeugbar; belegt durch die Unit-Tests (`test_api_errors_while_evaluating_block`, `test_listing_failure_fails_the_run_and_merges_nothing`) | `blocked` oder Lauf rot | durch Tests belegt | `tests/test_auto_merge_controller.py` |
| 11 | gleichnamiger Job aus anderem Workflow | in Actions nicht isolierbar (das Gate lehnt Änderungen unter `.github/` ohnehin ab); belegt durch `test_a_job_named_test_from_another_workflow_is_ambiguous_and_blocks` | `blocked` („ambiguous“) | durch Test belegt | `tests/test_auto_merge_controller.py` |

## 4. Ende-zu-Ende-Pilot des gehärteten Issue-Runners

Der LaunchAgent bleibt **während des Pilots gestoppt**; der Runner wird von Hand gestartet.

0. Getrennter macOS-Benutzer für den Runner eingerichtet ([`AUTO_MERGE_IDENTITIES.md`](AUTO_MERGE_IDENTITIES.md), Abschnitt 5) und die
   Isolationsprüfung 4a **bestanden**. Ohne bestandene Prüfung 4a beginnt der Pilot nicht.
1. Runner-Patch P6 auf PR #146 angewendet und gemerged oder lokal ausgecheckt; Worker-App eingerichtet, `TIM_WORKER_LOGIN` und
   `TIM_WORKER_GH_TOKEN` nur im Prozess gesetzt.
2. Ein harmloses Issue mit `priority:p1`, `status:ready` und `agent:pilot` (z. B. eine Doku-Ergänzung) anlegen.
3. `python3 scripts/github_issue_pipeline.py --dry-run --mode pilot` (wählt das Issue, schreibt nichts), danach ohne `--dry-run`.
4. Erwartet: Codex-Analysekommentar, Claude-Dateiänderung in `claude/issue-N-*`, **Draft-PR** vom Worker-Autor, `pr-gate/head`
   und die beiden Checks laufen. Der Controller (Dry-Run) meldet `would-mark-ready`.
5. Abbruchtest: den Runner mitten im Lauf beenden und erneut starten; erwartet sind Wiederaufnahme ohne neuen Claude-Lauf
   (Fälle „committed, unpushed“ und „pushed“ des Patches) oder ein sauberer Stopp mit Hinweis.
6. `--maintain` nach einem Base-Update: der veraltete PR wird aktualisiert und neu geprüft.

## 4a. Isolationsprüfung: Runner-Benutzer, Inhaber-Anmeldung und Merger-Schlüssel

Ziel: Weder Claude noch Codex (beide laufen als Runner-Benutzer `timrunner`) können die `gh`-Anmeldung des Inhabers oder den
Merger-Schlüssel lesen. Die Prüfung gibt **nie Inhalte aus**, nur Exit-Codes und Berechtigungsmeldungen; Dateien werden nicht mit `cat` geöffnet.
`OWNER` steht für den Kurznamen des Inhaber-Benutzers, `MERGER_KEY` für den Pfad, an dem eine lokale Merger-Schlüsseldatei liegen *würde*.

Teil 1: als Runner-Benutzer in einer Terminal-Sitzung (`sudo -u timrunner -i` vom Inhaber aus, oder direkt angemeldet):

```bash
OWNER=<kurzname-des-inhabers>; MERGER_KEY=<pfad-einer-moeglichen-lokalen-merger-schluesseldatei>
id -Gn | tr ' ' '\n' | grep -qx admin && echo "FAIL: Runner-Benutzer ist in der Gruppe admin"
sudo -n true 2>/dev/null && echo "FAIL: sudo ohne Passwort möglich"
for f in "/Users/$OWNER/.config/gh/hosts.yml" "/Users/$OWNER/.config/gh/config.yml" "$MERGER_KEY"; do
  test -r "$f" && echo "FAIL: lesbar: $f" || echo "ok: nicht lesbar: $f"
done
ls "/Users/$OWNER" >/dev/null 2>&1 && echo "FAIL: Home des Inhabers auflistbar" || echo "ok: Home nicht auflistbar"
security find-generic-password -s "gh:github.com" >/dev/null 2>&1 && echo "FAIL: gh-Eintrag im Schlüsselbund des Runner-Benutzers" || echo "ok: kein gh-Eintrag"
security find-generic-password -s "gh:github.com" "/Users/$OWNER/Library/Keychains/login.keychain-db" >/dev/null 2>&1 && echo "FAIL: Schlüsselbund des Inhabers lesbar" || echo "ok: Schlüsselbund des Inhabers nicht lesbar"
env -u GH_TOKEN -u GITHUB_TOKEN -u TIM_WORKER_GH_TOKEN gh auth status >/dev/null 2>&1 && echo "FAIL: persönliche gh-Anmeldung im Runner-Benutzer" || echo "ok: keine persönliche gh-Anmeldung"
```

Teil 2: dieselben Zugriffe **durch die Agenten selbst**, damit die Sandbox und die Werkzeugrechte mitgeprüft werden. Ein harmloses
Pilot-Issue weist Codex (Analyse) und Claude (Umsetzung) an, nur die oben stehenden `test -r`-Zeilen auszuführen und Treffer zu melden
(keinen Dateiinhalt). Erwartet: jede Zeile „nicht lesbar“, kein Treffer, kein Fehler im Pilot-Lauf selbst. Zusätzlich im Runner-Protokoll
prüfen, dass kein Zugangsdaten-Muster erscheint (`grep -Ei 'ghp_|ghs_|github_pat_|BEGIN .*PRIVATE KEY' <logdatei>` muss leer sein).

Teil 3: Gegenprobe, dass der Test etwas misst: als Inhaber-Benutzer dieselben `test -r`-Zeilen ausführen; die Inhaber-Dateien müssen dort
lesbar sein (sonst prüft der Test einen falschen Pfad und ist wertlos).

Beleg ablegen: Ausgabe der drei Teile mit Datum, macOS-Version und Benutzernamen im Pilotprotokoll. **Jedes „FAIL“ stoppt den Pilot;**
LaunchAgent und Auto-Merge bleiben aus, bis die Ursache behoben und die Prüfung vollständig wiederholt ist. Dieser Nachweis ist
Teil der Aktivierungsfreigabe (Abschnitt 5) und gilt nur für den geprüften Stand (nach OS-Update, neuem Schlüssel oder geänderten Rechten wiederholen).

## 5. Aktivierungsvorschau (nicht angewendet, nur zur Freigabe)

Erst wenn Rulesets, getrennte Identitäten, alle Negativversuche (im Testrepository, dazu der lesende Beleg im Produktionsrepository), der getrennte macOS-Benutzer mit bestandener Isolationsprüfung 4a und der Pilot belegt sind, würde eine **eigene** Änderung
folgende Punkte enthalten. Sie wird **vor Ausführung zur Freigabe vorgelegt** und nicht vorab committet.

`.github/auto-merge-policy.json`:

```diff
-  "enabled": false,
-  "dry_run": true,
+  "enabled": true,
+  "dry_run": false,
-  "worker_logins": [],
+  "worker_logins": ["tim-worker[bot]"],
```

`.github/workflows/auto-merge-controller.yml`: den Block `schedule:` (zurzeit auskommentiert) einkommentieren und
`actions/create-github-app-token` auf einen geprüften Commit pinnen.

`CI.md` und `CLAUDE.md`: Regel (b) „Mensch genehmigt, GitHub merged“ durch „vollautomatisch ohne menschliches Review nach den
Schutzregeln“ ersetzen; das Gate-Regelwerk um die Erweiterungen dieses Branches ergänzen (neue Testdateien nur als `test_*.py`,
bestehende Tests geschützt, Größenlimit, Commit-Status `pr-gate/head`); die Garantie-Matrix mit dem beobachteten Stand aktualisieren.

Der LaunchAgent des Runners wird erst danach in einer weiteren, ebenfalls freizugebenden Änderung gestartet (`production`).
