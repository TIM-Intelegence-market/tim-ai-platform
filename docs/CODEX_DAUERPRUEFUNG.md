# INFRA-10: Dauerhafte unabhängige Codex-Abnahme

Stand: 26.11.2026, Version 0.2 (Entwurf; 0.1 vom 25.11., Ergänzung INFRA-11 in §9). Status: **nur Plan. Nichts davon ist aktiviert.**
Auftrag: Mission INFRA-10 des Owners vom 25.11.2026. `TRADING_AUTHORIZED=NO`.

## 0. Grenzen dieses Plans

- Keine eigenständige Aktivierung. Jede Phase unten braucht ein eigenes GO des Owners.
- Keine Änderung der bestehenden Freigaberegeln (`docs/TIM_AGENT_HANDOFF.md`, `CI.md`, Ruleset
  "platform-main merge conditions", `config/auto-merge-policy.json`). Wo der Plan sie berührt, steht der Vorschlag
  hier und wird erst nach Freigabe als eigener Owner-PR umgesetzt.
- Keine Produktionsänderung. Server und Mac-Live-Dienste bleiben unberührt.
- INFRA-09 (Archiv auf der Warpgate-Platte) bleibt gesperrt, bis die unabhängige Abnahme vorliegt. Dieser Plan
  ersetzt sie nicht und erteilt sie nicht.
- Repo ist öffentlich: keine Hostnamen, Adressen, Konten, Schlüssel oder UUIDs in diesem Dokument.

## 1. Problem

Heute muss für jedes Paket jemand von Hand dafür sorgen, dass Codex prüft: Handoff in #372 schreiben, Codex am Mac
starten, Ergebnis zurück nach GitHub tragen. Der Codex-Bot auf GitHub antwortet für dieses Repo mit "create an
environment for this repo", ist also nicht eingerichtet. Folge: Pakete stehen `READY_FOR_REVIEW`, ohne dass eine
Prüfung läuft (Beispiel INFRA-09, #389 bis #394, Nacht 24./25.11.).

Ziel: Jeder neue Commit-Stand eines TIM-PRs bekommt ohne Koordinationsaufwand eine unabhängige, reproduzierbare
Prüfung mit dem Urteil PASS, FAIL oder INCONCLUSIVE, und ein Merge ohne dieses Urteil ist technisch nicht möglich.

## 2. Bestand (nur gelesen)

| Baustein | Heute | Erzwingt Unabhängigkeit? |
|---|---|---|
| `ci.yml` Job `test` | Ubuntu, PostgreSQL 16, Pflicht im Ruleset | nein, prüft nur Tests |
| `pr-gate.yml` (pull_request_target, Status `pr-gate/head`) | Pflicht, gesperrte Pfade, nur für Worker-Branches wirksam | nein |
| `review-gate.yml` | prüft Form und Rolle des Zettels `TIM_HANDOVER_V1` auf kritischen Pfaden, **keine** Pflicht im Ruleset | nein, prüft nicht wer schrieb |
| `dco.yml` | Signed-off-by | nein |
| `tim-full-suite.yml`, `auto-merge-controller.yml` | nur manuell | – |
| `config/auto-merge-policy.json` | `enabled: false`, `dry_run: true` | – |
| Ruleset platform-main | Pflicht `test` + `PR gate`, keine Umgehung, Review-Pflicht aus, strict aus | nein |
| CODEOWNERS | Owner und Chris für alles | nur wenn Review-Pflicht an |
| `docs/TIM_AGENT_HANDOFF.md` | Rollen, Kopfzeile, PASS nur mit Beleg, `NOT_RUN` ist kein PASS, max. 3 Versuche | organisatorisch |
| Codex auf GitHub | nicht eingerichtet (Bot verlangt Umgebung) | – |

**Lokale Codex-Prüfumgebung am Mac** (Stand 24.11., aus Mission 07-INFRA; heute nicht erneut gelistet, weil der
Ordner dieser Sitzung nicht freigegeben ist):

- Ordner `review-env/` mit getrennten Bereichen `codex/` und `claude/`, je eigener Git-Spiegel, dazu `integration/`.
- Skripte `review-fetch.sh` (Stand holen) und `review-run.sh codex <sha>` (Lauf auf genau einem SHA).
- venv mit Python 3.13 und Hypothesis, Wegwerf-PostgreSQL je Bereich auf eigenem Port; im Claude-Bereich zusätzlich
  ein PG18-Lauf.
- Bekannte Lücke: 11 Mac-Umgebungstests scheitern dort auch auf `platform-main`.
- Regel: Claude startet nie Läufe im Bereich `codex/`.
- Schwäche: Unabhängigkeit hängt an Disziplin auf einem gemeinsamen Rechner mit einem Benutzerkonto; der Lauf
  muss von Hand angestoßen werden; die Ergebnisse kommen nicht automatisch nach GitHub.

## 3. Bewertung der Prüfinstanzen

Quellen: OpenAI-Dokumentation (learn.chatgpt.com/docs/third-party/github, learn.chatgpt.com/codex/environments/
cloud-environments, learn.chatgpt.com/codex/security) und openai.com/index/codex-security-now-in-research-preview,
gelesen 25.11.2026. Was dort nicht steht, ist als **UNGEPRÜFT** markiert.

### 3.1 Codex Cloud Code Review (Hauptkandidat)

- Einrichtung: Repo mit Codex verbinden, Cloud-Umgebung anlegen, je Repo "Automatic review" einschalten
  (Modus "alle PRs"). Alternativ Auslösen per Kommentar `codex review` mit vorangestelltem At-Zeichen.
- Ergebnis: ein normales GitHub-Review am PR. **UNGEPRÜFT:** ob es einen Status-Check erzeugt, den ein Ruleset
  verlangen kann. Laut Doku nicht erwähnt; Plan geht davon aus, dass **nicht**.
- Liest Prüfregeln aus `AGENTS.md` (Abschnitt `## Code Review Rules`, verschachtelte Dateien gelten für ihren Ordner).
  `AGENTS.md` ist ein gesperrter Pfad: Änderung nur per Owner-PR.
- Umgebung: eigenes Installationsskript und Start für Dienste, Internetzugang abschaltbar oder auf Paketquellen und
  einzelne Domains begrenzbar. **UNGEPRÜFT:** ob PostgreSQL 18 als Dienst dort sauber läuft.
- Unabhängigkeit: läuft in OpenAIs Umgebung unter der Codex-Verbindung des Owners, getrennt von Claudes Cloud und vom
  Mac. Das ist die stärkste Trennung, die heute ohne eigene Infrastruktur erreichbar ist.
- Risiken: Kontingent/Kosten je Review, Review ist ein LLM-Urteil (braucht trotzdem den Testlauf aus 4.2), Bot
  postet unter dem Konto, das die Verbindung herstellt.

### 3.2 Codex Security (zusätzlich, nur defensiv)

- Früher "Aardvark". Baut ein Bedrohungsmodell, bestätigt Funde in einer Sandbox, schlägt Patches vor.
  Forschungsvorschau für ChatGPT Pro/Business/Enterprise/Edu (Ankündigung 06.03.2026).
- **UNGEPRÜFT:** welche Repo-Rechte es braucht und ob es selbst PRs öffnet (Doku zeigt einen Status "PR created").
- Einsatz im Plan: nur Funde lesen und als Befunde in den PR tragen; **keine** automatischen Fix-PRs, kein
  Schreibrecht auf Branches. Funde gelten als `NEEDS_EVIDENCE`, bis sie im Prüfstand reproduziert sind.

### 3.3 Daybreak (zusätzlich, nur defensiv)

- Laut Codex-Security-Doku eine der Nutzungsformen ("Daybreak Defense Factory": GitHub-Repos scannen, Funde sortieren,
  Fixes vorschlagen). Presse (Mai 2026) beschreibt Zugang teils nur für freigegebene Nutzer.
- **UNGEPRÜFT:** Verfügbarkeit für dieses Konto, Kosten, Rechte. Erst klären, dann frühestens in Phase 5.
- Gleiche Grenze wie 3.2: nur lesen und berichten.

### 3.4 Was ausdrücklich nicht als unabhängige Prüfung zählt

Claude-Subagenten (z. B. `pr-reviewer`), OpenCode/GLM, Hilfsagenten in Claudes Sitzung. Sie dürfen vorprüfen,
ihr Ergebnis heißt aber nie PASS im Sinne dieses Plans (siehe `TIM_AGENT_HANDOFF.md` §8).

## 4. Zielarchitektur

```
Claude pusht Commit ──► PR (Entwurf oder offen)
                         │
     ┌───────────────────┼──────────────────────────────┐
     ▼                   ▼                              ▼
 CI `test` (wie heute)  Codex Cloud Review         Prüfstand-Lauf (4.2)
                        (LLM-Befunde)              Py3.13 + PG18 + Hypothesis
     │                   │                              │
     └─────────► Abnahme-Sammler (4.4) ◄────────────────┘
                         │  schreibt Status `codex-abnahme` = PASS / FAIL / INCONCLUSIVE
                         │  für genau den HEAD-SHA, plus Bericht
                         ▼
          Ruleset verlangt `codex-abnahme` (Phase 4, eigenes GO)
                         ▼
          Merge nur durch Mensch (unverändert)
```

### 4.1 Rollen und Berechtigungen

| Rolle | Darf | Darf nicht |
|---|---|---|
| Claude (Entwickler) | eigene Branches `claude/*` pushen, Entwurfs-PRs öffnen, `READY_FOR_REVIEW` setzen, Befunde beantworten | Status `codex-abnahme` setzen; Prüfstand-Konfiguration, Prüfregeln oder Workflow ändern; mergen; Läufe im Codex-Bereich starten |
| Codex (Prüfer) | Reviews/Kommentare am PR, Prüfstand-Lauf auslösen | auf Entwicklungs-Branches pushen, Fix-Commits in den geprüften PR schreiben, mergen |
| Abnahme-Sammler (Workflow) | Status `codex-abnahme` schreiben, Bericht als Artefakt/Kommentar ablegen | Code ausführen, der aus dem PR stammt, mit Schreib-Token (siehe 4.5) |
| Mensch (Owner, Chris) | Phasen freigeben, Prüfregeln ändern, mergen, deployen | – |

Technische Trennung (Vorschlag, jeweils eigenes GO):

- Status `codex-abnahme` darf nur ein Workflow auf `pull_request_target`/`workflow_run` mit Base-seitigem Code
  setzen, nie ein Job, der PR-Code mit Schreibrecht ausführt (gleiche Bauart wie `pr-gate.yml`).
- Ruleset: `codex-abnahme` als Pflicht-Status, **an eine bestimmte GitHub-App gebunden** (Ruleset-Option
  "expected source"), damit niemand mit Repo-Schreibrecht den Status von Hand setzen kann.
- Prüfregeln (`AGENTS.md` Abschnitt Code Review Rules, Prüfstand-Skripte unter `scripts/`/`.github/`) sind
  gesperrte Pfade; Änderungen nur per Owner-PR mit Review durch Owner oder Chris.
- Claudes Cloud-Zugang bekommt keinen Zugang zur Codex-Verbindung und keine Secrets des Prüfstands.

### 4.2 Isolierter Linux-Prüfstand

Zwei Varianten, Empfehlung A:

- **A: GitHub-Actions-Job `codex-pruefstand`** auf `ubuntu-latest`: Python 3.13, PostgreSQL 18 als Service-Container,
  Hypothesis mit festem Profil. Kein Secret, nur Lesetoken, kein Netz außer Paketquellen. Läuft auf dem HEAD-SHA,
  frische Datenbank je Lauf. Vorteil: reproduzierbar, unabhängig von Mac und Claude-Cloud, nichts zu warten.
- **B: Codex-Cloud-Umgebung** mit Installationsskript (Py3.13, PG18, Hypothesis). Vorteil: Codex prüft in derselben
  Umgebung, in der es denkt. Nachteil: Ergebnis kommt nur als Review-Text, nicht als Status.
- Der Mac-Prüfstand (`review-env/`) bleibt als Rückfall und für Mac-spezifische Tests, wird aber nicht mehr der
  Hauptweg.

Inhalt des Laufs:

1. Volle Suite wie in der CI (`-m "not local_env and not serial" -n 4 --dist loadgroup`, danach `serial`).
2. Zusätzliche **unabhängige Regressionstests** aus einem Ordner, den nur Codex/der Mensch pflegt
   (Vorschlag `tests/independent/`, im PR-Gate für Claude-Branches gesperrt). Claude darf sie nicht anpassen, damit
   der Entwickler die Prüfung nicht an seinen Code anpasst.
3. Hypothesis mit festem Seed-Profil (`derandomize`) für Reproduzierbarkeit, plus ein zweiter Lauf mit Zufallssaat,
   dessen Fund als FAIL zählt und den Seed in den Bericht schreibt.
4. PG18-spezifische Tests (z. B. Archiv-Pakete INFRA-09).

### 4.3 Reproduzierbarer Prüfbericht

Je Lauf eine Datei `pruefbericht.json` (+ Kurztext als PR-Kommentar):

```
schema: tim-pruefbericht/1
pr, head_sha, base_sha, merge_base
umgebung: os, python, postgres, hypothesis, lockfile_hash
befehle: [exakte Befehle]
ergebnis_tests: passed/failed/skipped/errors je Schritt, Dauer
codex_review: review_id, commit_id des Reviews, Befunde [{datei, zeile, schwere, text}]
security: {quelle, befunde} oder NOT_RUN
urteil: PASS | FAIL | INCONCLUSIVE
gruende: [...]
```

Jeder kann den Lauf mit `head_sha` und den Befehlen nachstellen. Der Bericht enthält keine Logs mit Secrets oder
internen Adressen.

### 4.4 Urteilsregeln (verbindlich)

- **PASS** nur, wenn alles zugleich gilt: Prüfstand-Lauf auf genau dem aktuellen HEAD-SHA ohne Fehler; Codex-Review
  bezieht sich auf denselben SHA; kein offener Befund der Schwere hoch/kritisch; Security-Prüfung ohne offenen Fund,
  falls für den Pfad Pflicht.
- **FAIL**, sobald eines gilt: ein Test rot; Codex-Befund hoch/kritisch nicht mit `REJECT`+Beleg beantwortet;
  bestätigter Sicherheitsfund; gesperrter Pfad verletzt.
- **INCONCLUSIVE** in allen anderen Fällen, insbesondere: Lauf nicht gestartet, abgebrochen oder Zeitüberschreitung
  (`NOT_RUN`); Review auf älterem SHA; Werkzeug nicht verfügbar; Kontingent erschöpft; widersprüchliche Ergebnisse.
- INCONCLUSIVE ist für den Merge wie FAIL. Ein neuer Commit setzt das Urteil auf INCONCLUSIVE zurück, bis neu geprüft.
- Ein Urteil gilt nur für den SHA, für den es geschrieben wurde.

### 4.5 Automatischer READY_FOR_REVIEW-Handoff

- Auslöser: PR wechselt von Entwurf auf "Ready for review" **oder** neuer Push auf einen nicht-Entwurfs-PR
  **oder** Label `abnahme:anfordern`.
- Ein Workflow schreibt den Handoff-Kommentar im Format von `TIM_AGENT_HANDOFF.md` (Kopf, BASE_SHA, HEAD_SHA,
  geänderte Dateien, Prüfbefehl) und stößt Codex Review und Prüfstand an. Kein Mensch muss etwas weiterreichen.
- Schutz vor Schleifen und Kosten: höchstens ein Lauf je SHA (`concurrency` je PR, ältere Läufe abbrechen), keine
  Prüfung von Entwürfen, Tageshöchstzahl Läufe, keine Wiederholung auf unverändertem SHA (passt zur Owner-Regel
  "keine unnötigen Wiederholungen").
- Fork-PRs: kein Lauf mit Secrets, nur der Lesetest; Urteil INCONCLUSIVE bis ein Mensch freigibt.

### 4.6 Merge- und Deployment-Schutz unabhängig vom Entwickler

- Phase 4 (eigenes GO): Ruleset verlangt zusätzlich `codex-abnahme`; die bestehenden Pflichten `test` und `PR gate`
  bleiben. Keine Umgehungsliste.
- Merge bleibt Menschensache wie heute; der Status macht ihn nur zusätzlich technisch abhängig von der Prüfung.
- Deployment: Server-/Mac-Deployments nur von gemergtem `platform-main` und nur, wenn der Merge-Commit eine
  gültige Abnahme hat. Vorschlag GitHub-Environment `produktion` mit Pflicht-Freigabe durch den Owner; nicht
  Teil dieser Mission, nur vorgemerkt.
- Auto-Merge-Policy bleibt `enabled: false`. Falls sie je eingeschaltet wird, muss `codex-abnahme = PASS` Bedingung
  sein (eigener Owner-PR).

### 4.7 Bestehende Schutzmechanismen bleiben

PR gate, gesperrte Pfade, DCO, Review gate mit `TIM_HANDOVER_V1`, Signalgruppen-Test, Holdout-Sperre, Warpgate und
SSH-Rechte, Zero-Trust-Regeln in `TIM_SECURITY_ZERO_TRUST_CONSTITUTION.md`. Der Plan fügt nur eine Prüfung hinzu
und lockert keine. Kein Workflow bekommt Server- oder Warpgate-Zugang.

## 5. Umsetzungsplan in Phasen

Jede Phase: eigenes GO, eigener PR, Rückbau benannt. Pfade unter `.github/`, `scripts/`, `config/`, `AGENTS.md`
sind gesperrt, also Owner-PR.

| Phase | Inhalt | Wer handelt | Prüfung/Abnahme | Rückbau |
|---|---|---|---|---|
| 0 | Dieses Dokument | Claude | Owner liest, Codex prüft | PR schließen |
| 1 | Codex Cloud einrichten: Umgebung anlegen, Automatic review für dieses Repo **an**, Internet nur Paketquellen | **Owner** in den ChatGPT-Einstellungen (Claude hat dort keinen Zugang) | Probe-PR bekommt ein Codex-Review ohne Zutun | Automatic review aus |
| 2 | Prüfstand-Workflow `codex-pruefstand` (Py3.13, PG18, Hypothesis), Bericht `tim-pruefbericht/1`, **nicht Pflicht** | Owner-PR, Claude entwirft, Codex prüft | 3 bekannte PRs reproduzierbar: gleiches Ergebnis bei 2 Läufen | Workflow löschen |
| 3 | Abnahme-Sammler + automatischer Handoff, Status `codex-abnahme` nur informativ | Owner-PR | 1 Woche Schattenbetrieb, Abgleich mit Hand-Urteilen | Workflow aus |
| 4 | Ruleset: `codex-abnahme` Pflicht, an App gebunden | **Owner oder Chris** im Ruleset | Versuch, ohne PASS zu mergen, scheitert | Pflicht entfernen |
| 5 | Codex Security / Daybreak nur lesend anbinden, Funde in den Bericht | Owner (Konto, Verfügbarkeit klären) | Fund wird reproduziert oder als Fehlalarm belegt | Anbindung trennen |
| 6 | Deployment-Schutz (Environment `produktion`) | Owner + Chris | Deployment ohne Abnahme wird abgelehnt | Environment-Regel aus |

Reihenfolge-Abhängigkeit: 1 vor 3; 2 vor 3; 3 vor 4. Phase 5 und 6 unabhängig, später.

## 6. INFRA-09 unter diesem Plan

INFRA-09 (#389, #390, #392, #393, #394) bleibt gesperrt. Sobald Phase 1 steht, wird für diese PRs ein Codex-Review
auf den aktuellen HEADs angefordert; ein PASS dort plus Testlauf ist die "unabhängige Abnahme" im Sinne der
Owner-Freigabe vom 24.11. Bis dahin: keine Einrichtung, kein Archivlauf.

## 7. Offene Entscheidungen für den Owner

1. Phase 1 freigeben und selbst in den Codex-Einstellungen einschalten (nur der Owner kann das).
2. Prüfstand Variante A (GitHub Actions) oder B (Codex-Umgebung). Empfehlung A, B zusätzlich für Codex.
3. Ob `tests/independent/` als von Claude nicht änderbarer Ordner eingeführt wird.
4. Kostenrahmen: Höchstzahl Codex-Reviews je Tag.
5. Codex Security / Daybreak: Kontozugang klären, bevor Phase 5 geplant wird.

## 8. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Codex-Review erzeugt keinen Pflicht-Status | eigener Sammler-Status (4.4), an App gebunden |
| LLM-Review übersieht Fehler | Urteil verlangt zusätzlich Testlauf und unabhängige Tests |
| Kosten/Schleifen | ein Lauf je SHA, keine Entwürfe, Tageslimit |
| Entwickler passt Prüfung an | Prüfregeln und `tests/independent/` gesperrt, nur Owner-PR |
| Status von Hand gesetzt | Ruleset bindet Status an App |
| Workflow führt PR-Code mit Schreibrecht aus | Base-seitiger Sammler, PR-Code nur im lesenden Job |
| Codex nicht verfügbar | Urteil INCONCLUSIVE, Merge blockiert, kein stilles Durchwinken |

## 9. Ergänzung INFRA-11 (26.11.2026)

Weiterhin **nichts aktiviert**: kein Workflow, keine Ruleset-Änderung, kein Pflicht-Status. Neu ist nur Code unter
`src/review_pipeline/` mit Tests, den ein späterer Owner-PR (Phase 2/3) aufrufen kann.

### 9.1 Neuer Bestand seit 0.1

- Die Codex-Cloud-Umgebung ist veröffentlicht und funktioniert: Gates 1–3 und die Netzwerk-Durchsetzung für #397 und
  Private #464 PASS, Owner-only INCONCLUSIVE (#372 Kommentar 7172531879). Damit ist Phase 1 technisch weitgehend
  erledigt; offen ist der unabhängige Owner-only-Nachweis. Ob "Automatic review" für dieses Repo an ist, ist
  **UNGEPRÜFT** (die letzte Bot-Antwort "create an environment" stammt von vor der Veröffentlichung).
- Prüfstand Variante B (Codex-Umgebung) ist damit belegt lauffähig, PG16 und PG18 (Docker) inklusive.

### 9.2 Befund: Selbstfreigabe ist heute technisch möglich

Alle Agenten schreiben auf GitHub unter demselben Konto des Owners. Der Kopf `[AGENT: CODEX] [STATE: PASS]` ist reiner
Text und kann von jedem Agenten mit Schreibrecht erzeugt werden. **Ein Kommentar kann deshalb nie als Abnahme
zählen**, egal welcher Kopf darin steht.

Gegenmaßnahme `src/review_pipeline/verdict.py` (fail-closed):

| Quelle | Zählt? | Bedingung |
|---|---|---|
| Kommentar eines Nutzerkontos, auch mit `[AGENT: CODEX]` | **nie** (nur `INFO_ONLY`) | – |
| PR-Review des Codex-Connectors | ja | `user.type == "Bot"`, Login exakt der Connector-Bot, `commit_id` == aktueller HEAD |
| Check-Run `codex-abnahme` | ja | erwartete App-ID ist konfiguriert und stimmt; ohne App-ID nie gültig |
| Testlauf | ja | auf exakt HEAD, `failed == errors == 0`, `passed > 0` |

PASS nur bei grünem Testlauf **und** gültigem Bot-Review ohne offenen Befund hoch/kritisch auf demselben SHA. Ein
vertrauenswürdiges Review ohne lesbare Befundliste verhindert PASS. Alles andere ist INCONCLUSIVE; roter Test oder
hoher Befund FAIL.

Grenze: Wer Owner-Rechte hat, kann App-ID und Ruleset ändern. Der Schutz wirkt gegen Agenten, nicht gegen den Owner.
Darum gehören Prüfregeln und App-ID in gesperrte Pfade (`config/`, `.github/`), Änderung nur per Owner-PR.

### 9.3 Automatische Übergabe bei neuem Commit-SHA

`src/review_pipeline/handoff.py`: `should_trigger` startet höchstens einen Lauf je HEAD-SHA, nur für
`ready_for_review`/`synchronize` auf Nicht-Entwürfen oder bei Label `abnahme:anfordern`, nie für Fork-PRs.
`build_handoff_comment` schreibt den Kopf nach `TIM_AGENT_HANDOFF.md` §4 mit BASE_SHA, HEAD_SHA, Dateien und
Prüfbefehl. Offen für Phase 3: Tageshöchstzahl, Adapter, der Codex-Befunde aus dem Review-Text in die Befundliste
überführt (bis dahin bleibt jedes Review INCONCLUSIVE, also fail-closed).

### 9.4 Einheitlicher Prüfbericht

`src/review_pipeline/report.py` prüft `tim-pruefbericht/1` (Pflichtfelder, SHA-Format, Zähler, PASS mit Fehlern
ungültig) und sucht nach Geheimnis- und Adressmustern; ein Treffer macht den Bericht ungültig.
`python -m src.review_pipeline.report DATEI.json` → Exit 0 gültig, 1 ungültig.

### 9.5 Isolierte Linux-Prüfumgebung: Bewertung

| Kandidat | Isolation | Reproduzierbar | Aufwand | Urteil |
|---|---|---|---|---|
| Codex-Cloud-Umgebung | stark (fremde Infrastruktur, eingeschränkter Egress) | ja (belegt 25.11.) | gering, steht | **nutzen** als Codex-Prüfstand |
| GitHub Actions `ubuntu-latest` + PG18-Service | stark, frisch je Lauf | ja | Owner-PR unter `.github/` | **empfohlen** für den Status `codex-abnahme` |
| Linux-VM am Mac (z. B. Lima/UTM, eigener Benutzer) | mittel (gleiches Gerät, gleicher Owner) | ja | mittel | nur Rückfall |
| Mac `review-env/` | schwach (gleiches Konto) | teils (11 Mac-Fehler) | steht | nur Rückfall |
| PS4/PS5 | schwach, geteilt mit Forschung, kein sudo | nein | – | **nicht geeignet** |
| Server tim-core-01 | Produktion | – | – | **ausgeschlossen** |

Tests: `python -m pytest tests/test_review_pipeline.py -q` (38 Tests).
