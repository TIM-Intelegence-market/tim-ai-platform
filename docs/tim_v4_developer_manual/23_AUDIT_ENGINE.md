# TIM V4 Developer Manual — Kapitel 23

# Audit Engine

Version: **0.1.0**
Status: **Konsistent für IST (AuditBuilder, ResearchAuditEngine)**
Verbindlichkeit: **Ja**

Dieses Kapitel dokumentiert die Audit-Fähigkeit von TIM. Es gibt zwei reale
Bausteine: den **Entscheidungs-Audit** (`src/orderflow_scenario/audit.py`)
für die Reproduzierbarkeit jeder Entscheidung und den **Research-Audit**
(`src/research_ops/audit.py`) für die Integrität von Reports.

## 1. Zweck

Jede Entscheidung deterministisch reproduzierbar machen: Input-Hashes,
Datenquellen, Zeitstempel, Feature-/Regel-/Modul-Versionen, Szenarien,
Scores, Bestätigungen, Risiko-Entscheidungen, Betriebsmodus und
Kill-Switch-Status. **Keine** sensiblen Schlüssel oder unnötige persönliche
Daten werden geschrieben.

## 2. Reale Implementierung (IST)

### 2.1 `src/orderflow_scenario/audit.py`

`AuditBuilder`:

- `add_input(name, payload, *, redact=True)`: sichert Input (redacted),
  berechnet SHA-256-Digest, trägt `source=deterministic`.
- `add_engine(engine, version, result)`.
- `build(*, mode, kill_switch_enabled, timestamp)`: erzeugt
  - `mode`, `kill_switch_enabled`
  - `feature_version`, `ruleset_version`, `module_version`
  - `model = DETERMINISTIC_RULES`, `timestamp`
  - `inputs` (Name+Hash), `engines`
  - `live_execution: False` (fest).

`_redact`: ersetzt Werte, deren Schlüssel `secret/token/password/api_key/
authorization/credential` enthalten, durch `[REDACTED]` (rekursiv).

`analysis_id_for(symbol, venue, timestamp)`: `ofsc_<sha256-24>`.

`serialize_audit`: deterministisches JSON (sorted keys).

### 2.2 `src/research_ops/audit.py`

`ResearchAuditEngine.audit(as_of)`: prüft Report-Metadaten, deklarierte
Hashes und Struktur über `_validate_*`; `canonical`/`digest` für
deterministische Digests (Kapitel 19).

## 3. Datenfluss

```mermaid
flowchart LR
    Input[Datenquellen] --> AB[AuditBuilder.add_input]
    Engines[Engines] --> AB2[AuditBuilder.add_engine]
    AB --> Build[AuditBuilder.build]
    AB2 --> Build
    Build --> Audit[Audit-Doc (live_execution=False)]
    Research[Reports] --> RA[ResearchAuditEngine]
    RA --> Issues[Issues/Hashes]
```

## 4. Öffentliche Schnittstellen

- `AuditBuilder`, `analysis_id_for`, `serialize_audit` (`orderflow_scenario/audit.py`).
- `ResearchAuditEngine`, `canonical`, `digest` (`research_ops/audit.py`).

## 5. Invarianten

1. `live_execution` ist im Audit fest `False`.
2. Sensible Schlüssel werden geschwärzt, nie geschrieben.
3. Hashes/Serialisierung sind deterministisch.
4. Input-Digest basiert auf (name, geschützter payload).

## 6. Fehlerfälle

| Fall | Verhalten |
|---|---|
| sensibler Key | mit `[REDACTED]` ersetzt |
| fehlende Report-Metadaten | ResearchAudit → Issue |

## 7. Tests

- `tests/test_research_operations.py` deckt `research_ops/audit.py` ab.
- `test_repository_governance.py` testet **nicht** `orderflow_scenario/audit.py`
  (deckt DB/Repository/Observation-Governance) — keine falsche Zuordnung mehr.

[SPEZIFIKATION] Dedizierte Audit-Invarianten-Tests (Redaction,
Versionsfelder, analysis_id-Eindeutigkeit) stehen aus.

## 8. Bekannte Einschränkungen

- `AuditBuilder` erzeugt ein In-Memory-Audit-Dokument; keine dauerhafte
  Audit-Kette über den Prozess hinaus spezifiziert.

## 9. Offene Lücken

| Bereich | IST | SOLL |
|---|---|---|
| Audit-Persistenz | In-Memory | durable Audit-Log/DB [SPEZIFIKATION] |
| durchgängige Integrität | deklarierte Versionen | Hash-Kette über Audit-Reihe [SPEZIFIKATION] |

## 10. Roadmap [SPEZIFIKATION]

- Audit-Kette/Hash-Verkettung für durchgängige Integrität.
- Dauerhafte Archivierung und Replay des Audits (Kapitel 25).

---

## Code Coverage (Phase 2)

```
VERIFIED .......... 86 %
PARTIAL ........... 12 %
SPECIFICATION ..... 2 %
```

Befunde: `AuditBuilder` (`add_input`/`add_engine`/`build`), `_redact`,
`analysis_id_for`, `serialize_audit` sowie `ResearchAuditEngine`/`canonical`/
`digest` verifiziert. Test-Referenz korrigiert (`test_repository_governance.py`
deckt den Audit-Bereich nicht ab).

---

*Ende Kapitel 23.*