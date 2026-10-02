# Research Lab – Externe Daten (BTC Research Engine V1: Data & Events, V1.1: Live-Ingest)

| Feld | Wert |
|---|---|
| Code | `src/research_lab/external/` |
| Tests | `tests/test_research_lab_external.py` (synthetische Fixtures), `tests/test_research_lab_external_v1_1.py` (Live-Schicht mit Fake-Transport, echtes ALFRED-Fixture); beide ohne Netzwerk |
| Echtes Fixture | `tests/fixtures/research_lab/alfred_cpiaucsl_fixture_2019_2020/` (unveränderte API-Antworten, SHA-256 in `provenance.json`) |
| Verifikationsbericht | `docs/research_lab/reports/alfred_cpi_v1_1_verification.md` (+ `.json`) |
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
- Sonst (Korrekturen, fehlender Kalender, auf den Anfragebeginn gekappte Vintages,
  reine Revisionstermine, siehe unten): Ende des Vintage-Tages in New York,
  `END_OF_VINTAGE_DAY`. Das ist konservativ: der Wert wird eher zu spät als zu
  früh sichtbar. Solche Vintages haben keine Ereigniszeit.

**Reine Revisionstermine (V1.1, aus echten Daten):** Der FRED-CPI-Kalender enthält
in den meisten Jahren im Februar zwei Termine wenige Tage auseinander (z. B.
2024-02-09 und 2024-02-13; im Forschungszeitraum 2017 und 2019–2024, nicht 2018,
wo die Revision mit dem Januar-Release zusammenfällt). Am ersten zeigt ALFRED nur Revisionen älterer Perioden (jährliche
Saisonrevision der letzten fünf Jahre), die Januarzahl erscheint erst am zweiten.
Laut BLS werden die revidierten saisonbereinigten Indizes an einem Datum ohne
Uhrzeitangabe bereitgestellt. Ein Kalendertermin gilt als reiner Revisionstermin,
wenn (1) Vintages an ihm beginnen, (2) keine Periode an ihm zum ersten Mal
erscheint (das früheste brauchbare archivierte Vintage einer Periode zählt nur als Erstdruck,
wenn seit Periodenende kein regulärer Termin vergangen ist; Zeilen, die als
unbrauchbar gelten (Vintage vor Periodenende, kein Periodenbeginn, kein gültiger
Wert, widersprüchliche Duplikate) oder nur „kein Wert“ (`.`) melden, sind nie ein
Erstdruck; sonst fehlt der
Erstdruck im Archiv und das Vintage ist eine Revision) und (3) der nächste Kalendertermin höchstens 7 Tage später folgt (der
BLS-Kalender ist vorab veröffentlicht). Solche Termine veröffentlichen keine
Periode und haben keine Release-Zeit (`END_OF_VINTAGE_DAY`). Fehlt Bedingung (3),
bleibt der Termin ein normaler Release, eine fehlende Periode bleibt fehlend.

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
| Metadaten in Real-Time-Versionen (echte Antwort: 6 Versionen, Einheit bis 1988 „Index 1967=100“) | Versionen müssen lückenlos sein und alle archivierten Vintages abdecken, sonst `NOT_READY`. Widerspricht eine Version der Spezifikation (Einheit, Frequenz, Saisonbereinigung, ID), sind die in ihrer Gültigkeit veröffentlichten Vintages ab ihrer Verfügbarkeit `UNKNOWN` (`INCONSISTENT_METADATA`); frühere Vintages und Replays bleiben unberührt. Ältere Versionen ohne Zeilen in der Payload zählen nicht |
| Zeile außerhalb des erklärten Beobachtungsbereichs (`observation_start`/`observation_end`) | Payload `NOT_READY`; Perioden außerhalb des Bereichs gelten nie als `MISSING_PERIOD` (nicht angefragt) |
| JSON ungültig, Payload fehlt, Release-Kalender unvollständig | `NOT_READY` |
| Zeile ohne `realtime_start` oder mit nicht lesbarem Perioden-/Vintage-Datum | ganze Payload `NOT_READY` (Verfügbarkeit oder Periode nicht bestimmbar) |
| Periodendatum lesbar, aber kein Periodenbeginn; Vintage vor Periodenende; `available_at > ingested_at`; ungültiger oder nicht positiver Wert | Periode ab diesem Vintage `UNKNOWN` |
| ungültiges oder widersprüchliches `realtime_end` (auch bei Duplikaten) | Ende gilt als unbekannt; das **nächste** Vintage der Periode wird ab seiner eigenen Verfügbarkeit `UNKNOWN` (das Ende ist erst dann erkennbar) |
| Gültigkeit überlappt mit irgendeinem früheren Vintage (auch einem unbrauchbaren) | späteres Vintage `UNKNOWN` |
| gleiche Periode/Vintage doppelt, gleicher Wert | eine Zeile behalten (unabhängig von der Reihenfolge), Warnung |
| gleiche Periode/Vintage doppelt, anderer Wert | `UNKNOWN` |
| Vintage endet (`realtime_end`), aber kein Vintage beginnt am Folgetag (fehlende Revision, Lücke) | `MISSING_VINTAGE`: Periode `UNKNOWN` ab dem Zeitpunkt, zu dem der fehlende Nachfolger sichtbar geworden wäre; frühere Replays unverändert |
| Periode laut Release-Kalender veröffentlicht, im Archiv zum fälligen Zeitpunkt aber ohne sichtbares Vintage | `MISSING_PERIOD` ab dem fälligen Release-Zeitpunkt; `latest()` `stale`, bis ein Vintage der Periode sichtbar wird (die ältere Periode bleibt als solche ausgewiesen, kein Ersatzwert; spätere Vintages ändern frühere Replays nicht) |
| Vintage außerhalb des erklärten Real-Time-Bereichs der Payload, oder Bereichsbeginn nach Bereichsende | Payload `NOT_READY` (`INCONSISTENT_METADATA`) |
| Release-Kalender mit fremder oder nicht exakt ganzzahliger `release_id` (z. B. `10.9`, `1e309`, `"10"`) | Payload `NOT_READY` (`MALFORMED_PAYLOAD`) |
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

**Grenzen für Erwartungswerte (V1.1)**, geprüft vor jeder Rechnung: nur `Decimal`,
endlich, Betrag höchstens 1e9, höchstens 12 Nachkommastellen, höchstens 20
signifikante Stellen. Begründung: ein CPI-Konsens ist ein Indexniveau (CPIAUCSL
2017–2024 etwa 240–320) oder eine Veränderung in Prozent (eine bis zwei
Nachkommastellen, historisch innerhalb ±25 %); die Grenzen liegen viele
Größenordnungen darüber und entsprechen den Grenzen der Reihenwerte selbst.
Die Überraschung wird in einem Kontext berechnet, der Rundung, Überlauf und
ungültige Operationen als Fehler behandelt: ein nicht exakt darstellbares
Ergebnis wird abgewiesen, nie gerundet. Abgewiesen heißt: `ValueError`, keine
Erwartung angehängt, das Ereignis bleibt unverändert.

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
- `invalid_candles="exclude"`: ausgeschlossene Kerzen zählen in der
  BTC-Vollständigkeit als fehlend, auch am Anfang oder Ende der Reihe (eine
  Kerze neben dem Raster markiert dabei den Rasterplatz, in den sie fällt).
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
`content_hash` eines früheren Replays nicht (getestet). Liegt die Replay-Zeit nach dem
Archivende (`coverage_end`, z. B. ein noch nicht einordenbarer Revisionstermin), enthält
der Replay nur, was bis zum Archivende verfügbar war: keine späteren Records,
Einträge, Ereignisse oder datierten Befunde (Zustand `INSUFFICIENT_DATA`). Dieselbe
Grenze gilt für `PointInTimeStore.visible_records`/`visible_unusable`/`entry_in_vintage`
und `release_events`.

## 9. Abruf

`alfred.fetch_bundle(CPI_US, api_key=..., fetcher=..., clock=...)` braucht einen
kostenlosen FRED-API-Key. Der Key steht nur in der URL, nie im Bundle, im
Manifest oder in der Provenienz; `RawPayloadStore.put` verweigert Anfragen mit
Zugangsdaten. Rohdaten liegen unter `data/research_lab/external/` (von Git
ignoriert), je Bundle ein Manifest-Eintrag `bundles/<id>.json`; alle Dateien
werden atomar geschrieben (temporäre Datei, dann Umbenennen), sodass parallele
oder abgebrochene Speichervorgänge frühere Bundles nicht beschädigen. Paging wird nicht unterstützt: eine unvollständige Antwort ist
`NOT_READY`.

**Live-Ingest (V1.1)**, `src/research_lab/external/live.py`, Bedienung über
`scripts/research_lab_alfred_ingest.py` (`fetch`, `verify`, `fixture`, `replay`):

- **Schlüssel:** `FredSecretResolver` nach dem bestehenden TIM-Modell
  (`config/secrets.py`, wie OpenMarket): genau ein ausdrücklich gewählter Provider
  (`TIM_FRED_SECRET_PROVIDER` = `keychain` | `file` | `env`), kein stiller
  Rückfall, Wert nur in `SecretValue`, Fehlermeldungen beschreiben Formfehler nur
  über Zählwerte, Fehler tragen keine Ausnahmekette (ein Keychain-Timeout kann den
  Wert in `TimeoutExpired.output` halten). `scripts/fred_store_key.py` speichert den
  Key mit verdeckter Eingabe als Datei mit Modus 0600 und verweigert Ziele innerhalb
  eines Git-Arbeitsverzeichnisses.
- **Echo-Schutz:** Enthält eine API-Antwort den Key, roh, als Text (dekodiert wie
  `json.loads`) oder in einem JSON-String (auch per `\uXXXX` maskiert oder in einem
  doppelten, sonst überschriebenen Feld), wird sie vor jeder weiteren
  Prüfung abgewiesen (die Fensterprüfung zitiert Antwortwerte) und nicht gespeichert.
- **Forschungsfenster:** `ResearchWindow` legt Beobachtungs- und Real-Time-Bereich
  fest; `RESEARCH_2017_2024` = Perioden 2016-01 … 2024-12 (ein Jahr Vorlauf),
  Vintages bis 2024-12-31. Ein Fenster, das den Holdout (2025-01-01) erreicht, lässt
  sich nicht bauen (`HoldoutLocked`); Downloads haben keinen Freigabeweg.
- **Antwortprüfung vor dem Speichern** (`check_window`): Envelope muss die Anfrage
  exakt wiedergeben; Vintages, `realtime_end` einer Zeile, Perioden, Kalendertermine
  oder Datumsangaben der Metadaten-Versionen (`realtime_start/end`,
  `observation_end`, `last_updated`) jenseits des Fensters ⇒ `LiveIngestError`,
  nichts wird gespeichert, nichts gekürzt. Eine Antwort mit späteren Daten
  erweitert das Fenster also nie. Ein JSON-Objekt mit doppeltem Feld wird
  abgewiesen (in `parse_bundle`: `MALFORMED_PAYLOAD`), weil `json.loads` sonst
  stillschweigend den letzten Wert behielte.
- **Transport** (`http_fetcher`): nur `https://api.stlouisfed.org/fred/…`,
  Weiterleitungen verweigert, Antwort höchstens 50 MB, 429/5xx/Netzfehler mit
  Backoff `2 s · 2^n` (4 Versuche), 4xx sofort Fehler. Fehler nennen Pfad und
  Status, nie URL oder Key (`FetchError`; Meldungen anderer Fetcher gibt
  `ingest_live` nicht weiter), und werden außerhalb des `except`-Blocks ausgelöst
  (ebenso die JSON-Fehler der Fensterprüfung; der Echo-Schutz prüft auch UTF-16/32):
  weder `__cause__` noch `__context__` hält die ursprüngliche Ausnahme (deren Text
  die URL mit dem Key enthalten kann).
- **Fixture-Echtheit:** `load_fixture` prüft jede Datei gegen ihren SHA-256 und
  berechnet die Bundle-ID des Downloads neu; eine bearbeitete Datei mit
  angepasstem Hash widerspricht der ID.
- **Wiederverwendung:** geparst wird immer ein gespeichertes Bundle
  (`load_research_ingest`), per Bundle-ID ohne Netz, nach erneuter Fensterprüfung.

## 10. Bekannte Grenzen

- Die Uhrzeit 08:30 New York ist eine Regel für BLS-CPI-Termine, kein Feld der
  Quelle: ALFRED/FRED liefern nur Daten ohne Uhrzeit. V1.1 hat die Regel an vier
  archivierten BLS-Meldungen belegt (Sperrfrist „8:30 a.m. (ET)“ am 2017-02-15,
  2020-02-13, 2022-07-13 und 2024-01-11, jeweils gleich dem ALFRED-Erstdruckdatum);
  für alle übrigen Termine bleibt sie eine Annahme. Stimmt ein ALFRED-Vintage-Datum
  nicht mit dem BLS-Termin überein, fällt es auf `END_OF_VINTAGE_DAY` zurück; einen
  Tag zu spätes ALFRED-Datum würde als späterer Zeitpunkt übernommen (konservativ,
  aber falsche Ereigniszeit).
- Die Genauigkeit historischer Release-Termine in FRED ist nur stichprobenartig
  (siehe oben) gegen BLS-Meldungen geprüft. Geprüft werden Vollständigkeit der Antwort
  (`count`), ein Termin vor dem Periodenende und dass dieser höchstens ein
  Release-Intervall (45 Tage) vor dem Erstdruck liegt; ein fehlender Monatstermin
  fällt damit auf. Falsch datierte (statt fehlende) Termine werden nicht erkannt.
  Echte Lücken über 45 Tage (z. B. Shutdown 2025) machen den Erstdruck
  konservativ unbekannt.
- Die Holdout-Sperre für externe Daten sitzt in `run_replay`. Direkte Abfragen an
  `PointInTimeStore` sind nicht gesperrt; Forschungsläufe gehen über `run_replay`.
- Nur Monatsreihen; nur eine Quelle.
- Kein Live-Abruf in Tests; der echte Abruf ist nicht Teil der CI. Die CI prüft
  die echte Semantik am unveränderten Fixture 2019–2020 (Erstdruck, Saisonrevision,
  Januar-Release), nicht am vollständigen Download 2017–2024.
- Die Erkennung reiner Revisionstermine stützt sich auf die Annahme, dass der
  nächste BLS-Termin vorab bekannt ist (BLS veröffentlicht den Kalender im Voraus);
  der FRED-Kalender selbst ist rückblickend.
- Reine Revisionstermine werden an den Revisionszeilen älterer Perioden erkannt.
  Enthält eine Payload nur Perioden ab dem Januar (enger Beobachtungsbereich ohne
  Vorlauf), sieht sie die Revision nicht: der Januar-Erstdruck gilt dann als
  unbekannt (`FIRST_RELEASE_UNAVAILABLE`, fail-closed, kein falscher Wert und keine
  falsche Zeit). Das Forschungsfenster hat deshalb ein Jahr Vorlauf; das Fixture
  enthält die revidierten Perioden.
- `replay_checks` gilt nur als bestanden, wenn der finale Replay `READY` ist und
  BTC-Kerzen sowie Ereignisse enthält.
- Die Grenze von 7 Tagen für reine Revisionstermine ist aus dem echten Kalender
  2005–2024 abgeleitet (wo ein solches Terminpaar vorkommt: 2 bis 6 Tage); ein abweichender künftiger Abstand würde den
  Termin als normalen Release behandeln (fail-closed: Januar dann als fehlend markiert).

## 11. Roadmap

Reihenfolge der BTC Research Engine: **V1 (#128) → V1.1 (#139) → V1.2 → V2**.

- **V1.2** ist der nächste Schritt. Ihr fachlicher und technischer Umfang ist noch
  nicht festgelegt und wird vor Beginn eigens spezifiziert.
- **V2 — Historical Relationship Analysis** (Event Studies, Lead/Lag, rollierende
  Zusammenhänge, mehrere Forschungshorizonte) folgt später. V2 beginnt erst, wenn
  die V1-Datenbasis ausreichend breit, sauber, reproduzierbar und
  Point-in-Time-sicher validiert ist.
