# S44: Dem Ausbruch aus einer verteidigten Range folgen (Präregistrierung, Entwurf 0.1)

| Feld | Wert |
|---|---|
| Studie | S44, Folgestudie zu S32-R (nächste freie Nummer nach S43, 25.11.2026; im Konzept vom 23.11. noch S42) |
| Version | **0.1, Entwurf.** Regeln als Code: `src/research_lab/studies/s44.py` (Config-SHA-256 in jeder Ergebnisdatei), Tests `tests/test_research_lab_s44.py`. `evaluate` gesperrt bis 1.x |
| Anlass | S32-R 1.0 (23.11.2026): Schmale verteidigte Ranges brechen fast immer binnen 60 Min aus, oben und unten etwa gleich oft; ein Ausbruch steht 60 Min später in etwa 55–60 % der Fälle noch. Barti 23.11.: Folgestudien „1, 2 und 3 machen“; 24.11.: Daten „beides“ (erst Stufe A, dann Stufe B) |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kosten aus `src/research_lab/protocol.py` (Taker) |
| Einordnung | Beobachtungsstudie mit gedachten Trades, ohne Registerplatz. Auch bei Bestehen kein Filter für S7b oder Engine |

## Warum andere Daten

Die Idee stammt aus den 55 Tardis-Tagen von S32-R. Dort darf sie nicht bestätigt werden. Deshalb zwei Stufen:

- **Stufe A (diese Präregistrierung):** Binance USDⓈ-M BTCUSDT, 1-Minuten-Kerzen (data.binance.vision, Prüfsummen wie
  im übrigen Labor), **alle Tage 2020-06-01 bis 2024-12-31 außer den 55 Tardis-Tagen** (1 620 Tage). Training bis
  2022-12-31, Validierung 2023–2024, Holdout ab 2025 gesperrt. Ohne Orderbuch.
- **Stufe B:** dieselbe Frage mit Orderbuch auf frischen Recorder-Daten (#253). Eigene Präregistrierung, eingefroren,
  bevor ein Recorder-Tag angesehen wird. Ausgewertet erst nach 30–60 Recorder-Tagen.

## 1. Regeln Stufe A

Je UTC-Tag, auf den Schlusskursen der 1-Minuten-Kerzen (der Schlusskurs ersetzt den Mittelkurs von S32):

| Regel | Wert |
|---|---|
| Range | 15-Minuten-Fenster, beide Ränder verteidigt wie S32 1.0 (`s32.defended`: Berührung im Abstand von 10 % der Breite, wieder verlassen um 25 %, mindestens 3 Berührungen), mindestens 14 von 15 Kerzen vorhanden |
| Breiten | 10–20, 20–60, 60–100, 100–150 bp, jede über den ganzen Tag und je Sitzung (Asien 0 Uhr, London 7 Uhr, New York 13:30, spät 20 Uhr UTC), 20 Gruppen |
| Zählung | eine Range in der Minute, in der sie erstmals als verteidigt gilt, danach in dieser Gruppe 60 Min nicht wieder (wie S32-R) |
| Ausbruch | binnen 60 Min die erste Kerze, deren Hoch ¼ der Breite über dem oberen Rand oder deren Tief ¼ der Breite unter dem unteren Rand liegt (S32-R). Erreicht eine Kerze beides: „unklar“, kein Trade (gezählt) |
| Einstieg | Market (Taker) zum Eröffnungskurs der nächsten Kerze, in Ausbruchsrichtung |
| Stop | Range-Mitte |
| Ziel | 1×, 2× und 3× die Breite ab Einstieg, jedes eine eigene Frage |
| Zeitausstieg | Schlusskurs 60 Kerzen nach dem Einstieg |
| Reihenfolge | in einer Kerze zuerst der Stop (vorsichtig, weil die Reihenfolge in der Kerze unbekannt ist) |
| Kein Platz | liegt der Einstieg schon jenseits des Stops: „no_room“, kein Trade |
| Kosten | Protokoll 1.3 Taker: 13 bp, mit Stop 18 bp; Stress doppelt |

Tagesgrenzen: Jeder Tag steht für sich. Fälle, deren Suche oder Haltedauer über das Tagesende reicht, fallen weg
(„missing“), für alle Gruppen gleich.

## 2. Hypothese und Test

Je Gruppe und Ziel eine Frage: **Ist das mittlere Netto-R größer als 0?** Untere Grenze per Block-Bootstrap über Tage
(9 999 Ziehungen, einseitig, α = 0,05 je Gruppe). Bestanden heißt: untere Grenze über 0 in Training **und**
Validierung. Unter 30 Trades in einem Abschnitt wird die Gruppe gezeigt, bekommt aber kein Urteil. Alle Gruppen
werden immer berichtet, dazu Anteile von Ziel, Stop und Zeitausstieg und das Netto-R unter Stresskosten.

Mehrfachtests: 3 Ziele × 20 Gruppen = 60 Felder. Wie bei S42/S43 hat jede Gruppe ihr eigenes α (Barti 16.11.), und
der Bericht nennt die Gesamtzahl der Felder aus S32, S42, S43 und S44 und für jedes bestandene Feld den Deflated
Sharpe mit dieser Zahl. Ein bestandenes Feld wird nur in Stufe B an neuen Daten bestätigt.

## 3. Ablauf

1. Barti und Uzi lesen den Entwurf. Änderungen nur jetzt.
2. `pytest tests/test_research_lab_s44.py` grün.
3. Zähllauf (ergebnisblind: Ranges, Ausbrüche, „unklar“ je Gruppe, ohne Ausgänge und ohne Netto-R):
   `python -m src.research_lab.studies.s44 count --root data/research_lab --out DIR --fetch`.
4. Einfrieren als 1.0 nur mit Uzis Wort **und** Bartis Go.
5. Genau ein Auswertungslauf (`evaluate`). Kein Nachbessern.

## 4. Stufe B (Skizze, wird eigene Präregistrierung)

Dieselben Regeln auf Sekunden mit Mittelkurs und Orderbuch aus dem Recorder, dazu ein Trendtest wie H1 in S32:
Steigt der Anteil „Ziel zuerst“, je dünner das Buch in Ausbruchsrichtung ist (log-Verhältnis Buch ±5 bp, Minimum der
letzten 3 s vor dem Einstieg)? Frühestens nach dem Recorder-Probelauf (#253) einfrieren.

## 5. Nicht Teil von S44

Andere Breiten, Stops, Ziele oder Haltedauern als oben, Spot, andere Börsen, die 55 Tardis-Tage, der Holdout,
Echtgeld, Live-Orders.
