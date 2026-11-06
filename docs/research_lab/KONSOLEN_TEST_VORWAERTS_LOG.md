# Test: Vorwärts-Log F3/F5 und Barometer auf den Konsolen (PS5/PS4)

Stand 06.11.2026. Zweck: prüfen, ob `src/research_lab/forward/macro_filters.py` auf einer Konsole genauso rechnet
wie auf dem Mac, **bevor** der Mac abgeschaltet wird. Bis zum Umschalten läuft das offizielle Log weiter auf dem Mac
(cron als `chris`, täglich 09:00 `log`, montags 09:30 `barometer`). Die Tests unten schreiben nur in einen
Testordner und berühren das offizielle Log nicht.

## 0. Voraussetzungen

- Python 3.11 oder neuer (`python3 --version`), Checkout dieses Repos auf `platform-main`, alle Befehle aus dem
  Repo-Ordner.
- TLS-Zertifikate für `https://api.stlouisfed.org` (z. B. Paket `certifi`, falls das System keine mitbringt).
- FRED-Schlüssel als Datei, Modus 0600 und dem laufenden Benutzer gehörend:

  ```sh
  export TIM_FRED_SECRET_PROVIDER=file
  export TIM_FRED_SECRET_FILE=/pfad/zur/fred-api-key   # Modus 0600
  ```

  Empfehlung: einen eigenen, kostenlosen FRED-Schlüssel nur für die Konsolen, damit er sich einzeln sperren lässt.
  Der Schlüssel wird nie ausgegeben, nie gespeichert und steht in keiner Rohantwort.

## 1. Unit-Tests (ohne Netz)

```sh
python3 -m pytest tests/test_research_forward_macro_filters.py -q
```

Erwartet: `12 passed`. Schlägt etwas fehl, nicht weitermachen.

## 2. Barometer von Hand (Testordner)

```sh
python3 -m src.research_lab.forward.macro_filters barometer --folder /tmp/test-makro
```

Erwartet: `geschrieben: /tmp/test-makro/barometer/barometer_<Jahr>-<Woche>.md`. Die Tabelle mit der Datei derselben
Woche vom Mac vergleichen (`data/research/forward/S7b-makro/barometer/`). Gleiche Treiber, gleiche Richtung
(„gestiegen“/„gefallen“). Kleine Abweichungen beim letzten Wert sind möglich, wenn FRED zwischen den Abrufen neue
Daten veröffentlicht hat.

## 3. Log von Hand (Testordner)

```sh
python3 -m src.research_lab.forward.macro_filters log --folder /tmp/test-makro
```

Erwartet: eine JSON-Zeile mit `f5_sperre_long` und `f3_sperre_long` (`ja`, `nein` oder `unbekannt`). Beide Werte
mit der Zeile desselben Tages im Mac-Log vergleichen (`data/research/forward/S7b-makro/f35_log.csv`). Ein zweiter
Aufruf am selben UTC-Tag meldet `schon geloggt` und schreibt nichts (gewollt).

## Bestanden, wenn

| Prüfung | Erwartet |
|---|---|
| Exit-Code beider Befehle | 0 |
| Ausgabe | enthält den FRED-Schlüssel nirgends |
| `f5_sperre_long`, `f3_sperre_long` | wie in der Mac-Zeile desselben Tages (Stand 05./06.11.2026: beide `ja`) |
| `f3_wert_mrd` | Größenordnung einige Tausend Mrd. USD (Anfang November 2026 etwa 5.700–5.900). Ein Wert um eine Million heißt: Einheit falsch gelesen, nicht umschalten |
| zweiter `log`-Lauf am selben UTC-Tag | `schon geloggt`, keine neue Zeile |
| Barometer | gleiche Treiber und Richtungen wie die Mac-Datei derselben Woche |

`--folder` darf vor oder nach `log`/`barometer` stehen.

## 4. Zeitplan

Den Zeitplan auf der Konsole so einrichten wie auf dem Mac (täglich `log`, montags `barometer`), zunächst weiter mit
`--folder /tmp/test-makro`, und mindestens einen automatischen Lauf abwarten. Nach einem Neustart prüfen, ob der
Zeitplan noch da ist.

## 5. Umschalten (erst nach bestandenem Test)

1. Barti oder Uzi melden „Test bestanden“.
2. Die bisherigen Daten vom Mac (`data/research/forward/S7b-makro/`) werden nach `/Users/Shared` gelegt und auf
   die Konsole in denselben relativen Ordner kopiert. Ohne diese Daten hätte das Log eine Lücke.
3. Zeitplan der Konsole auf den echten Ordner umstellen (ohne `--folder`).
4. Erst nach dem ersten echten Lauf auf der Konsole werden die cron-Einträge auf dem Mac abgeschaltet.
   Zwei Quellen für dasselbe Log gleichzeitig darf es nicht geben.

Warum die Reihenfolge wichtig ist: Die Auswertung (S7b-Studie, Abschnitt 15) nimmt pro Signal nur einen Filterstand,
der strikt vorher abgerufen wurde und höchstens 48 Stunden alt ist. Eine Lücke von mehr als zwei Tagen macht
Signale zu „ohne Filterstand“.
