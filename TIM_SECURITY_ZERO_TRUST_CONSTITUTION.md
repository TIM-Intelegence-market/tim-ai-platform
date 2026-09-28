# TIM Constitution Band 6 — Security & Zero Trust Constitution

Version: **TIM Constitution Band 6**
Status: **Authoritative Security Constitution**

Dieses Dokument definiert die Sicherheitsregeln des gesamten TIM-Ökosystems.
Jede Plattform, jeder Agent, jede Pipeline, jede KI und jedes Deployment muss
diesen Regeln folgen.

Band 6 besitzt denselben verbindlichen Constitution-Status wie die Bänder 1–5.
Für die Konfliktauflösung gilt weiterhin die etablierte Reihenfolge:

1. TIM Constitution Band 1
2. TIM Constitution Band 2
3. TIM Constitution Band 3
4. TIM Constitution Band 4
5. TIM Constitution Band 5
6. TIM Constitution Band 6
7. Master Prompts
8. Implementierung

## Zero Trust Philosophy

TIM vertraut grundsätzlich keinem Benutzer, Agenten, LLM, Programm, keiner
Bibliothek, keinem Plugin, keiner Datei und keinem Netzwerk. Auch intern gilt
Trust = 0. Jede Aktion wird überprüft.

## Security Goals

Die Sicherheitsziele besitzen folgende Priorität:

1. Integrität
2. Nachvollziehbarkeit
3. Authentizität
4. Verfügbarkeit
5. Vertraulichkeit

Performance besitzt niemals Vorrang vor Integrität.

## Identity

Jeder Benutzer, Agent, jedes Repository, jede Pipeline, jedes Dataset,
Knowledge Object, jede Research Session, jedes Feature, jede Decision und jede
Execution besitzt eine eindeutige Identity. Identities werden niemals
wiederverwendet.

## Authentication and Authorization

Jeder Zugriff benötigt Identity, Authentifizierung, Autorisierung und Audit.
Ohne vollständige Authentifizierung erfolgt keine Aktion.

Alle Berechtigungen folgen Least Privilege. Ein Agent besitzt ausschließlich
die für seine Aufgabe notwendigen Rechte. Globale Administratorrechte sind
verboten.

## Role Model

Rollen wie Read, Write, Review, Approve, Release, Deploy, Audit und Emergency
besitzen jeweils explizite, versionierte und reviewbare Berechtigungen.

## Protected Paths

Besonders geschützt sind:

- Foundation;
- Constitution;
- Schemas;
- Historical Data;
- Research Evidence;
- Release Tags;
- Secrets;
- Security Policies.

Nur ausdrücklich autorisierte Prozesse dürfen Änderungen vornehmen.

## Secrets

Secrets dürfen niemals im Repository, in Logs, Reports, Markdown oder Prompts
erscheinen. Dazu zählen insbesondere API Keys, Tokens, Passwörter, private
Zertifikate und lokale Zugangsdaten. Secrets werden ausschließlich über
geeignete Secret Stores bereitgestellt.

## Configuration

Konfiguration ist versioniert, reviewbar, validierbar und auditierbar.
Versteckte Konfigurationen sind verboten.

## Audit

Jede sicherheitsrelevante Aktion protokolliert mindestens Zeit, Identity,
Aktion, Objekt, Version, Hash und Ergebnis. Audit Logs sind immutable und
append-only.

## Supply Chain

Externe Bibliotheken gelten als nicht vertrauenswürdig. Neue Abhängigkeiten
erfordern Review, Lizenzprüfung, Security Review, Versionierung und
Dokumentation.

Abhängigkeitsversionen werden kontrolliert eingefroren. Unkontrollierte Updates
und automatische Major Upgrades sind verboten. Jede Änderung durchläuft Tests,
Review und Acceptance.

## File System

Pfadflucht, Symlink Escape und unkontrollierte Dateizugriffe sind verboten.
Jeder Dateizugriff wird gegen autorisierte Roots, Pfade, Typen und
Berechtigungen validiert.

## Network

Netzwerkzugriffe sind standardmäßig verboten. Externe Kommunikation muss
explizit erlaubt, protokolliert, begründet und versioniert sein.

## LLM Security

LLMs besitzen keinen Vertrauensstatus. Ausgaben sind Vorschläge, keine Wahrheit.
Jede relevante Ausgabe benötigt Review, Validierung, Tests und Dokumentation.

## Prompt Security

Prompts sind Code. Sie werden versioniert, reviewt, getestet und dokumentiert.
Prompt Injection ist Bestandteil des Threat Models und der Tests.

## Agent Security

Agenten dürfen niemals:

- eigene Rechte erweitern;
- die Constitution eigenständig ändern;
- Security deaktivieren;
- Tests entfernen oder abschwächen;
- Audit umgehen;
- nicht benötigte Secrets lesen;
- Produktions- oder Release-Freigaben eigenständig erteilen.

## Release Security

Ein Release benötigt Review, Acceptance, Security Review, Test Report, Release
Report, Rollback Plan und Recovery Plan. Ohne vollständige Nachweise gibt es
keinen Release.

## Backup

Backups sind vollständig, versioniert, prüfbar, wiederherstellbar und werden
regelmäßig getestet. Ein nicht getestetes Backup gilt als kein Backup.

## Disaster Recovery

Für jede kritische Plattform existiert ein dokumentierter Recovery Plan.
Recovery wird regelmäßig getestet und evidenzbasiert dokumentiert.

## Incident Model

Bei Sicherheitsvorfällen gilt:

1. Stop
2. Isolate
3. Collect Evidence
4. Audit
5. Root Cause Analysis
6. Fix
7. Regression Test
8. Review
9. Recovery
10. Post Mortem

## Production Security

Produktionsänderungen benötigen Review, Acceptance, Security Review, Rollback
Plan, Monitoring und Health Checks. Direkte Änderungen in Production sind
verboten.

## Security Quality Gate

Eine Änderung wird nur freigegeben, wenn:

- Security Review PASS;
- Tests PASS;
- Replay PASS;
- Audit vollständig;
- keine offenen Schwachstellen;
- Rollback vorhanden;
- Dokumentation vollständig.

Security ist keine optionale Funktion, sondern eine Grundeigenschaft des
Systems. Ein Umgehen dieses Dokuments gilt als Security-Governance-Verletzung.
