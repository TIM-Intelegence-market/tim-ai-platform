# TIM Signal Research UI Contract

Version: 1.0

Zweck: Read-only Oberfläche für deterministische Orderflow-Forschung.

## Scope

- Persistierte Orderflow-Observations
- Persistierte Validierungen
- Retrospektive Outcomes
- Multi-Timeframe Kontextmatrix
- Data Quality Gating / Exceptions

## Nicht erlaubt

- Trading-Signale
- Buy/Sell-Empfehlungen
- Long/Short-Empfehlungen
- Ausführung
- neue Regeln
- neue Prognosen

## UI-Zonen

### Globaler Forschungsstatus

Zeigt OBSERVE, READ-ONLY und RESEARCH ONLY.

### Evidence Card

Detailansicht pro Observation mit:

- observation_id
- timestamp_utc
- symbol
- timeframe
- observation_type
- rule_id
- rule_version
- evidence
- missing_evidence
- validation_status
- linked_research_case_id
- integrity_status

### Multi-Timeframe Kontextmatrix

Deskriptive Sicht auf Candle-Kontext für 60s, 1m, 5m, 15m und 1h.

### Retrospective Outcomes

Validierungsverlauf für 5m / 15m / 30m, ausschließlich retrospektiv.

### Data Quality Gating

Dokumentiert Coverage, Gap Count, fehlende AggTrades und fehlende Validierungen.

## Sortierung

Die Haupttabelle ist deterministisch nach:

1. exchange time
2. observation_id

sortiert. Sichtbare Einträge sind bewusst begrenzt; der Rest bleibt im Persistenzlayer.

## Read-only Contract

Die UI darf ausschließlich vorhandene Artefakte anzeigen. Sie darf keine neuen Beobachtungen, Cases oder Bewertungen erzeugen.
