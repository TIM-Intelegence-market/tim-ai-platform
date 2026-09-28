# Betriebs-Runbook: Ausfall der Binance-Datenpipeline

Paket 4 aus dem Beirat-Plan. Hintergrund: Der Orderflow-Anbieter TradingLite hat 2026 den
Betrieb eingestellt, nachdem Börsenänderungen und wochenlange Ausfälle nicht mehr allein zu
tragen waren. Sobald Pilotkunden Belege beziehen, braucht jeder Ausfall einen festen Ablauf.

Grundsatz aus der Governance: **Lücken werden dokumentiert, nie aufgefüllt.** Kein Backfill,
keine synthetische Rekonstruktion (siehe `docs/TIM_HEALTH_CENTER_ARCHITECTURE.md`).

## 1. Erkennen

| Prüfung | Wo | Grün, wenn |
|---|---|---|
| Gesamtstatus | `curl -s http://127.0.0.1:8765/api/health` → `operational_health.status` | `GREEN` |
| Stream | `operational_health.stream` | `GREEN` (Stream läuft **und** letzte Candle ≤ 120 s alt) |
| Datenalter | `operational_health.data_age_seconds` | Zahl zwischen 0 und 120 |
| Datenbank | `operational_health.database` | `GREEN` |
| Sichtprüfung | Dashboard → Health Center | keine CRITICAL-Karten im Abschnitt „Operational Health" |

Der Status `YELLOW` bedeutet: Datenbank verbunden, aber Stream steht oder Daten sind veraltet.

## 2. Einordnen

- **Kurzer Verbindungsabbruch:** `src/data_ingestion/binance_ws.py` verbindet sich selbst neu,
  mit Wartezeit 2, 4, 8, 16, dann 30 s (jeweils plus bis zu 1 s Zufall). Im Log steht
  „Binance public stream disconnected … retrying in …". Nichts tun, 2 Minuten beobachten.
- **Stream bleibt RED länger als 5 Minuten:** Eingriff nach Abschnitt 3.
- **Datenbank RED:** zuerst `docker compose ps` (TimescaleDB auf `127.0.0.1:5432`), dann Abschnitt 3.
- **Viele „Malformed Binance message skipped" im Log:** Binance hat vermutlich das Nachrichtenformat
  geändert. Nicht neu starten, sondern `BinanceTradeStream.parse_message` gegen die aktuelle
  Binance-Dokumentation prüfen. Das ist ein Codefehler, kein Betriebsfehler.

## 3. Beheben

1. Datenbank prüfen und ggf. starten: `docker compose up -d`
2. TIM-Prozess beenden und neu starten: `.venv/bin/python main.py`
3. Nach 2 Minuten erneut `/api/health` prüfen (Abschnitt 1).
4. Bleibt der Stream RED: Netzwerk und Erreichbarkeit von Binance prüfen; bei gesperrtem Zugang
   keinen alternativen, nicht dokumentierten Datenweg improvisieren.

## 4. Dokumentieren

- Beginn und Ende des Ausfalls (UTC), Ursache soweit bekannt, betroffene Zeitfenster.
- Die Lücke bleibt in den Daten sichtbar. Research Cases aus dem Zeitraum werden nicht nachträglich
  ergänzt; das Data-Quality-Gating markiert sie.
- Belege, die ein Zeitfenster mit Lücke betreffen, nicht an Kunden ausliefern.

## 5. Kunden informieren (Pilotphase)

Nur wenn ein zugesagter Beleg betroffen ist. Vorlage:

> Zwischen <Beginn> und <Ende> UTC hatte TIM keinen Datenzugang zu Binance. Für diesen Zeitraum
> gibt es keine Belege; wir füllen Lücken grundsätzlich nicht nachträglich auf. Belege außerhalb
> dieses Zeitraums sind nicht betroffen.

## Offene Punkte

- [OFFEN] Automatische Benachrichtigung bei RED (heute nur Dashboard und `/api/health`).
- [OFFEN] Wer vertritt den Gründer bei Abwesenheit.
- [OFFEN] Ab welcher Ausfalldauer eine Pilot-Gutschrift fällig ist.
