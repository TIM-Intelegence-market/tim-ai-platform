# TIM V2 Audit Disposition Matrix V1

**Datum:** 2026-09-01 18:20 UTC
**Autor:** Unabhängige Code-Inspektion (Read/Grep)
**Bezug:** `data/research/audit/latest.json` (audit_hash `9edcde21...`, 15 checked, 13 PASS, 2 FAIL), `TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md:131-145` (Provenance FAIL), `TIM_V2_REMEDIATION_PROGRAM.md Workstream 3+5`
**Prinzip:** Kein historischer Rewrite. Legacy bleibt FAIL, prospektive V2-Scope wird 100% grün. — `No audit code or historical artifact is changed by this program.`

## Disposition je Audit-Issue

| Issue | Code | Pfad | Einstufung | Behandlung | Evidence |
|---|---|---|---|---|---|
| I1 | `MISSING_DOCUMENTATION` | `data/research/module_a_cache.jsonl` (12874/12874 aktuell, 1602 am Cut-off 2026-07-23) | **Legacy-Dokumentationslücke** | Retain & Document — Bytes unverändert lassen, als Limitation markieren, V2-Scope isolieren | `audit/latest.json:133-135`, `module_a_cache.jsonl:1` (aktuell 12874 Zeilen, am Audit-Cut-off 1602, Felder `research_id, input_hash, provenance` vorhanden, `artifact_hash, generator_version, schema_version` fehlen) — Hash `8792931f...`, SHA `ce62d99f...` — Inventar `provenance_inventory_v1.json:1` |
| I2 | `OUTPUT_HASH_MISMATCH` | `data/research/status/tim_v1_readiness.json` | **Validator-Semantik False Positive** (cross-domain) | Retain & Reconcile — P0 RCA `TIM_OUTPUT_HASH_ROOT_CAUSE_REPORT.md` beweist deterministischen Hash-Domain-Collision, nicht Korruption; Readiness `artifact_hash` selbst valide, Insights `output_hash` valide in eigener Domäne — Governance-Entscheidung HC-1.0 erforderlich, kein Rewrite | `TIM_OUTPUT_HASH_ROOT_CAUSE_REPORT.md:1`, `TIM_HASH_CONTRACT_SPECIFICATION_V2.md:8.1` |

## Mapping zu Workstreams

- I1 → **Workstream 5 (Historical Provenance)** — Klasse *Partial legacy provenance* → *Retain and document* (`REMEDIATION_PROGRAM.md:206-209`), nicht *Complete prospective* → `V2-B05` bleibt OPEN bis V2-Scope 100% nachgewiesen, Legacy bleibt FAIL.
- I2 → **Workstream 3 (Audit FAIL)** — *validator semantic false positive* → *Retain FAIL where historical validator reports FAIL* + *Define future V2-only verification under HC-1.0* (`REMEDIATION_PROGRAM.md:150-158`), `V2-B03` bleibt OPEN bis HC-1.0 approved.

## Governance-Entscheidung (heute)

- **Kein Rewrite** von `module_a_cache.jsonl` — Bytes bleiben `8792931f...` (15:13 PASS/FAIL erhalten).
- **V2-Scope** ab 2026-09-01 18:20 UTC: alle neuen Artifacts müssen `artifact_hash, generator_version, schema_version` tragen — garantiert via `research_infrastructure_review.py:1` (SHA-256 kanonisch).
- **Audit bleibt FAIL** — korrekt, weil historisch FAIL. V2-Review nutzt *neuen* Audit-Pack isoliert (V2-Scope), nicht veränderten alten.
- **Nächster Schritt:** Provenance-Inventar `data/research/audit/provenance_inventory_v1.json` (100% prospektiv ab heute).

## Evidence-Hashes

- Audit `latest.json` SHA `6620681264615c88d58702cf773a0a938fc0ea227d394f162d3dbfa7613391fb` (unverändert)
- Quality `latest.json` SHA `eff0ce873d63d9398cf8b51f646c62ad7681bdd93ae7938fd6ed99ac1c6701d4` (unverändert)
- Diese Matrix SHA `$(shasum docs/TIM_V2_AUDIT_DISPOSITION_MATRIX_V1.md | cut -d' ' -f1)` — nach Commit eintragen

## Status

- **V2-B03 + V2-B05:** dispositioniert, aber **OPEN** bis HC-1.0 + V2-Scope 100% verifiziert (Phase 1 Integrity).
- **Kein Blocker geschlossen** — nur Disposition dokumentiert, wie `REMEDIATION_PROGRAM.md:5-6` verlangt.
