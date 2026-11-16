# Orderflow-Schatten: Auswertungsregel (eingefroren vor Plan 30)

Version 1.0, Entwurf 16.11.2026. Gilt ab Merge. Wochenplan 16.–22.11., Paket W2.

Der Orderflow-Schatten (`src/dashboard/orderflow_shadow.py`, Datei `data/journal/tim_orderflow_shadow.json`)
schreibt seit 08.11.2026 14:34 Ortszeit für jeden neuen Plan der Papier-Journale 15m und 1h mit, was der
Orderflow beim Plan und beim Fill sagte (Gate) und wann ein Orderflow-Ausstieg gekommen wäre (`of_exit`).
Er handelt nicht und ändert kein Journal. Diese Regel legt fest, wie die ersten 30 geschlossenen Pläne
ausgewertet werden, bevor Plan 30 schließt. Nichts davon wird nach Ansicht der Endzahlen geändert.

## Ehrlichkeit vorab: was schon gesehen wurde

Am 16.11.2026 am frühen Nachmittag wurden die Zwischenstände von 25 geschlossenen Plänen gelesen
(im Wochenplan und beim Schreiben dieser Regel):

- Gate beim Fill: NEUTRAL n=10 −5,23 R, GEGEN n=11 −4,30 R, BESTÄTIGT n=4 −1,91 R.
- Orderflow-Ausstieg: n=25, Schatten −0,23 R gegen Journal −11,44 R.
- Alle 25 Pläne sind LONG, alle aus einer fallenden Marktphase (Woche 46: Abverkauf).
- 15m- und 1h-Pläne sind oft derselbe Markt-Trade (gleiche Fill- und Schlusszeit).

Die Regel ist also nicht blind. Deshalb: keine Schwelle, kein Filter und kein Zeitrahmen wird aus diesen
Zahlen gewählt, die Vergleiche sind die zwei, die der Schatten seit dem Start vorsieht, und jedes
positive Ergebnis führt höchstens zu "im Papier weiter beobachten", nie zu einem Einbau.

Stand beim Einfrieren (beim Merge eintragen): ___ geschlossene Pläne.

## Stichprobe

1. Zählbar ist ein Plan mit `created_at` ≥ `started_at` (2026-11-08T13:34:42Z), `journal.status` = CLOSED
   und `journal.net_r` gesetzt. EXPIRED, REPLACED und ausgeschlossene Pläne zählen nicht.
2. Ausgewertet werden genau die ersten 30 zählbaren Pläne, sortiert nach `journal.closed_at`, bei Gleichstand
   nach `id`. Spätere Pläne gehören nicht dazu, auch wenn sie am Auswertungstag schon geschlossen sind.
3. Doppelte Trades: Pläne mit gleicher Richtung, gleichem `journal.filled_at` und gleichem `journal.closed_at`
   bilden einen Cluster (ein Markt-Trade). Gezählt wird weiter je Plan (30 Pläne), aber jeder Bootstrap
   zieht ganze Cluster, damit Doppelungen keine falsche Sicherheit erzeugen. Die Zahl der Cluster steht im Bericht.

## Kennzahlen (für jede Gruppe)

- Netto-R je Plan nach Kosten, wie der Schatten sie rechnet (5 bps je Seite, `r_of`): Summe und Mittelwert.
- Trefferquote: Anteil Pläne mit Netto-R > 0.
- Größter Rückgang (Max Drawdown) der kumulierten Netto-R in `closed_at`-Reihenfolge.
- Band: 95-%-Bootstrap über Cluster, 10 000 Ziehungen, Seed 20261116. Für die zwei Entscheidungsvergleiche
  gilt Bonferroni (2 Tests): Band 97,5 % (Quantile 1,25 % und 98,75 %).

## Vergleich A: Gate BESTÄTIGT gegen GEGEN

- Gate je Plan: `gate_at_fill`, aber nur wenn `lage_at_fill.as_of` vor `journal.closed_at` liegt. Sonst
  (Fill und Schluss zwischen zwei Schritten, die Lage wäre nach dem Trade gelesen) gilt `gate_at_plan`.
  Die Zahl dieser Ersetzungen steht im Bericht. Das weicht bewusst von `summary` ab, das immer `gate_at_fill` nimmt.
- Größe: Mittelwert Netto-R (BESTÄTIGT) minus Mittelwert Netto-R (GEGEN). NEUTRAL wird berichtet, entscheidet nicht.
- Mindestgröße: je Gruppe mindestens 8 Pläne und mindestens 5 Cluster.

Genau ein Urteil:

| Lage | Urteil |
|---|---|
| eine Gruppe unter der Mindestgröße | ZU WENIG: Schatten läuft weiter, einmalige Nachauswertung bei 60 Plänen mit derselben Regel |
| Differenz > 0 und untere Bandgrenze (97,5 %) > 0 | GATE HILFT IM PAPIER: Vorschlag an Uzi, das Gate als Schatten-Filter weiter zu beobachten (kein Einbau) |
| obere Bandgrenze < 0 | GATE UMGEKEHRT: Gate-Idee in dieser Form verworfen |
| sonst | NICHT BELEGT: Gate-Idee in dieser Form verworfen |

## Vergleich B: Orderflow-Ausstieg gegen Journal-Ausstieg

- Je Plan gepaart: Schatten-Netto-R minus Journal-Netto-R. Schatten-Netto-R ist `of_exit.net_r`, wenn ein
  `of_exit` vorliegt, sonst das Journal-Ergebnis (Differenz 0).
- Vorab-Prüfung (vor dem Urteil, durch studien-pruefer): `of_exit.at` liegt nach `journal.filled_at` und vor
  `journal.closed_at`, und `of_exit.price` ist ein Kurs, der zu diesem Zeitpunkt bekannt war. Pläne, bei denen das
  nicht stimmt, werden als Fehler gezählt; mehr als 3 solche Pläne heißt: kein Urteil, erst Fehler beheben.
- Mindestgröße: 30 Pläne, mindestens 10 Cluster.

Genau ein Urteil:

| Lage | Urteil |
|---|---|
| unter der Mindestgröße oder Vorab-Prüfung gescheitert | KEIN URTEIL: Grund im Bericht, Schatten läuft weiter |
| mittlere Differenz > 0 und untere Bandgrenze (97,5 %) > 0 | OF-AUSSTIEG BESSER IM PAPIER: Vorschlag an Uzi, ihn als eigenes Schatten-Journal mit festem Ausstieg weiterzuführen (kein Einbau) |
| obere Bandgrenze < 0 | OF-AUSSTIEG SCHLECHTER: verworfen |
| sonst | NICHT BELEGT: verworfen |

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
