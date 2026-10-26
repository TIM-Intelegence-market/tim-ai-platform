# CI.md – Merge-Regeln für Pipeline-PRs

Beschreibung für Menschen und Agenten. **Durchgesetzt wird nichts durch diese Datei**, sondern durch
GitHub (Ruleset) und die Checks unten. Stand 25.10.2026: Ruleset aktiv, Auto-Merge ist **nicht** aktiv.

## Grundsatz

Ein PR, den ein Worker (Claude) erzeugt hat, darf nur von einer Stelle zugelassen werden, die der Worker
nicht kontrolliert. Labels, Marker im PR-Text, Branch-Namen und ein Check, den der PR selbst definiert,
beweisen weder Herkunft noch Freigabe.

## Vertrauensgrenzen

| Was | Wer setzt es durch | Kann der Worker es ändern? |
|---|---|---|
| Pfad- und Modus-Gate (`PR gate`) | `.github/workflows/pr-gate.yml` per `pull_request_target`, läuft aus dem Base-Stand | nein (Pfad ist gesperrt, Workflow kommt aus `platform-main`) |
| Policy (`.github/pr-gate-policy.json`) | wird aus dem Base-Stand gelesen | nein |
| Testlauf (`TIM full suite`, `test`) | `pull_request`, läuft mit dem Code des PR | **ja**, deshalb allein kein Freigabebeweis |
| Review und Merge | Mensch (Ruleset: Pflicht-Review, Pflicht-Checks) | nein, sofern der Worker kein Schreibrecht auf `platform-main` hat |

## Was das PR gate prüft (nur Branches `claude/issue-N-…`)

- Jede geänderte Datei liegt unter `src/`, `tests/` oder `docs/`.
- Gesperrt, auch darunter: `.github/`, `.claude/`, `scripts/`, `config/`, `schemas/`, `ops/`, `artifacts/`,
  `src/database/`, `src/tim_incident/`, `src/__init__.py`, `CLAUDE.md`, `AGENTS.md`, `CI.md`, `conftest.py`,
  `pytest.ini`, Abhängigkeitslisten, `docker-compose.yml`, `.gitattributes`, `.gitmodules`.
- `src/tim_incident/` ist gesperrt, weil dort die Schutzlogik des Vorfall-Melders liegt (Redaktion, Schreibschutz,
  Label-Allowlist); ein Worker darf sie nicht abschwächen, auch nicht beim Beheben eines Vorfalls (`docs/TIM_CHECKUP.md`).
  Ebenso gesperrt ist `src/__init__.py`: Es läuft bei jedem Import im Checkup-Prozess, der den App-Schlüssel hält.
- Nicht gesperrt, aber im selben Prozess geladen: `src/task_governance/` (samt `__init__.py`, `engine_bridge.py`,
  `legacy.py`). Eine Änderung dort wirkt auf den Melder; solche PRs nur nach genauem Review mergen.
- Nur Status A/M/D, nur reguläre Dateien (`100644`); keine Symlinks, Submodule, Rechte- oder Typwechsel.
- Keine Löschung unter `tests/`, höchstens 40 Dateien, höchstens 1 MB je geänderter Datei, kein leerer Diff.
- Läuft auch bei `edited` (zum Beispiel Wechsel des Ziel-Branches), nicht nur bei neuen Commits.
- Bei jedem Fehler oder unlesbarer Policy: Check schlägt fehl (fail-closed).

Der Check gilt **nur** für Branches nach dem Schema `claude/issue-N-…`. Ein Worker, der anders benennt,
fällt aus dem Gate. Deshalb darf eine spätere Automatik nie anhand des Branch-Namens entscheiden,
sondern nur Menschen oder eine getrennte Merge-Identität nehmen PRs in den Merge auf.

## Freigaberegel (Stand 25.10.2026: Mensch sagt „merge“, GitHub prüft)

Das Ruleset „platform-main merge conditions“ steht seit 13.10.2026 und hat keine Bypass-Akteure, auch keine Admins.
Pflicht-Checks sind `test` (`.github/workflows/ci.yml`) und `PR gate` (`.github/workflows/pr-gate.yml`), beide auf dem
selbst gehosteten Runner `mac-mini-tim`. `TIM full suite` und der Auto-Merge-Controller laufen nur von Hand
(`workflow_dispatch`) und sind keine Pflicht.

Zwei Schalter sind bewusst **aus**, beide auf Uzis Entscheidung:

- **Review-Pflicht aus.** Ein grüner PR kann technisch ohne zweites Augenpaar gemergt werden. Die Schranke ist Uzis
  ausdrückliches „merge“ (Threads liefern PRs merge-fertig, mergen aber nicht von selbst; „go“ heißt bauen). Für
  kritische Pfade (Journal-Logik, Kostenmodell, `src/database/` u. a.) stehen Uzi und Chris seit 26.10.2026 als
  Code-Eigner in `.github/CODEOWNERS` (R1); Pflicht wird es erst mit dem Ruleset-Schalter „Review von Code-Eignern“ (R2, Uzi).
- **„Branch muss aktuell sein“ (strict) aus seit 25.10.2026.** Ein PR kann grün sein gegen einen älteren Stand von
  `platform-main`. Deshalb nach jedem Merge den Push-Lauf von `test` auf `platform-main` ansehen; ein roter Lauf dort
  wird sofort repariert; der Job `report-red-main` in `ci.yml` öffnet dafür ein Issue mit Label `ci-red` (oder kommentiert das offene).

Vor der Meldung „merge-fertig“ bringt der Thread seinen PR auf den aktuellen Stand von `platform-main`, löst Konflikte
und lässt die volle Suite in der Cloud laufen (`pytest -m "not local_env and not serial" -n 4`, danach
`-m "not local_env and serial"`). Produktivmodus und Auto-Merge der Pipeline bleiben ausgeschaltet.

## Offene Punkte beim ersten GitHub-Lauf (historisch, 2025/26 geklärt)

Das Gate läuft seit Oktober 2026 produktiv auf `platform-main`; die Punkte bleiben als Entwurfsgeschichte stehen.

- Der erste Merge dieses Gates nach `platform-main` ist ein manuell geprüfter Bootstrap-Schritt, weil
  `pull_request_target` nur die Workflow-Datei des Base-Branches nutzt.
- Ob der `pull_request_target`-Check als Required Check für den aktuellen PR-Commit zählt, ist unbestätigt:
  der Event läuft auf dem Base-Stand, GitHub verlangt Checks für den neuesten PR-Commit. Falls nicht, ist die
  Ausweichlösung ein Commit-Status auf der PR-Head-SHA (braucht `statuses: write`, weiterhin ohne PR-Code).
- Ob `git fetch` auf `refs/pull/N/head` im privaten Repo mit den Standard-Zugangsdaten läuft, zeigt ebenfalls erst der Lauf.
  Der Workflow bricht ab, wenn der geholte Stand nicht der auslösenden `head.sha` entspricht.

## Nicht Teil dieser Datei

- Aktivierung von LaunchAgent oder Produktivmodus der Pipeline.
- Änderungen an Repository-Einstellungen, Secrets oder Rechten (macht der Repository-Inhaber).
- Reparatur der roten `TIM full suite` (eigenes Paket).

## Durch den Repository-Inhaber erledigt oder offen

1. Gate nach `platform-main` gemergt und aktiv: erledigt.
2. Ruleset auf `platform-main` mit Checks `PR gate` und `test`, Force-Push gesperrt: erledigt (13.10.2026). Review-Pflicht
   und strict: bewusst aus (siehe Freigaberegel). Sicherung des Rulesets liegt auf dem Mac.
3. Worker-Konto `apoman74-art` nur mit Schreibrecht, kein Merge-Recht auf `platform-main`: erledigt.
4. Negativtest (Änderung in `.github/` scheitert am `PR gate`): nicht dokumentiert, offen.
