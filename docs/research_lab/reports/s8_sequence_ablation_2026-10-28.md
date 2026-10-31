# S8-Sequenzvergleich: kein praktischer Zusatznutzen im Primärmodell

**Ergebnis: Die vorab festgelegte Verbesserung von mindestens 1 % weniger Log-Loss wurde nicht nachgewiesen.**
Die drei Sequenzmerkmale sind implementiert und technisch geprüft. Im primären CatBoost-Vergleich ist der
Unterschied statistisch nicht von null unterscheidbar. Die logistische Regression verbessert sich leicht,
bestätigt aber ebenfalls keinen Vorteil von mindestens 1 %.

Datum: 28.10.2026. Prüfcode: `2e0d36f051896b223280ce65ae1029220530ac5e`, Ausgangsstand
`6f91fea51aa028e39509a6c816472de7ca4a33dd`. Planversion `s8-sequence-ablation-1.0.0`.
Prüfplan und Merkmale wurden vor Datenabruf festgelegt; Uzi bestätigte die unveränderte 1-%-Schwelle vor
dem ersten Fit. Keine Betrachtung von Modellresultaten vor dieser Bestätigung.

## Gemessene Unterschiede auf identischen Validierungszeilen

Kleinerer Log-Loss ist besser. Verbesserung = `(Loss mit 35 Merkmalen - Loss mit 38 Merkmalen) / Loss mit 35 Merkmalen`.

| Modell | 35 bisherige Merkmale | 38 Merkmale | relative Verbesserung | gepaartes 95%-Intervall |
|---|---:|---:|---:|---|
| **CatBoost, primär** | 0,46721219 | 0,46724086 | **-0,006 %** | -0,075 % bis +0,056 % |
| Logistische Regression, ergänzend | 0,52216981 | 0,51839297 | +0,723 % | +0,470 % bis +1,017 % |

Die obere Intervallgrenze des Primärvergleichs liegt deutlich unter der geforderten praktischen Verbesserung
von 1 %. Für die logistische Regression liegt die Punktschätzung darunter und das Intervall bestätigt die
Mindestgröße ebenfalls nicht. Diese ergänzende Auswertung ändert die vorab festgelegte Primärentscheidung nicht.

Zum Vergleich: Die allein aus den Trainings-Klassenhäufigkeiten gebildete Referenz erreicht auf der Validierung
0,59556028 Log-Loss. Ihre Accuracy beträgt bereits 83,997 %; Accuracy um 84 % ist hier wegen der dominierenden
Neutral-Klasse kein eindrucksvoller Richtungsnachweis. Die Auswertung berichtet deshalb Log-Loss und zusätzlich
Brier-Score, nicht eine angebliche Trading-Trefferquote.

| Modell/Variante | Brier-Score | Accuracy |
|---|---:|---:|
| CatBoost 35 | 0,24612057 | 84,0207 % |
| CatBoost 38 | 0,24608742 | 84,0372 % |
| Logistische Regression 35 | 0,26581362 | 83,8375 % |
| Logistische Regression 38 | 0,26417962 | 83,8536 % |

Beide logistischen Fits konvergierten (106 beziehungsweise 124 Iterationen, maximal 1000). Alle vier
Modellartefakte und die gepaarten Validierungsprognosen wurden im ignorierten Labor-Ausgabepfad gespeichert.

## Daten und Prüfdesign

- 480 nach Kalender und SHA-256 ausgewählte Archivtagesdateien, ein rotierender Acht-Tage-Block je Monat
  von 2020 bis 2024. 881.275.222 aggregierte Binance-Spot-BTCUSDT-Trade-Ereignisse; offizielle Prüfsummen geprüft.
- Training: 288 geladene Tage, 361.772 nutzbare Zeilen an 252 Tagen. Validierung: 192 geladene Tage,
  241.800 nutzbare Zeilen an 168 Tagen. Der erste Tag eines getrennten Blocks liefert unter anderem die
  benötigten Vortagsprofile. Dies ist eine Stichprobe, nicht die vollständige Historie.
- Keine ID-Lücken, keine Zeitrücksprünge, keine exakten Duplikate. 892 Minuten ohne Trade-Ereignisse in den
  Trainingsarchiven, null in den ausgewählten Validierungsarchiven. Fehlende Merkmale und veraltete Start- oder
  Zielpreise werden nach dem bestehenden S8-Vertrag ausgeschlossen, nicht künstlich als neutral klassifiziert.
- Beide Featurevarianten verwenden dieselben vollständigen Zeilen, dieselben Fünf-Minuten-Labels und
  unveränderte zeitliche Grenzen. Kein Validationstuning oder frühes Stoppen.
- CatBoost: 500 Iterationen, Tiefe 4, Lernrate 0,05, Seed 20261028, zwei Threads. Logistische Regression:
  nur am Training geschätzte Standardisierung, C=1, lbfgs, Toleranz 1e-6, maximal 1000 Iterationen.
- 4000 gepaarte Bootstrap-Ziehungen kompletter Monatsblöcke, 24 Validierungscluster, Seed 20261028.
  Die Intervalle beschreiben diese fest trainierten Modelle und diese historische Stichprobe. Sie enthalten
  keine vollständige Unsicherheit über neue Trainingsstichproben oder andere Marktregime und ersetzen keine
  prospektive Power-Planung.

## Implementierung und technische Nachweise

Neue Merkmale: `last_run_norm_1`, `sign_autocorr_1`, `burst_share_1`. Balken- und Merkmalsversion 1.2.0;
die bisherige 35er-Liste bleibt als `BASE_FEATURE_NAMES` erhalten. Alte Balkencaches werden durch die
Versionsprüfung abgewiesen und müssen gesondert neu reduziert werden. Roharchive werden nicht aus der
Runtime-Datenbank bezogen.

- 28 S8-Tests mit den optionalen ML-Abhängigkeiten unter Python 3.13 bestanden. Enthalten sind manuelle
  Gegenbeispiele, vollständige Gleichheit der alten Merkmale, Duplikate, Minutengrenzen, Zukunftsmanipulation,
  Export/Replay, Paarung, Bootstrap und Holdout-Sperren.
- Zusätzlicher realer Kompatibilitätsabgleich: Für alle 1440 Minuten am 16.01.2020 stimmen die bisherigen
  35 Werte exakt mit dem unveränderten ursprünglichen S8-Code überein.
- Gesamtsuite mit Python 3.13 wie in der Projekt-CI: 6416 bestanden, 129 übersprungen; anschließend
  245 serielle Tests bestanden. Die ML-spezifischen numerischen Tests wurden zusätzlich in der eigenen
  Python-3.13-Umgebung mit NumPy, scikit-learn und CatBoost ausgeführt.
- Der erste Gesamtlauf unter Python 3.14 in einem Pfad mit Leerzeichen zeigte fremde Skript-/Umgebungsfehler.
  Im Pfad ohne Leerzeichen verschwanden diese; ein JSON-Protokolltest scheiterte unter Python 3.14 auch
  auf dem unveränderten Ausgangscommit (167 bestanden, 1 fehlgeschlagen). Dieser geschützte Bereich wurde
  nicht geändert. Die CI-gleiche Python-3.13-Prüfung ist grün.

## Reproduzierbare Belege

| Beleg | SHA-256 / Version |
|---|---|
| Eingefrorener Plan | `479393ff9c6b3ad9559cb83b615bdcde4325f872cd13ce0e8c869bde42309cf8` |
| Eingangsdatensatz | `e3688fd205d8382999a03e98f915040f0f7429de23be21c046c14d4621b9175f` |
| Merkmale | `13513a83060765aa7e249b31df9d5f32235c83311ec99f1d23d3cc5ca2cb03c3` |
| Labels | `99eeb6411be074f420b19bfa06027572d8df7d3a3dca5a44ceaa5f1158640aa0` |
| Python / NumPy | 3.13.16 / 2.5.4 |
| scikit-learn / CatBoost | 1.9.1 / 1.2.10 |

Plan: [S8_SEQUENCE_PLAN.json](../studien/S8_SEQUENCE_PLAN.json). Methode und Befehle:
[S8_SEQUENZVERGLEICH.md](../studien/S8_SEQUENZVERGLEICH.md). Originale Ergebnisse, Gewichte und Prognosen
liegen lokal unter `output/s8_sequence/`; die qualitätsgeprüften Balken und Profile unter `data/s8_sequence/`.
Der Ergebniscode verweigert das Überschreiben eines vorhandenen Ergebnisses.

## Einordnung und Abschluss

**IMPLEMENTED und TESTED:** drei Merkmale und der feste Vergleich. **Kein nachgewiesener praktischer
Zusatznutzen im primären historischen Vergleich.** Keine prospektive Bestätigung, kein Nettoertrags- oder
Ausführungsnachweis und keine wissenschaftliche Handelsfreigabe. Es wurde kein bestehendes trainiertes
S8-Modell ersetzt; im Ausgangsstand gab es noch keinen Trainer oder Checkpoint.

**Der gesperrte Holdout ab 2025 wurde weder abgerufen noch gelesen.** Runtime, Kampagnenregister,
Holdout-Register, S2-Preisdateien und produktive Installationsskripte wurden nicht geändert. Keine Orders,
kein automatischer Merge und kein Rollout. Die Merkmale bleiben ein dokumentierter Forschungsbaustein;
aus diesem Versuch folgt keine Empfehlung, sie als verbessertes Prognosemodell freizugeben.
