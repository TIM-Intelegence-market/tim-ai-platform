# TIM Linux + Qube Plan

Stand: 7. September 2026 · Status: Plan, keine Migrations- oder Live-Freigabe

Quelle: ChatGPT-Gespräch „TIM mit Qube verbinden“ (Konversation 6a9d5e69-d8c8-83ed-b7bb-39db457dc608), einschließlich der dort besprochenen Missionsfolge 08–18 und des Auftrags zur Übernahme ins TIM-Projekt. Dieses Dokument ist eine strukturierte Zusammenfassung, kein wortgetreues Chatarchiv.

## 1. Grundentscheidung und Reihenfolge

TIM wird auf **Ubuntu Server 26.04 LTS** als Zielplattform vorbereitet. TIM bleibt der **Intelligence-Layer**; ein unabhängiger TIM Risk Gate kontrolliert jede Ausführungsfreigabe. **Qube/QubeAlgo** wird anschließend als separate Execution-Schicht angebunden.

**Qube wird erst nach einem stabilen und verifizierten TIM-Linux-Stand integriert.** Ein Plattformwechsel ersetzt keine Bereinigung der Daten-, Queue- oder Recovery-Probleme.

```text
TIM-Zustand bereinigen → Linux aufbauen → TIM/PostgreSQL migrieren
→ Linux validieren und stabilisieren → Qube-Kompatibilität nachweisen
→ Adapter → Replay → Shadow → Paper → Production Readiness Audit
```

Standard ist `EXECUTION_MODE=OFF`. Auch `LIVE_READY` aktiviert keinen Live-Handel; dafür bleibt eine separate ausdrückliche Freigabe erforderlich.

## 2. Ausgangslage und Grenzen der Bestandsaufnahme

### Im Quellchat berichteter TIM-Zustand

- Mission 07: Datenbasis insbesondere für Open Interest, Funding, Liquidations, Volume Profile und Wochen-/Monatskontext vervollständigen und verifizieren.
- Queue/Outbox, PROCESSING-Einträge, Leases, Quarantine/Recovery sowie historische Head-of-Line- und Out-of-order-Probleme müssen vor der Migration nachvollziehbar abgeschlossen werden.
- Tests gegen die Produktionsdatenbank wurden als Problem benannt; Testisolation ist ein Migrationskriterium.
- Als macOS-Betriebsproblem wurde `launchd → StandardErrorPath → com.apple.macl/Logrotation → EX_CONFIG 78` beschrieben.
- Recovery soll nicht nebenbei den Dashboard-Port `8765` binden; Dienste und Recovery-Werkzeuge brauchen getrennte Lebenszyklen.

Diese Punkte sind aus dem Chat übernommene Befunde, keine am 7. September neu geprüfte Laufzeitdiagnose.

### Im gespeicherten TIM-Projekt tatsächlich eingesehen

Das in Codex gespeicherte TIM-Projekt liegt unter `/Users/tim/Documents/New project`.
Vorhanden sind Agent00-Orchestrator-Dateien, Kompatibilitäts-Einstiegspunkte und launchd-Logdateien. `codex/auto/current_task.yaml` (im Workspace „New project“, nicht im Repository) enthält einen Stand vom 6. Juli 2026 mit `agent07-memory-event-integration` als `queued`. `codex/auto/handoff.md` (ebenfalls dort) beschreibt einen abgeschlossenen Event-Bus-Query/Replay-Block und die Memory-Integration als nächsten Schritt. Diese Agent07-Aufgabe ist nicht automatisch mit Mission 07 der Trading-Roadmap gleichzusetzen.

Diese älteren Dateien belegen weder den heutigen Produktionszustand noch einen erfolgreichen Linux-Betrieb. Datenbank, laufende Dienste und Produktionsdaten wurden für diese Dokumentationsübernahme nicht geprüft. **Alle folgenden Gates sind offen, bis ein datierter Nachweis vorliegt.**

## 3. Zielarchitektur

```text
Exchange-Marktdaten
        ↓
TIM Collector
        ↓
PostgreSQL / Queue / Outbox
        ↓
TIM Worker → Candles / Features / Orderflow / OI / Funding / Liquidations
        ↓
Data Quality / Gap Detection / Duplicate Protection
        ↓
SHORT / MID / LONG Analyse ← optionale Ollama-/Research-Beiträge
        ↓
TIM Decision Engine
        ↓
Execution Gateway: Datenqualität + Signalvalidierung
        ↓
unabhängiger TIM Risk Gate
        ↓
Qube Adapter → Qube Execution → Exchange
        ↑              │
        └── ACK / Rejection / Fill / Orderstatus / Reconciliation

Ubuntu Server 26.04 LTS · systemd
Prometheus / Grafana / TIM Dashboard / Alerts
Graphify: ergänzende Struktur- und Abhängigkeitsanalyse
```

### Verantwortlichkeiten

| Baustein | Aufgabe |
|---|---|
| TIM Intelligence | Marktdaten, Candles, Orderflow, OI, Funding, Liquidations, Volume Profile, Kontext und SHORT/MID/LONG-Analysen |
| Decision Engine | Reproduzierbare Signalbewertung, Analyse-ID, Datenzustand und Trade-Kandidat |
| PostgreSQL | Persistente Daten- und Zustandsbasis; Schema, Migrationen und Wiederherstellung nachweisen |
| Queue / Outbox / Worker | Nachvollziehbare Verarbeitung, persistente Übergaben, Idempotenz, Leases und Recovery |
| Execution Gateway | Validiert das Signal und reicht nur vollständig definierte Befehle an den Risk Gate weiter |
| TIM Risk Gate | Unabhängige, deterministische Ausführungserlaubnis oder Sperre |
| Qube Adapter | Übersetzt freigegebene Befehle; ordnet Ausführungsereignisse eindeutig zu |
| Qube | Geplante Execution-Schicht einschließlich Order-Lebenszyklus; konkrete Funktionen erst durch Mission 13 bestätigt |
| Ollama | Optionale lokale KI-/Research-Unterstützung; kein direkter Orderzugriff |

## 4. Gate 0: Migration vorbereiten

`MIGRATION_READY` (im Chat auch `TIM_MIGRATION_READY`) darf erst gesetzt werden, wenn:

- Queue und Outbox konsistent sind; `PROCESSING = 0` oder jeder Restzustand vollständig erklärt ist.
- Keine unbekannten Leases bestehen; Quarantine, Recovery und Head-of-Line-Fälle dokumentiert und reproduzierbar behandelt sind.
- Tests isoliert von Production laufen und keine Produktionsdaten verändern.
- Ein Backup durch Wiederherstellung in einer isolierten Umgebung verifiziert ist.
- Datenqualitätsfehler, Lücken, Cursor und Hashes abgeglichen sind.
- Code-Version, Konfiguration und Schema-Version als Migrationsbasis feststehen.
- Trading deaktiviert ist und ein dokumentierter Rückweg existiert.

Ein dokumentierter Restfehler benötigt Auswirkungen, Verantwortlichkeit und eine begründete Entscheidung, ob er die Migration blockiert. Dokumentation allein macht einen unsicheren Zustand nicht migrationsfähig.

## 5. Linux-Migration und Betrieb

### Plattform

Zielentscheidung aus dem Chat: **Ubuntu Server 26.04 LTS**. Dort wurde auch 26.04.1 als Installationsstand vorgeschlagen. Das konkret eingesetzte Image, Patchlevel und die Paketversionen werden in Mission 09 festgehalten; dieses Dokument bestätigt keine Herstellerzertifizierung.

ARM64 kann als Linux-Testumgebung auf Apple Silicon dienen; AMD64 ist eine mögliche spätere Serverplattform. Ein Architekturwechsel erfordert eigene Dependency-, Daten- und Ergebnisprüfungen. Qube-Unterstützung für beide Architekturen ist offen.

Geplante Verzeichnisse:

| Pfad | Zweck |
|---|---|
| `/opt/tim` | Versionierter Anwendungscode / Releases |
| `/etc/tim` | Konfiguration und geschützte Secret-Verweise |
| `/var/lib/tim` | Persistenter Anwendungszustand |
| `/var/log/tim` | Falls nötig dateibasierte Logs; sonst journald |
| `/backups/tim` | Lokaler Backup-Bereich, ergänzt um eine getrennte Sicherung |

Python, PostgreSQL, Git, NTP/chrony, SSH, Firewall, Backups und Monitoring gehören zur Basis. Docker/Podman ist eine optionale Betriebsform, keine bereits beschlossene Pflicht. Qube bleibt bis zur Klärung seiner Deployment-Anforderungen separat. macOS-Keychain-Abhängigkeiten müssen durch geeignete Linux-Secret-Verwaltung ersetzt werden.

### systemd statt launchd

Geplante Dienste sind `tim-collector.service`, `tim-worker.service`, `tim-analysis.service`, `tim-api.service`, `tim-dashboard.service` und `tim-monitor.service`.

Für jeden Dienst werden Benutzerrechte, Arbeitsverzeichnis, Konfiguration, Startabhängigkeiten, Neustartverhalten, geordnetes Herunterfahren, Ressourcenlimits und Logging definiert. Dashboard-Ausfälle dürfen Collector und Worker nicht stoppen. Recovery darf keine UI-Dienste implizit starten.

Damit entfällt die im Chat genannte launchd/MACL-spezifische Fehlerklasse; Linux-Rechte, Logrotation und Restart-Verhalten müssen trotzdem separat getestet werden.

### PostgreSQL und Datenübernahme

Versionen und Erweiterungen inventarisieren, konsistente Sicherung erstellen, isoliert wiederherstellen und Schema/Counts/Hashes/Cursor vergleichen. Queue-/Outbox-Zustände kontrolliert übernehmen oder mit dokumentierter Regel abschließen. Gleichzeitige aktive Verarbeitung auf Quell- und Zielsystem verhindern. Cutover und Rollback müssen festlegen, welches System Schreibautorität besitzt und wie neue Daten erhalten bleiben.

TIM startet auf Linux zunächst ohne Qube und mit deaktivierter Execution. Abnahme erfordert:

- Datenaufnahme, Queue-Recovery, Outbox und PostgreSQL funktionieren.
- Restart/Resume, Duplicate Protection, Gap Detection und Candle-Determinismus bestehen.
- Backup/Restore ist praktisch nachgewiesen.
- macOS- und Linux-Ausgaben auf identischen Eingaben stimmen überein oder Unterschiede sind begründet und akzeptiert.
- Ein mindestens 24-stündiger Stabilitätslauf liefert überprüfbare Ergebnisse.

## 6. Qube-Kompatibilitätsgate und Adapter

Mission 13 klärt mit belastbaren Herstellerunterlagen bzw. einem isolierten Test: Ubuntu-26.04-Unterstützung, AMD64/ARM64, erforderliches JDK, Installation als JAR/Container/Dienst, Java-/REST-/gRPC-/Bus-Schnittstellen, unterstützte Crypto-Venues, Feed-Anbindung, Lizenzierung, Paper/Testnet, Replay sowie Order-Recovery nach Crash.

Die im Chat genannten Qube-Funktionen sind Planungsannahmen. Die dortigen internen Suchzitate werden nicht als unabhängig geprüfte Produktnachweise übernommen. Ergebnis ist eine datierte Kompatibilitätsmatrix mit Versionen, Quellen und Testergebnissen. Ohne `QUBE_VERIFIED` wird kein Adapter gebaut.

Ein TIM-Signal enthält mindestens `analysis_id`, Symbol, Horizont, Richtung, Confidence, Entry-Zone, Invalidation/Stop, Take-Profit, Datenzustand und Entscheidung. Ein `TRADE_CANDIDATE` ist noch keine Order.

Der Adaptervertrag ergänzt Schema-Version, Erzeugungszeit, Gültigkeit, Modus, Korrelations-/Idempotenz-ID und validierte Ausführungsparameter. Wiederholungen dürfen keine Doppelorder erzeugen. ACK, Rejection, Partial Fill, Fill, Cancel und unbekannte Zustände werden dauerhaft erfasst und mit dem tatsächlichen Ausführungszustand abgeglichen. Bei unklarem Zustand erfolgt keine blinde erneute Orderaufgabe.

## 7. Unabhängiger Risk Gate und Betriebsmodi

Der TIM Risk Gate prüft Datenqualität und Aktualität, Signal-Gültigkeit, Confidence-Regel, Positionsgröße, Hebel, definierten Stop, Tagesrisikobudget, bestehende Exponierung und Kill-Switch. Schwellenwerte werden später explizit konfiguriert und getestet. Fehlende oder widersprüchliche Voraussetzungen sperren neue Ausführung. Qube-interne Kontrollen ergänzen diesen Gate.

| Modus | Verhalten | Echte Börsenorders |
|---|---|---|
| `OFF` | Analyse/Datenerfassung möglich; keine neue Execution | Nein |
| `REPLAY` | Historische Daten, kontrollierte Zeit und simulierte Ausführung | Nein |
| `PAPER` | Ausschließlich Testnet-, Demo- oder Paper-Infrastruktur | Nein |
| `SHADOW` | Echtzeitdaten und protokollierte hypothetische Orders/Fills | Nein |
| `LIVE` | Freigegebene reale Execution innerhalb der Limits | Nur nach separater Freigabe |

Endpunkte, Konten, Schlüssel und persistenter Modus müssen eindeutig getrennt sein. Neustarts oder Fehler dürfen keinen automatischen Wechsel zu LIVE auslösen. OFF/Kill-Switch sperrt neue Orders; Umgang mit bereits offenen Orders und Positionen benötigt eine explizite Cancel-/Reconciliation-Regel und darf sie nicht unbeaufsichtigt lassen.

## 8. Replay/Backtesting, Shadow und Paper

### Replay / Backtesting

Historische TIM-Daten → TIM Replay → Decision → Risk Gate → Qube Replay bzw. nachgewiesene Simulation. Eingaben, Code, Konfiguration und Zeitbasis versionieren; Look-ahead vermeiden. Erwartete Entries/Stops/Exits mit simulierten Fills vergleichen. Gebühren, Slippage, Latenz, Partial Fills und Annahmen zum Market Impact dokumentieren. SHORT, MID und LONG getrennt auswerten. Replay-Ergebnisse sind kein Nachweis realer Fill-Qualität.

### Shadow Trading

Echte Marktdaten durchlaufen die vollständige Entscheidungskette, erzeugen aber keine echten Börsenorders. Speichern: Signalzeit, erwarteter Entry, hypothetischer Fill, Slippage-Annahme, Maximum Adverse/Favorable Excursion, Stop, Take-Profit und Ergebnis. Hypothetische Fills klar als solche markieren.

### Paper Trading

Ausführung nur auf geprüfter Testnet-/Demo-/Paper-Infrastruktur. Testfälle: TIM-, Qube- und PostgreSQL-Restart, Netzwerkverlust, WebSocket-Abbruch, Exchange-API-Fehler, doppelte Befehle, verspätete ACKs, Partial Fills, Rejections und Out-of-order-Events. Dabei Idempotenz, Recovery und Reconciliation nachweisen. Shadow- und Paper-Abnahmedauer sowie Grenzwerte vor dem Lauf festlegen; im Chat wurden dafür keine konkreten Zahlen beschlossen.

## 9. Monitoring, Graphify und Ollama

Prometheus sammelt Metriken; Grafana und TIM Dashboard stellen sie dar; Alerts melden handlungsrelevante Zustände. Graphify ist als ergänzende Struktur-/Abhängigkeitsanalyse vorgesehen. Das konkret gemeinte Graphify-Werkzeug, seine Schnittstellen und sein Betriebsnutzen sind noch zu klären.

Ab Mission 12 überwachen: Exchange-Latenz, Collector-Lag, Queue-/Outbox-Tiefe und Alter, Worker-Durchsatz, Datenlücken, Fehlerquote, Dienstzustand und Backup-Erfolg. Mit Qube ergänzen: Qube-/Order-ACK-/Fill-Latenz, Slippage, Orderzustände, Reconciliation-Abweichungen, PnL, Drawdown, Risikobudget sowie SHORT/MID/LONG-Performance. Simulation und Live-Metriken bleiben unterscheidbar.

Ollama unterstützt lokale KI-Aufgaben, Research und gegebenenfalls Entscheidungsvorbereitung erst auf stabilem Fundament. Beiträge laufen durch TIMs deterministische Regeln und den Risk Gate. Kein Pfad `Ollama → Qube → Order`. Der vorhandene Ollama-Fallback-Workflow (`codex/auto/handoff.md` im Workspace „New project“) beschränkt den dortigen Fallback auf Review/Research/Planung; eine weitergehende KI-Rolle ist ein zukünftiger Entwurf, keine Änderung dieser bestehenden Betriebsregel.

## 10. Missionsfolge 08–18

Die Nummerierung folgt dem Quellchat. Sämtliche Ergebnisse sind Soll-Gates, keine bereits erreichten Zustände.

| Mission | Aufgabe | Ergebnis / Abnahmenachweis |
|---|---|---|
| **08** | Aktuellen TIM-Zustand bereinigen | `MIGRATION_READY`: Gate 0, Mission-07-Datenstand, Recovery und Testisolation dokumentiert |
| **09** | Linux-Umgebung bauen | `LINUX_BASE_READY`: Ubuntu-Image, Architektur, Pakete, Rechte, Zeit, Netzwerk und Backup-Basis festgehalten |
| **10** | PostgreSQL + TIM migrieren | `TIM_LINUX_RUNNING`: isolierter Restore und TIM-Datenpipeline unter Linux, Execution OFF |
| **11** | Linux-Datenvalidierung | `TIM_LINUX_VERIFIED`: Daten-/Output-Abgleich, deterministische Verarbeitung, Duplikat-/Lückenprüfung |
| **12** | Dienste/systemd/Monitoring | `TIM_LINUX_STABLE`: Restart/Recovery, Backup/Restore, Alerts und mindestens 24h Stabilitätslauf bestanden |
| **13** | Qube-Kompatibilität prüfen | `QUBE_VERIFIED`: dokumentierter Nachweis zu OS, Architektur, JDK, Schnittstellen, Venues, Lizenz und Simulation |
| **14** | TIM-Qube Adapter bauen | `QUBE_CONNECTED`: versionierter Vertrag, Risk Gate, Idempotenz und Rückkanal in isolierter Umgebung geprüft |
| **15** | Replay/Backtest | `REPLAY_PASS`: reproduzierbare Resultate, Kosten-/Fill-Annahmen und Auswertung nach Horizont |
| **16** | Shadow Trading | `SHADOW_PASS`: Echtzeitkette ohne echte Orders, Abweichungen innerhalb vorab definierter Grenzen |
| **17** | Paper Trading | `PAPER_PASS`: ausschließlich Testinfrastruktur; Fehler-, Restart- und Order-Recovery-Fälle bestanden |
| **18** | Production Readiness Audit | `LIVE_READY`: vollständige Evidenz, Limits, Kill-Switch, Betrieb, Alarmierung und Rückweg geprüft |

Die im Chat ebenfalls genannten Bezeichner `TIM_LINUX_READY` und `QUBE_COMPATIBILITY_VERIFIED` sind zusammenfassende Gates: Linux-ready setzt hier Mission 11 **und** 12 voraus; Qube-Kompatibilität entspricht Mission 13. Keine zusätzlichen Implementierungsflags sind durch dieses Dokument angelegt.

**Mission 18 schaltet LIVE nicht ein.** Eine spätere Aktivierung benötigt eine eigene dokumentierte Entscheidung mit Konto/Venue, Limits, Verantwortlichkeit und Startzeit.

## 11. Nachweise und nächster Schritt

Jede Mission erhält vor Abschluss: Datum, verantwortliche Person, Code-/Schema-/Konfigurationsversion, Testumgebung, Abnahmekriterien, Resultate, Berichtspfade, Restprobleme und Gate-Entscheidung. Keine Freigabe ausschließlich aufgrund alter Chat-Aussagen oder vorhandener Logdateien.

Nächster Umsetzungsschritt ist **Mission 08: aktuellen tatsächlichen TIM-Code- und Betriebsstand identifizieren und Migrationsfähigkeit nachweisen**. Danach folgen Mission 09–12. Qube-Integration bleibt bis zum stabilen und verifizierten TIM-Linux-Stand gesperrt.

Diese Übernahme ergänzt ausschließlich Dokumentation. Sie verändert weder laufende Dienste noch Datenbank, Secrets, Trading-Modus oder bestehende TIM-Dateien.

> Übernommen am 2026-10-12 aus dem Workspace „New project“ (Stand 07.09.2026) ins Repository. Inhalt unverändert bis auf Verweise auf Dateien außerhalb des Repos und den Chat-Link, die jetzt als Textangabe stehen. Hinweis: Der Server tim-core-01 läuft inzwischen auf Debian 13 (`docs/TIM_V1_LIVE_STATUS.md`, Issue #88); die Ubuntu-Zielentscheidung in Abschnitt 5 stammt aus dem Quellchat vom September.
