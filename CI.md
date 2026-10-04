# CI.md – Merge-Regeln für Pipeline-PRs

Beschreibung für Menschen und Agenten. **Durchgesetzt wird nichts durch diese Datei**, sondern durch
GitHub (Ruleset) und die Checks unten. Stand: Entwurf, Auto-Merge ist **nicht** aktiv.

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
  `src/database/`, `CLAUDE.md`, `AGENTS.md`, `CI.md`, `conftest.py`, `pytest.ini`, Abhängigkeitslisten,
  `docker-compose.yml`, `.gitattributes`, `.gitmodules`.
- Nur Status A/M/D, nur reguläre Dateien (`100644`); keine Symlinks, Submodule, Rechte- oder Typwechsel.
- Keine Löschung unter `tests/`, höchstens 40 Dateien, kein leerer Diff.
- Bei jedem Fehler oder unlesbarer Policy: Check schlägt fehl (fail-closed).

Der Check gilt **nur** für Branches nach dem Schema `claude/issue-N-…`. Ein Worker, der anders benennt,
fällt aus dem Gate. Deshalb darf eine spätere Automatik nie anhand des Branch-Namens entscheiden,
sondern nur Menschen oder eine getrennte Merge-Identität nehmen PRs in den Merge auf.

## Freigaberegel (entschieden: Mensch genehmigt, GitHub merged)

Pflicht-Review plus Pflicht-Checks `PR gate` und `test` im Ruleset auf `platform-main`; danach darf ein
Mensch Auto-Merge aktivieren. `TIM full suite` wird **erst später** Pflicht-Check, nachdem die rote Suite
repariert ist (eigenes Paket); bis dahin ist sie nur Information. Merge ohne Menschen gibt es nicht. Produktivmodus und
Auto-Merge der Pipeline bleiben ausgeschaltet.

**Noch nicht technisch erzwungen:** Branch-Protection und Rulesets liefern für dieses private Repository
derzeit HTTP 403. Bis das Ruleset steht, ist die Regel eine Verabredung, kein Schutz. Außerdem ist
`TIM full suite` weiterhin rot und darf deshalb noch nicht Pflicht-Check sein.

## Offene Punkte, erst durch den ersten GitHub-Lauf klärbar

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

## Einmalig durch den Repository-Inhaber zu tun

1. Dieses Gate erst nach dem Merge nach `platform-main` aktiv: `pull_request_target` nutzt die Workflow-Datei des Base-Branches.
2. Ruleset auf `platform-main`: Review erforderlich, Checks `PR gate` und `test` erforderlich (`TIM full suite` erst nach Reparatur ergänzen), Force-Push gesperrt.
3. Worker-Konto/-Token ohne Schreibrecht auf `platform-main`.
4. Negativtest: Test-PR mit Änderung in `.github/` muss am `PR gate` scheitern.
