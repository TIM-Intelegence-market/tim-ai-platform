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

1. Beide Apps in den Einstellungen der Organisation `TIM-Intelegence-market` anlegen („Developer settings → GitHub Apps“),
   jeweils ohne Webhook, nur für „Only on this account“, auf dieses Repository installieren, Rechte wie in der Tabelle.
   Seit dem Umzug des Repositorys (2026-10-04) ist eine unter dem persönlichen Konto angelegte App mit „Only on this account“
   nicht mehr auf dem Repository installierbar.
2. Worker-Schlüssel im Schlüsselbund ablegen, Merger-Schlüssel als Actions-Secret hinterlegen. Keinen Schlüssel in Chat,
   Issue, PR oder Datei einfügen.
3. `worker_logins` in `.github/auto-merge-policy.json` erst bei der Aktivierung eintragen (siehe Rollout-Dokument).
4. Negativversuche der Rechte (**zuerst im Testrepository**, nur mit dem jeweiligen Token ausführen und die erwartete Ablehnung festhalten):
   Worker-Token versucht, auf `platform-main` zu pushen (muss abgelehnt werden), eine Datei unter `.github/workflows/` zu
   pushen (muss abgelehnt werden) und einen PR zu mergen (muss durch das Ruleset abgelehnt werden). Merger-Token versucht, einen PR mit rotem oder fehlendem Pflicht-Check, einen veralteten Branch oder ohne PR zu mergen
   beziehungsweise zu pushen (alles muss abgelehnt werden; die vollständige Liste steht in `AUTO_MERGE_RULESET.md`, Abschnitt 4).

## 5. Getrennter macOS-Benutzer für den Runner (Aktivierungsvoraussetzung)

Die Trennung der GitHub-Identitäten schützt nichts, solange Runner, Codex und Claude als **derselbe macOS-Benutzer** laufen wie
der Inhaber: Dieser Benutzer kann die `gh`-Anmeldung des Inhabers (`~/.config/gh/hosts.yml` oder Schlüsselbund-Eintrag `gh:github.com`)
und jeden lokal abgelegten Schlüssel lesen, und damit mit Inhaber- oder Admin-Rechten handeln. Der Token-Fix im Runner
(`agent_env`, keine Zugangsdaten an `codex`/`claude`) entfernt nur die *vererbte* Umgebung, nicht den Zugriff über das Dateisystem.

**Voraussetzung vor jeder Aktivierung (LaunchAgent, `schedule`, Auto-Merge bleiben bis dahin aus):**

1. Ein eigener, nicht administrativer macOS-Benutzer (Vorschlag `timrunner`, kein Mitglied von `admin`, keine `sudo`-Regel,
   kein automatischer Login, kein Dateifreigabe- oder Fernzugriff) führt Runner, `codex` und `claude` aus. Der Inhaber startet nichts davon
   unter seinem eigenen Benutzer.
2. Das Repository wird für diesen Benutzer **neu geklont** (eigenes Arbeitsverzeichnis, eigener `gh`-Konfigurationsordner, eigener Schlüsselbund).
   Der Worker-App-Schlüssel liegt ausschließlich im Schlüsselbund dieses Benutzers.
3. Der Inhaber-Benutzer schützt seine Daten: Home-Verzeichnis auf `700` (macOS-Standard erlaubt anderen Benutzern das Auflisten),
   `~/.config/gh` bleibt `700`, keine Schlüsseldateien in gemeinsam lesbaren Ordnern (`/Users/Shared`, `/tmp`, das Repository).
4. Der **Merger-Schlüssel** existiert nur als Actions-Secret von GitHub. Es gibt keine lokale Kopie (auch nicht „zur Sicherheit“,
   nicht im Downloads-Ordner, nicht im Passwortmanager des Runner-Benutzers). Sollte eine lokale Kopie unvermeidbar sein, gehört sie
   in den Schlüsselbund des Inhabers und gilt für den Pilot als „muss unlesbar sein“.
5. Der Runner-Benutzer ist weder Admin noch Maintainer des Repositorys und hat keine eigene `gh`-Anmeldung mit persönlichen Rechten
   (`gh auth status` im Runner-Benutzer zeigt nur den Worker-Token der Prozessumgebung).

Der Nachweis steht im Pilot ([`AUTO_MERGE_ROLLOUT.md`](AUTO_MERGE_ROLLOUT.md), Abschnitt 4a). Fällt eine Prüfung durch, bleibt der
LaunchAgent aus und es wird nichts aktiviert. Eingerichtet hat Claude diesen Benutzer nicht; die Einrichtung ist Handarbeit des Inhabers.
