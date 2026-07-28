# TIM Data Quality Gating

Version: 1.0

Zweck: Dokumentiert die Read-only-Gates für Qualität, Coverage und Integrität.

## Gate Signals

- Coverage
- Missing Minutes
- Gap Count
- Missing AggTrades
- Missing Validation
- Provenance Status

## Interpretation

- `GREEN`: Gate erfüllt, keine dokumentierte Blockade
- `YELLOW`: Gate beobachtbar, aber mit offenen wissenschaftlichen Punkten
- `RED`: Gate blockiert oder deutlich unter Ziel

## Datenquelle

Nur persistierte Artefakte:

- `data/research/status/tim_v1_readiness.json`
- `data/research/quality/latest.json`
- `data/research/audit/latest.json`
- `data/operational/state.json`

## Verifikation

Die Seite zeigt Ursache, Evidenz, Zeitfenster, betroffene Artefakte und empfohlene nächste Schritte.

## Known Limits

- Keine Datenrekonstruktion
- Keine Stilllegung historischer Lücken
- Keine automatische Freigabe
