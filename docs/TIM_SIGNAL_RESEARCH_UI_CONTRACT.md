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

## Retrospektive Häufigkeiten im Fall-Export

Gilt für den prüfbaren Fall-Export (`src/research/case_export.py`, `src/research/retrospective.py`).
Das Dashboard bleibt davon unberührt.

- Gezählt werden nur frühere, vollständig validierte Orderflow-Observations mit gleicher
  `observation_type`, gleicher `rule_version` und gleicher `validation_version`.
  Versionen werden nie zusammengelegt.
- Ein Fall zählt nur, wenn sein Ausgang zum Stichtag (`as_of` = Eröffnung des Research Case)
  bereits bekannt war: Beobachtung, alle Horizont-Zielzeiten und `validated_through` liegen
  vor dem Stichtag. Die eigenen Observations des Case sind ausgeschlossen. `TEST_ONLY`-Daten
  sind ausgeschlossen.
- Unter 10 vergleichbaren Fällen werden keine Häufigkeiten angezeigt.
- Ausgabe nur als Anzahl je Outcome (`PRICE_INCREASED`, `PRICE_DECREASED`, `PRICE_SIDEWAYS`),
  Label `RETROSPECTIVE`, Hinweis „Keine Prognose, keine Empfehlung, kein Signal".
  Keine Wahrscheinlichkeiten, keine Richtungsaussage, kein Ranking.
- Der Block ist Teil des gehashten Exports; jede Änderung macht den `output_hash` ungültig.
- Jeder Block nennt seine Grundlage (`basis`): die Anzahl der Orderflow-Beobachtungen im
  geladenen Verlauf. Der Rückblick beansprucht nicht, die vollständige Historie abzudecken.
