# TIM V4 Developer Manual — Kapitel 01

# Governance

Version: **0.1.0**
Status: **Konsistent (reflektiert TIM Constitution Band 2)**
Verbindlichkeit: **Ja**

Dieses Kapitel operationalisiert die Engineering-Governance: Repository-,
Branching-, Commit-, Schema-, Test-, Review-, Merge-, Release- und
Sicherheitsregeln. Es ergänzt dies durch die konkrete Betriebssteuerung des
Orderflow-Scenario-Pakets (`src/orderflow_scenario/governance.py`):
Kill-Switch und Mode-Guards.

## 1. Ziel

Verbindliche Entwicklungsregeln, damit TIM wie ein langlebiges
Enterprise-System (kritische Infrastruktur) entwickelt wird und nicht wie ein
Hobbyprojekt oder Experiment. Jede Regel ist prüfbar.

## 2. Repository-Policy

- Genau ein autoritatives Repository.
- Das Repository ist die Wahrheit. Keine Schatten-Repos, keine konkurrierenden
  Wahrheiten, keine lokalen Sonderlösungen.
- Alle Entwicklung beginnt im autoritativen Repository.

## 3. Verzeichnis-Policy

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

## 4. Branching und Scope

- Jede Plattform erhält einen eigenen Branch.
- Niemals an mehreren Plattformen gleichzeitig arbeiten.
- Ein Branch = eine Plattform = ein Scope = eine Abnahme.
- Cross-Platform-Features, versteckte Änderungen und Scope-Vermischung sind
  verboten.

## 5. Commit-Policy

Commits sind klein, verständlich, deterministisch, reviewbar. Format:

```text
type(scope): summary
```

Beispiele: `feat(research):`, `fix(dataset):`, `docs(governance):`,
`test(strategy):`, `refactor(feature):`, `build(ci):`, `chore(dev):`.

## 6. Versionierung

Semantic Versioning ist verbindlich (MAJOR = Architektur, MINOR = Features,
PATCH = Fixes). Versionssprünge und manuelle Versionsänderungen erfordern
dokumentierte Freigabe.

## 7. Schema-Policy

Öffentliche Verträge besitzen immutable, versionierte, reviewbare und
getestete Schemas. Breaking ist jede Änderung, die bestehende Verträge
ungültig macht. Details: Kapitel 24.

## 8. Code-Standard

Klare Namen, kleine Funktionen. Verboten: Magie, versteckte Seiteneffekte,
unnötige Komplexität, tote Pfade, Copy-Paste. Lesbarkeit hat Vorrang.
Details: Kapitel 04.

## 9. Test-Politik

Jede Plattform besitzt: Unit-, Integration-, Schema-, Regression-, Replay-,
Determinismus-, Hash-, Lineage-, Acceptance-Tests. Tests dürfen niemals
abgeschwächt werden. Details: Kapitel 25.

## 10. Review-Politik

Vor jeder Freigabe geprüft: Architektur, Scope, Code, Tests, Dokumentation,
Schemas, Lineage, Replay, Performance, Regression, Working Tree, Doctor,
Validate, Full Suite.

## 11. Dokumentations-Politik

Jede Plattform besitzt mindestens: `implementation.md`, `acceptance.md`,
`architecture.md`, `decision_log.md`, `release_notes.md`. Dokumentation ist
Bestandteil der Implementierung.

## 12. Change Control

Jede Änderung dokumentiert: Problem, Ziel, Alternativen, Entscheidung,
Risiken, Tests, Review, Acceptance. Quick Fixes ohne Nachweis sind verboten.

## 13. KI-Governance

KI darf: Code, Tests und Dokumentation erzeugen; Reviews vorbereiten;
Architektur analysieren; Refactoring vorschlagen; Regressionen finden;
Replays prüfen.

KI darf niemals allein: Architektur ändern, Sicherheitsregeln entfernen,
Tests deaktivieren, Schutzmechanismen umgehen, Releases freigeben,
Produktionsentscheidungen treffen.

## 14. Multi-Agent-Politik

Agenten dürfen parallel arbeiten, nie auf derselben Plattform. Jeder Agent
besitzt eigenen Branch, Scope, Review, Acceptance. Konflikte nur über Pull
Requests.

## 15. Merge-Politik

Merge nur wenn: Acceptance PASS, Doctor PASS, Validate PASS, Full Suite PASS,
Working Tree sauber, Review fertig, Dokumentation vollständig, keine offenen
Regressionen, keine offenen TODOs im Scope.

## 16. Release-Politik

Ein Release besitzt: Version, Commit, Tag, Release Notes, Migration Notes,
Known Limitations, Test Report, Acceptance Report, Release Checklist, Evidence.
Details: Kapitel 27.

## 17. Sicherheit

Secrets (API Keys, Tokens, Passwörter, Zertifikate) dürfen niemals committed
werden. Details: Kapitel 23.

## 18. Operational Governance — Kill-Switch und Mode-Guards

Referenz: `src/orderflow_scenario/governance.py`. Zweck: Ausführung in
OBSERVE/PAPER/SHADOW-Modi unter deterministischen Produktionszuverlässigkeits-
Bedingungen kontrollieren. Keine Live-Orders ohne explizite, separate Freigabe
außerhalb dieses Pakets.

### 18.1 KillSwitch-Invarianten

- Aktivierter KillSwitch (`enabled=True`) **muss** Live-, Paper- und
  Shadow-Ausführung blockieren
  (`block_live_execution`, `block_paper_execution`, `block_shadow_execution`
  = True). Verletzung → `ValueError` bei Erstellung.
- Deaktivierter KillSwitch blockiert nichts.
- Aktiviert muss das System Execution in OBSERVE, PAPER und SHADOW zwingend
  verhindern.

```python
class KillSwitch:
    enabled: bool
    block_live_execution: bool
    block_paper_execution: bool
    block_shadow_execution: bool
```

### 18.2 OperationalModeGuard

```python
class OperationalModeGuard:
    veto_live: bool
    veto_paper: bool
    veto_shadow: bool
```

- `violates(mode)`: OBSERVE → veto_live oder veto_paper;
  PAPER → veto_live oder veto_shadow; SHADOW → veto_shadow.

### 18.3 OrderflowScenarioGovernance-Konsistenz

- `veto_live_execution` muss einem `guard.veto_live` entsprechen (analog
  Paper/Shadow). Verletzung → `ValueError`.
- `blocks_execution(mode)` → True bei aktivem KillSwitch und Block-Flag für
  den jeweiligen Mode.
- `enforce_mode_safety(mode)` setzt die Guards durch.

### 18.4 Default-Konfiguration

Die voreingestellte Governance blockiert Live-, Paper- und Shadow-Ausführung
und setzt alle Veto-Flags auf `True` (sicherste Voreinstellung). Quelle:
`governance.py` → `default_governance_config()` (nicht `config.py`).

### 18.5 Mode-Matrix (verbindlich)

| Mode | Analyse | Paper | Shadow | Live |
|---|---|---|---|---|
| OBSERVE | ja | nein | nein | nein |
| PAPER | ja | ja | ja | nein |
| SHADOW | ja | nein | ja | nein |

Live-Ausführung ist ohne separate, explizite, dokumentierte Freigabe außerhalb
dieses Pakets in keinem Modus zulässig.

## 19. Definition of Done

Scope vollständig; Dokumentation, Schemas und Tests vollständig; Replay
erfolgreich; Doctor/Validate/Full Suite/Acceptance PASS; Review fertig;
Working Tree sauber; Merge freigegeben.

## 20. Akzeptanzkriterien

- [ ] Konformität zu TIM_ENGINEERING_GOVERNANCE.md (Band 2) verifiziert.
- [ ] Kill-Switch-, Guard- und Konsistenzinvarianten decken die Implementierung
      ab (`src/orderflow_scenario/governance.py`).
- [ ] Mode-Matrix korrespondiert zur Implementierung.
- [ ] Tests für Governance-Gate vorhanden (siehe `tests/` V2-Suite).
- [ ] Jede Aussage referenziert Code, Tests oder Schemas.

---

## Code Coverage (Phase 2)

```
VERIFIED .......... 78 %
PARTIAL ........... 17 %
SPECIFICATION ..... 5 %
```

Befunde: `KillSwitch`-Semantik (active→block live/paper/shadow) und
`OperationalModeGuard.violates` verifiziert. Korrigiert: `default_governance_config()`
liegt in `governance.py` (nicht `config.py`). Codeblöcke im Manual lassen
Felder `reason`/`mode` aus. Kein dedizierter Governance-Test (nur
`test_repository_governance.py`).

---

*Ende Kapitel 01.*