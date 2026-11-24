# T15: Datenbericht (vor dem Handelslauf)

Dieser Bericht fasst `ergebnisse/t15_datenaudit.json` zusammen (Abschnitt 4 des Zusatzprotokolls 1.1-T15). Er wurde festgehalten (Commit), **bevor** der Handelslauf gestartet wurde. Es wurde bis hierher keine Handelssimulation auf diesen Daten gerechnet; aus der Signallogik wurde nur gezählt, wie viele Kerzen 200 lückenlose Vorlaufkerzen haben.

## 1. Ablauf und Reihenfolge

| Schritt | Zeitpunkt (UTC, Container) | Beleg |
|---|---|---|
| Zusatzprotokoll 1.1-T15 eingefroren und gepusht | 2026-11-16 14:10:49 | Commit `ceed9f9`, SHA-256 der Datei `8f57c81e4907a52847a53cb15fdd62e1302ede39eb7f11167070e5c8eea134f2` |
| Daten von `data.binance.vision` geladen (auf dem Mac) und in den Container übertragen | 2026-11-16 14:13:18 (Dateizeit im Container) | `manifest_t15.json`: 58 Dateien, SHA-256 je Datei gegen die `.CHECKSUM`-Datei von Binance geprüft |
| Code für Datenbericht und Handelslauf festgehalten | danach | Commit `b0e8575` (`t15_ausserhalb.py`) |
| Datenbericht erzeugt | danach | `ergebnisse/t15_datenaudit.json` (SHA-256 `afefae25ba6530fbd53b3bd3b74a7446035e8c113ac995ece9317b4ca3c53b6d`) |

## 2. Befunde (für beide Symbole gleich, wo nicht anders vermerkt)

| Prüfung | BTCUSDT | ETHUSDT |
|---|---|---|
| Monatsdateien (erwartet 29: 2017-08 bis 2019-12) | 29 | 29 |
| Prüfsumme (SHA-256) gegen Manifest und `.CHECKSUM`-Datei | 29 von 29 stimmen | 29 von 29 stimmen |
| CSV je Archiv, Spalten, Kopfzeile, Zeilen außerhalb des Monats | 1 CSV, 12 Spalten, keine Kopfzeile, 0 | wie BTC |
| Erste / letzte Kerze | 2017-08-17 04:00Z / 2019-12-31 20:00Z | wie BTC |
| Kerzen vorhanden | 5 185 | 5 185 |
| Erwartet im 4h-Raster (erste Kerze bis 2019-12-31 20:00Z) | 5 201 | 5 201 |
| Fehlend | 16 (0,31 %) | 16 (0,31 %) |
| Fehlend, bezogen auf das Raster ab 2017-08-01 (nur zur Information) | 113 (2,13 %) | 113 (2,13 %) |
| Abbruchschwelle | 5 % → **nicht ausgelöst** | **nicht ausgelöst** |
| Lücken | 8, längste 7 Kerzen (2018-02-08 00:00Z bis 2018-02-09 08:00Z) | gleiche Lücken zu denselben Zeiten |
| Duplikate, unsortierte Zeilen, Zeitstempel außerhalb des 4h-Rasters | 0, 0, 0 | 0, 0, 0 |
| Ungültige Kerzen (Hoch unter Tief, nichtpositive Preise, Eröffnung oder Schluss außerhalb Hoch/Tief, NaN, negatives Volumen) | 0 | 0 |
| Kerzen ohne Volumen, flache Kerzen (Hoch gleich Tief) | 0, 0 | 0, 0 |
| Schlusskurs kleinster / größter | 2 919,0 / 19 709,5 | 82,17 / 1 388,02 |
| Größte Schlusskursänderung von einer 4h-Kerze zur nächsten (logarithmisch) | 27,2 % am 2017-09-15 12:00Z | 27,5 % in derselben Kerze |
| Kerzen mit 200 lückenlosen Vorlaufkerzen (Voraussetzung für ein Signal) | **3 623 von 5 185 (69,9 %)**, erste am 2017-10-10 00:00Z | gleich |

Beide Symbole haben exakt dieselben Zeitstempel (5 185 gemeinsame, keine nur bei einem Symbol); die Lücken betreffen also beide gleichzeitig (ANNAHME zur Ursache: Wartung oder Ausfall der Börse, nicht geprüft). Die größte Kursänderung fällt bei beiden Symbolen auf dieselbe Kerze und ist deshalb vermutlich eine echte Marktbewegung (Einbruch Mitte September 2017) und kein Fehler eines einzelnen Symbols; eine zweite, unabhängige Kursquelle wurde nicht herangezogen.

**Ergebnis nach Abbruchregel: keine Abbruchbedingung erfüllt, T15 wird ausgewertet.**

## 3. Folge für die erwartete Trade-Zahl und die Aussagekraft (vor dem Lauf festgehalten)

Die Engine (unverändert aus T1 bis T13, Protokoll 1.0) gibt ein Signal nur, wenn die letzten 200 Kerzen lückenlos im 4h-Raster liegen. In den Futures-Daten 2020 bis 2024 gab es keine Lücken; in den Spot-Daten 2017 bis 2019 setzen die acht Lücken den Vorlauf mehrfach zurück. Dadurch können nur 3 623 von 5 185 Kerzen (69,9 %) ein Signal auslösen. Das entspricht etwa 19,8 Monaten (3 623 × 4 h) statt der 27 Monate, mit denen Abschnitt 7 des Zusatzprotokolls gerechnet hat.

| | Zusatzprotokoll Abschnitt 7 | angepasst an den Datenbericht |
|---|---|---|
| Zeitraum mit Signalmöglichkeit | etwa 27 Monate | etwa 19,8 Monate |
| Erwartete Trades (7,2 je Monat wie C3 in 2020 bis 2024, T7) | etwa 195 | etwa 143 |
| Power des einseitigen Tests (5 %) bei wahrer Erwartung +0,24 R, Streuung 1,73 R | etwa 62 % | etwa 51 % |
| Kleinste bei 80 % Power nachweisbare Erwartung | etwa +0,31 R | etwa +0,36 R |

Die Regel wird **nicht** geändert (zum Beispiel keine Toleranz für Lücken): Das Zusatzprotokoll schreibt denselben Code ohne Parameteränderung vor. Die geringere Aussagekraft ist eine Einschränkung des Tests und wird mit dem Ergebnis berichtet; ein negatives oder unklares Ergebnis schließt einen kleineren Vorteil nicht aus. Die Schätzung der Trade-Zahl nimmt dieselbe Trade-Häufigkeit je signalfähigem Zeitraum wie 2020 bis 2024 an (ANNAHME; das Handelsgeschehen 2017 bis 2019 kann davon abweichen).

## 4. Festgehaltene Daten

`ergebnisse/t15_datenaudit.json` enthält je Datei Pfad, URL, Größe und SHA-256 (berechnet, laut Manifest, laut `.CHECKSUM`-Datei). Der Handelslauf berechnet die SHA-256 der Dateien erneut und verweigert den Start, wenn eine Datei vom Datenbericht abweicht. Rohdaten liegen nicht im Repository; Beschaffung siehe `README.md` (Reproduktion).
