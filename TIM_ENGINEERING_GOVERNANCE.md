# TIM Constitution Band 2 — Engineering Governance

Version: **TIM Constitution Band 2**
Status: **Authoritative Engineering Governance**

Dieses Dokument definiert die Entwicklungsregeln des TIM-Ökosystems und
ergänzt Band 1. Bei Konflikten gilt folgende Präzedenz:

1. TIM Constitution Band 1
2. TIM Constitution Band 2
3. Master Prompts
4. Implementierung

## Engineering

TIM wird als langfristiges Enterprise-System entwickelt, nicht als
Hobbyprojekt, Proof of Concept, Experiment, Trading Script oder AI Demo. Jede
Änderung muss auch in zehn Jahren verständlich sein. Die Qualitätsmaßstäbe
entsprechen langlebiger kritischer Infrastruktur.

## Repository Policy

- Es existiert genau ein autoritatives Repository.
- Dieses Repository stellt die Wahrheit dar.
- Es gibt keine Schatten-Repositories, konkurrierenden Wahrheiten, lokalen
  Sonderlösungen oder undokumentierten Branches.
- Alle Entwicklung beginnt im autoritativen Repository.

## Directory Policy

Verzeichnisse besitzen klar getrennte Verantwortungen:

| Verzeichnis | Verantwortung |
|---|---|
| `/schemas` | ausschließlich Schemas |
| `/docs` | ausschließlich Dokumentation |
| `/src` | Produktionscode |
| `/tests` | Tests |
| `/artifacts` | generierte Artefakte |
| `/scripts` | Hilfsskripte |
| `/tools` | Entwicklungswerkzeuge |

Verantwortungen dürfen nicht vermischt werden.

## Branching and Scope

Jede Plattform erhält einen eigenen Branch. Es wird niemals an mehreren
Plattformen gleichzeitig gearbeitet.

Ein Branch entspricht genau:

- einer Plattform;
- einem Scope;
- einer Abnahme.

Cross-Platform-Features, versteckte Änderungen und Scope-Vermischung sind
verboten.

## Commit Policy

Jeder Commit ist klein, verständlich, deterministisch und reviewbar. Commit
Messages folgen `type(scope): summary`, beispielsweise:

- `feat(research): ...`
- `fix(dataset): ...`
- `docs(governance): ...`
- `test(strategy): ...`
- `refactor(feature): ...`
- `build(ci): ...`
- `chore(dev): ...`

## Versioning

Semantic Versioning ist verbindlich:

- MAJOR: Architekturänderungen;
- MINOR: neue Funktionen;
- PATCH: Fehlerkorrekturen.

Versionssprünge und manuelle Versionsänderungen benötigen dokumentierte
Freigabe.

## Schema Policy

Alle öffentlichen Verträge besitzen immutable, versionierte, reviewbare und
getestete Schemas. Eine Änderung ist breaking, wenn sie bestehende Verträge
ungültig macht.

## Code Standards

Code besitzt klare Namen und kleine Funktionen. Verboten sind Magie,
versteckte Seiteneffekte, unnötige Komplexität, tote Pfade und
Copy-Paste-Logik. Lesbarkeit hat Vorrang.

## Test Policy

Jede Plattform besitzt:

- Unit Tests;
- Integration Tests;
- Schema Tests;
- Regression Tests;
- Replay Tests;
- Determinismus Tests;
- Hash Tests;
- Lineage Tests;
- Acceptance Tests.

Tests dürfen niemals abgeschwächt werden.

## Review Policy

Vor jeder Freigabe werden Architektur, Scope, Code, Tests, Dokumentation,
Schemas, Lineage, Replay, Performance, Regression, Working Tree, Doctor,
Validate und Full Suite geprüft.

## Documentation Policy

Jede Plattform besitzt mindestens:

- `implementation.md`;
- `acceptance.md`;
- `architecture.md`;
- `decision_log.md`;
- `release_notes.md`.

Dokumentation ist Bestandteil der Implementierung.

## Change Control

Jede Änderung dokumentiert Problem, Ziel, Alternativen, Entscheidung, Risiken,
Tests, Review und Acceptance. Quick Fixes ohne Nachweis sind verboten.

## AI Governance

KI darf Code, Tests und Dokumentation erzeugen, Reviews vorbereiten,
Architektur analysieren, Refactoring vorschlagen, Regressionen finden und
Replay prüfen.

KI darf nicht eigenständig Architektur ändern, Sicherheitsregeln entfernen,
Tests deaktivieren, Schutzmechanismen umgehen, Releases freigeben oder
Produktionsentscheidungen treffen.

## Multi-Agent Policy

Mehrere Agenten dürfen parallel arbeiten, jedoch niemals auf derselben
Plattform. Jeder Agent besitzt einen eigenen Branch, Scope, Review und eine
eigene Acceptance. Konflikte werden ausschließlich über Pull Requests gelöst.

## Merge Policy

Ein Merge ist nur zulässig, wenn:

- Acceptance PASS;
- Doctor PASS;
- Validate PASS;
- Full Suite PASS;
- Working Tree sauber;
- Review abgeschlossen;
- Dokumentation vollständig;
- keine offenen Regressionen;
- keine offenen TODOs im Merge-Scope.

## Release Policy

Ein Release besitzt Version, Commit, Tag, Release Notes, Migration Notes,
Known Limitations, Test Report, Acceptance Report, Release Checklist und
Release Evidence.

## Security

Secrets dürfen niemals committed werden. Dazu zählen insbesondere API Keys,
Tokens, Passwörter, private Zertifikate und lokale Zugangsdaten.

## Performance

Performanceoptimierungen dürfen Determinismus, Replay, Lesbarkeit, Validierung
und Schema-Stabilität niemals beschädigen.

## Definition of Done

Eine Plattform ist ausschließlich abgeschlossen, wenn:

- Scope vollständig;
- Dokumentation vollständig;
- Schemas vollständig;
- Tests vollständig;
- Replay erfolgreich;
- Doctor PASS;
- Validate PASS;
- Full Suite PASS;
- Acceptance PASS;
- Review abgeschlossen;
- Working Tree sauber;
- Merge freigegeben.

## Long-Term Rule

Jede Entscheidung muss verständlich, erweiterbar, testbar, wartbar und
deterministisch sein. Kurzfristige Vorteile dürfen niemals die langfristige
Architektur verschlechtern.
