# TIM – Wissensindex aus den Projektchats

Stand: 27. September 2026  
Zweck: Dieses Dokument bündelt die Themen und wiederkehrenden Erkenntnisse aus den als **TIM** einsortierten Chats. Es ist ein Navigations- und Arbeitsindex, kein Laufzeitnachweis. Aussagen über Dienste, Datenbank, Netzwerk oder Freigaben gelten erst mit datierter Evidenz als bestätigt.

## Zentrale Referenz

Die verbindliche technische Roadmap, Architektur und die Freigabegates stehen in [TIM_LINUX_QUBE_PLAN.md](TIM_LINUX_QUBE_PLAN.md). Neue TIM-Arbeit soll dort gegen die Missionen und Gates eingeordnet werden.

## Datierte Übergaben

- [TIM_THREAD_CHECKUP_QWEN_2026-10-17.md](TIM_THREAD_CHECKUP_QWEN_2026-10-17.md): 24/7-Checkup, Qwen-Modell und Server-Zustand (Claude-Projekt-Thread, Stand 17.10.2026)

## Themenlandkarte

| Bereich | Gesammeltes Wissen | Relevante Chats |
|---|---|---|
| Datenqualität & Live-Daten | Vollständigkeit, Alter, Gaps, Cursor, Hashes und Provenance müssen überprüfbar sein. Reparaturen benötigen eine Ursache, einen Nachweis und eine Prävention gegen Wiederholung. | Daten 100% Prüfung; TIM Live-Data Repair; Behebe anhaltende Data Gaps; PostgreSQL Provenance Masterprompt |
| PostgreSQL & Runtime | PostgreSQL, Schema, Indizes, Listener und Runtime sind getrennt zu prüfen. Tests müssen von Produktion isoliert bleiben; Recovery darf keine unbeabsichtigten Dienste starten. | Prüfe TIM PostgreSQL read-only; Prüfe TIM-Produktionsindex-Build; Stabilisiere TIM-Runtime lokal; Beweise Runtime hinter Port 8765 |
| Betrieb & Observability | Überwachung umfasst Datenalter, Queue/Outbox, Worker, Fehler, Dienstzustand und klare Betriebsgrenzen. Ein Dashboard belegt allein keine gesunde Pipeline. | Überwachung; TIM-Dashboard auf Mainline heben; Qwen-Dashboard im TIM-Setup; Qwen Terminal Dashboard Setup |
| Server & Zugang | Tailscale, SSH, Admin-Konten und Serverzugang sind Voraussetzungen für einen kontrollierten Betrieb. Zugriffe sollen klein, nachvollziehbar und getrennt von Daten-/Runtime-Freigaben bleiben. | Mit Fleckbarts AI-Server verbinden; Verbinde Codex mit TIM-Server; Tailscale-Verbindung für TIM prüfen; Richte direkten Tailscale-SSH-Zugang; Zweiten TIM-Admin anbinden |
| Deployment & Migration | Migration setzt einen bereinigten, reproduzierbaren Ausgangsstand voraus. Linux, PostgreSQL und Runtime müssen isoliert validiert werden; Cutover braucht einen Rollback und eine eindeutige Schreibautorität. | TIM Server Migration; Prüfe TIM-Server Bring-up; Produktions-Cutover-Empfehlungen; Stabilisiere TIM-Runtime lokal (2) |
| KI-Unterstützung | Qwen, GLM, Ollama und OpenCode sind Unterstützungswerkzeuge für Analyse, Review und Self-Repair. Sie dürfen keine ungeprüften Änderungen oder direkte Ausführung auslösen. | Bewerte Qwen Self-Improving; GLM TIM OPEN SOURCE; Erstelle TIM-Trainingszusammenfasss; Bereite Self-Repair-Start vor; Execute TIM Mission 09.2 |
| MCP & Integrationen | Jede Integration braucht Zweck, Rechte, Datenfluss und überprüfbare Freigaben. MCP-Verbindungen werden vor produktiver Nutzung auditierbar dokumentiert. | TIM MCP-Verbindungen prüfen; TIM MCP Audit; Prüfe TIM-Integrationsfreigaben |
| Architektur & Sicherheit | TIM bleibt Intelligence- und Decision-Layer. Execution ist getrennt, durch einen unabhängigen Risk Gate abgesichert und standardmäßig deaktiviert. | TIM Serverarchitektur darstellen; Review TIM v1 release report; TIM OPEN CODE PROMPTS |

## Dauerhafte Arbeitsregeln

1. `EXECUTION_MODE=OFF` bleibt der Ausgangszustand; keine Chat-Zusammenfassung ist eine Live-Freigabe.
2. Jede Änderung an Datenfluss, Runtime oder Server benötigt einen vorab definierten Evidenzpfad: Umgebung, Versionen, Prüfschritte, Ergebnis und Rest-Risiken.
3. Datenqualität wird vor Analyse-, Dashboard- oder Ausführungsentscheidungen geprüft.
4. Recovery, Migration und Tests laufen isoliert und dürfen keine Produktionspfade verändern.
5. Netz-, Zugriffs- und Admin-Änderungen werden getrennt von Trading-/Execution-Freigaben bewertet.
6. KI-generierte Vorschläge bleiben Vorschläge, bis sie gegen Code, Daten und Tests validiert sind.

## Offene, wiederkehrende Prüfpunkte

- Aktuellen Datenstand und verbliebene Gaps mit frischer Evidenz feststellen.
- Queue, Outbox, Leases, Recovery und Idempotenz unter Fehler- und Neustartfällen nachweisen.
- Tatsächlichen PostgreSQL-/Runtime-/Port-8765-Zustand unabhängig prüfen.
- Serverzugang, Tailscale und Rollenmodell auf den minimal nötigen Zugriff begrenzen.
- Linux-Migrationsgates erst nach isoliertem Restore, Datenvergleich und Stabilitätslauf abschließen.
- Qube oder andere Execution-Integration erst nach stabiler TIM-Basis, Risk Gate und expliziter Freigabe bewerten.

## Pflegeprozess

- Neue TIM-Chats werden im Seitenleistenordner **TIM** abgelegt.
- Wenn ein Chat eine belastbare Erkenntnis, Entscheidung oder Evidenz liefert, wird die passende Zeile oben aktualisiert und auf den Chat oder einen Bericht verwiesen.
- Zeitkritische Betriebsstände gehören zusätzlich in einen datierten Bericht; dieser Index bleibt bewusst stabil und thematisch.

> Übernommen am 2026-10-12 aus dem Workspace „New project“ (Stand 27.09.2026) ins Repository, damit TIM-Arbeit die hier genannten Gates im Repo nachlesen kann. Inhalt unverändert.
