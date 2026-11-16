# Konsolidierung der TIM-Studien: Reproduktion und Prüfspur

Diese Datei erklärt, wie die Ergebnisse der konsolidierten Studie aus ihren Eingaben neu erzeugt werden, in welcher Reihenfolge sie entstanden sind und was Dritte **nicht** nachrechnen können. Die Studie selbst steht in [`KONSOLIDIERTE_STUDIE.md`](KONSOLIDIERTE_STUDIE.md). Ihr Abschlussurteil lautet **INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND** (Stufe 2 von 4). Nichts hier erlaubt Echtgeld: `TRADING_AUTHORIZED=NO` bleibt unverändert, der Holdout (ab 2025-01-01) wurde nie geladen, an der Produktion wurde nichts geändert.

Alle Uhrzeiten in dieser Datei sind UTC (Commit-Zeiten im Container). Alle Befehle werden aus dem Wurzelordner des Repos gestartet. Commit-IDs: Die Studie, das Register, die Testlogs und die Ergebnisdateien nennen die IDs von vor dem Sign-off-Umschreiben der Historie; die Zuordnung zu den heutigen IDs steht in Abschnitt 2.1.

## 1 Inhalt des Ordners

| Pfad | Inhalt |
|---|---|
| `KONSOLIDIERTE_STUDIE.md` | die Studie, zwölf Abschnitte nach dem Auftrag plus Abschlussurteil (erzeugt von `studie.py` aus den Ergebnisdateien) |
| `STUDIENREGISTER.md`, `studienregister.json` | 74 Einträge: 69 gefundene Studien und Berichte, 5 eigene Nachrechnungen; je Eintrag Prüftiefe, Qualitätsklasse, Kennzeichnung jeder Aussage (VERIFIZIERT / NUR BERICHTET / ANNAHME / NICHT PRÜFBAR) |
| `EVIDENZMATRIX.md`, `evidenzmatrix.json` | 18 Zeilen (E1 bis E17 und E1b); jede der 69 gefundenen Studien ist genau einmal zugeordnet |
| `PROTOKOLL_KONSOLIDIERUNG.md` | Prüfprotokoll 1.0, eingefroren vor der Bewertung neuer Kandidaten |
| `PROTOKOLL_KONSOLIDIERUNG_T15.md` | Zusatzprotokoll 1.1-T15 (Test außerhalb des Entwicklungszeitraums), eingefroren vor dem Laden der Daten |
| `TESTLOG.md`, `TESTLOG_T15.md` | Testlogs der Läufe T1 bis T13 und T15 (je Test: Zeitraum, Konfiguration, Ergebnisdatei, Grenzen) |
| `T15_DATENBERICHT.md` | Datenbericht zu T15, festgehalten vor dem Handelslauf |
| `ergebnisse/` | je Test eine JSON-Datei mit `meta` (Befehl, Code-Commit, Seed, Zeitraum, Grenzen) und `ergebnis`; `kriterien.json` (mechanische Auswertung der Kriterien); `nachtrag_gegenpruefung.json` |
| `grafiken/` | acht Bilder, aus den Ergebnisdateien gezeichnet |
| `eingaben/` | Manifeste der Binance-Archive, Prüfsummenlisten, Kopien der Laborlisten S7/S7b, Bitunix-Rohdateien (Abschnitt 4) |
| `src/research_lab/konsolidierung/` (vom Repo-Wurzelordner aus) | Code der Konsolidierung; die ursprünglichen Studien und ihr Code bleiben unverändert |
| `tests/test_konsolidierung_*.py` (vom Repo-Wurzelordner aus) | 118 Tests (Abschnitt 6) |

## 2 Festgehaltener Stand und Reihenfolge

Die Protokolle wurden eingefroren, bevor die Ergebnisse vorlagen, die sie bewerten. Das lässt sich nachprüfen (die IDs in diesem Abschnitt sind die heutigen, siehe Abschnitt 2.1):

```bash
git show e8cc946:docs/research_lab/konsolidierung/PROTOKOLL_KONSOLIDIERUNG.md | sha256sum      # e82a31f060c20651d9502f390b8fa317c03e0687b9baf234ee912262f6d759a2
git show 941ec31:docs/research_lab/konsolidierung/PROTOKOLL_KONSOLIDIERUNG_T15.md | sha256sum  # 8f57c81e4907a52847a53cb15fdd62e1302ede39eb7f11167070e5c8eea134f2
git diff e8cc946 HEAD -- docs/research_lab/konsolidierung/PROTOKOLL_KONSOLIDIERUNG.md          # leer: Protokoll 1.0 ist seit dem Einfrieren unverändert
```

| Schritt | Commit | Zeit (UTC) | Bedeutung |
|---|---|---|---|
| Datenaudit, unabhängige Nachrechnung S7/S7b, Bitunix-Abgleich | `78c2510` | 13:12:54 | vor dem Einfrieren gerechnet, deshalb in der Studie als „berichtet“, nicht als vorab festgelegt ausgewiesen |
| Prüfprotokoll 1.0 eingefroren | `e8cc946` | 13:16:21 | Kriterien G1 bis G11 und Urteilsstufen stehen fest |
| Code der Tests T1 bis T13 | `5ecf4a9`, `bc307b6` | 13:31:30 / 13:32:50 | vor den Läufen festgehalten |
| Ergebnisse T1 bis T13, Kriterienauswertung | `2ac5077` | 13:34:47 | `code_commit` `f1c3940` (alte ID, jetzt `bc307b6`), `code_unsauber: false` |
| Kennzahlenbasis der Handelslisten-Studien, Abgleich der Logbuchzahlen | `9dca282`, `86cfb8d` | 13:39:02 / 13:43:52 | Konsistenzprüfung, keine neue Simulation |
| Studienregister, Evidenzmatrix, Grafiken | `045afe1`, `2ec5876`, `eb3c0d1` | 13:55:59 / 14:02:53 / 14:07:59 | |
| Zusatzprotokoll T15 eingefroren | `941ec31` | 14:10:49 | vor dem Laden der Daten (Dateizeit im Container 14:13:18) |
| T15-Code | `7f9d273` | 14:21:49 | vor Datenbericht und Lauf |
| T15-Datenbericht | `822e7eb` | 14:22:59 | vor dem Handelslauf; keine Abbruchbedingung erfüllt |
| T15-Ergebnis (ein Lauf) | `6e88d21` | 14:23:47 | `code_commit` `3fb2198` (alte ID, jetzt `822e7eb`), `code_unsauber: false` |
| T15 in Register, Matrix und Grafik; Studie; Tests | `25af6d2`, `694552e`, `7a64ac4` | 14:27:09 / 14:41:14 / 14:54:44 | |
| Eingabe-Manifeste, Download-Hilfe, Code des Nachtrags | `d153a4d` | 15:09:30 | |
| Nachtrag der Gegenprüfung (Diagnose, ändert keine Stufe) | `1f1359f` | 15:09:37 | nach dem Einfrieren gerechnet, in der Studie als Nachtrag ausgewiesen |
| Korrekturen nach der unabhängigen Gegenprüfung | `62141d6` | 15:25:55 | Studie, Register, Matrix, Tests; Liste in Abschnitt 4 der Studie |

### 2.1 Zuordnung der Commit-IDs vor und nach dem Sign-off

Der Check „DCO sign-off“ verlangt in jedem Commit ein `Signed-off-by`, das zum Autor passt. Deshalb wurde die Historie dieses Branches am 16.11.2026, nach den Läufen und nach der Gegenprüfung, mit `git rebase --signoff --committer-date-is-author-date` auf `platform-main` (Stand `eb3a6cf`) neu geschrieben. Der Inhalt blieb gleich: an der Spitze (Nr. 24) derselbe Dateibaum (`12ded309bc62…`), je Commit dieselbe `patch-id`, dieselbe Betreffzeile und dieselbe Autor-Zeit. Neu sind die Commit-IDs und die Zeile `Signed-off-by` in jeder Commit-Nachricht. Der Merge-Commit `173dcfa` (Einmischen von `platform-main` am Stand `eb3a6cf`) entfällt, weil die Commits jetzt direkt auf `eb3a6cf` aufbauen.

Die Studie, das Register, die Testlogs und die Ergebnisdateien (`meta.code_commit`, `PROTOKOLL_STAND.json`) sind festgehaltene Läufe und nennen weiter die **alten** IDs. Die Tabelle ordnet sie zu. Die Unveränderlichkeit der Protokolle belegen die SHA-256-Summen ihrer Dateien (Befehle oben), nicht die Commit-IDs. Eine Abweichung bei den Zeiten: Beim Commit Nr. 22 lag die Committer-Zeit ursprünglich 43 Sekunden nach der Autor-Zeit (15:34:49 gegen 15:34:06 UTC); sie ist jetzt gleich der Autor-Zeit. Alle anderen Zeiten sind unverändert.

| Nr. | Zeit (UTC) | alte ID | neue ID | Betreff |
|---|---|---|---|---|
| 1 | 13:12:54 | `08c67f6` | `78c2510` | Konsolidierung: Datenaudit, unabhängige S7/S7b-Nachrechnung, Bitunix-Abgleich (Zwischenstand) |
| 2 | 13:16:21 | `1e9270a` | `e8cc946` | Konsolidierung: Prüfprotokoll 1.0 eingefroren (vor Bewertung neuer Kandidaten) |
| 3 | 13:16:21 | `de878d8` | `c1bea5d` | Konsolidierung: Protokollstand (Commit-Hash und SHA-256 des eingefrorenen Protokolls) |
| 4 | 13:31:30 | `f586d5c` | `5ecf4a9` | Konsolidierung: Kennzahlenbasis, Trendtests T1-T9, Carry, Referenzen, Kombination, … |
| 5 | 13:32:50 | `f1c3940` | `bc307b6` | Konsolidierung: Gesamtlauf T1-T13 mit Kriterienauswertung und Testlog (Code, vor den … |
| 6 | 13:34:47 | `9d40bdd` | `2ac5077` | Konsolidierung: Ergebnisse T1-T13 (Lauf nach eingefrorenem Protokoll), Kriterienauswertung, … |
| 7 | 13:39:02 | `277f723` | `9dca282` | Konsolidierung: einheitliche Kennzahlen der Handelslisten-Studien (S34-S38, OF2), Abgleich mit … |
| 8 | 13:43:52 | `d1ea465` | `86cfb8d` | Konsolidierung: Abgleich der Logbuch-Zahlen mit den Ergebnisdateien (159 von 168 Zahlen … |
| 9 | 13:55:59 | `0d10a07` | `045afe1` | Konsolidierung: Studienregister (73 Einträge: 69 gefundene Studien und Berichte, 4 eigene … |
| 10 | 14:02:53 | `d7e91fd` | `2ec5876` | Konsolidierung: Evidenzmatrix (17 Erkenntnisse, alle 69 gefundenen Studien zugeordnet, Zahlen … |
| 11 | 14:07:59 | `bcc6c2c` | `eb3c0d1` | Konsolidierung: Grafiken (Netto-Verlauf, Drawdowns, Kostensensitivität, zeitliche Stabilität, … |
| 12 | 14:10:49 | `ceed9f9` | `941ec31` | Konsolidierung: Zusatzprotokoll T15 (Test außerhalb der Entwicklung, BTC/ETH Spot 2017-08 bis … |
| 13 | 14:21:49 | `b0e8575` | `7f9d273` | Konsolidierung: T15-Code (Datenbericht und einmaliger Handelslauf), festgehalten vor dem … |
| 14 | 14:22:59 | `3fb2198` | `822e7eb` | Konsolidierung: T15-Datenbericht (keine Abbruchbedingung, 5 185 Kerzen je Symbol, 8 Lücken), … |
| 15 | 14:23:47 | `f1cdd73` | `6e88d21` | Konsolidierung: Ergebnis T15 (BTC/ETH Spot 2017-2019, ein Lauf): nicht bestätigt, Richtung … |
| 16 | 14:27:09 | `5b8c425` | `25af6d2` | Konsolidierung: T15 in Register (74 Einträge), Evidenzmatrix (E1b) und Grafik g8 eingearbeitet |
| 17 | 14:41:14 | `13185c8` | `694552e` | Konsolidierung: konsolidierte Studie (12 Abschnitte, Generator studie.py aus Ergebnisdateien, … |
| 18 | 14:54:44 | `41df1a6` | `7a64ac4` | Konsolidierung: 92 Tests (Kennzahlen, Simulationskern, Datenschranke, T15, Register, … |
| 19 | 15:09:30 | `d5f0066` | `d153a4d` | Konsolidierung: Eingabe-Manifeste und Bitunix-Rohproben ins Repo, Download-Hilfe mit … |
| 20 | 15:09:37 | `61d5715` | `1f1359f` | Konsolidierung: Nachtrag der Gegenprüfung (Diagnose nach dem Einfrieren): Bootstrap über alle … |
| 21 | 15:25:55 | `ba311e3` | `62141d6` | Konsolidierung: Korrekturen nach der unabhängigen Gegenprüfung (Trefferquoten S4/S6, … |
| 22 | 15:34:06 | `0dc8373` | `5211d8f` | Konsolidierung: README mit Reproduktionsanleitung und Prüfspur, Laborlisten und Bitunix-Kerzen … |
| 23 | 15:37:00 | `9666c67` | `dde8ad5` | Konsolidierung: Tests überspringen sich ohne numpy (numpy steht nicht in requirements.txt, wie … |
| 24 | 15:42:11 | `787f98d` | `e6603c5` | Konsolidierung: README präzisiert (Pfadangaben, SOL-Beginn, Vorwärts-Journal) |

Die Reihenfolge der Commits ist unverändert (Nr. 2 und 3 tragen dieselbe Sekunde). Der Commit, der diesen Abschnitt enthält, folgt auf Nr. 24 und hat deshalb selbst keine Zeile.

Weitere Stände: Protokoll-Hash und Commit des Einfrierens stehen in `ergebnisse/PROTOKOLL_STAND.json` (dort mit der alten Commit-ID, Zuordnung in Abschnitt 2.1). Der Datenbericht von T15 hat die SHA-256 `afefae25ba6530fbd53b3bd3b74a7446035e8c113ac995ece9317b4ca3c53b6d` (`ergebnisse/t15_datenaudit.json`), der Datenaudit der Laborarchive `56b44a7f89643eafb7de1b163157a5eaf906203bb3432f625e14dd344a5eb2d2` (`ergebnisse/datenaudit.json`).

**Abdeckung des Registers:** Das Register bildet den Stand von `platform-main` am Commit `3799781` (2026-11-16 12:46 UTC) ab. Danach kamen vier Pull Requests hinzu (#283, #284, #286, #287: Zugriff auf den Twelve-Data-Schlüssel, Orderbuch-Dashboard, OF2-Modell M8 mit Kerzenprofil, Flow-Wechsel und Positionsführung). Sie ändern nur Code und Tests unter `src/dashboard/` und `src/research_lab/of2/` sowie `docs/ORDERBUCH_LIVE.md`; Ergebnisdateien oder Berichte enthalten sie nicht (`git diff --stat 3799781 eb3a6cf`). Sie sind nicht bewertet. „Alle auffindbaren Studien“ gilt nur im durchsuchten Umfang (Studienordner, Logbuch, Berichte, Ergebnisdateien und Zählungen in diesem Stand).

## 3 Umgebung

- Python 3.13.18, numpy 2.5.3. matplotlib 3.11.2 nur für die Grafiken, pytest 9.2.0 nur für die Tests. Keine weiteren Pakete.
- Kein Netzzugriff außer `daten_holen` (Abschnitt 4). Kein GPU, ein Prozess.
- Zufall: `numpy.random.default_rng` mit festem Seed `20261116` (T3: 1.000 Ziehungen; T7 und Nachtrag: 10.000 Ziehungen, davon 2.000 für die Drawdown-Verteilung; die Zahlen stehen je Ergebnisdatei in `meta.konfiguration`).
- Wiederholbarkeit: Ein erneuter Lauf aus den Eingaben dieses Ordners plus den Binance-Dateien (Abschnitt 4) ergab am 2026-11-16 für T1 bis T13 und den Nachtrag einen Teil `ergebnis`, der dem festgehaltenen **exakt** entspricht (gleiche Zahlen bis zur letzten Stelle; Unterschiede nur in `meta`: Zeitpunkt, Commit, Befehl). Datenaudit, Kennzahlenbasis, Logbuchabgleich und alle acht Grafiken sind sogar Byte für Byte gleich, die Orderbuch-Momentaufnahme ebenfalls zahlengleich. T1 bis T13 laufen in rund 80 Sekunden. T15 wurde nicht wiederholt (Abschnitt 5, Hinweise).
- NumPy garantiert für `Generator` keine versionsübergreifend gleichen Zufallsströme. Mit einer anderen NumPy-Version können Zufallsgrößen (Bootstrap-Bänder, p-Werte der Zufallsvergleiche) in den hinteren Stellen abweichen; Handelslisten und Erwartungswerte hängen nicht vom Zufallsstrom ab.

## 4 Eingaben

| Eingabe | Wo | Prüfsumme | Im Repo? |
|---|---|---|---|
| Binance-Archive USD-M Futures und Spot, 2020-01 bis 2024-12 (BTCUSDT und ETHUSDT ab 2020-01; SOLUSDT: Futures ab 2020-09, Spot ab 2020-08) | `eingaben/manifest_binance_archiv_2020_2024.json` (1.093 Einträge, davon 861 benötigt: Kerzen 1h, 4h, 1d, Funding 8h; die 1m- und 15m-Serien braucht die 4h-Konsolidierung nicht) | SHA-256 je Datei im Manifest; Manifest selbst `13740b65231b30b0f09297bc159bf1f3220b4892796a2a7ea7d514d6ce7ccea1` | nein (Download) |
| Binance Spot 4h, BTCUSDT und ETHUSDT, 2017-08 bis 2019-12 (T15) | `eingaben/manifest_t15.json` (58 Dateien) | SHA-256 je Datei im Manifest und laut `.CHECKSUM`-Datei von Binance; Manifest selbst `bd51d844a15efbbc38144cea0f372b664e1cc9be00fe24a875e0567d725dc0c4` | nein (Download) |
| Laborlisten von S7 und S7b (Trainingsläufe des Labors; T1 vergleicht damit 4.879 Trades) | `eingaben/laborlisten/` | `eingaben/SHA256_laborlisten.txt` | ja (2,2 MB, unverändert kopiert; die Originale liegen im Labor) |
| Bitunix: Kerzen 4h (BTC, ETH, SOL), Orderbuch-Schnappschüsse (45 im Abstand von etwa 2 s), Funding-Rate, Handelspaare | `eingaben/bitunix/` | `eingaben/SHA256_bitunix.txt` | ja (2,8 MB Kerzen und 0,3 MB Orderbuch; öffentliche Marktdaten vom 2026-11-16) |
| Ergebnisdateien der Trainingsläufe S34 bis S38 (Handelslisten) und die Bestenlisten der OFX-Suche (`lauf1`, `lauf2`) | PS5-Kopie des Labors (`results/s34`, `s35a`, `s36`, `s37`, `s38`, `ofx`) | in `ergebnisse/studien_kennzahlen.json` (S34 `828cd209…`, S35a `d7d42eff…`, S36 `98a05a77…`, S37 `7a9be035…`, S38 `8fd6605d…`) und `ergebnisse/ofx_bestenlisten_aggregat.json` (`e6e6e864…`, `906cc068…`) | nein (zusammen etwa 60 MB; S35a allein 17,7 MB) |
| Logbuch, Berichte, OF2-Trainingsliste, Studienordner | `docs/research_lab/` im Repo | Git | ja |

**Binance-Archive beschaffen.** Das Manifest bildet je Pfad auf `url` und `sha256` ab. Muster der Adressen: `https://data.binance.vision/data/futures/um/monthly/klines/<SYM>/<iv>/<SYM>-<iv>-YYYY-MM.zip`, `…/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip` und `…/spot/monthly/klines/<SYM>/<iv>/<SYM>-<iv>-YYYY-MM.zip`; zu jeder Datei gibt es eine `.CHECKSUM`-Datei. Die Datei `daten_holen.py` lädt nach dem Manifest, behält nur Dateien mit passender SHA-256, überschreibt nichts und lädt nie Monate ab 2025-01.

```bash
KONS=docs/research_lab/konsolidierung
ARCHIV=/pfad/zum/archiv     # Ziel für Futures und Spot 2020 bis 2024
T15=/pfad/zum/t15           # Ziel für Spot 2017 bis 2019
python3 -m src.research_lab.konsolidierung.daten_holen $KONS/eingaben/manifest_binance_archiv_2020_2024.json $ARCHIV --checksum-datei
cp $KONS/eingaben/manifest_binance_archiv_2020_2024.json $ARCHIV/manifest.json      # der Datenaudit liest manifest.json aus der Archivwurzel
python3 -m src.research_lab.konsolidierung.daten_holen $KONS/eingaben/manifest_t15.json $T15 --checksum-datei
```

Die Ordnerstruktur ist danach `futures_um/klines/<SYM>/<iv>/…`, `futures_um/fundingRate/<SYM>/8h/…` und `spot/klines/<SYM>/<iv>/…`. **Grenze:** `daten_holen` ist nur gegen lokale `file://`-Quellen getestet (der Container erreicht `data.binance.vision` nicht). Die T15-Dateien wurden auf dem Mac von den Adressen des Manifests geladen und gegen die `.CHECKSUM`-Dateien geprüft (`T15_DATENBERICHT.md`); die Laborarchive 2020 bis 2024 stammen aus dem Archiv des Labors (`lab_klines_funding.tar`, SHA-256 `d88cb24d9af35a8b23b616afae98bcbca77b8ff3652e13c45c19b9acb2973b12`, nicht im Repo) und wurden gegen das Manifest geprüft (861 von 861 Dateien stimmen, keine Abweichung). Wer die Dateien frisch von Binance lädt, bekommt sie nur dann als gültig, wenn jede SHA-256 mit dem Manifest übereinstimmt; sonst bricht `daten_holen` mit Rückgabewert 1 ab.

## 5 Befehlsfolge

Die Reihenfolge entspricht der Entstehung. Ohne PS5-Dateien sind die Schritte 1 bis 3, 5, 6, 7 (ohne `--ofx`) und 8 bis 9 ausführbar; Schritt 4 und der Aufruf mit `--ofx` brauchen die PS5-Kopie (`PS5`). Fehlt sie, bleiben die festgehaltenen Dateien `studien_kennzahlen.json`, `logbuch_abgleich.json` und `ofx_bestenlisten_aggregat.json` unverändert Eingabe der späteren Schritte.

```bash
PS5=/pfad/zu/ps5/results                       # nur für Schritt 4 und für grafiken --ofx
LAB=$KONS/eingaben/laborlisten
BITUNIX=$KONS/eingaben/bitunix

# 1  Datenaudit (Lücken, Duplikate, Reihenfolge, OHLC, 4h gegen 1h, Funding, Manifest-Prüfung)
python3 -m src.research_lab.konsolidierung.datenaudit $ARCHIV $KONS/ergebnisse/datenaudit.json

# 2  Orderbuch-Momentaufnahme von Bitunix (Spread, Marktorder-Schlupf je Ordergröße)
python3 -m src.research_lab.konsolidierung.bitunix_tiefe $BITUNIX/bitunix_depth_samples.json > $KONS/ergebnisse/bitunix_tiefe_momentaufnahme.json

# 3  Tests T1 bis T13 mit Kriterienauswertung (schreibt ergebnisse/*.json, kriterien.json und TESTLOG.md eine Ebene über dem Ergebnisordner)
python3 -m src.research_lab.konsolidierung.lauf $ARCHIV $KONS/ergebnisse $LAB/s7b_train_2026-10-26T1305Z_trades.json $LAB/s7_train_2026-10-26T1049Z_trades.json $BITUNIX

# 4  einheitliche Kennzahlen der Handelslisten-Studien (S34 bis S38, OF2) und Abgleich der Logbuchzahlen
python3 -m src.research_lab.konsolidierung.studien_kennzahlen $PS5 . $KONS/ergebnisse/studien_kennzahlen.json
python3 -m src.research_lab.konsolidierung.logbuch_abgleich docs/research_lab/LOGBUCH.json docs/research_lab/reports $PS5 $KONS/ergebnisse/logbuch_abgleich.json

# 5  Zusatzprotokoll T15: erst der Datenbericht, dann (nur wenn kein Abbruch) der einzige Handelslauf
python3 -m src.research_lab.konsolidierung.t15_ausserhalb audit $T15 $KONS/eingaben/manifest_t15.json
python3 -m src.research_lab.konsolidierung.t15_ausserhalb lauf $T15 $ARCHIV

# 6  Nachtrag der Gegenprüfung (braucht ergebnisse/t15_ausserhalb.json im Ergebnisordner)
python3 -m src.research_lab.konsolidierung.nachtrag_gegenpruefung $ARCHIV $KONS/ergebnisse

# 7  Grafiken (zuerst das Aggregat der OFX-Bestenlisten, dann die Bilder)
python3 -m src.research_lab.konsolidierung.grafiken --ofx $PS5/ofx
python3 -m src.research_lab.konsolidierung.grafiken

# 8  Register, Evidenzmatrix und Studie neu erzeugen (reine Textgeneratoren aus den Ergebnisdateien; das Register ist von Hand in register_daten_*.py gepflegt)
python3 -m src.research_lab.konsolidierung.register $KONS
python3 -m src.research_lab.konsolidierung.evidenz $KONS
python3 -m src.research_lab.konsolidierung.studie

# 9  Tests
python3 -m pytest tests/test_konsolidierung_*.py -q
```

Hinweise:

- **Ergebnisse nicht überschreiben, sondern vergleichen.** Wer nachrechnet, gibt den Schritten einen eigenen Ergebnisordner (zum Beispiel `/tmp/repro/ergebnisse`; `TESTLOG.md` landet dann in `/tmp/repro/`) und vergleicht den Teil `ergebnis` der JSON-Dateien mit den festgehaltenen. `lauf.py` überschreibt sonst `TESTLOG.md` in diesem Ordner, deshalb schreibt T15 in `TESTLOG_T15.md`.
- **T15 ist ein einmaliger Lauf.** Das Zusatzprotokoll schreibt genau einen Handelslauf vor; `t15_ausserhalb lauf` verweigert den Start, wenn schon ein Ergebnis vorliegt, wenn Code oder Protokoll nicht festgehalten sind oder wenn die Daten nicht dem Datenbericht entsprechen. Diese Wiederholung wurde bewusst nicht gemacht, um die Regel einzuhalten. Wer sie prüfen will, tut das in einem eigenen Klon des Repos nach Entfernen von `ergebnisse/t15_ausserhalb.json`; die Maschinerie ist zusätzlich an handgerechneten Beispielen getestet (`tests/test_konsolidierung_t15.py`).
- **Reihenfolge der Schritte 5 bis 8 nicht vertauschen.** Der Datenbericht von T15 wird vor dem Handelslauf festgehalten (Commit), sonst verweigert der Lauf den Start. Register, Matrix und Studie lesen die Ergebnisdateien und müssen nach jeder Änderung neu erzeugt werden.
- **Holdout.** `daten.py` und `daten_holen.py` lesen und laden nur Monate vor 2025-01. Ein Test, der den Holdout bräuchte, wird nicht gerechnet.

## 6 Tests

```bash
python3 -m pytest tests/test_konsolidierung_*.py -q      # 118 passed in rund 2 Sekunden
```

| Datei | Tests | Prüft |
|---|---|---|
| `test_konsolidierung_kennzahlen.py` | 16 | Wilson-Intervall, Drawdown, Profit-Faktor, Kennzahlen je Handelsliste, Monatsblock-Bootstrap, Newey-West, Probabilistic und Deflated Sharpe an handgerechneten Beispielen |
| `test_konsolidierung_simulation.py` | 23 | Simulationskern (Signal, Stopp, Ziel, Lücken, Zeitstopp, Short, Kosten, Funding, Positionsgrenze, Abschnittsregel), Datenlader und Holdout-Schranke |
| `test_konsolidierung_t15.py` | 23 | Datenbericht, Abbruchregeln, Vorbedingungen und Handelslauf von T15 auf synthetischen Daten; Hashes der Protokolle und des Datenberichts; Kennzahlen gegen die gespeicherte Handelsliste |
| `test_konsolidierung_daten_holen.py` | 10 | Download-Hilfe (nur `file://`), Prüfsummen, Holdout-Schranke, Format der Manifeste, Prüfsummen der Eingaben im Repo |
| `test_konsolidierung_nachtrag.py` | 7 | Hilfsfunktionen des Nachtrags; Abgleich der festgehaltenen Nachtragsdatei mit den Ergebnissen von T1 bis T13 |
| `test_konsolidierung_register_studie.py` | 39 | Register (Schema, Zählung, Kennzeichnung), Evidenzmatrix (Abdeckung 69 von 69), Studie (zwölf Abschnitte, Zahlen aus den Ergebnisdateien, keine Platzhalter), Korrekturen nach der Gegenprüfung |

Die Tests prüfen Rechenwege und innere Stimmigkeit. Sie beweisen nicht, dass die Beschreibung der Regel richtig ist: T1 zeigt, dass zwei unabhängige Rechenwege mit derselben Regelbeschreibung dieselben 4.879 Trades erzeugen; ein gemeinsamer Fehler in der Beschreibung würde T1 nicht finden.

## 7 Was Dritte nicht nachrechnen können

1. **PS5-Dateien** (Handelslisten S34 bis S38, OFX-Bestenlisten mit 8,1 Mio. Varianten): nicht im Repo, nur über die festgehaltenen Prüfsummen an die Rechnung gebunden. Die Neuberechnung der Studienläufe selbst ist nicht Teil dieser Konsolidierung; sie bräuchte die Laborcodes und die PS5-Daten.
2. **S32 (137 Coins, Übertragung der Regel):** nur berichtet. Rohdaten und Handelsliste liegen nicht vor; die Aussage ist in der Studie mit NUR BERICHTET gekennzeichnet.
3. **S7b-Sonde Juli bis Oktober 2026 (35 Trades, −5,8 R):** versehentlich gesehen, nicht aufbewahrt, nicht reproduzierbar, nur berichtet. **Vorwärts-Journal der Regel D20-T3 (4 geschlossene Papier-Trades):** eine Kopie des Journals (`journal.jsonl`, SHA-256 `852cfb98…`) wurde geprüft (Hash-Kette lückenlos, Zahlen nachgerechnet), liegt aber nicht im Repo.
4. **Register und Evidenzmatrix** sind von Hand geführt (`register_daten_a.py`, `register_daten_b.py`, `register_daten_c.py`, `evidenz.py`). Die Tests prüfen Schema, Zählungen und Verweise, nicht die Richtigkeit der Einordnung. Jede Aussage trägt ihre Kennzeichnung und Quelle; die Prüftiefe (A bis D) sagt, wie weit sie nachgerechnet wurde.
5. **Bitunix:** Kerzen, Orderbuch und Funding-Rate sind Momentaufnahmen vom 2026-11-16 (Orderbuch: 45 Schnappschüsse über rund 90 Sekunden in ruhigem Markt). Eine spätere Abfrage liefert andere Werte; für die Wiederholung gelten die Dateien in `eingaben/bitunix/`. Gebühren, Funding-Einheit und Verhalten bei Stress sind unbestätigt, die Kostenstufen K1 bis K3 nehmen Annahmen. Unbekannte Gebühren wurden nie als null gerechnet.
6. **Geldmarkt-Vergleichswert** des Carry-Tests (Jahreszinsen 2020 bis 2024) ist eine Annahme und als solche gekennzeichnet.
7. **Zeitlich nach dem Register** liegende Arbeiten im Repo (siehe Abschnitt 2, Abdeckung) sind nicht bewertet.

## 8 Schranken dieses Auftrags

Kein Holdout (ab 2025-01-01), kein Echtgeld, keine Broker-Freigabe, keine Live-Aktivierung, kein Löschen von Produktionsdaten, kein Eingriff in `~/Documents/TIM/tim`, `~/TIM-live` oder `~/TIM-worker`. Das Ergebnis ist ein Forschungsurteil; ein Merge oder ein Einsatz in der Produktion ist damit nicht freigegeben. Der einzige nächste Schritt, der den Holdout nutzen würde, braucht das ausdrückliche Wort von Uzi und Barti und ist in Abschnitt 12 der Studie als Option beschrieben, nicht als Voraussetzung.

## 9 Berichtigungen an festgehaltenen Dokumenten

Festgehaltene Dokumente werden nicht nachträglich geändert. Fehler darin stehen hier; Korrekturen an der Studie selbst stehen in Abschnitt 4 der Studie.

- `T15_DATENBERICHT.md`, Abschnitt 3, Satz „In den Futures-Daten 2020 bis 2024 gab es keine Lücken“: Das gilt für BTCUSDT und ETHUSDT. SOLUSDT hat zwei Lücken in den 4h-Kerzen (nach 2022-02-25 20:00Z: 18 fehlende Kerzen; nach 2022-03-31 20:00Z: 12 fehlende Kerzen; `ergebnisse/datenaudit.json`, ebenso im Abrufprotokoll `eingaben/laborlisten/s7_fetch.log`). T15 und die Regel C3 verwenden SOL nicht; C1 handelt auch SOL, und die Engine setzt dort nach einer Lücke 200 Kerzen Vorlauf voraus (Studie, Abschnitt 3).
