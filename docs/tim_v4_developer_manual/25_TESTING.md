# TIM V4 Developer Manual — Kapitel 25

# Testing & Verifikation

Version: **0.1.0**
Status: **Ist-zentriert, mit [SPEZIFIKATION]-Rückständen**
Verbindlichkeit: **Ja**

Dieses Kapitel beschreibt die Teststrategie und den realen Teststand von TIM.
Es gilt die Grundregel aus Kapitel 04: Tests belegen IST-Verhalten; fehlende
Abdeckung wird als **OFFENE LÜCKE** gemeldet, nicht als vorhanden behauptet.

## 1. Test-Stufen

1. **Unit** (Engine-Logik, deterministisch) — Ist-Stand s. u.
2. **Vertrag/Integration** (Persistenz, Watchdog, Pipeline-V2, Durable).
3. **Research/TIM v2** (Module, Registries, Readiness, Completion).
4. **Betrieb** (Dashboard, Ops, Log-Rotation, Paper).

## 2. Wichtige reale Befunde (Stand der Erstellung dieses Handbuchs)

- Das **Orderflow-Scenario-Paket** hat **nur eine echte Testdatei**:
  `tests/test_orderflow_scenario_data_quality.py`.
- `tests/test_orderflow_scenario/` existiert, ist aber **leer** (keine Tests drin).
- Ausgeführt und grün: `pytest tests/test_orderflow_scenario_data_quality.py
  tests/test_data_quality.py -q` → **18 passed**.
- `test_orderflow_metrics.py`, `test_orderflow_validation.py` → grün (verifiziert).
- `test_orderflow_observations.py` → ein Fall schlägt nur wegen Umgebung fehl:
  `SecretProviderError: macOS Keychain secret ist nicht verfügbar`
  (`config/secrets.py:132`) — Sekret-Umgebung, nicht Logikfehler.

## 3. Engines: Testabdeckung

| Engine | IST-Tests |
|---|---|
| Data Quality (Gate) | `test_orderflow_scenario_data_quality.py` (18) |
| Market State / Auction | keine eigenen (nur Gate-Integration) [LÜCKE] |
| Scenario / Confirmation / Probability | keine eigenen [LÜCKE] |
| Decision / Risk / Trade Plan | keine eigenen [LÜCKE] |
| Backtest / Paper / Shadow / Review / Audit | keine eigenen [LÜCKE] |

Für jedes Kapitel sind die Test-Abschnitte 08–23 bereits mit diesen Befunden
aktualisiert; neue Tests sind in den Kapiteln als [SPEZIFIKATION] gekennzeichnet.

## 4. Empfohlene Testbefehle

```bash
# Kern-Datenqualitäts-Kette
.venv/bin/python -m pytest tests/test_orderflow_scenario_data_quality.py \
  tests/test_data_quality.py -q

# Einzelne Grenz-/Validierungsdateien
.venv/bin/python -m pytest tests/test_orderflow_metrics.py \
  tests/test_orderflow_validation.py -q

# Gesamtheit (erwartet: einige env-abhängige Fehler)
.venv/bin/python -m pytest tests/ -q
```

## 5. Metriken/Verifikation

- Deterministische IDs (analysis_id, obs_id, scenario_id).
- Schema-Konformität via `validate_analysis` (Kapitel 24).
- Restore-/Rekonstruktions-Kriterien in Backtest (Kapitel 18).

## 6. Invarianten im Test

1. Empfang (Input) wird nicht durch Tests verändert.
2. Persistenz ist deterministisch wiederaufnehmbar.
3. Empirische Engine lädt Epsilons nur fallback-weise (Kapitel 13).

## 7. Offene Lücken

| Bereich | IST | SOLL |
|---|---|---|
| Engine-Prüfung (08–16) | fehlt | Unit-Tests je Engine ausbauen |
| Audit-Invarianten | fehlt | Tests ergänzen (Kapitel 23) |
| Schema-Deviationsprüfung | Basis 24 | mehr Randfälle abdecken |

## 8. Roadmap [SPEZIFIKATION]

- Unit-Tests für jede Engine (08–16) ergänzen.
- Reproduzierbarkeit (deterministische Flags) testen.
- CI-Gate auf die realen Grünen Suiten festlegen.

---

*Ende Kapitel 25.*