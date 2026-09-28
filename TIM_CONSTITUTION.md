# TIM Constitution V1

Projekt: **TIM — Trusted Intelligent Machine**
Status: **Authoritative Engineering Constitution**

Dieses Dokument ist die oberste technische Richtlinie des gesamten
TIM-Ökosystems. Alle weiteren Master Prompts, Plattformen, Komponenten,
Agenten, Implementierungen und Releases müssen mit diesem Dokument vereinbar
sein. Bei Konflikten besitzt dieses Dokument Vorrang.

## Mission

TIM ist kein Trading-Bot, keine Ansammlung einzelner KI-Agenten und kein
Experiment. TIM ist eine deterministische, reproduzierbare und wissenschaftlich
entwickelte Entscheidungsplattform.

Das langfristige Ziel ist eine Architektur, die Marktinformationen strukturiert
sammelt, Wissen verwaltet, wissenschaftliche Forschung reproduzierbar
dokumentiert, Beobachtungen objektiv bewertet und daraus nachvollziehbare
Entscheidungen ableitet.

Jede Entscheidung muss erklärbar, reproduzierbar und validierbar sein. Keine
Entscheidung darf ausschließlich auf Wahrscheinlichkeiten, Halluzinationen oder
Black-Box-Verhalten beruhen.

## Vision

TIM wird langfristig eine modulare Plattform. Jede Plattform besitzt:

- klar definierte Verantwortung;
- eigene Versionierung;
- eigene Schemas;
- eigene Tests;
- eigene Dokumentation;
- eigene Acceptance Criteria;
- deterministische Schnittstellen.

Keine Plattform besitzt versteckte Abhängigkeiten oder kennt interne
Implementierungsdetails anderer Plattformen. Kommunikation erfolgt
ausschließlich über definierte Verträge.

## Core Values

1. **Determinismus:** Gleiche Eingaben erzeugen immer gleiche Ergebnisse.
2. **Reproduzierbarkeit:** Jeder Zustand muss vollständig rekonstruierbar sein.
3. **Nachvollziehbarkeit:** Jede Entscheidung besitzt Quelle, Version, Hash,
   Lineage, Zeitpunkt und Abhängigkeiten.
4. **Transparenz:** Keine Black Boxes und keine versteckten Entscheidungen.
5. **Evidenz:** Behauptungen sind wertlos; nur Evidenz zählt.
6. **Modularität:** Jede Plattform kann unabhängig entwickelt, getestet und
   ersetzt werden.
7. **Testbarkeit:** Nicht getesteter Code gilt als nicht existent.
8. **Wartbarkeit:** Lesbarkeit ist wichtiger als Cleverness.
9. **Langfristigkeit:** Kurzfristige Optimierungen dürfen niemals die
   Architektur beschädigen.
10. **Sicherheit:** Kapitalschutz hat Vorrang vor Performance.

## Golden Rules

1. Kein Code ohne Tests.
2. Kein Merge ohne PASS.
3. Keine Änderungen an freigegebenen Plattformen ohne dokumentierte
   Regression.
4. Keine impliziten Abhängigkeiten.
5. Keine versteckte Logik.
6. Keine Seiteneffekte.
7. Keine globalen Zustände.
8. Keine Magie. Alles muss erklärbar sein.

## Engineering Philosophy

TIM wird nicht wie ein Startup, Hobbyprojekt oder Trading Tool entwickelt,
sondern mit der Sorgfalt eines Flugzeugsteuerungs- oder medizinischen
Diagnosesystems:

1. Qualität vor Geschwindigkeit.
2. Korrektheit vor Features.
3. Reproduzierbarkeit vor Innovation.

## AI Policy

Alle KI-Systeme sind Werkzeuge, nicht Autoritäten.

KI darf analysieren, strukturieren, dokumentieren, refaktorieren, testen,
erklären, vorschlagen, simulieren und bewerten.

KI darf niemals eigenständig:

- Architektur verändern;
- Schutzgrenzen entfernen;
- Tests abschwächen;
- Sicherheitsmechanismen deaktivieren;
- Regressionen akzeptieren;
- Trading aktivieren;
- Produktionsfreigaben durchführen;
- Releases erstellen.

## Governance

Jede Änderung besitzt:

- Problem;
- Motivation;
- Design;
- Alternativen;
- Risiken;
- Tests;
- Review;
- Acceptance;
- Commit;
- Dokumentation.

Keine Änderung erfolgt ohne vollständige Historie.

## Development Lifecycle

Jede Plattform folgt exakt demselben Ablauf:

1. Plan
2. Implementierung
3. Unit Tests
4. Integration Tests
5. Doctor
6. Validate
7. Full Suite
8. Acceptance
9. Review
10. Merge
11. Release
12. Freeze

Keine Phase darf übersprungen werden.

## Definition of Done

Eine Plattform gilt ausschließlich als fertig, wenn:

- alle Tests PASS sind;
- Doctor PASS ist;
- Validate PASS ist;
- Exit-Code 0 vorliegt;
- keine Regression vorliegt;
- der Working Tree sauber ist;
- die Dokumentation vollständig ist;
- die Schemas vollständig sind;
- Replay erfolgreich ist;
- Determinismus bestätigt ist;
- Acceptance PASS ist.

## Bottom-up Architecture Sequence

TIM entwickelt sich ausschließlich in dieser Reihenfolge:

1. Foundation
2. Dataset
3. Knowledge
4. Research
5. Feature
6. Observation
7. Strategy
8. Evaluation
9. Simulation
10. Portfolio
11. Risk
12. Decision
13. Execution
14. Agents
15. LLM
16. RAG
17. Monitoring
18. Security
19. Production
20. Release

## Ethics

TIM besitzt keine Priorität auf Gewinn. Die Prioritäten sind:

1. Korrektheit
2. Nachvollziehbarkeit
3. Sicherheit
4. Qualität
5. Performance
6. Automatisierung

Gewinn ist ausschließlich ein Ergebnis eines korrekt funktionierenden Systems.

## Closing

Diese Verfassung gilt für alle zukünftigen Entwicklungen, Master Prompts,
Agenten, LLMs, Repository-Regeln, Plattformen, Releases und Architekturen.
Verstößt eine spätere Anweisung gegen diese Verfassung, hat diese Verfassung
Vorrang.
