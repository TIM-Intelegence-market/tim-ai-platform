# S8/P2: Datenvertrag Orderbuch (Binance Spot BTCUSDT) – Entwurf

**Status: ENTWURF 0.1.** Noch kein Collector, keine Aufzeichnung. Grundlage: Bauplan P2 (26.10.2026).
Vor der Umsetzung gegen die dann aktuelle Binance-Spot-Dokumentation prüfen: Die Stream-Felder unten sind am
26.10. auf developers.binance.com nachgelesen; der Synchronisationsablauf (Abschnitt 3) stammt aus der bekannten
Dokumentation „How to manage a local order book correctly“ und war in der Cloud nicht abrufbar.

## 1. Quellen

| Quelle | Endpunkt | Inhalt |
|---|---|---|
| Diff-Depth-Stream | `wss://stream.binance.com:9443/ws/btcusdt@depth@100ms` | `e`=depthUpdate, `E` Ereigniszeit (ms), `s` Symbol, `U` erste Update-Id, `u` letzte Update-Id, `b`/`a` Preis-/Mengenpaare (Menge 0 = Stufe entfernen) |
| Snapshot | `GET https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5000` | `lastUpdateId`, `bids`, `asks` |

Öffentliche Daten, kein API-Schlüssel. Snapshot mit Limit 5000 kostet Request-Gewicht; nur beim Start und nach
einer Lücke abrufen, nie periodisch „zur Sicherheit“.

## 2. Was gespeichert wird (Rohdaten, append-only)

Jede Nachricht unverändert plus Empfangsmetadaten; daraus muss jeder Buchzustand nachgebaut werden können.

| Feld | Typ | Bedeutung |
|---|---|---|
| `kind` | `snapshot` \| `diff` \| `resync` \| `gap` | Art des Eintrags |
| `exchange_event_ms` | int | `E` (diff) bzw. leer (snapshot) |
| `receive_ns` | int | lokale Empfangszeit, monotone Uhr + Wanduhr-Bezug je Sitzung |
| `first_update_id` / `final_update_id` | int | `U` / `u`; beim Snapshot `lastUpdateId` |
| `bids` / `asks` | Liste [Preis-Text, Mengen-Text] | Texte unverändert, keine Float-Umwandlung |
| `session_id` | uuid | eine Verbindung = eine Sitzung |
| `source` | Text | Endpunkt und Collector-Version |
| `payload_sha256` | hex | Prüfsumme der Rohnachricht |

Ablage: Tagesdateien (UTC) unter `data/research_lab/orderflow_ml/depth/`, komprimiert, mit Tagesmanifest
(Zeilenzahl, Prüfsumme, Sitzungen, Lücken). Nicht in der Runtime-Datenbank, solange P2 Labor ist.

## 3. Synchronisation (je Verbindung)

1. Stream öffnen und Nachrichten puffern; `U` der ersten Nachricht merken.
2. Snapshot holen. Ist `lastUpdateId` < `U` der ersten gepufferten Nachricht, Snapshot erneut holen.
3. Gepufferte Nachrichten mit `u` ≤ `lastUpdateId` verwerfen.
4. Die erste angewandte Nachricht muss `U` ≤ `lastUpdateId` + 1 ≤ `u` erfüllen.
5. Danach muss jede Nachricht `U` = vorheriges `u` + 1 haben. Sonst: Eintrag `gap`, Buch ungültig, ab 1. neu.
6. Menge 0 entfernt die Preisstufe; eine Stufe, die nicht im Buch ist, wird ignoriert.
7. Verbindungsende (Binance trennt spätestens nach 24 h) und Neustart erzeugen eine neue Sitzung und einen
   neuen Snapshot; die Zeit dazwischen ist eine ausgewiesene Lücke.

## 4. Abgeleitete Sekundenmerkmale (erst nach Replay-Abnahme)

Je volle Sekunde aus dem bis dahin **empfangenen** Buch: beste Kurse, Spread, Microprice-Näherung,
Tiefenungleichgewicht in festen Abständen (z. B. 5/10/25 bp), mehrstufige Buchänderung seit der Vorsekunde.
Reicht die erfasste Tiefe nicht bis zum Abstand, ist das Merkmal fehlend. Ein ungültiges Buch (Abschnitt 3,
Schritt 5) liefert keine Merkmale und keine Prognose.

Grenzen: L2-Aggregat, keine Identifikation von Akteuren, keine sichere Zuordnung von Storno/Nachfüllen, kein
Nachweis von Spoofing oder Icebergs.

## 5. Abnahme (Vorschlag)

- Replay der Rohdaten ergibt dieselben Buchzustände wie der Live-Collector (Prüfsumme je Sekunde).
- Getestet: Neustart, Sequenzlücke, doppelte Nachricht, Snapshot älter als Puffer.
- Technische Probe 72 h: ≥ 99,5 % qualitätsgültige Sekunden, maximale Ausfalllänge ausgewiesen, null Merkmale
  auf ungültigen Sekunden. Nach 24 h Datenmenge messen; Speicherplan = Menge je Tag × Aufbewahrungstage × 1,3.
- Prospektive Daten bekommen eigene, vorab registrierte Zeitgrenzen; sie umgehen den Archiv-Holdout nicht.

## 6. Nicht Teil dieses Vertrags

Kein Collector-Start ohne Uzis Freigabe (läuft dauerhaft auf dem Mac und belastet Netz und Platte), keine
Änderung an `~/TIM-live`, keine Orders.
