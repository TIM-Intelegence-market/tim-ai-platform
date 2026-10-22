# T11: Runner-, Agenten- und Zugriffsgrenzen (Entwurf)

Stand 22.10.2026, aus Workflows, Docs und Projektnotizen. Zone A/B; die Umstellung (Abschnitt 4) ist Zone C.

## 1. Wer darf heute was

| Akteur | Rechte | Vertrauensgrenze | Beleg |
|---|---|---|---|
| PR-Testjob (`ci.yml`) | führt beliebigen PR-Code als `timrunner` auf dem Mac aus; Postgres 16 auf 5434 (Test-DB), Netz | läuft auf dem Kampagnen-Mac; `timrunner` ohne Admin; Arbeitsordner bleibt zwischen Läufen | ci.yml, CI_SELF_HOSTED_RUNNER.md [V] |
| PR gate (`pr-gate.yml`) | setzt den Pflichtstatus `PR gate` mit `statuses: write` | **derselbe Runner, derselbe Benutzer** wie der Testjob | pr-gate.yml:19 [V] |
| Priority Board (`tim-priority-board.yml`) | schreibt Issue-Board | gleicher Runner | [V] |
| Issue-Worker (Qwen) | GitHub-Konto apoman74-art, nur Write; erzeugt Branches `claude/issue-*`; darf laut Uzi (12.10.) genehmigen und mergen | Pfadsperren über das Gate (`pr-gate-policy.json`) | [N], Policy [V] |
| Codex (ChatGPT) | über GitHub-Connector, Branches `codex/*` | Gate-Policy gilt **nicht** (Regex nur `claude/issue-*`) | pr-gate-policy.json [V] |
| Cloud-Threads (Claude) | Branches `claude/project-thread-*`, können mergen | Gate-Policy gilt nicht | [V]/[N] |
| Chris (fleckbarti-ai) | Admin im Repo; eigene Claude-Sitzungen | Ruleset ohne Bypass, auch für Admins | [N] |
| Modelle (Ollama, Qwen) | lokal auf dem Mac | keine Tool-Rechte außerhalb des Workers | [N] |
| Ruleset `platform-main merge conditions` | Pflichtchecks `test`, `PR gate`, Branch aktuell; keine Bypass-Akteure | serverseitig | [N] |

## 2. Risiko aus der geteilten Identität (Codex/Claude H3)

Ein PR-Testjob läuft mit denselben Rechten wie der Gate-Job. Er könnte (a) das Runner-Verzeichnis oder
`~timrunner/.gitconfig` so verändern, dass ein späterer Gate-Lauf anderen Code prüft oder einen Status fälscht,
(b) das Runner-Token aus dem Prozessspeicher oder `.runner`-Dateien lesen, (c) den Kampagnen-Mac auslasten.
Das ist ein *Risiko aus Konfiguration*; ein Angriff wurde nicht reproduziert und wird hier nicht reproduziert.
Dämpfung heute: privates Repo, keine Forks, Auto-Merge aus, Merge nur auf Uzis Wort, `timrunner` ohne Admin.

## 3. Lücke in der Gate-Policy

`applies_to_branch_regex` erfasst nur Worker-Branches. Codex- und Claude-Branches können Pfade unter `.github/`,
`scripts/`, `ops/` ändern, ohne dass das Gate es sperrt. Das war Absicht (menschlich betreute Agenten), muss aber
im Dossier als bewusste Ausnahme stehen. Vorschlag: zweite, mildere Policy für `codex/*` und `claude/*`
(mindestens `.github/workflows/` und `pr-gate-policy.json` selbst gesperrt), damit kein Agent das Gate umschreibt.

## 4. Umstellungsentwurf (nicht während der Kampagne)

**Option A, eigener Gate-Runner:** zweiter Runner-Dienst auf dem Mac unter einem neuen macOS-Benutzer `timgate`
(ohne Admin, ohne Zugriff auf `~timrunner`), Label `tim-gate`; `pr-gate.yml` bekommt `runs-on: [self-hosted,
macOS, tim-gate]`. Der Gate-Job braucht nur `git` und Python ohne Abhängigkeiten. Rückweg: Label zurücksetzen.

**Option B, serverseitige Regel:** GitHub-Ruleset „restrict file paths“ (in der Organisation verfügbar je Plan).
Dann entfällt der Gate-Job als Pflichtcheck; die Pfadliste wandert ins Ruleset. Rückweg: Ruleset deaktivieren.
Vorteil: kein Code auf dem Mac entscheidet mehr über die Freigabe. Zu prüfen, ob der Organisationsplan das kann.

**Option C, gehosteter Runner für das Gate:** erst wieder möglich, wenn Actions-Minuten vorhanden sind.

Empfehlung: B prüfen; wenn nicht möglich, A. Keine bestehende Schutzregel wird für die Umstellung abgeschaltet.

## 5. Schreibbefugnisse und Auto-Merge

Inventar: Uzi (Owner), Chris (Admin), apoman74-art (Write, Worker), Codex über Connector mit Uzis Identität,
Cloud-Threads mit Uzis Identität. Auto-Merge-Controller ist aus (`enabled false`, `dry_run true`); PR #333 (Draft)
führt Worker und Controller auf einen Pfad, bleibt Draft. Uzis Erlaubnis vom 12.10. für den Worker ist eng
(Worker-Issues) und wird nicht als allgemeine Merge-Freigabe gelesen. Für T11 wird keine neue Merge-Automatik aktiviert.

## 6. Router, Tailnet, Wiederzugriff

Router (pfSense) und Tailnet `tailnet.example.ts.net` laufen über Chris' Konto. Fällt Chris aus, verliert Uzi den
Fernzugang und die Möglichkeit, den Router neu zu starten. Vorschlag: Uzi als zweiten Admin eintragen (Tailscale
Admin-Konsole, Router-Benutzer), Zugangsdaten im macOS-Schlüsselbund, ein Blatt „wer kann was neu starten“. Das ist
eine Entscheidung von Chris und Uzi, keine Maßnahme dieses Branches.

## 7. Home-Git und Pinning (nur lesend zu prüfen, auf dem Mac)

- `~/.git` existiert (get_device_info). Prüfen: `git -C ~ remote -v`, `git -C ~ log -1`, `.gitignore`. Weder `.git`
  noch Historie löschen, bevor Zweck und Remote bekannt sind. Risiko: ein `git add .` im Home erfasst Dokumente und
  Konfiguration; Geheimnisse liegen laut Regel nur im Schlüsselbund.
- Actions: `codecov-action` per SHA gepinnt, `actions/checkout@v7` und `upload-artifact@v7` per Tag. Vorschlag: alle
  per SHA mit Kommentar der Version. Codecov-Upload scheitert still (`continue-on-error`); entweder Token setzen
  oder den Schritt entfernen. CodeQL läuft nachts, Ergebnisse werden nach Beleglage nicht ausgewertet; ein
  monatlicher Blick in „Security → Code scanning“ gehört zur Betriebsroutine.

## 8. Abnahme T11

PR-Code kann den Pflichtstatus nicht beeinflussen (A oder B umgesetzt), Betreiberzugang zu Netz und Tailnet
liegt bei zwei Personen, Policy-Lücke für `codex/*`/`claude/*` geschlossen oder als bewusste Ausnahme dokumentiert,
Rückweg je Schritt notiert. Umsetzung im Wartungsfenster nach dem 23.11.
