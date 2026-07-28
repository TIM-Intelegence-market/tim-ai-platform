# TIM Final Scientific Reconciliation Report

**Projekt:** TIM - Transparent Intelligence for Markets  
**Core:** 1.0.0, `FROZEN`  
**Betriebsmodus:** `OBSERVE`  
**Dokumentstatus:** Finaler Abgleich der vorhandenen Evidenz  
**Stand der verwendeten Evidenz:** 2026-07-23 18:47:09 UTC  
**Gesamturteil:** `NOT_READY_FOR_V2` / `NO-GO`

## 1. Executive Summary

TIM Core 1.0 ist laut `config/core_manifest.json` funktional eingefroren und
arbeitet ausschließlich im Modus `OBSERVE`. Die vorhandene Evidenz bestätigt
eine technisch stabile, deterministische Public-Data-Research-Pipeline ohne
Trading- oder Orderausführung. Der reale 72-Stunden-Lauf ist abgeschlossen,
die Datenbank- und Dashboard-Verfügbarkeit sind hoch, und die erforderliche
Fallzahl von mindestens 1.000 vollständig validierten Cases wurde in einem
späteren Readiness-Snapshot überschritten.

Eine wissenschaftliche Freigabe oder V2-Freigabe ist dennoch nicht gegeben.
Der 72h-Acceptance-Report endet mit `NO-GO` bei 85 Prozent, weil die
Provenance-Anforderungen im vollständigen historischen Operationsdatensatz
nicht erfüllt sind. Der spätere Readiness-Snapshot endet mit
`NOT_READY_FOR_V2`, weil die zusammenhängende 1m-Coverage nur 60,659 Prozent
beträgt, 63 neue DATA_GAPs ungeklärt sind und der manuelle Scientific Review
aussteht. Der Artefakt-Audit meldet darüber hinaus einen
`OUTPUT_HASH_MISMATCH` für den Readiness-Snapshot.

Die unterschiedlichen Provenance-Aussagen sind kein Widerspruch zwischen den
beiden Bewertungssichten:

- Der 72h-Acceptance-Report bewertet den vollständigen operativen Bestand
  einschließlich Legacy- und vorläufiger Records.
- Der Readiness-Snapshot bewertet den definierten neuen Evidence-Scope und
  meldet für neu erzeugte Artefakte `PASS`.

Die beiden Hauptberichte stimmen in ihrer bindenden Aussage überein: TIM ist
technisch betriebsfähig, aber wissenschaftlich nicht freigegeben. Der offene
Hash-Befund ist davon getrennt zu behandeln; er ist ein tatsächlicher
Integritätsbefund innerhalb der aktuellen Readiness-Artefakte.

## 2. Report Registry

| Report | Path | Evidence Cut-off | Scope | Verdict |
|---|---|---|---|---|
| TIM 72h Acceptance Report | `docs/TIM_72H_ACCEPTANCE_REPORT.md` | Eingefrorene Reconciliation-Kopie vom 2026-07-23 18:47:09 UTC, abgeleitet aus `data/operational/state.json`; 75,568 reale Stunden | Vollständiges operatives 72h-Fenster einschließlich historischer und Legacy-Records | `NO-GO`, 85 % |
| TIM V1 Scientific Validation Report | `docs/TIM_V1_SCIENTIFIC_VALIDATION_2026-07-23.md` | Fester Repeatable-Read-Snapshot: 2026-07-22 23:02:37.321353 UTC | Fester wissenschaftlicher Snapshot, Coverage-Audit, Replay, Hashes, Versionen und Forward-only-Prüfung | `NOT_COMPLETE` |

Der maschinenlesbare Readiness-Snapshot
`data/research/status/tim_v1_readiness.json`, erzeugt am
2026-07-23 14:27:42.127641 UTC, aktualisiert die Scientific-Readiness-Zahlen
nach dem festen Validation-Snapshot. Er enthält 1.339 validierte Cases,
60,659 Prozent zusammenhängende Coverage und 63 ungeklärte neue DATA_GAPs.
Sein Status ist `NOT_READY_FOR_V2`; `eligible_for_scientific_review` und
`v2_approved` sind beide `false`.

Unterstützende Evidence-IDs in diesem Dokument:

| Evidence ID | Artifact |
|---|---|
| E1 | `config/core_manifest.json` |
| E6 | `data/research/status/tim_v1_readiness.json` |
| E7 | `data/research/audit/latest.json` |
| E8 | `data/research/quality/latest.json` |

## 3. Scope Differentiation

### 3.1 72h Acceptance

Der 72h-Acceptance-Report bewertet die vollständige operative Historie im
persistierten Acceptance-Fenster. Er umfasst 1.826 Samples und 1.825
Validator-Zyklen. Die Auswertung bezieht damit historische Records ein, die
vor der finalen Provenance- und Artefaktmetadaten-Struktur erzeugt wurden.

Die Prüfung endet mit folgenden zwei FAIL-Kriterien:

- Research Cases: 2.413 Cases, davon 460 mit der vom Acceptance-Gate
  erwarteten Provenance.
- Deterministische Provenance: 4.500 von 8.336 Records.

Alle übrigen acht Acceptance-Kriterien sind `PASS`, darunter reale Laufzeit,
Validator-Gesundheit, Datenbankkonsistenz, Candle-Zuwachs, eindeutige
Observations, API-Verfügbarkeit, Dashboard Auto-Refresh und OBSERVE-only.

### 3.2 Scientific Validation und Readiness

Der Scientific Validation Report arbeitet mit einem festen
Repeatable-Read-Snapshot. Zu diesem frühen Zeitpunkt enthielt er 165
vollständig validierte Cases und dokumentierte eine historische 1m-Coverage
von 42,5952865871 Prozent. Der Report verändert, rekonstruiert oder schätzt
keine Daten.

Der später erzeugte Readiness-Snapshot betrachtet den definierten
kontinuierlichen Zeitraum ab der ersten vollständigen Minute nach Beginn der
Raw-AggTrade-Persistenz:

- Start: 2026-07-22 20:14:00 UTC
- Ende: 2026-07-23 14:26:00 UTC
- Erwartete 1m-Intervalle: 1.093
- Persistierte 1m-Intervalle: 663
- Fehlende 1m-Intervalle: 430
- Continuous Coverage: 60,659 Prozent
- Validierte Cases: 1.339 von geforderten 1.000
- Ungeklärte neue DATA_GAPs: 63

### 3.3 Abgrenzung

Die Aussagen `new_artifact_provenance = PASS` und historische Provenance
`4.494/8.316 = FAIL` beziehen sich nicht auf denselben Datensatz. Die erste
Aussage gilt für den neuen, definierten Artefakt-Scope. Die zweite Aussage
gilt für den vollständigen historischen Acceptance-Scope. Es liegt deshalb
keine logische Inkonsistenz zwischen diesen beiden Provenance-Messungen vor.

Nicht durch die Scope-Differenz erklärt wird der separate Hash-Befund:
`tim_v1_readiness.json` meldet in seinen Kriterien `hash_consistency = PASS`,
während der zeitgleich erzeugte Artefakt-Audit für dieselbe Datei
`OUTPUT_HASH_MISMATCH` und Status `FAIL` meldet. Dieser Befund bleibt offen.

## 4. Provenance Breakdown

| Kategorie | Count | Status | Source Report / Artifact | Erklärung |
|---|---:|---|---|---|
| Neue Artefakte im definierten Readiness-Scope | Kein einzelner aggregierter Record-Count persistiert | `PASS` | `data/research/status/tim_v1_readiness.json` | `new_artifact_provenance_status = PASS`; Aussage gilt nur für den definierten neuen Artefakt-Scope |
| Legacy Module-A Records am aktuellen Audit-Cut-off | 1.602 | Legacy Limitation / `FAIL` | `data/research/audit/latest.json` | `artifact_hash`, `generator_version` und `schema_version` fehlen |
| Legacy Module-A Records im früheren festen Scientific Snapshot | 1.172 | Legacy Limitation / `FAIL` | `docs/TIM_V1_SCIENTIFIC_VALIDATION_2026-07-23.md` | Frühere Momentaufnahme; die spätere Audit-Zahl 1.602 ist kein identischer Cut-off |
| Historische deterministische Provenance gesamt | 4.500 / 8.336 | `FAIL` | Eingefrorene Reconciliation-Kopie von `docs/TIM_72H_ACCEPTANCE_REPORT.md` | Vollständiger operativer Scope einschließlich Legacy- und Preliminary-Capture-Records |
| Research-Case Provenance | 460 / 2.413 | `FAIL` | Eingefrorene Reconciliation-Kopie von `docs/TIM_72H_ACCEPTANCE_REPORT.md` | Vollständiger historischer Case-Bestand, teilweise vor Schema- und Provenance-Finalisierung |
| Artefakt-Audit | 13 / 15 Artefakte `PASS` | `FAIL` | `data/research/audit/latest.json` | Zwei Findings: Legacy-Metadaten und Readiness-`OUTPUT_HASH_MISMATCH` |

Die Zahlen 1.172 und 1.602 sind zeitlich getrennte Messungen desselben
Legacy-Problems. Sie dürfen nicht als identischer Bestand verglichen oder
subtrahiert werden. Ebenso sind 165 validierte Cases im festen Scientific
Snapshot und 1.339 validierte Cases im späteren Readiness-Snapshot
unterschiedliche, chronologisch wachsende Evidence-Cut-offs.

## 5. Consistency Argument

### 5.1 Vereinbare Aussagen

Die folgenden Aussagen sind über die vorhandenen Berichte hinweg vereinbar:

1. TIM Core 1.0 bleibt `FROZEN` und `OBSERVE-only`.
2. Die technische Pipeline ist betriebsfähig.
3. Es existieren keine Execution Events.
4. Replay, Forward-only und Schema-Prüfungen sind für die jeweils festgelegten
   Snapshots erfolgreich.
5. Die vollständige historische Provenance ist unvollständig.
6. Die neue zusammenhängende Datenabdeckung liegt unter dem 95-Prozent-Gate.
7. Eine wissenschaftliche oder V2-Freigabe liegt nicht vor.

### 5.2 Direkt vergleichbare Metriken

Direkt vergleichbar sind nur Metriken mit demselben Cut-off, demselben Scope
und derselben Definition. Dazu gehören innerhalb des 72h-Reports die zehn
Acceptance-Kriterien und innerhalb des Readiness-Snapshots dessen
Gate-Matrix. File-System-SHA-256-Werte sind nur für exakt dieselbe Dateiversion
vergleichbar.

### 5.3 Nicht direkt vergleichbare Metriken

Nicht direkt vergleichbar sind:

- Case Counts aus dem festen Snapshot und dem späteren Live-/Readiness-Scope.
- Historische Provenance-Coverage und Provenance neuer Artefakte.
- Historische Gesamt-Coverage und die neue Continuous Coverage ab
  Raw-AggTrade-Persistenz.
- Legacy-Record-Counts mit unterschiedlichen Generierungszeitpunkten.
- Hashes von Artefakten, die zwischen zwei Prüfungen neu erzeugt wurden.

Die Scope-Differenz erklärt die unterschiedlichen Provenance-Ergebnisse. Sie
erklärt nicht den zeitgleichen Readiness-Hash-Widerspruch; dieser bleibt ein
eigenständiger P0-Befund.

## 6. Binding V2 Release Criteria

| Criterion | Source | Priority | Blocking? | Aktueller Status |
|---|---|---:|---|---|
| Continuous Coverage >= 95 % im definierten neuen Fenster | Readiness und dokumentierte Release-Policy | P0 | YES | `WAITING`, 60,659 % |
| Neue ungeklärte DATA_GAPs = 0 | Readiness | P0 | YES | `FAIL`, 63 |
| Artifact Audit vollständig `PASS` | Audit / Quality | P0 | YES | `FAIL`, 13/15 Artefakte `PASS` |
| Hash Consistency reproduzierbar geklärt | Readiness / Audit | P0 | YES | Offen: Readiness `PASS`, Audit `OUTPUT_HASH_MISMATCH` |
| Manueller Scientific Review | Readiness / Core Freeze Policy | P0 | YES | `WAITING` |
| Validierte reale Cases >= 1.000 | Readiness | P0 | YES | `PASS`, 1.339 |
| Replay, Forward-only, OBSERVE-only und Regression | Readiness | P0 | YES | jeweils `PASS` im Snapshot |
| Historische Provenance | 72h Acceptance | P1 | Für den historischen 72h-Acceptance-Claim: YES. Für einen klar versionierten, isolierten zukünftigen V2-Evidence-Scope: dokumentierte Legacy-Limitation, kein eigener P0-Gate-Eintrag im Readiness-Snapshot | `FAIL` |

Historische Records werden nicht nachträglich verändert. Ein zukünftiger
versionsisolierter Evidence-Scope darf historische Provenance-Lücken nicht
stillschweigend als aktuelle Provenance ausweisen. Der 72h-Acceptance-Claim
bleibt für seinen vollständigen historischen Scope `NO-GO`.

## 7. Updated Release Sequence

| Step | Gate | Deliverable |
|---:|---|---|
| 1 | Scientific Reconciliation | `docs/TIM_FINAL_SCIENTIFIC_RECONCILIATION_REPORT.md` |
| 2 | Continuous Coverage >= 95 % im fest definierten Zeitraum | Coverage Report mit unveränderlichem Start, Ende, Expected, Persisted und Missing |
| 3 | Neue DATA_GAPs = 0; vorhandene Root Causes und Auswirkungen dokumentiert | Operational Incident Register |
| 4 | Readiness-/Audit-Hash-Widerspruch reproduzierbar geschlossen | Konsistente Hash-Evidenz für denselben Artefakt-Cut-off |
| 5 | Alle bindenden Gates erneut `PASS` | Final Technical Evidence Pack |
| 6 | Manueller Scientific Review | Bewusste Freigabe oder erneutes `NO-GO` |

Die Sequenz erzeugt keine automatische Freigabe. `v2_approved` bleibt bis zu
einer dokumentierten manuellen Entscheidung `false`.

## 8. Evidence Hashes

Die folgenden Werte sind File-System-SHA-256-Hashes der am
2026-07-23 18:47:09 UTC verwendeten Artefaktversionen. Der 72h-Report wurde
für diesen Cut-off in eine temporäre, unveränderliche Reconciliation-Kopie
übernommen, weil die operative Quelldatei nach Abschluss weiterhin aktualisiert
wurde. Die Hashes identifizieren die Dateien dieses Reconciliation-Cut-offs;
sie ersetzen nicht die semantischen
`artifact_hash`-, `dataset_hash`- oder `output_hash`-Felder innerhalb der
Artefakte.

| Artifact | SHA-256 | Source |
|---|---|---|
| `config/core_manifest.json` | `82bfe439178299adc5bca0ac1de17614a3fd5fe6ed72a110861f88af9d014ca6` | E1 |
| `data/research/status/tim_v1_readiness.json` | `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a` | E6 |
| `data/research/audit/latest.json` | `6620681264615c88d58702cf773a0a938fc0ea227d394f162d3dbfa7613391fb` | E7 |
| `data/research/quality/latest.json` | `eff0ce873d63d9398cf8b51f646c62ad7681bdd93ae7938fd6ed99ac1c6701d4` | E8 |
| Eingefrorene Reconciliation-Kopie von `docs/TIM_72H_ACCEPTANCE_REPORT.md` | `51cdd28f29ce6d8e4cddf3c8492738da333ea75b2c4427c51b519b2ced8fdb69` | 72h Acceptance, Cut-off 18:47:09 UTC |
| `docs/TIM_V1_SCIENTIFIC_VALIDATION_2026-07-23.md` | `ca0fefc622437f4e8f68cc652f97f683483b5a3a5cd1bc54f40837c640cb1b79` | Scientific Validation |

Interne Hashwerte aus dem Readiness-Snapshot:

- `dataset_hash`:
  `915ea39fa265eb78ebe3589e1d1024ab61426e679f1aa4d5118fe011cc38b9c0`
- `output_hash`:
  `00f7c5ab0e458063bd105cbd98cd40c3c4ad2ff76b9ed3026a192ac972d61b31`
- `snapshot_id`:
  `f6ffe6a3917a07f448b11db8a88de3743c09a7ed84005f9d4632e9484d94cced`

Der Artefakt-Audit bewertet den internen `output_hash` dennoch als
`OUTPUT_HASH_MISMATCH`. Dieser Bericht löst oder überschreibt den Befund nicht.

## 9. Conclusion

TIM Core 1.0 bleibt unverändert `FROZEN`. Der dokumentierte Core enthält keine
Trading-Ausführung und bleibt im Modus `OBSERVE`. Die technische
Betriebsfähigkeit, der abgeschlossene reale 72h-Lauf und mehr als 1.000
validierte reale Cases ändern den Freigabestatus nicht.

Die final abgeglichene Evidenz lautet:

- 72h Acceptance: `NO-GO`, 85 Prozent.
- Scientific Readiness: `NOT_READY_FOR_V2`.
- V2 Approval: `false`.
- Manual Scientific Review: ausstehend.
- Continuous Coverage: 60,659 Prozent.
- Ungeklärte neue DATA_GAPs: 63.
- Artefakt-Audit: `FAIL`.
- Historische Provenance: unvollständig.
- Neue Artefakt-Provenance im definierten Readiness-Scope: `PASS`.

Dieses Dokument ist ausschließlich eine Reconciliation der bestehenden
Evidenz. Es verändert keinen Code, keine Datenbankstruktur, keine Marktregel,
keine Metrik, keine Datenquelle und keinen historischen Datensatz. Es führt
keine Rekonstruktion oder künstliche Auffüllung durch.
