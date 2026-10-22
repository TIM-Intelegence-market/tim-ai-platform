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
| NEGATIVE | Jede gültige Rasterzelle ohne Beobachtung dieses Typs in den 60 Minuten davor und in der Startminute |
| NEUTRAL_CONTROL | Jede gültige Rasterzelle, Auslösung egal |

Das Negativfenster wird nur mit dem Wissen zum Fensterbeginn bestimmt. „Kein Signal im ganzen
Fenster“ hätte ruhige Fenster bevorzugt und damit den Ausgang vorweggenommen. Abgeglichen wird
nicht 1:1, sondern in der Auswertung über Schichten (UTC-Stunde, Wochentagsart, Regime).
Fenster derselben Klasse überlappen sich nie; zwischen den Klassen ist Überlappung erlaubt.
Ein Signaltyp, der fast immer im Rückblick feuert, hat keine Negativfenster und gilt als
**nicht prüfbar**. Das ist selbst ein Befund (das Signal trennt nichts). `kind_testability`
misst diesen Anteil vor T0.

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
  Typs, Kontrollen liegen auf dem Raster, Negativfenster haben kein Signal im Rückblick,
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

1. `kind_testability` pro Signaltyp auf Daten vor dem Kampagnenstart (lesend, Backup-Kopie).
2. Power-Simulation S2.
3. Deine Freigabe der Spezifikation.

## Prüfbefehl

```
python -m pytest tests/test_sk_control_regime_study.py -q
```
