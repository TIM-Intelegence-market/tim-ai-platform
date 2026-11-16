# Orderflow-Schatten: Auswertungsregel (eingefroren vor Plan 30)

Version 1.1, Entwurf 16.11.2026 (1.0 nach Prüfung durch studien-pruefer nachgebessert). Gilt ab Merge.
Wochenplan 16.–22.11., Paket W2.

Der Orderflow-Schatten (`src/dashboard/orderflow_shadow.py`, Datei `data/journal/tim_orderflow_shadow.json`)
schreibt seit 08.11.2026 14:34 Ortszeit für jeden neuen Plan der Papier-Journale 15m und 1h mit, was der
Orderflow beim Plan und beim Fill sagte (Gate) und wann ein Orderflow-Ausstieg gekommen wäre (`of_exit`).
Er handelt nicht und ändert kein Journal. Diese Regel legt fest, wie die ersten 30 geschlossenen Pläne
ausgewertet werden, bevor Plan 30 schließt. Nichts davon wird nach Ansicht der Endzahlen geändert.

## Ehrlichkeit vorab: was schon gesehen wurde

Am 16.11.2026 am frühen Nachmittag wurden die Zwischenstände von 25 geschlossenen Plänen gelesen
(im Wochenplan und beim Schreiben dieser Regel):

- Gate laut `summary`: NEUTRAL n=10 −5,23 R, GEGEN n=11 −4,30 R, BESTÄTIGT n=4 −1,91 R.
- Orderflow-Ausstieg laut `summary`: n=25, Schatten −0,23 R gegen Journal −11,44 R (ungleiche Kosten, siehe Vergleich B).
- Alle 25 Pläne sind LONG, alle aus einer fallenden Marktphase (Woche 46: Abverkauf).
- 15m- und 1h-Pläne sind oft derselbe Markt-Trade (gleiche Fill- und Schlusszeit).

Die Regel ist also nicht blind. Deshalb: keine Schwelle, kein Filter und kein Zeitrahmen wird aus diesen
Zahlen gewählt, die Vergleiche sind die zwei, die der Schatten seit dem Start vorsieht, und jedes
positive Ergebnis führt höchstens zu "im Papier weiter beobachten", nie zu einem Einbau.

Stand beim Einfrieren (beim Merge eintragen): ___ geschlossene Pläne, Zeitpunkt ___.

## Stichprobe

1. Zählbar ist ein Plan mit `created_at` ≥ `started_at` (2026-11-08T13:34:42Z), `journal.status` = CLOSED
   und `journal.net_r` gesetzt. EXPIRED, REPLACED, INVALIDATED und ausgeschlossene Pläne zählen nicht.
2. Ausgewertet werden genau die ersten 30 zählbaren Pläne, sortiert nach `journal.closed_at`, bei Gleichstand
   nach `id`. Spätere Pläne gehören nicht dazu, auch wenn sie am Auswertungstag schon geschlossen sind.
3. Doppelte Trades: Pläne mit gleicher Richtung, gleichem `journal.filled_at` und gleichem `journal.closed_at`
   bilden einen Cluster (ein Markt-Trade). Gezählt wird weiter je Plan, aber jeder Bootstrap zieht ganze
   Cluster. Die Zahl der Cluster und die Zahl der Cluster, die sich zeitlich mit einem anderen überlappen,
   stehen im Bericht. Überlappende Cluster sind nicht unabhängig; das Band ist deshalb eher zu schmal.
4. Für die Ergebnisse werden die Journal-Einträge selbst gelesen (`tim_plan_journal_short.json`,
   `tim_plan_journal_mid.json`: `entry`, `stop`, `fill_price`, `targets`, `tp_hits`, `stop_path`, `net_r`).

## Kennzahlen (für jede Gruppe)

- Netto-R je Plan nach dem Kostenmodell des Journals (Protokoll 1.1: 0,05 % Gebühr und 0,03 % Schlupf je
  Seite, 0,05 % Schlupf bei Stop-Ausführung, Risiko = |entry − stop|): Summe und Mittelwert.
  Für das Journal ist das `journal.net_r`.
- Trefferquote: Anteil Pläne mit Netto-R > 0.
- Größter Rückgang (Max Drawdown) der kumulierten Netto-R in `closed_at`-Reihenfolge.
- Band: 95-%-Bootstrap über Cluster, 10 000 Ziehungen, Seed 20261116. Für die zwei Entscheidungsvergleiche
  gilt Bonferroni (2 Tests): Band 97,5 % (Quantile 1,25 % und 98,75 %).
- Stresstest: jeder Entscheidungsvergleich zusätzlich mit doppelten Kosten. Ein positives Urteil gilt nur,
  wenn das Vorzeichen der mittleren Differenz bei doppelten Kosten gleich bleibt; sonst NICHT BELEGT.

## Vergleich A: Gate BESTÄTIGT gegen GEGEN

Gate je Plan, in dieser Reihenfolge (die Lage muss vor oder sehr kurz nach dem Fill gelesen sein):

1. `gate_at_fill`, wenn `lage_at_fill` vorhanden ist und `lage_at_fill.as_of` ≤ `journal.filled_at` + 5 Minuten
   und vor `journal.closed_at` liegt.
2. sonst `gate_at_plan`, wenn `lage_at_plan` vorhanden ist und `lage_at_plan.as_of` ≤ `journal.filled_at` liegt.
3. sonst UNBEKANNT. Fehlende Lage (`lage_at_*` = null) heißt immer UNBEKANNT, nie NEUTRAL, auch wenn der
   Code dort NEUTRAL schreibt. UNBEKANNT-Pläne fallen aus Vergleich A heraus.

Die Zahl der Pläne je Stufe steht im Bericht. Nur beschreibend: dasselbe mit 35 Minuten statt 5 Minuten.

- Größe: Mittelwert Netto-R (BESTÄTIGT) minus Mittelwert Netto-R (GEGEN). NEUTRAL wird berichtet, entscheidet nicht.
- Mindestgröße: je Gruppe mindestens 8 Pläne und mindestens 5 Cluster.

Genau ein Urteil:

| Lage | Urteil |
|---|---|
| eine Gruppe unter der Mindestgröße | ZU WENIG: Schatten läuft weiter, einmalige Nachauswertung bei 60 Plänen mit derselben Regel (siehe unten) |
| Differenz > 0, untere Bandgrenze (97,5 %) > 0, Stresstest gleiches Vorzeichen | GATE HILFT IM PAPIER: Vorschlag an Uzi, das Gate als Schatten-Filter weiter zu beobachten (kein Einbau) |
| obere Bandgrenze < 0 | GATE UMGEKEHRT: Gate-Idee in dieser Form verworfen |
| sonst | NICHT BELEGT: Gate-Idee in dieser Form verworfen |

Nachauswertung bei 60 Plänen: nur für Vergleich A und nur, wenn bei 30 ZU WENIG herauskam. Sie ist ein zweiter
Blick auf dieselbe Frage; dort gilt deshalb Bonferroni mit 3 Tests (Band 98,33 %, Quantile 0,83 % und 99,17 %).
Ist auch bei 60 eine Gruppe zu klein, lautet das Endurteil NICHT PRÜFBAR.

## Vergleich B: Orderflow-Ausstieg gegen Journal-Ausstieg

Je Plan gepaart: Schatten-Netto-R minus `journal.net_r`. Das Schatten-Ergebnis wird **nicht** aus
`of_exit.net_r` genommen (dort nur 5 bps Gebühr, ganze Position, Risiko ab Fill), sondern mit der Rechnung des
Journals neu gebildet:

- Drittel, deren Zeit in `tp_hits` vor `of_exit.at` liegt, bleiben zu ihrem Ziel gebucht wie im Journal.
- Der Rest schließt zu `of_exit.price` zur Zeit `of_exit.at` als normaler Ausstieg (kein Stop-Schlupf).
- Brutto, Gebühr und Schlupf wie `_close` und `costs_r` in `src/dashboard/plan_journal.py` (Risiko = |entry − stop|).
- Kein `of_exit`: Schatten-Ergebnis = Journal-Ergebnis (Differenz 0). Die Zahl solcher Pläne und die Zahl der
  Pläne, bei denen die Lage während des Trades zeitweise fehlte, stehen im Bericht.

Vorab-Prüfung je Plan (vor dem Urteil, durch studien-pruefer):

1. `of_exit.at` liegt nach `journal.filled_at` und vor `journal.closed_at`.
2. Bei LONG liegt `of_exit.price` über dem Stop, der laut `stop_path` zur Zeit `of_exit.at` aktiv war
   (bei SHORT darunter). Sonst war der Stop in derselben Minute schon gefallen.

Ein Plan, der eine Prüfung nicht besteht, zählt mit Differenz 0 (als ob es keinen `of_exit` gegeben hätte) und
wird im Bericht einzeln genannt. Bei mehr als 3 solchen Plänen gibt es kein Urteil, erst wird der Fehler behoben.

- Mindestgröße: 30 Pläne, mindestens 10 Cluster.

Genau ein Urteil:

| Lage | Urteil |
|---|---|
| unter der Mindestgröße oder mehr als 3 Fehler in der Vorab-Prüfung | KEIN URTEIL: Grund im Bericht, Schatten läuft weiter |
| mittlere Differenz > 0, untere Bandgrenze (97,5 %) > 0, Stresstest gleiches Vorzeichen | OF-AUSSTIEG BESSER IM PAPIER: Vorschlag an Uzi, ihn als eigenes Schatten-Journal mit festem Ausstieg weiterzuführen (kein Einbau) |
| obere Bandgrenze < 0 | OF-AUSSTIEG SCHLECHTER: verworfen |
| sonst | NICHT BELEGT: verworfen |

## Was nicht ausgewertet wird

Die Aufteilungen in `summary` nach Session und Volumen (`by_session`, `by_volume`) und die Timing-Felder
(`timing_at_plan`, `timing_at_fill`) werden im Bericht höchstens als Tabelle gezeigt. Aus ihnen folgt kein
Urteil, kein Vorschlag und keine neue Regel; eine Frage daraus braucht eine eigene Studie mit frischen Plänen.

## Grenzen, die im Bericht stehen müssen

- Nur LONG und nur eine Marktphase: ein Ergebnis gilt für diese Phase, nicht allgemein. Eine Bestätigung braucht
  neue Pläne, darunter SHORT, in einer anderen Phase.
- Ein früher Ausstieg sieht in einem fallenden Markt fast zwangsläufig besser aus. Der Bericht nennt deshalb den
  Anteil der Pläne, die im Journal am Stop endeten, und die Differenz getrennt für Gewinner und Verlierer des Journals.
- Woche 46 (09.–15.11., Abverkauf nach Nachrichten) liegt im Fenster und wird nicht herausgenommen.
- Zwischenstände bis Plan 25 waren bekannt (siehe oben).
- Kein Holdout 2025, kein Echtgeld, keine Änderung an TIM. Jedes Urteil ist nur eine Ja/Nein-Frage an Uzi.

## Ablauf

1. Diese Regel per Pull Request, Merge nur auf Uzis "merge", vor Plan 30.
2. Sobald 30 zählbare Pläne geschlossen sind: Auswertung genau nach dieser Regel (Paket W3), Bericht unter
   `docs/research_lab/berichte/`, Prüfung durch studien-pruefer, dann ein Satz plus höchstens eine Frage an Uzi.
