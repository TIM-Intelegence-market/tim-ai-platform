# TIM V4 Developer Manual

**Betriebshandbuch für TIM — Trusted Intelligent Machine**

Version: **0.1.0 (Foundation)**
Status: **Inkrementell im Aufbau**

Dieses Handbuch ist das verbindliche Referenzwerk für Entwicklung,
Weiterentwicklung und Betrieb des TIM-Ökosystems. Es übersetzt die
TIM-Constitution-Bände und Master Prompts in eine strukturierte, entwickelbare
und testbare Spezifikation. Es ist bewusst als **inkrementelles** Dokument
aufgebaut: Jedes Kapitel wird vollständig ausgearbeitet, geprüft und
versioniert, bevor das nächste folgt.

## Zielsetzung

- Verbindliche technische Spezifikation für alle Weiterentwicklungen.
- Grundlage für Architektur-, Governance- und Qualitätsentscheidungen.
- Nachvollziehbare Dokumentation der Plattformen, Verträge und Regeln.
- Referenz für Coding Standards, Teststrategie und API.

## Konvention

Dieses Handbuch ist stets **ehrlich**: Es beschreibt den tatsächlichen Zustand
von TIM auf Grundlage von Code, Tests, Schemas und Git-Stand, nicht nur auf
Basis von Wünschen. Wo eine Spezifikation noch nicht im Code umgesetzt ist,
wird dies explizit als `[SPEZIFIKATION]` markiert — nicht als Implementierung
dargestellt.

## Struktur

```text
TIM_V4_DEVELOPER_MANUAL/
├── README.md
├── 00_CONSTITUTION.md
├── 01_GOVERNANCE.md
├── 02_SYSTEM_ARCHITECTURE.md
├── 03_REPOSITORY_STRUCTURE.md
├── 04_CODING_STANDARD.md
├── 05_DATA_PLATFORM.md
├── 06_DATA_QUALITY.md
├── 07_ORDERFLOW_ENGINE.md
├── 08_AUCTION_MARKET_ENGINE.md
├── 09_MARKET_STRUCTURE_ENGINE.md
├── 10_LIQUIDITY_ENGINE.md
├── 11_SCENARIO_ENGINE.md
├── 12_CONFIRMATION_ENGINE.md
├── 13_PROBABILITY_ENGINE.md
├── 14_TRADE_DECISION_ENGINE.md
├── 15_TRADE_PLAN_ENGINE.md
├── 16_RISK_ENGINE.md
├── 17_PORTFOLIO_ENGINE.md
├── 18_BACKTEST_ENGINE.md
├── 19_RESEARCH_ENGINE.md
├── 20_PAPER_ENGINE.md
├── 21_SHADOW_ENGINE.md
├── 22_REVIEW_ENGINE.md
├── 23_AUDIT_ENGINE.md
├── 24_JSON_SCHEMAS.md
├── 25_TESTING.md
├── 26_ACCEPTANCE.md
├── 27_RELEASE.md
├── 28_API_REFERENCE.md
└── 29_CHANGELOG.md
```

## Kopfzeilen-Template pro Kapitel

Jedes Kapitel folgt einem einheitlichen Aufbau, sofern fachlich sinnvoll:

| Abschnitt | Zweck |
|---|---|
| Ziel | Was das Kapitel verbindlich festlegt |
| Architektur/UML | Beteiligte Komponenten und Abhängigkeiten |
| Datenfluss | Ein- und Ausgaben, Sequenzen |
| Datenmodelle | Records, Schemas, Felder |
| Regeln | Verbindliche Invarianten und Constraints |
| State Machines | Zustände und erlaubte Übergänge |
| JSON-Beispiele | Validuse und Sonderfälle |
| Diagramme | Mermaid-Diagramme |
| Teststrategie | Erforderliche Testarten und Abdeckung |
| Fehlerszenarien | Erwartete Fehler und Verhalten |
| Akzeptanzkriterien | Definition of Done für das Kapitel |

## Grundprinzipien (Auszug)

1. Determinismus: Gleiche Eingaben → gleiche Ergebnisse.
2. Reproduzierbarkeit: Jeder Zustand rekonstruierbar.
3. Nachvollziehbarkeit: Quelle, Version, Hash, Lineage, Zeitpunkt.
4. Transparenz: Keine Black Boxes.
5. Evidenz: Nur Evidenz zählt.
6. Modularität: Plattformen unabhängig.
6. Testbarkeit: Nicht getesteter Code gilt als nicht existent.
8. Wartbarkeit: Lesbarkeit vor Cleverness.
9. Sicherheit: Kapitalschutz vor Performance.

## Dokument-Management

Dieses README wird bei jedem Erreichen eines neuen Kapitelstandes aktualisiert
(Änderungslog in `00_...` bzw. im `29_CHANGELOG.md`). Jedes Kapitel wird erst
versioniert und als "konsistent" markiert, wenn Tests, Schemas und Doc
übereinstimmen.

## Phase 2 — Verifikation (abgeschlossen)

Jedes Kapitel wurde satzweise gegen den realen Quellcode geprüft. Ergebnis:

- `VERIFICATION_REPORT.md` — Implementierungsgrad je Kapitel, fehlende
  Klassen/Funktionen/Tests, Risiko, Empfehlung.
- `IMPLEMENTATION_GAP.md` — priorisierte Lückenregister (HIGH/MEDIUM/LOW).
- `ROADMAP_V5.md` — nur aus Verifikation abgeleitete Maßnahmen.
- `ARCHITECTURE_REVIEW.md` — Imports, tote Logik, Duplikate, Enums.

Jedes Kapitel trägt am Ende einen Abschnitt `## Code Coverage (Phase 2)` mit
dem verifizierten Status. Gesamt: ~88 % VERIFIED, ~8 % PARTIAL, ~4 % SPEC.

---

*TIM V4 Developer Manual — erzeugt inkrementell, verifiziert (Phase 2).*