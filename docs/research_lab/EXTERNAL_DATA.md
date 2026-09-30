# Research Lab – Externe Daten (BTC Research Engine V1: Data & Events)

| Feld | Wert |
|---|---|
| Code | `src/research_lab/external/` |
| Tests | `tests/test_research_lab_external.py` (ohne Netzwerk, synthetische Fixtures) |
| Transform-Version | `1.0.0` (`records.TRANSFORM_VERSION`) |
| Erste Quelle | ALFRED, US-CPI `CPIAUCSL` (alle Vintages) |

Dieses Modul macht externe Daten für die BTC-Forschung **zeitlich korrekt**
nutzbar. Es erzeugt keine Prognose, kein Signal, keine Aussage „X treibt BTC“
und berührt weder die Produktions-DB noch einen Order-Pfad. Die Regeln aus
`PROTOKOLL.md` (insbesondere die Holdout-Sperre) gelten unverändert.

## 1. Datenfluss

```
ALFRED-Payload (series, observations, release_dates)
  → store.RawPayloadStore        Rohbytes, SHA-256, Anfrage ohne API-Key
  → alfred.parse_bundle          Normalisierung + Datenqualität → IngestResult
  → pit.PointInTimeStore         was war wann bekannt
  → events.release_events        CPI-Veröffentlichungen (actual/previous/revision)
  → align.BtcSeries/align_*      Ausrichtung auf Research-Lab-Klines
  → replay.run_replay            deterministischer Forschungsdatensatz
```

## 2. Zeitbegriffe

| Feld | Bedeutung |
|---|---|
| `period_start` / `period_end` | Referenzperiode (Monat), Ende exklusiv |
| `vintage` | ALFRED `realtime_start`: Datum, ab dem der Wert galt (ohne Uhrzeit) |
| `release_time` | geplanter Veröffentlichungszeitpunkt, nur bei Release-Terminen |
| `available_at` | ab wann TIM den Wert nutzen darf |
| `ingested_at` | wann TIM die Daten abgerufen hat |
| `vintage_end` | ALFRED `realtime_end`; **nie** für Sichtbarkeit genutzt (späteres Wissen) |

`available_at`:

- Vintage-Datum ist ein Termin aus dem Release-Kalender (`release/dates`, Release 10):
  Datum 08:30 America/New_York (BLS-Veröffentlichung, Sommerzeit beachtet),
  `availability_basis = SCHEDULED_RELEASE`.
- Sonst (Korrekturen, fehlender Kalender, auf den Anfragebeginn gekappte Vintages):
  Ende des Vintage-Tages in New York, `END_OF_VINTAGE_DAY`. Das ist konservativ:
  der Wert wird eher zu spät als zu früh sichtbar. Solche Vintages haben keine
  Ereigniszeit.

FRED übernimmt die BLS-Zahlen erst später am Morgen. `available_at` beschreibt
die öffentliche Verfügbarkeit bei der Primärquelle, nicht den FRED-Import.

## 3. Point-in-Time-Regel

Zum Zeitpunkt T ist ein Vintage nur sichtbar, wenn `available_at <= T`. Je
Periode gilt das neueste sichtbare Vintage. Zustände:

| Status | Bedeutung |
|---|---|
| `AVAILABLE` | Wert bekannt |
| `MISSING` | Quelle hat „kein Wert“ (`.`) veröffentlicht |
| `UNKNOWN` | Vintage existiert, ist aber unbrauchbar (Konflikt, Formatfehler, unmögliche Zeitfolge) |
| `NOT_AVAILABLE` | zu T noch nichts veröffentlicht |
| `INSUFFICIENT_DATA` | T liegt nach der abgerufenen Abdeckung (`coverage_end`) |

Es gibt keinen stillen Rückfall: Ist das neueste sichtbare Vintage unbrauchbar,
lautet das Ergebnis `UNKNOWN`, nicht der ältere Wert. `stale = true`, wenn die
nächste Periode laut `max_first_release_lag` (45 Tage) überfällig ist.

## 4. Revisionen und Vintages

- Jede Wertänderung in ALFRED ist ein eigener Datensatz. Replay vor der Revision
  sieht den alten, danach den neuen Wert (`revision_number`).
- `output_type=1` liefert eine neue Zeile nur, wenn sich der Wert ändert:
  `revision_number` zählt Wertänderungen, nicht jede Veröffentlichung.
- Liegt das früheste archivierte Vintage einer Periode später als eine erste
  Veröffentlichung sein konnte, wird die Periode als
  `REVISION_HISTORY_UNAVAILABLE` markiert (`first_release_in_archive = false`).
  Der Wert ist dann erst ab diesem Vintage sichtbar, nie früher. Mit
  Release-Kalender muss das früheste Vintage außerdem der erste Kalendertermin
  nach Periodenende sein; sonst gilt der Erstdruck ebenfalls als fehlend (die
  Verzugsgrenze kann einen Erstdruck nur widerlegen, nicht belegen). Der
  Kalender muss dafür einen Termin vor dem Periodenende enthalten, höchstens
  ein Release-Intervall (45 Tage) vor dem Erstdruck; ohne
  Kalendertermine (fehlend oder leer) gilt kein Erstdruck als belegt.

## 5. Datenqualität

Wiederverwendet: `QualityIssue`/`Severity` aus `src/quality/framework.py`.

| Befund | Wirkung |
|---|---|
| unbekannte Quelle | `UnknownSource` |
| Zugangsdaten in den Anfrageparametern | `ValueError` (vor jeder Ausgabe) |
| Metadaten weichen ab (ID, Einheit, Frequenz, Saisonbereinigung, Transformation, `output_type ≠ 1`, Paging, Release-ID) | Payload `NOT_READY` |
| JSON ungültig, Payload fehlt, Release-Kalender unvollständig | `NOT_READY` |
| Zeile ohne `realtime_start` oder mit nicht lesbarem Perioden-/Vintage-Datum | ganze Payload `NOT_READY` (Verfügbarkeit oder Periode nicht bestimmbar) |
| Periodendatum lesbar, aber kein Periodenbeginn; Vintage vor Periodenende; `available_at > ingested_at`; ungültiger oder nicht positiver Wert | Periode ab diesem Vintage `UNKNOWN` |
| ungültiges oder widersprüchliches `realtime_end` (auch bei Duplikaten) | Ende gilt als unbekannt; das **nächste** Vintage der Periode wird ab seiner eigenen Verfügbarkeit `UNKNOWN` (das Ende ist erst dann erkennbar) |
| Gültigkeit überlappt mit irgendeinem früheren Vintage (auch einem unbrauchbaren) | späteres Vintage `UNKNOWN` |
| gleiche Periode/Vintage doppelt, gleicher Wert | eine Zeile behalten (unabhängig von der Reihenfolge), Warnung |
| gleiche Periode/Vintage doppelt, anderer Wert | `UNKNOWN` |
| Vintage endet (`realtime_end`), aber kein Vintage beginnt am Folgetag (fehlende Revision, Lücke) | `MISSING_VINTAGE`: Periode `UNKNOWN` ab dem Zeitpunkt, zu dem der fehlende Nachfolger sichtbar geworden wäre; frühere Replays unverändert |
| Periode laut Release-Kalender veröffentlicht, im Archiv aber ganz ohne Vintage | `MISSING_PERIOD` ab dem fälligen Release-Zeitpunkt; `latest()` ab dann `stale` (die ältere Periode bleibt als solche ausgewiesen, kein Ersatzwert) |
| Vintage außerhalb des erklärten Real-Time-Bereichs der Payload, oder Bereichsbeginn nach Bereichsende | Payload `NOT_READY` (`INCONSISTENT_METADATA`) |
| fehlender oder leerer Release-Kalender | Warnung, alle Vintages `END_OF_VINTAGE_DAY`, kein Erstdruck belegt |
| Wert außerhalb 1e-6 … 1e9 (Betrag) oder mit mehr als 20 Stellen | `UNKNOWN` (`MALFORMED_VALUE`), damit die Ereignisrechnung im festen Decimal-Kontext nie überläuft |
| Datum am Kalenderrand ohne darstellbare Periodenrechnung oder `available_at` (z. B. Periode 0001-01 oder 9999-12) | nicht datierbar: Payload `NOT_READY` |
| BTC-Kerze mit ungültigem Preis/Volumen oder falschem Raster (bis zur Replay-Zeit) | `ValueError`; Kerzen nach der Replay-Zeit werden weder genutzt noch geprüft |

Replay zeigt nur Befunde, die zu T datiert oder undatiert (Payload-Ebene) sind,
damit die Befundliste keine späteren Vintages verrät.

## 6. Ereignisse

`events.ReleaseEvent` je Vintage, das eine neue Periode veröffentlicht:
`actual` (Erstwert der neuen Periode), `previous` (Vorperiode unmittelbar vor der
Veröffentlichung), `previous_revised` (Vorperiode in dieser Veröffentlichung),
`revision`, `derived_change_pct` (aus den Indexwerten desselben Vintage).
Fehlt der Erstdruck der Periode im Archiv (`first_release_in_archive = false`),
ist das Vintage nicht die Veröffentlichung: Status `FIRST_RELEASE_UNAVAILABLE`,
`event_time` leer, keine Fenster und keine Erwartung.

`expected` und `surprise` bleiben leer (`UNAVAILABLE_NO_EXPECTATION`), solange
keine belegte Erwartung vorliegt. `with_expectation` verlangt Quelle, Kennung, eine
bekannte Ereigniszeit und einen Erwartungszeitpunkt strikt davor; Konsenswerte
werden nie erfunden. Rechnungen laufen in einem festen Decimal-Kontext.
`surprise_normalized` wird hier nicht berechnet.

## 7. BTC-Ausrichtung

- Klines aus dem Research Lab (`data.parse.Kline`), streng steigend, auf dem
  Intervallraster. Klines im Holdout (ab 2025-01-01) nur mit Holdout-Freigabe
  (`HoldoutLocked` sonst).
- Zeitreihe: je geschlossene Kerze der zum Kerzenschluss bekannte Wert
  (`decision_time = open_time + Intervall`), mit Split-Label (train/validation/holdout).
- Ereignis: Referenzkerze, die spätestens zur Veröffentlichung schließt
  (`btc_close_before`), und Kerzenfenster für 5m, 15m, 1h, 4h, 24h, 7d. Liegt die
  Veröffentlichung innerhalb einer Kerze, wird diese ausgewiesen und nicht
  verwendet. Status je Fenster: `COMPLETE`, `INSUFFICIENT_DATA`,
  `RESOLUTION_TOO_COARSE`, `NOT_AVAILABLE_AT_REPLAY_TIME`, `HOLDOUT_LOCKED`.
  Eine Veröffentlichung im Holdout liefert ohne Freigabe weder Referenzkerze noch
  Fenster.
- Es werden keine Renditen oder Reaktionen berechnet.

## 8. Replay und Reproduzierbarkeit

`run_replay(ingest, klines, ReplayConfig(replay_at, interval, horizons))` liest
weder Uhr noch Netz noch Zufall. Eine Replay-Zeit ab 2025-01-01 (Holdout, Protokoll
3.2) verlangt die Holdout-Freigabe, auch für externe Daten. Nicht nutzbare
Einträge gehen in die Datensatz-Identität ein, ebenso Zustand, bis T sichtbare
Befunde, ein Archivende vor der Replay-Zeit und Perioden ohne Erstdruck; bei
unbrauchbarer Payload (`NOT_READY`, `INSUFFICIENT_DATA`) sind es Zustand, Befunde
und Payload-Hashes. Ausgabe: `dataset_id`, `content_hash` (Inhalt),
`output_hash` (inkl. Provenienz), Versionen, Konfiguration, sichtbare
Datensatz-IDs, BTC-Hash und -Vollständigkeit. Eine spätere Revision ändert den
`content_hash` eines früheren Replays nicht (getestet).

## 9. Abruf

`alfred.fetch_bundle(CPI_US, api_key=..., fetcher=..., clock=...)` braucht einen
kostenlosen FRED-API-Key. Der Key steht nur in der URL, nie im Bundle, im
Manifest oder in der Provenienz; `RawPayloadStore.put` verweigert Anfragen mit
Zugangsdaten. Rohdaten liegen unter `data/research_lab/external/` (von Git
ignoriert), je Bundle ein Manifest-Eintrag `bundles/<id>.json`; alle Dateien
werden atomar geschrieben (temporäre Datei, dann Umbenennen), sodass parallele
oder abgebrochene Speichervorgänge frühere Bundles nicht beschädigen. Paging wird nicht unterstützt: eine unvollständige Antwort ist
`NOT_READY`.

## 10. Bekannte Grenzen

- Die Uhrzeit 08:30 New York ist eine Regel für BLS-CPI-Termine, kein Feld der
  Quelle. Stimmt ein ALFRED-Vintage-Datum nicht mit dem BLS-Termin überein, fällt
  es auf `END_OF_VINTAGE_DAY` zurück; einen Tag zu spätes ALFRED-Datum würde als
  späterer Zeitpunkt übernommen (konservativ, aber falsche Ereigniszeit).
- Die Genauigkeit historischer Release-Termine in FRED ist nicht gegen den
  BLS-Archivkalender geprüft. Geprüft werden Vollständigkeit der Antwort
  (`count`), ein Termin vor dem Periodenende und dass dieser höchstens ein
  Release-Intervall (45 Tage) vor dem Erstdruck liegt; ein fehlender Monatstermin
  fällt damit auf. Falsch datierte (statt fehlende) Termine werden nicht erkannt.
  Echte Lücken über 45 Tage (z. B. Shutdown 2025) machen den Erstdruck
  konservativ unbekannt.
- Die Holdout-Sperre für externe Daten sitzt in `run_replay`. Direkte Abfragen an
  `PointInTimeStore` sind nicht gesperrt; Forschungsläufe gehen über `run_replay`.
- Nur Monatsreihen; nur eine Quelle.
- Kein Live-Abruf in Tests; der echte Abruf ist nicht Teil der CI.
