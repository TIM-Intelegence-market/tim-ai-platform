# TIM Constitution Band 4 — Canonical Data Model

Version: **TIM Constitution Band 4**
Status: **Authoritative Canonical Data Model**

Dieses Dokument definiert die Datenstrukturen, Objektregeln, Identitätsregeln,
Ereignismodelle und Versionierungsprinzipien des gesamten TIM-Ökosystems.
Keine Plattform darf davon abweichen.

Die Präzedenz lautet:

1. TIM Constitution Band 1
2. TIM Constitution Band 2
3. TIM Constitution Band 3
4. TIM Constitution Band 4
5. Master Prompts
6. Implementierung

## Philosophy

TIM speichert keine veränderlichen Objekte, sondern unveränderliche Fakten.
Jeder Record ist immutable, versioniert, hashbar, serialisierbar, replayfähig,
schema-validiert und nachvollziehbar. Records werden niemals überschrieben;
jede Änderung erzeugt eine neue Version.

## Canonical Record

Alle Plattformen verwenden denselben Basistyp `CanonicalRecord` mit folgenden
Pflichtfeldern:

- `id`
- `entity_type`
- `entity_version`
- `schema_version`
- `created_at`
- `effective_at`
- `status`
- `hash`
- `parent_hash`
- `lineage_id`
- `correlation_id`
- `source_platform`
- `producer`
- `metadata`
- `payload`
- `validation`
- `confidence`
- `tags`

Kein neues Plattformobjekt darf diese Pflichtstruktur verletzen.

## Identity

Jede Entität besitzt eine lebenslang stabile Entity ID. Versionen besitzen
zusätzlich eine streng monoton steigende Entity Version. Überschreiben ist
verboten.

## Hashing

Jede Version besitzt einen SHA-256-Hash. Der Hash wird ausschließlich aus
Schema, Metadata und Payload berechnet. Whitespace, Feldreihenfolge und
Formatierung dürfen den Hash nicht verändern.

## Canonical Serialization

Alle Records werden durch eine gemeinsame kanonische Serialisierung abgebildet:
identische Daten erzeugen identische Bytes und damit denselben Hash.
Plattformmodule dürfen keine abweichende Serialisierung definieren.

## Versioning

Versionen sind immutable, append-only und auditierbar. Jede Version
dokumentiert:

- `created_at`;
- Autor;
- Grund;
- Change Summary;
- `supersedes`.

## Lineage

Lineage dokumentiert Parent, Origin, Dependencies sowie relevante Dataset-,
Knowledge-, Research-, Feature- und Decision-Referenzen. Lineage-Ketten müssen
azyklisch sein; Zyklen sind verboten.

## Provenance

Provenance dokumentiert Quelle, Zeit, Autor, Plattform, Version, Schema, Hash,
Pipeline, Commit, Branch, Review und Acceptance. Keine Entität darf Provenance
verlieren.

## Canonical Event

TIM arbeitet ereignisbasiert. Jedes immutable Event besitzt:

- Event ID;
- Event Version;
- Timestamp;
- Entity ID;
- Entity Version;
- Source Platform;
- Target Platform;
- Correlation ID;
- Payload;
- Hash;
- Schema Version.

## Snapshots

Immutable Snapshots bilden Zustände ab und enthalten Version, Hash, Timestamp,
Entities, Dependencies, Statistics und Checksums.

## Metadata and Payload

Metadata beschreibt einen Record, beispielsweise Author, Owner, Review Status,
Labels, Environment, Build, Runtime, Priority und Classification. Metadata
verändert niemals den Payload.

Payload enthält ausschließlich Fachinformationen, keine Plattformlogik,
Laufzeitobjekte oder temporären Daten.

## Validation

Jeder Record wird auf Schema, Version, Hash, Pflichtfelder, verbotene Felder,
Timestamp, Lineage, Dependencies und State geprüft. Ungültige Records werden
abgelehnt.

## Replay

Replay ist verpflichtend:

```text
identischer Input
→ identischer Record
→ identischer Hash
→ identische Ausgabe
```

Jede Plattform unterstützt Replay.

## Dependencies

Records referenzieren andere Records ausschließlich über IDs. Direkte
Objektverweise, Pointer und Speicherreferenzen über Plattformgrenzen sind
verboten.

## Schema Metadata

Jedes Schema dokumentiert Schema Version, Status, Author, Compatibility, Hash,
Breaking Change Flag und Migration Notes.

## Compatibility

Änderungen werden als PATCH, MINOR oder MAJOR klassifiziert. Breaking Changes
müssen dokumentiert, getestet, migriert und reviewt werden.

## Failure Model

Ungültige Records werden niemals gespeichert, ungültige Events niemals
verarbeitet und ungültige Versionen niemals akzeptiert.

## Interoperability

Dataset, Knowledge, Research, Feature, Observation, Strategy, Evaluation,
Simulation, Portfolio, Risk, Decision, Execution, Agent, LLM und Monitoring
verwenden dieselben Kernregeln.

## Definition of Valid

Ein Record ist nur gültig, wenn:

- Schema gültig;
- Hash gültig;
- Version gültig;
- Lineage gültig;
- Provenance vollständig;
- Replay erfolgreich;
- Validation erfolgreich;
- Dependencies gültig.

## Migration Rule

Band 4 gilt verbindlich für neue Verträge. Bereits abgenommene Records, die das
Modell noch nicht vollständig erfüllen, werden als explizite Migrationsschuld
inventarisiert. Ihre Anpassung erfordert einen eigenen, kompatibilitätsgeprüften
Migrationsauftrag und darf nicht still oder rückwirkend erfolgen.

Ein Verstoß gegen dieses Dokument gilt als Architekturverletzung.
