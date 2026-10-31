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

Ideen stehen in `data/research/IDEEN.jsonl` (seit F6 nur auf dem Mac in `~/TIM-live`, nicht versioniert; Anzeige folgt mit F9): eine Zeile je Idee oder Statuswechsel, Hash-Kette, nie
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

## Studien-Generator (F3)

Aus einer Idee mit Status „bereit“ und einer Spezifikation (JSON) schreibt der Generator einen
Präregistrierungs-Entwurf nach `docs/research_lab/studien/<Sn>_..._PRAEREGISTRIERUNG_ENTWURF.md`.

- Vorlagen und Pflichtfelder: alle brauchen `question`, `data`, `metric`, `min_effect`, `min_cases`, `stop_rule`,
  `limits`; dazu **Regel-Backtest** `variants` (je `id`, `rule`, feste `params`), `costs`, `random_baseline`;
  **Ereignis-Studie** `events`, `comparison`; **Modellvergleich** `model`, `features`, `label`,
  `prospective_window` (`start`, `days`). Eine abgeleitete Idee braucht `prior_burden` (Vorbelastung).
- Fehlt ein Feld oder reicht der Zeitraum in den Holdout, entsteht kein Entwurf.
- Name: nächste freie Nummer; auch Namen, die nur im Logbuch stehen (z. B. das abgelehnte S11), gelten als vergeben.
- Register: Regel-Backtests zeigen m vorher/nachher und brechen ab, wenn das Register (60) voll wäre.
  Ereignis-Studien und Modellvergleiche sind eigene Familien ohne Registerplätze (wie S1, S8).
- Ab 5 Varianten steht der Glückstest SPA/StepM als Pflicht im Entwurf.
- Der Entwurf trägt den SHA-256 der Spezifikation. Die Idee wechselt auf „Studien-Entwurf angelegt“ und
  verbraucht einen Platz im Monatsbudget.
- Der Generator schreibt **nichts** ins Register und lädt keine Daten. In Stufe 1 gibt Uzi jeden Entwurf frei;
  die Registrierung folgt danach wie bisher nach `PROTOKOLL.md`.

```bash
python -m src.research_lab.workshop draft --idea I-0001 --spec spec.json --dry-run   # nur anzeigen
python -m src.research_lab.workshop draft --idea I-0001 --spec spec.json             # Entwurf schreiben
```

## Auftrags-Runner und Ergebnis-Bündel (F4)

`src/research_lab/workshop/runner.py`. Freigaben und Aufträge stehen lokal in `data/research/jobs/jobs.jsonl`
(Hash-Kette), Ergebnisse als Bündel unter `data/research/bundles/<Auftrag>/` (beides nur auf dem Mac).

- **Freigabe (Stufe 1):** Ohne festgehaltene Freigabe von Uzi mit Beleg (Datum, Nachricht) nimmt der Runner
  keinen Auftrag an. `--commit-register` nur, wenn die Freigabe die Registrierung ausdrücklich erlaubt.
- **Nur Labor:** erlaubt sind `scripts/research_lab_*.py` und Module unter `src.research_lab`. Ein Argument, das
  den Holdout nennt oder ein Datum ab 2025-01-01 enthält, wird abgewiesen, bevor etwas startet.
- **Rechner:** `mac` läuft lokal mit `nice 15`. `server` läuft über ssh auf Chris' Rechenhost: Der Mac baut die
  Verbindung auf und holt die Ausgaben per rsync ab. Der Commit dort muss dem Commit auf dem Mac entsprechen,
  sonst wird das Ergebnis verworfen. Einrichtung des Hosts ist F8.
- **Bündel:** Manifest mit Commit, Befehl, Hashes aller Eingaben und Ausgaben, Exit-Code und Hash des
  Ausgabeprotokolls. Der Inhalts-Hash lässt Auftragsnummer, Rechner und Zeiten weg: Derselbe Auftrag auf
  denselben Eingaben ergibt überall denselben Hash. `verify` rechnet alles nach und weist jede Änderung ab.
- Der Runner merged nichts, pusht nichts und fasst die Runtime nicht an.

```bash
python -m src.research_lab.workshop approve --study S12 --reference "Uzi 31.10. 16:00 im Thread"
python -m src.research_lab.workshop submit --study S12 -- scripts/research_lab_s12.py --count
python -m src.research_lab.workshop run --pending
python -m src.research_lab.workshop verify --bundle data/research/bundles/J-0001
```

## Bericht, Logbuch und Monats-Reflexion (F5)

`src/research_lab/workshop/report.py`.

- **Ergebnisvertrag:** Eine Studie schreibt `out/result.json` in ihr Bündel: `status` (bestätigt, Kandidat,
  nicht bestanden, nicht testbar, wartet, abgebrochen), `result`, `lesson` (Pflicht, auch beim Nullergebnis),
  optional `metrics` und `edge` (nur bei bestätigtem Handelsvorteil nach Kosten).
- **Bericht und Logbuch:** `report` prüft das Bündel erneut, schreibt den Bericht nach
  `docs/research_lab/reports/` und trägt die Studie ins Logbuch ein (mit Inhalts-Hash des Bündels). Ein Lauf mit
  Fehler-Exit, ein verändertes Bündel oder ein fehlendes Pflichtfeld ändern das Logbuch nicht.
- **Monats-Reflexion:** `reflect-month` zählt neue Ideen je Quelle, was aus den Studien jeder Quelle wurde,
  welche fehlenden Daten Ideen blockieren, die häufigsten Lehren der Papier-Trades und die ehrliche Zahl
  „Handelsvorteile nach Kosten belegt“ (heute 0; S1 ist ein bestätigter Markteffekt, kein Handelsvorteil).
  Daraus höchstens drei Vorschläge. `--write` legt den Bericht als `reports/forschung_JJJJ-MM.md` ab.

```bash
python -m src.research_lab.workshop report --bundle data/research/bundles/J-0001 --title "POC-Retest London" --draft <entwurf.md>
python -m src.research_lab.workshop reflect-month --month 2026-10
```

## Reflexion jedes Trades

Uzi 31.10.2026: „er soll jeden trade reflektieren“. `src/research_lab/workshop/trade_reflection.py` liest die
Plan-Journale (nur lesend) und schreibt für **jeden geschlossenen Papier-Trade** genau einen Eintrag nach
`data/research/trade_reflections.jsonl` (append-only, Hash-Kette, liegt nur auf dem Mac, nicht im Repo).

Ein Eintrag enthält die Fakten (netto/brutto R, Kosten, bestes Plus, tiefstes Minus, Ausstieg, Ziele, TIMs Urteil,
Marktzustand), die Wissenszeit `known_at` (ab wann alle Fakten feststanden; für die Lernschleife) und die Lehren nach festen Regeln (`trade-reflection/1.0`):

| Lehre | Wann |
|---|---|
| Kosten haben den Gewinn aufgefressen | brutto > 0, netto ≤ 0 |
| Gewinn verschenkt | bestes Plus ≥ 1 R, netto ≤ 0 |
| Sofort falsch | tiefstes Minus ≤ −0,8 R und bestes Plus < 0,3 R |
| Stop per Docht | Stop-Prüfung meldet Docht |
| Gegen den Trend | Richtung gegen TIMs Marktzustand |
| Zeit abgelaufen / Ungültig / Alle Ziele / Datenlücke | Ausstieg TIMEOUT / INVALIDATION / TP3 / Kerzenlücke |

Die Reflexion sagt nur, was passiert ist. Sie behauptet nicht, was mit anderen Regeln passiert wäre, und ändert
keinen Stop, kein Ziel, keine Kosten. Taucht eine Verlust-Lehre in mindestens 30 % von mindestens 20 Trades eines
Journals auf, wird daraus **eine** Idee im Ideen-Eingang (Quelle „Reflexion jedes Papier-Trades“). Ab dort gilt der
normale Weg: Prüfung, Studie, prospektiver Test.

```bash
python -m src.research_lab.workshop reflect-trades --journal ~/TIM-live/data/journal/tim_plan_journal.json --dry-run
python -m src.research_lab.workshop reflect-trades --journal <journal.json> [--journal ...] --ideas
```

Automatisch nach jedem Trade läuft das mit dem Zeitplan (F6, stündlich auf dem Mac). Anzeige je Trade im
Journal-Bildschirm des neuen Control Centers (F9).

## Verhältnis zur Lern-Spur

Die Lernschleife (Champion/Herausforderer, Bauplan „TIM lernt aktiv aus Trades“) ist die Spur „Lernen“ in diesem
Bereich. Ihr Modell-Register liegt in `src/research_lab/learning/` (eigener Thread). Der wöchentliche Journal-Lernweg
läuft über den Ideen-Eingang hier (`import --journal-review`), nicht über einen zweiten Weg.

## Zeitplan auf dem Mac (F6)

LaunchAgent `com.tim.research-workshop` (`ops/launchd/com.tim.research-workshop.plist`), alle 15 Minuten,
Nice 15, gedrosselte Festplatte. Logik: `src/research_lab/workshop/schedule.py`, Aufruf
`scripts/research_workshop_schedule.py` (`--dry-run`, `--task trades|weekly|monthly`, `--no-ki`, `--install`).

| Aufgabe | Wann (Ortszeit) | Was |
|---|---|---|
| `trades` | stündlich | jeden neu geschlossenen Papier-Trade der Journale tim, struct, short, mid, long reflektieren; wiederkehrende Muster als Idee |
| `weekly` | ab Sonntag 02:00, einmal je Woche | alle Ideen prüfen (`check --record`), abgelaufene Schatten-Fenster bewerten (F7), danach KI-Runde |
| `monthly` | ab dem 1. 03:00, einmal je Monat | Monats-Reflexion des Vormonats |

- Die Automatik schreibt nur unter `data/research/` (nicht versioniert): Ideen-Liste `data/research/IDEEN.jsonl`,
  Trade-Reflexionen, KI-Runden (`ki_runde/<Woche>.json` mit Frage und Antwort), Monatsberichte (`reports/`),
  Status `schedule/state.json` und Verlauf `schedule/history.jsonl`. Der Live-Checkout bleibt sauber; was nach
  `docs/` soll, kommt per PR.
- KI-Runde: Claude Code ohne Werkzeuge bekommt Satzung, bisherige Studien, Ideen-Liste und Trade-Muster als Daten
  und darf höchstens die freien Plätze der Woche (3) vorschlagen, jede mit Gegenargument. Die Antwort gilt als
  nicht vertrauenswürdig: unbekannte Daten, fehlendes Gegenargument oder zu lange Texte werden verworfen, danach
  gelten die Grenzen der Ideen-Liste und die Ideen-Prüfung (Holdout, schon getestet, Daten, Budget). Fällt die
  KI aus, läuft die Woche ohne sie weiter.
- Kein Studien-Entwurf, keine Freigabe, kein Lauf und keine Regeländerung im Zeitplan (Stufe 1).
- Rücksicht auf CI: Läuft ein CI-Job (`Runner.Worker`), wartet jede Aufgabe; nach 3 Stunden Warten läuft sie
  trotzdem, gedrosselt. Pause: Datei `data/research/schedule/PAUSE` anlegen.
- Abnahme: eine Woche Probelauf auf dem Mac; Laufzeiten stehen je Aufgabe im Status (`seconds`), CI-Laufzeiten
  der Woche werden mit der Vorwoche verglichen.

## Schattenbetrieb für Updates (F7)

Code `src/research_lab/workshop/shadow.py`, aufgesetzt auf das Lernregister (`src/research_lab/learning/registry.py`,
unverändert; abgestimmt mit der Lern-Spur am 31.10.). Ein Ergebnis „Kandidat“ ändert nichts an TIM, bevor es
30 Tage auf ungesehenen Live-Daten mitgelaufen ist:

1. `shadow-start`: je Studie eine eigene Familie `<Studie>-schatten` mit festen Regeln (Konfiguration = Hash der
   registrierten Variante, Kennzahl Netto-R je Trade, 30 Tage, Mindestzahl Trades, kleinster Effekt, Intervall
   99,5 %, Freigabe nur Uzi), Champion `kein-trade` (0 R) und der Kandidat als Herausforderer. Das Fenster beginnt
   einen Horizont nach der Anmeldung; das Register lehnt Vor- und Rückdatieren ab.
2. Pläne des Kandidaten gehen in ein eigenes Schatten-Journal `data/research/shadow/<Studie>.jsonl` (Hash-Kette,
   Kennung `schatten:<Studie>`, jede Zeile `counts_in_net_r: false`). Ein Plan wird mit der echten Uhrzeit zur
   Entscheidung geschrieben, nur im Fenster, nie nachträglich; jedes Ergebnis genau einmal und nach dem Plan.
   Das Papier-Journal und sein Netto-R sehen davon nichts.
3. Bewertung genau einmal nach Fensterende (sonntags in der Forschungsrunde, F6): mittleres Netto-R je Trade minus
   0 R mit Bootstrap-Intervall 99,5 %. Offene Pläne oder mehr als 10 % Datenlücken ergeben „kein Urteil“.
4. Wechsel nur mit Uzis Freigabe (`approvers = ["Uzi"]`); Rückweg ohne Freigabe nur zu einem früheren Champion.

Register `data/research/shadow/register.jsonl` (nur auf dem Mac); jede Bewertung nennt den Kopf-Hash, der mit dem
Bericht per PR ins Repo kommt. Zufallsprüfung: Eine Münzwurf-Strategie mit Kosten und eine Strategie ohne Vorteil
werden in je 1 000 Simulationen in unter 5 % befördert (`tests/test_research_workshop_shadow.py`).

Grenze: Die Pläne liefert der Live-Code der jeweiligen Studie über `ShadowJournal.record_plan` und
`record_outcome`; einen allgemeinen Plan-Erzeuger gibt es nicht.

## Anzeige (F9)

Der Bildschirm „Forschung“ des Control Centers (`/forschung`) zeigt über dem Logbuch die Forschungswerkstatt:
offene Ideen (nächste zuerst, mit Quelle und Prüfgrund), Studien-Budget des Monats, Zahl der reflektierten Trades
und ihre häufigsten Lehren, letzte Läufe des Zeitplans (mit Fehlern und Warten auf CI), letzte Monats-Reflexion
und den Schattenbetrieb. Nur lesen (`src/research_lab/workshop/overview.py`); eine kaputte Datei erscheint als
Hinweis, nie als leerer gesunder Stand.

## Regel-Anfrage (F10)

Uzi beschreibt eine Regel in Worten, TIM testet sie ohne neuen Code (`src/research_lab/workshop/rules.py`,
Schema `tim_rule/1`). Bausteine:

| Teil | Bausteine |
|---|---|
| Markt | BTCUSDT, ETHUSDT, SOLUSDT (USD-M Perp), Zeitrahmen 15m, 30m, 1h, 4h, 1d (fehlende aus 5m zusammengesetzt) |
| Einstieg | `sma_cross` {n}, `breakout` {n}, `prev_day_level` {high, low, close, poc, vah, val; retest oder break}, `vwap_cross` (Tages-VWAP) |
| Filter | `hours` (Ortszeit Deutschland), `weekdays`, `trend` (mit SMA n) |
| Stop | `atr` {k}, `signal_bar` (hinter dem Docht + Puffer in ATR), `percent` |
| Ausstieg | Ziel in R und/oder Zeitstopp in Kerzen; Stop und Ziel in derselben Kerze zählen als Stop |

POC/VAH/VAL des Vortags kommen aus den Kerzen (Volumen gleichmäßig über die Spanne jeder Kerze, 50 Stufen,
Value Area 70 %): eine Näherung, kein echtes Volume Profile aus Einzeltrades. Alle Bausteine sehen nur
geschlossene Kerzen; gekauft wird zur Eröffnung der nächsten Kerze (Engine aus R0–R4).

Ablauf:

1. **Übersetzen:** `rule-from-text --text "..."` fragt die Claude-CLI. Die Antwort gilt als nicht vertrauenswürdig;
   nur eine Regel, die `validate` besteht, wird gespeichert (`data/research/rules/specs/`). Was sich nicht abbilden
   lässt, steht im Feld `note` und wird angezeigt, nie stillschweigend weggelassen. Im Chat kann Claude die Regel
   auch direkt als JSON schreiben.
2. **Vorschau:** `rule-preview` zeigt die Regel in Worten, den Regel-Hash und die Mindestzahl der Trades.
   Uzi sagt ja oder nein, bevor gerechnet wird.
3. **Erkundung:** `rule-test` rechnet Training (2020–2022) und Validierung (2023–2024) mit Protokollkosten, mit
   doppelten Kosten und gegen Zufallseinstiege: gleiche Filter-Zeiten, Stop-Abstände (in ATR) aus den eigenen
   Signalen, gleiches Ziel und gleicher Zeitstopp. So misst der Vergleich nur den Einstiegszeitpunkt.
   „Kandidat“ heißt: Mindestzahl Trades erreicht (Protokoll, Validierung die Hälfte), in beiden Abschnitten mehr
   als 0,05 R je Trade, mit doppelten Kosten in der Validierung noch positiv und in beiden Abschnitten Zufall
   p < 0,05. Die Erkundung belegt **keinen** Registerplatz und beweist nichts. Jede Erkundung steht mit Hash-Kette
   in `data/research/rules/log.jsonl`, Bericht unter `data/research/rules/runs/R-nnnn/`. Die Anzeige nennt die Zahl
   aller Versuche, denn bei 20 Versuchen ist ein zufällig guter zu erwarten.
4. **Studie:** `rule-study --spec regel.json --run R-nnnn` legt die Idee an und schreibt die Generator-Spezifikation
   (eine Variante, ein Registerplatz, Vorbelastung aus der Erkundung). Danach wie gehabt `check --record`,
   `draft`, Uzis Freigabe, `submit -- scripts/research_lab_rule.py --spec ...`, `run`, `report`. Der Holdout bleibt
   bis zu Uzis ausdrücklichem Wort zu; ein bestandener Holdout führt in den Schattenbetrieb (F7).

Stand 31.10.: Das Holdout-Register hat m = 58 von 60. Für mehr als zwei neue Regel-Studien braucht es einen neuen
Holdout-Zeitraum (Uzis Entscheidung); Erkundungen sind davon nicht betroffen.

Die Archivdaten liegen auf dem Mac in einem Worktree (z. B. `--archive ~/Documents/TIM/worktrees/s4-zaehllauf/data/research_lab`).

## Selbst-Verbesserung aus den eigenen Trades (F11)

Uzi, 31.10.: „TIM soll seine trades reflektieren koennen, um einfach besser zu traden.“ Die Wochenrunde (F6)
führt dafür `src/research_lab/workshop/self_improve.py` aus. Uzi muss dafür keine Regel formulieren.

1. **Filter aus Lehren.** Jede Lehre der Trade-Reflexion hat einen festen Filter, der solche Trades auslässt:
   `MIT_TREND` (gegen TIMs Marktzustand), `KOSTEN_DECKEL` (geplante Kosten über 0,15 R, also Stop zu eng),
   `OHNE_GRADE_C`, `NUR_BESTAETIGT` (fehlende Bestätigung). Die Filter lesen nur, was beim Planen bekannt war.
   Die Schwellen stehen im Code fest und werden nicht an die Trades angepasst.
2. **Rückblick.** Jeder Filter wird an allen abgeschlossenen Trades der Plan-Journale nachgerechnet: Was
   haben die Trades gebracht, die er ausgelassen hätte? Das ist ein In-Sample-Ergebnis, weil die Lehren aus
   denselben Trades stammen. Es entscheidet nur, ob ein Filter beobachtet wird: Es müssen mindestens 20 Trades
   da sein und mindestens 8 wegfallen, höchstens 90 % aller Trades, und die weggefallenen müssen zusammen im
   Minus sein.
3. **30 Tage Beobachtung.** Es zählen nur Trades, die nach dem Start geplant wurden. An TIM ändert sich nichts.
4. **Ein Urteil je Fenster.** Bestanden heißt: mindestens 20 neue Trades, davon mindestens 5 weggefallen, und
   das Bootstrap-Band der weggefallenen Trades liegt ganz unter null (Bonferroni über die vier Filter). Danach
   steht „bereit für deine Entscheidung“. Nur Uzis Ja ändert TIMs Regel, per PR. Bei zu wenigen Trades beginnt
   ein neues Fenster. Ein nicht bestandener Filter wird nicht wiederholt.

Protokoll: `data/research/self_improve/log.jsonl` (Hash-Kette). Anzeige: Karte „Selbst-Verbesserung“ unter
/forschung. Von Hand ansehen: `python -m src.research_lab.workshop learn` (nur lesen, mit `--write` wie die
Wochenrunde).

Rückblick am 31.10. auf 29 Trades: Trades gegen den Trend brachten zusammen +2,50 R. Die Lehre „gegen den
Trend“ hätte als Regel also geschadet. Trades mit Kosten über 0,15 R brachten −3,87 R (17 Trades). Grade C und
fehlende Bestätigung betreffen alle 29 Trades und taugen deshalb nicht als Filter.

## Nächste Pakete

F8 Server als Rechenhost (zurückgestellt, Uzi 31.10.: erst alles auf dem Mac).

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-10-31 | 1.0 | Satzung angelegt (F0), Ideen-Eingang und Ideen-Prüfung (F1, F2) |
| 2026-10-31 | 1.0 | Studien-Generator (F3) |
| 2026-10-31 | 1.0 | Reflexion jedes Trades (Uzis Wunsch), Quelle `trade_reflexion` |
| 2026-10-31 | 1.0 | Auftrags-Runner und Ergebnis-Bündel (F4) |
| 2026-10-31 | 1.0 | Bericht, Logbuch und Monats-Reflexion (F5) |
| 2026-10-31 | 1.0 | Zeitplan auf dem Mac (F6) |
| 2026-10-31 | 1.0 | Schattenbetrieb für Updates (F7) |
| 2026-10-31 | 1.0 | Anzeige im Forschung-Bildschirm (F9) |
| 2026-10-31 | 1.0 | Selbst-Verbesserung aus den eigenen Trades (F11) |
| 2026-10-31 | 1.0 | Regel-Anfrage (F10): Regel aus Bausteinen, Erkundung ohne Registerplatz, Weg zur Studie |
