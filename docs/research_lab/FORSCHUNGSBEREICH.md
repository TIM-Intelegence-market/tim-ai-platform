# TIM-Forschungsbereich („Forschungswerkstatt“): Satzung

Stand 31.10.2026, Version `forschungsbereich/1.0`, freigegeben von Uzi am 31.10.2026 14:02 Ortszeit („go“ auf den
Bauplan, Vorschläge E1–E7 übernommen). Code: `src/research_lab/workshop/` (Werte in `charter.py`).

## Zweck

TIM forscht dauerhaft und reflektiert darüber: Ideen sammeln, prüfen, als Studie anmelden, rechnen, ehrlich berichten,
daraus lernen. Ein bestandenes Ergebnis wird ein Update-Vorschlag. Es zählt erst nach einem prospektiven Test.

## Feste Grenzen (ändern sich nie automatisch)

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen, auch nicht auf einem Rechenhost. Öffnen nur mit Uzis ausdrücklichem Wort.
- Kein automatischer Merge. Gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.
- TIM läuft zu 100 % auf dem Mac. Chris' Server tim-core-01 ist höchstens Rechenhost für Archiv-Aufträge.

## Autonomie-Stufen

| Stufe | TIM macht allein | Uzi macht |
|---|---|---|
| 0 Werkzeug | nichts | alles |
| **1 Vorschlagen und Rechnen (aktuell)** | Ideen sammeln und prüfen, Studien-Entwurf, nach Freigabe rechnen, Bericht, Logbuch, Monats-Reflexion | Freigabe je Studie, Update-Karte |
| 2 Selbst forschen im Rahmen | Studien aus freigegebenen Vorlagen innerhalb des Budgets anmelden und rechnen | Vorlagen, Budget, Updates |

Stufe 2 frühestens 3 Monate nach Stufe 1 ohne Regelbruch, nur auf Uzis Wort. Bei einem Regelbruch (abgewiesener
Holdout-Zugriff, gebrochene Hash-Kette) fällt TIM selbst auf Stufe 0 zurück und meldet es.

## Zahlen (E2–E6)

| Wert | Festlegung |
|---|---|
| Forschungsrunde | wöchentlich, Sonntagnacht Ortszeit |
| Reflexion der Forschung | monatlich am 1. |
| Budget | 4 neue Studien-Entwürfe je Kalendermonat (Ortszeit) |
| KI-Runde | höchstens 3 Ideen je ISO-Woche, jede mit Gegenargument; schreibt nur Ideen/Entwürfe, rechnet und merged nicht |
| Glückstest (SPA/StepM) | Pflicht ab 5 Varianten |
| Prospektives Fenster für Updates | 30 Tage Schattenbetrieb, jedes Fenster genau einmal |
| Rechner | Archiv auf Chris' Server nach Absprache (sonst Mac, nachts gedrosselt); alles Live auf dem Mac |

## Ideen-Eingang und Ideen-Prüfung (F1, F2)

Ideen stehen in `docs/research_lab/IDEEN.jsonl`: eine Zeile je Idee oder Statuswechsel, Hash-Kette, nie
überschreiben. Quellen: Uzi, Plan-Journal (`journal_review`), wöchentliche Reflexion, Lehren aus dem Logbuch,
GoatHub/Broncx (nur als Frage), KI-Runde. Dieselbe Hypothese kommt nicht zweimal hinein; derselbe Lernvorschlag
wird nur einmal importiert.

Die Prüfung entscheidet in dieser Reihenfolge, ohne Daten zu laden:

1. **Holdout:** Archivdaten mit Zeitraum ab 2025-01-01 → „bräuchte den Holdout 2025 (gesperrt)“.
2. **Schon getestet:** ähnlich einer Studie im Logbuch oder einer abgelehnten Idee → „schon getestet“ mit Verweis.
   Eine bewusst abgeleitete Idee wird mit `--derived-from` angemeldet und muss ihre Vorbelastung im Entwurf nennen.
3. **Daten:** Quelle fehlt, unbekannt oder noch nicht da (Perp, Orderbuch-Tiefe) → „wartet auf Daten“.
4. **Budget:** Monatsbudget verbraucht → „wartet auf Budget“.
5. Sonst „bereit für Studien-Entwurf“. Die Fallzahl misst erst der Zähllauf der Studie.

„Abgelehnt“ setzt nur Uzi. Die Ähnlichkeit ist ein einfacher Wortvergleich (Jaccard ab 0,4) und kann sich irren:
Sie ist ein Hinweis, kein Urteil.

```bash
python -m src.research_lab.workshop add --source uzi --title "POC-Retest London" \
    --hypothesis "Retest am Vortags-POC hält öfter als Zufall" --data archive_spot_klines --template regel_backtest
python -m src.research_lab.workshop import --journal-review reports/journal_review/<datei>.json
python -m src.research_lab.workshop check            # zeigt nur
python -m src.research_lab.workshop check --record   # schreibt geänderte Ergebnisse in die Liste
python -m src.research_lab.workshop list
```

## Verhältnis zur Lern-Spur

Die Lernschleife (Champion/Herausforderer, Bauplan „TIM lernt aktiv aus Trades“) ist die Spur „Lernen“ in diesem
Bereich. Ihr Modell-Register liegt in `src/research_lab/learning/` (eigener Thread). Der wöchentliche Journal-Lernweg
läuft über den Ideen-Eingang hier (`import --journal-review`), nicht über einen zweiten Weg.

## Nächste Pakete

F3 Studien-Generator aus Vorlagen, F4 Auftrags-Runner mit Ergebnis-Bündel, F5 Bericht und Logbuch automatisch plus
Monats-Reflexion, F6 Zeitplan, F7 Schattenbetrieb für Updates (auf dem Lern-Register), F8 Server als Rechenhost,
F9 Anzeige im Forschung-Bildschirm des neuen Control Centers.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-10-31 | 1.0 | Satzung angelegt (F0), Ideen-Eingang und Ideen-Prüfung (F1, F2) |
