# TIM V4 Developer Manual — Kapitel 24

# JSON Schemas

Version: **0.1.0**
Status: **Konsistent für IST (analysis_output_v1.json)**
Verbindlichkeit: **Ja**

Dieses Kapitel dokumentiert die JSON-Schemas von TIM. Der einzige
vertragsstützende Schema-Container im Szenario-Paket ist
`src/orderflow_scenario/schemas/analysis_output_v1.json` (draft-07).

## 1. Zweck

Maschinenlesbare, deterministische Ausgabe des Orderflow-Scenario- und
Trade-Decision-Managers bereitstellen. Das Schema kodiert: **keine
Live-Order-Anweisungen** und **keinen Anspruch auf realisierten Profit**.

## 2. Reale Implementierung (IST)

### 2.1 `analysis_output_v1.json`

- `$schema`: draft-07; `$id`: `https://tim.local/schema/.../analysis_output_v1.json`.
- `required`: schema_version, analysis_id, timestamp, symbol, venue,
  market_type, timeframe, mode, data_quality, market_state, auction_state,
  orderflow, scenarios, decision, report_text, audit.
- `schema_version` `const`: `1.0.0`.

Kernfelder:

| Feld | Bedeutung |
|---|---|
| `mode` | enum OBSERVE/RESEARCH/SIMULATE/PAPER/SHADOW |
| `data_quality.status` | enum PASS/PARTIAL/INSUFFICIENT_DATA |
| `market_state` | primary, secondary, evidence, conflicts, confidence, ... |
| `auction_state` | Auktionszustand |
| `orderflow` | Orderflow-Interpretation |
| `scenarios` | Szenario-Liste |
| `decision` | NO_TRADE / TRADE_PLAN |

### 2.2 Validator (`schema_validation.py`)

- `validate_analysis(output)` → `(bool, list[Warnungen])`.
- `load_reference_schema()`: lädt das Schema.
- `_require_keys`: rekursive Pflichtschlüsselchecks.

## 3. Vorgehen

| Prüfung | Geltung |
|---|---|
| Pflichtschlüssel vorhanden | `_require_keys` |
| enums | mode, data_quality.status |
| schema_version const | 1.0.0 |

## 4. Beispieldatei

Referenzbeispiel: `artifacts/orderflow_scenario/example_analysis.json`
(validiert durch `validate_analysis`).

## 5. Schema-Versionierung

- `schema_version` ist immutable (`const`).
- Änderungen → neue Schema-Versionen erfordern eine solche Policy (siehe
  Migrations-/Schema-Policy Kapitel 02).

## 6. Invarianten

1. `schema_version == "1.0.0"` fixiert.
2. Ausgabe enthält keine Live-Order-Anweisungen.
3. Validierung ist deterministisch.

## 7. Fehlerfälle

| Fall | Verhalten |
|---|---|
| fehlender Pflichtschlüssel | Validierungsfehler |
| unzulässiger enum-Wert | Validierungsfehler |

## 8. Tests

- Schema-Validierung über `validate_analysis` + Beispiel.
- (weitere Tests siehe Kapitel 25-Liste).

## 9. Bekannte Einschränkungen

- Nur **ein** Schema (analysis_output_v1) im Szenario-Paket; Schemas für
  Trade/Candle/Sonstiges fehlen (siehe Kapitel 05 [SPEZIFIKATION]).

## 10. Roadmap [SPEZIFIKATION]

- Dedizierte Schemas für Trade/Candle/Event (Kapitel 05).
- Audit-Schema und Review-Schema ergänzen.

---

*Ende Kapitel 24.*