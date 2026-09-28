# TIM — Priorisierter Abschlussplan

Stand: 9. September 2026. Auftrag: zeitnah fertigstellen, anhand überprüfbarer
Betriebsnachweise. Ziel ist zuerst stabiler Live-Datenbetrieb, danach technische
Freigabereife für Trading. Echte Orders benötigen weiterhin eine eigene Freigabe.

## Arbeitsweise

Ein aktiver Implementierungsblock, keine konkurrierenden Änderungen im selben
Repository. Bestehende Automatisierung setzt diesen Plan fort. Jeder Lauf muss
Code, Testevidenz oder einen aufgelösten Blocker liefern, sofern ein ausführbarer
Task vorhanden ist. Keine neuen Dashboards, KI-Integrationen oder Refactorings,
solange sie nicht nachweislich einen Abnahmeblocker beseitigen. Alle bestehenden
Missionspflichten bleiben verbindlich; keine Tests oder Gates streichen.

## Kritischer Pfad und Abnahmen

| Priorität | Arbeit | Konkreter Abschlussnachweis |
|---|---|---|
| P0 | Mission 09.1: Defekt-Reproduktion, Test-DB-Guard, offene Regressionen, Observer-Metriken, Shadow-Beobachtung | Sämtliche 09.1-Pflichtgates belegt; keine Geheimnisse im Speicher/Prozessaufruf; Neustart/Rotation/Storm bestanden; keine automatischen unsicheren Reparaturen |
| P1 | Aktuellen TIM-Datenbetrieb verifizieren, Quelle/Code/Schema/Config zuordnen; offene Mission-07/08-Datenanforderungen abgleichen | Datierte Bestandsaufnahme; isolierter Restore; Queue/Outbox/Leases erklärt; Cursor/Counts/Hashes und verarbeitete Live-Daten nachgewiesen |
| P2 | Freigegebene Linux-Stufen 09–12 des bestehenden Linux-/Qube-Plans | MIGRATION_READY vor Cutover; isolierter Linux-Betrieb, Datenparität, systemd/Monitoring, Backup/Restore und mindestens 24h stabiler Betrieb ohne unerklärte Integritätsabweichung |
| P3 | Execution-Vorbereitung gemäß Stufen 13–17: Schnittstellen-Kompatibilität, Risk Gate, Replay, Shadow/Paper | Hersteller-/Schnittstellennachweise, idempotenter Adapter, Restart-/Reconciliation-/Netzausfall-Tests; nur simulierte oder explizite Testendpunkte; dokumentierte technische Abnahme |
| P4 | Production Readiness Audit, Stufe 18 | Alle Pflichtgates nachvollziehbar; offene Risiken, Betriebsanleitung, Alarmierung, Kill-Switch und Rückweg; unabhängiger Review soweit verlangt; separate Live-Freigabe bleibt ausstehend |

Der bestehende Linux-/Qube-Plan liegt unter
`/Users/tim/Documents/New project/docs/TIM_LINUX_QUBE_PLAN.md`.
Seine Reihenfolge wird nicht übersprungen. Nummern aus Daten-Missionen und
Linux-Missionen werden anhand ihrer Quelle zugeordnet, nicht blind gleichgesetzt.

## Nächste ausführbare Arbeit

1. M09.1-G-004 / G-008: Die bestehende Keychain-Argumentoffenlegung mit künstlichem
   Secret und ausschließlich simuliertem Prozessaufruf reproduzieren; Quellhash
   und verletzte Invariante speichern. Kein echter Keychain-Aufruf.
2. M09.1-H-001: Vor jedem Testzugriff die Zielidentität prüfen. Identisches
   Runtime-/Testziel, Host-Aliase und mehrdeutige DSN-Parameter müssen vor einem
   Verbindungsversuch scheitern. Vorhandenen Runtime-Normalbetrieb beibehalten.
3. Breite Testfehler einzeln reproduzieren. Graphify-Testkonfiguration isolieren,
   ohne eine lokale Aktivierung still umzuschalten. Snapshot-Tests nur bei
   ruhendem Repository wiederholen.
4. Eine verfügbare, nachweislich separate PostgreSQL-Testinstanz verwenden oder
   lokal isoliert aufsetzen. Keine Runtime-Credentials laden und keine Tests
   gegen Production. Fehlen Binärdateien/Plattform/Zugriff, einen konkreten
   Abhängigkeitsblocker mit nächstem zulässigem Schritt speichern.
5. Observer-Metriken, Restore-/Resilience-Prüfungen und Abnahmeberichte abschließen.

## Zeitsteuerung

Stündlicher Fortsetzungslauf; ein Lauf arbeitet einen vollständigen prüfbaren
Block ab und setzt weitere unabhängige Tasks fort, solange das sinnvoll möglich
ist. Fälligkeiten sind Arbeitsschwerpunkte, keine unbewiesenen Fertigzusagen:

- Nächster Arbeitsblock: konkrete Defekt-Reproduktion plus Guard-Regressionen.
- Danach: erste vollständige Testbilanz mit einer geklärten Isolationsumgebung.
- Anschließend: Beobachtungs-/Stabilitätsläufe; der vorgeschriebene 24h-Lauf
  benötigt reale Laufzeit und darf nicht durch Tests simuliert als erfüllt gelten.
- Vor Shadow/Paper: Dauer, technische Grenzwerte und Fehlerszenarien festlegen;
  Freigabe nur nach tatsächlich gemessenen Resultaten, nicht wegen Zeitablauf.

Ein Termin für echte Orders wird erst nach stabiler Datenbasis, vorhandener
Execution-Schnittstelle und bewerteten Shadow-/Paper-Ergebnissen belastbar.

## Blocker- und Abschlussregel

Kein Stillstand wegen eines einzelnen Blockers: unabhängige autorisierte Tasks
weiterführen. Unveränderte Blocker nicht jede Stunde erneut melden. Benachrichtigen
bei gelöstem Abnahmeschritt, neuem konkretem externen Bedarf oder fertigem Audit.
Der Programmstate unterscheidet IMPLEMENTED, VERIFIED und EXTERNAL_APPROVAL_PENDING.
Die Automation darf technische Fertigstellung dokumentieren, aber keine echte
Handelsausführung oder unabhängige Produktionsfreigabe selbst erteilen.

## Umsetzung im ersten Arbeitsblock

- M09.1-G-004 / G-008: konkrete Credential-Argumentoffenlegung in einem begrenzten,
  geprüften Quellfunktions-Fixture reproduziert; künstliches Secret, simulierte
  Prozessschnittstelle, deterministischer Quellhash. 8 neue Fixturetests bestanden.
- M09.1-H-001: Runtime-/Testzielgleichheit und DSN-Zielüberschreibungen werden
  vor Verbindungsaufbau abgewiesen. Gegenproben scheiterten vor dem Fix;
  Komponenten-/Guard-/Recovery-Prüfung danach: 125 bestanden.
- Neue PostgreSQL-18.4-Instanz mit eigenem Datenverzeichnis, eigener Rolle,
  einmaligem Testpasswort und separatem Loopback-Port gestartet. Identität durch
  `SHOW data_directory` und Datenbankname überprüft. Kein Runtime-Secret geladen.
- Vollständige Suite auf dieser Instanz: **980 bestanden, 4 fehlgeschlagen,
  keine übersprungenen Tests**, 63,18 s. Server anschließend sauber gestoppt.
- Verbleibend: Credential-Transport und drei Graphify-Konfigurationsannahmen.
  Keine kosmetischen Korrekturen nur zum Bestehen der Suite. Insbesondere ist
  die Annahme des bisherigen Credential-Mocks über eine einzelne stdin-Zeile
  gesondert zu korrigieren/validieren, bevor ein sicherer Adapter freigegeben wird.

Belege unter `work/mission09_1/known_defect_reproduction.json`,
`isolated_postgres_summary.json`, `isolated_postgres_tests.xml` und
`isolated_postgres_tests.log`. Der stündliche Fortsetzungslauf wurde auf den
vollständigen Programmplan P0–P4 erweitert.
