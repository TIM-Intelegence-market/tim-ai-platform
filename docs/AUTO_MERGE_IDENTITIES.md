# Auto-Merge: Identitäten, Rechte und Schlüssel

**Status: Entwurf, nichts davon ist eingerichtet.** Das persönliche Admin-`gh`-Konto des Inhabers ist weder Worker noch Merger.
Der Runner arbeitet nur noch mit einer eigenen Worker-Identität (Patch P6 für PR #146); der Controller nur mit einer eigenen
Merger-Identität. Keine Zugangsdaten stehen in Git, in einer PR-Beschreibung oder in Logs.

## 1. Zwei getrennte Identitäten

| | **Worker** | **Merger** |
|---|---|---|
| Aufgabe | eigenen Branch `claude/issue-N-*` pushen, Draft-PR öffnen, Issue-Labels und -Kommentare setzen, PR-Branch aktualisieren | PRs nach `platform-main` mergen, die der Controller freigegeben hat |
| Typ (empfohlen) | **GitHub App** „TIM Worker“, nur auf diesem Repository installiert. Alternative: ein separates Maschinenkonto mit fein abgestuftem Token | **GitHub App** „TIM Merger“, nur auf diesem Repository installiert |
| Repository-Rechte der App | Contents: Read and write · Pull requests: Read and write · Issues: Read and write · Metadata: Read | Contents: Read and write · Pull requests: Read and write · Checks: Read · Commit statuses: Read · Actions: Read · **Administration: Read-only** (nur um Ruleset und Bypass-Konfiguration zu prüfen; kein Schreiben) · Metadata: Read |
| **Nie** gewähren | Workflows (damit kann der Worker keine `.github/workflows/**` pushen, GitHub lehnt das selbst ab), Actions, Administration, Commit statuses, Checks, Secrets, Environments | Workflows, Administration, Secrets, Issues |
| Ruleset-Rolle | **kein** Bypass | **einziger** Bypass-Akteur des Rulesets „platform-main restrict updates“ und **in keinem anderen**; im Ruleset „platform-main merge conditions“ (Pflicht-Checks) steht kein Bypass-Akteur |
| Erkennung | Autor-Login `tim-worker[bot]` (Eintrag `worker_logins` der Merge-Policy) | führt den Merge aus; der Controller verlangt `TIM_MERGER_TOKEN_KIND=app` |
| Token-/Schlüsselort | privater Schlüssel (`.pem`) im **macOS-Schlüsselbund** des Rechners, auf dem der Runner läuft; der Launcher holt ihn, erzeugt ein Installations-Token (läuft nach ca. 1 Stunde ab) und setzt nur `TIM_WORKER_GH_TOKEN` und `TIM_WORKER_LOGIN` für den Runner-Prozess | privater Schlüssel als **Actions-Secret** `TIM_MERGER_APP_PRIVATE_KEY` und App-ID als Repository-Variable `TIM_MERGER_APP_ID`; `actions/create-github-app-token` erzeugt pro Lauf ein Kurzzeit-Token |
| Rotation | Schlüssel alle 90 Tage: neuen Schlüssel erzeugen, im Schlüsselbund ersetzen, alten in den App-Einstellungen löschen | wie links; Secret ersetzen, alten Schlüssel löschen |
| Widerruf | App-Installation aussetzen oder Schlüssel löschen; Wirkung sofort, laufende Installations-Token enden spätestens nach 1 Stunde | wie links; zusätzlich Bypass-Eintrag im Ruleset entfernen oder `enabled: false` setzen |

Der Worker ist **nicht** der Inhaber und darf weder Admin- noch Maintain-Rechte haben. Der Runner prüft das vor jeder
schreibenden Aktion (GraphQL-`viewer` gleich `TIM_WORKER_LOGIN`; `permissions.admin` und `permissions.maintain` müssen `false`
sein; fehlen die Angaben, bricht er ab). Das ist ein Prüfschritt im Runner und **keine** GitHub-seitige Durchsetzung; ob GitHub
diese Felder für Installations-Token liefert, ist im Pilot zu bestätigen.

## 2. Was der Controller-Workflow an PR-Code abgibt: nichts

Der Controller-Job läuft nur auf `platform-main`, checkt nur `platform-main` aus und holt PR-Köpfe ausschließlich als
Git-Objekte (`git fetch refs/pull/N/head`), um deren Diff zu lesen. PR-Code wird nie installiert oder ausgeführt. Das
Merger-Token steht nur diesem Job zur Verfügung; Workflows aus PR-Branches des Workers kann es nicht geben, weil dem Worker
das Recht „Workflows“ fehlt und das Pfad-Gate Änderungen unter `.github/` ablehnt.

## 3. Löst `github.token` die gewünschten Folge-Workflows aus?

**Nein, nach meinem Kenntnisstand nicht** (dokumentiertes GitHub-Verhalten: Ereignisse, die mit `GITHUB_TOKEN` ausgelöst werden,
starten keine neuen Workflow-Läufe, Ausnahme `workflow_dispatch` und `repository_dispatch`; `docs.github.com` ist in meiner
Umgebung gesperrt, deshalb nicht selbst nachgelesen, im Pilot zu bestätigen). Ein Merge mit `github.token` würde also zum
Beispiel `ci.yml` bei `push` auf `platform-main` nicht auslösen. Außerdem kann `github-actions[bot]` nicht als Ruleset-Bypass-Akteur
dienen. Deshalb verlangt der Controller für echte Merges ein **App-Token** (`require_app_token: true`; Workflow-Schritt
`create-github-app-token`, sobald `TIM_MERGER_APP_ID` gesetzt ist) und blockiert mit `github.token` jeden echten Merge.
Vor der Aktivierung ist `actions/create-github-app-token` auf einen geprüften Commit zu pinnen.

## 4. Einrichtung (alles Handarbeit des Inhabers, nichts davon hat Claude getan)

1. Beide Apps unter den persönlichen Einstellungen anlegen („Developer settings → GitHub Apps“), jeweils ohne Webhook,
   nur für „Only on this account“, auf dieses Repository installieren, Rechte wie in der Tabelle.
2. Worker-Schlüssel im Schlüsselbund ablegen, Merger-Schlüssel als Actions-Secret hinterlegen. Keinen Schlüssel in Chat,
   Issue, PR oder Datei einfügen.
3. `worker_logins` in `.github/auto-merge-policy.json` erst bei der Aktivierung eintragen (siehe Rollout-Dokument).
4. Negativversuche der Rechte (nur mit dem jeweiligen Token ausführen und die erwartete Ablehnung festhalten):
   Worker-Token versucht, auf `platform-main` zu pushen (muss abgelehnt werden), eine Datei unter `.github/workflows/` zu
   pushen (muss abgelehnt werden) und einen PR zu mergen (muss durch das Ruleset abgelehnt werden). Merger-Token versucht, einen PR mit rotem oder fehlendem Pflicht-Check, einen veralteten Branch oder ohne PR zu mergen
   beziehungsweise zu pushen (alles muss abgelehnt werden; die vollständige Liste steht in `AUTO_MERGE_RULESET.md`, Abschnitt 4).
