# TIM V4 Developer Manual — Kapitel 00

# Verfassung

Version: **0.1.0**
Status: **Konsistent (reflektiert TIM Constitution Band 1 und Band 10)**
Verbindlichkeit: **Ja**

Dieses Kapitel überführt die TIM-Verfassung in eine entwickel- und prüfbare
technische Spezifikation. Im Konfliktfall hat die jeweilige Constitution-Band
Vorrang; dieses Kapitel ist ihre widerabgespiegelte Repräsentation. Jede Regel
ist deterministisch formuliert, prüfbar und referenzierbar.

## 1. Ziel

Die nicht verhandelbaren, unabdingbaren Prinzipien dokumentieren, gegen die
jede Weiterentwicklung von TIM geprüft wird. Kein Kapitel, kein Master Prompt,
kein Agent, kein Modell, keine Plattform und kein Release darf diese Prinzipien
verletzen.

## 2. Kernwerte (verbindlich)

| # | Wert | Bedeutung |
|---|---|---|
| 1 | Determinismus | Identische Eingaben erzeugen stets identische Ausgaben. |
| 2 | Reproduzierbarkeit | Jeder Zustand ist vollständig rekonstruierbar (Replay). |
| 3 | Nachvollziehbarkeit | Jede Entscheidung hat Quelle, Version, Hash, Lineage, Zeitpunkt. |
| 4 | Transparenz | Keine Black Boxes, keine versteckten Entscheidungen. |
| 5 | Evidenz | Nur Evidenz zählt; Behauptungen sind wertlos. |
| 6 | Modularität | Jede Plattform unabhängig entwickelbar, testbar, ersetzbar. |
| 7 | Testbarkeit | Nicht getesteter Code gilt als nicht existent. |
| 8 | Wartbarkeit | Lesbarkeit wichtiger als Cleverness. |
| 9 | Langfristigkeit | Kurzzeitige Optimierung darf Architektur nicht beschädigen. |
| 10 | Sicherheit | Kapitalschutz vor Performance. |

Konformität zu diesen Werten wird in Kapitel 02 (Architektur) und Kapitel 25
(Testing) zu automatischen, vertesteten Prüfungen verknüpft.

## 3. Goldene Regeln

1. Kein Code ohne Tests.
2. Kein Merge ohne PASS.
3. Keine Änderungen an freigegebenen Plattformen ohne dokumentierte Regression.
4. Keine impliziten Abhängigkeiten.
5. Keine versteckte Logik.
6. Keine Seiteneffekte.
7. Keine globalen Zustände.
8. Keine Magie — alles muss erklärt werden.

## 4. Engineering-Philosophie

TIM wird entwickelt mit der Sorgfalt eines Flugzeugsteuerungs- oder
medizinischen Diagnosesystems, nicht wie ein Startup- oder Trading-Tool:

1. Qualität vor Geschwindigkeit.
2. Korrektheit vor Features.
3. Reproduzierbarkeit vor Innovation.

## 5. KI-Policy

KI-Systeme sind Werkzeuge, keine Autoritäten.

**Erlaubt:** analysieren, strukturieren, dokumentieren, refaktorieren, testen,
erklären, vorschlagen, simulieren, bewerten.

**Niemals eigenständig:** Architektur verändern, Schutzgrenzen entfernen, Tests
abschwächen, Sicherheitsmechanismen deaktivieren, Regressionen akzeptieren,
Trading aktivieren, Produktionsfreigaben durchführen, Releases erstellen.

Diese Politik ist in Kapitel 19, 20, 21, 22 und 23 operationalisiert
(Shadow- / Paper-Scope, Review- und Audit-Zwang).

## 6. Entwicklungslifecycle (verbindliche Reihenfolge)

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

Keine Phase darf übersprungen werden. Die für jede Phase erforderlichen
Qualitätsgates sind in Kapitel 26 (Acceptance) spezifiziert (Doctor,
Validate, Full Suite, Acceptance).

## 7. Definition of Done

Eine Plattform ist ausschließlich fertig, wenn **alle** zutreffen:

- alle Tests PASS
- Doctor PASS
- Validate PASS
- Exit-Code 0
- keine Regression
- Working Tree sauber
- Dokumentation vollständig (dieses Handbuch, siehe Kapitel 25/26)
- Schemas vollständig (Kapitel 24)
- `Replay` erfolgreich
- Determinismus bestätigt
- Acceptance PASS

## 8. Bottom-up Architektur-Sequenz

Foundation → Dataset → Knowledge → Research → Feature → Observation →
Strategy → Evaluation → Simulation → Portfolio → Risk → Decision → Execution →
Agents → LLM → RAG → Monitoring → Security → Production → Release.

Die Reihenfolge ist verbindlich; jede Plattform baut auf der vorherigen auf.
Die Zuordnung zur Datenfluss- und Modulstruktur erfolgt in Kapitel 02.

## 9. Ethos

TIM besitzt keine Priorität auf Gewinn. Prioritäten:

1. Korrektheit
2. Nachvollziehbarkeit
3. Sicherheit
4. Qualität
5. Performance
6. Automatisierung

Gewinn ist ausschließlich das Ergebnis eines korrekt funktionierenden Systems,
kein Ziel an sich.

## 10. Architektur-Prinzipien (Band 1)

- Informationen fließen ausschließlich vorwärts (siehe Kapitel 02).
- Rückkopplung nur über explizite Replay-/Feedback-Mechanismen.
- Plattformen kommunizieren nur über definierte Verträge.
- Keine versteckten Abhängigkeiten.

## 11. Vertrauens-Grenzen (Trust Boundaries)

- Dataset darf niemals Execution steuern.
- Research darf niemals Orders erzeugen.
- Knowledge darf niemals Portfolio verändern.
- Feature darf niemals Trades eröffnen.
- Risk darf niemals Dataset manipulieren.
- Execution darf niemals Schemas verändern.

## 12. Evolutionskonzept (Band 10)

- Neue Technologie nur kontrolliert integrieren.
- Evolution ersetzt keine Governance; Innovation keine Qualität; Komplexität
  keine Klarheit.
- Modellunabhängigkeit: kein einzelnes Modell ist Teil der stabilen Architektur.
- Autonomie wird durch Evidenz verdient, nie vorausgesetzt.
- Die Constitution wird versioniert weiterentwickelt; Grundsätze bleiben.

## 13. Akzeptanzkriterien

- [ ] Konformität zu TIM_CONSTITUTION.md und Band 10 verifiziert.
- [ ] Keine Widersprüche zu Kernwerten und Golden Rules.
- [ ] Prüfbar formuliert (jede Regel referenzierbar).

---

*Ende Kapitel 00.*