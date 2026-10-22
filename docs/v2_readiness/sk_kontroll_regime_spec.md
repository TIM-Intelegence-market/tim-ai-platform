# Zusatzstudie S-K: Kontrollklassen und Regime

Stand: 22.10.2026. **Vorschlag, noch nicht freigegeben.** Maßgeblich ist die gehashte Datei
`artifacts/v2_completion/sk_control_regime_spec.json`; dieses Dokument erklärt sie.

## Warum

Die laufende Kampagne `V2_PROSPECTIVE_QUALIFICATION_V1` (Start 20.10.2026 20:34 UTC, eingefroren
auf f469ad6) verlangt in ihrer Vorregistrierung Negativ- und Neutralkontrollen sowie Regimeabdeckung.
Umgesetzt ist beides nicht: `validate_independent_units` zählt Klassen, verlangt aber keine
Mindestzahl (eine leere Stichprobe ergibt PASS), und Regimeschwellen sind nirgends festgelegt.
S-K schließt diese Lücke, ohne die Kampagne anzufassen.

## Grundregeln

- Eigene Spezifikation mit eigenem Hash. Die Vorregistrierung der Kampagne bleibt unverändert.
- **T0** ist der Merge der Spezifikation in platform-main. Prospektiv zählen nur Fenster, die
  ab T0 beginnen; T0 und deine Freigabe werden danach in einer eigenen Datei festgehalten, damit
  der Spezifikations-Hash stabil bleibt.
- Ausgewertet wird offline auf einer Kopie des täglichen DB-Backups, nie in `~/TIM-live`.
- Kontrollen werden vollständig aus einem festen Raster gebildet, nicht gezogen oder ausgesucht.

## Befund, der das Design bestimmt

Die Detektoren feuern zusammen etwa zweimal pro Minute (3.825 vollständige Validierungszeilen in
den ersten 27,5 Kampagnenstunden). Ein 30-Minuten-Fenster ganz ohne Auslösung gibt es damit praktisch
nicht. Darum wird **jeder Signaltyp einzeln** geprüft.

Kontrollen werden **nicht gezogen**, sondern vollständig aus einem festen Halbstunden-Raster
(:00 und :30 UTC) gebildet. Jede Rasterzelle wird nur nach ihren eigenen Daten beurteilt. Darum
ändert sich keine Kontrolle, wenn der Zeitraum wächst oder anderswo eine Lücke liegt, und es gibt
nichts auszusuchen.

| Klasse | Definition |
| --- | --- |
| POSITIVE | Nicht überlappende 30-Minuten-Fenster, die bei einer Beobachtung dieses Typs beginnen (gleiche Regel wie die Fallprüfung der Kampagne, auf den Typ beschränkt) |
| NEGATIVE | Jede gültige Rasterzelle ohne Beobachtung dieses Typs in den 5 Minuten davor und in der Startminute |
| NEUTRAL_CONTROL | Jede gültige Rasterzelle, Auslösung egal |

Das Negativfenster wird nur mit dem Wissen zum Fensterbeginn bestimmt. „Kein Signal im ganzen
Fenster“ hätte ruhige Fenster bevorzugt und damit den Ausgang vorweggenommen. Abgeglichen wird
nicht 1:1, sondern in der Auswertung über Schichten (UTC-Stunde, Wochentagsart, Regime).
Fenster derselben Klasse überlappen sich nie; zwischen den Klassen ist Überlappung erlaubt.
Ein Signaltyp, der fast immer im Rückblick feuert, hat keine Negativfenster und gilt als
**nicht prüfbar**. Das ist selbst ein Befund (das Signal trennt nichts). `kind_testability`
misst diesen Anteil vor T0.

## Messung vor T0 (22.10.2026)

Quelle: tägliches Backup `tim_20261022T011503Z.dump`, Tabelle `orderflow_observations`, mit
`pg_restore` direkt gelesen (keine Datenbankverbindung, nichts wiederhergestellt, `~/TIM-live`
unberührt). Zeitraum 01.10.–20.10.2026 20:34 UTC, 954 Rasterzellen. Gelesen wurden nur Zeitpunkte
und Typen der Signale, **keine Ergebnisse** (Kursverläufe).

| Signaltyp | Minuten mit Signal | Negativ-Anteil bei Rückblick 0 / 5 / 15 / 30 / 60 min | erwartet in 34 Tagen (5 min) |
| --- | --- | --- | --- |
| EXTREME_BUY_RATIO_ACTIVITY | 15,8 % | 85,5 / 43,9 / 16,6 / 6,7 / 2,5 % | 716, prüfbar |
| EXTREME_SELL_RATIO_ACTIVITY | 10,6 % | 86,8 / 52,6 / 27,0 / 13,7 / 4,7 % | 858, prüfbar |
| FALLING_CVD_ACTIVITY | 28,3 % | 70,4 / 12,2 / 1,4 / 0 / 0 % | 199, unter Minimum |
| HIGH_TRADE_FREQUENCY | 9,4 % | 90,1 / 52,9 / 22,7 / 6,3 / 1,0 % | 863, prüfbar |
| LARGE_INDIVIDUAL_TRADE_ACTIVITY | 99,0 % | 1,2 / 0 / 0 / 0 / 0 % | 0, **nicht prüfbar** |
| RISING_CVD_ACTIVITY | 31,0 % | 73,1 / 9,6 / 1,2 / 0 / 0 % | 157, unter Minimum |
| STRONG_BUYER_ACTIVITY | 16,3 % | 85,5 / 30,6 / 7,3 / 1,0 / 0,1 % | 499, prüfbar |
| STRONG_SELLER_ACTIVITY | 18,8 % | 79,7 / 23,1 / 4,1 / 0,8 / 0,1 % | 377, prüfbar |

Folgen:

- Mit 60 Minuten Rückblick gäbe es für keinen Typ genug Negativfenster. Der Rückblick für
  Negativfenster ist darum **5 Minuten** (`negative_lookback_minutes`); der Regime-Rückblick
  bleibt 60 Minuten. Gewählt nur nach Signalhäufigkeit, ohne Blick auf Ergebnisse.
- `LARGE_INDIVIDUAL_TRADE_ACTIVITY` feuert in 99 % aller Minuten und trennt damit nichts. Die
  Schwelle gehört nach der Kampagne überprüft, nicht während.
- Die beiden CVD-Typen brauchen etwa 52 bzw. 66 Tage, sonst werden sie als unter Minimum berichtet.
- Die ersten 28,7 Kampagnenstunden zeigen dasselbe Muster.

## Regime

Nur Daten **vor** Fensterbeginn (60 geschlossene 1-Minuten-Kerzen):

| Regime | Messgröße | Stufen |
| --- | --- | --- |
| Volatilität | Wurzel der Summe quadrierter 1-Minuten-Log-Renditen | Terzile LOW/MID/HIGH |
| Liquidität | Handelsvolumen in USDT | Terzile LOW/MID/HIGH |
| Sitzung | UTC-Stunde: 00–08 ASIA, 08–16 EUROPE, 16–24 US | 3 |
| Wochentag | ISO-Wochentag (UTC) | WEEKDAY / WEEKEND |

Terzilgrenzen: einmal auf 01.10.–20.10.2026 20:34 UTC (vor Kampagnenstart) kalibriert, dann eingefroren.

## Abnahme pro Signaltyp (`validate_study`)

- jede Klasse mindestens 300 Fenster (Vorschlag, mit Power-Simulation S2 bestätigen),
- jede Regimestufe mit mindestens 30 Fenstern, in jeder Klasse,
- jede Einheit erfüllt ihre Klassendefinition: Positivfenster beginnen bei einem Signal dieses
  Typs, Kontrollen liegen auf dem Raster, Negativfenster haben kein Signal in den 5 Minuten davor,
- alles in [T0, Studienende), keine doppelten IDs, keine Überlappung innerhalb einer Klasse.

Einheiten ohne vollständigen 60-Minuten-Rückblick werden ausgeschlossen und gezählt
(`with_regimes`), nicht mit leerem Regime behalten.

Eine leere oder rein positive Stichprobe ergibt FAIL, ebenso umetikettierte Positivfenster.
`human_approval` bleibt immer `false`; die Freigabe ist ein eigener menschlicher Schritt.

## Integrität

Jede Funktion prüft den Spezifikations-Hash neu. Die Terzilgrenzen tragen einen eigenen Hash und
den Spezifikations-Hash. Der T0-Eintrag hält zusätzlich den Commit und den SHA-256 von
`src/v2_completion/control_regime_study.py` fest.

## Unabhängige Prüfung (22.10.2026)

Eine erste Fassung mit Zufallsziehung wurde unabhängig geprüft. Bestätigte Fehler und ihre
Behebung: unerfüllbare 1:1-Quote bei dichter Belegung (jetzt Raster), Validator zählte nur
(jetzt Klassendefinition geprüft), Spezifikations-Hash nur beim Laden geprüft (jetzt überall),
Ziehung verschob sich bei längerem Zeitraum (jetzt stabil), eine Rückblicklücke ließ alles
scheitern (jetzt Ausschluss), Startzeit mit Sekunden (jetzt gerundet). Jeder Befund hat einen Test.

## Vor T0 offen

1. Power-Simulation S2.
2. Deine Freigabe der Spezifikation.

Erledigt: Messung der Prüfbarkeit pro Signaltyp (siehe oben).

## Prüfbefehl

```
python -m pytest tests/test_sk_control_regime_study.py -q
```
