# Orderflow-Schatten: Auswertung der ersten 30 Pläne (Papier), 19.11.2026

Wochenplan 16.–22.11., Paket W3. Ausgewertet genau nach `docs/research_lab/studien/OF_SCHATTEN_AUSWERTUNGSREGEL.md`
(Version 1.2, eingefroren am 16.11. bei 25 geschlossenen Plänen). Nichts an der Regel wurde nach Ansicht der Zahlen geändert.
Nur Papier, kein Echtgeld, keine Änderung an TIM, kein Holdout 2025.

## Urteile

| Vergleich | Urteil | Folge laut Regel |
|---|---|---|
| A: Gate BESTÄTIGT gegen GEGEN | **ZU WENIG** | Schatten läuft weiter; einmalige Nachauswertung bei 60 Plänen mit derselben Regel (Band dann 98,33 %) |
| B: Orderflow-Ausstieg gegen Journal-Ausstieg | **NICHT BELEGT** | In dieser Form verworfen |

Frage an Uzi: keine. Beide Urteile führen laut Regel zu keinem Vorschlag.

## Stichprobe

- 30 zählbare Pläne, alle ausgewertet (am Auswertungstag gab es genau 30). Erster Schluss 10.11. 17:38, letzter 19.11. 02:35 (deutsche Zeit).
- Alle 30 sind LONG. 16 Pläne 15m, 14 Pläne 1h.
- 26 Cluster (Markt-Trades); 14 davon überlappen zeitlich mit einem anderen. Das Band ist deshalb eher zu schmal.
- Nachrechnung des Journals mit dem Kostenmodell trifft `journal.net_r` bei allen 30 Plänen (größte Abweichung 0,0004 R).

| Gruppe | Pläne | Summe R | Mittel R | Trefferquote | Größter Rückgang R |
|---|---:|---:|---:|---:|---:|
| Journal (alle 30) | 30 | −11,08 | −0,369 | 36,7 % | 13,45 |
| Schatten mit Orderflow-Ausstieg (alle 30) | 30 | −2,91 | −0,097 | 20,0 % | 3,76 |

## Vergleich A: Gate

Das Gate kam bei allen 30 Plänen aus Stufe 1 (`gate_at_fill`, Lage höchstens 5 Minuten nach dem Fill). Stufe 2: 0, UNBEKANNT: 0.

| Gate | Pläne | Cluster | Summe R | Mittel R | Trefferquote | Größter Rückgang R |
|---|---:|---:|---:|---:|---:|---:|
| BESTÄTIGT | 6 | 5 | −0,81 | −0,135 | 50,0 % | 2,36 |
| GEGEN | 12 | 10 | −4,30 | −0,358 | 33,3 % | 6,32 |
| NEUTRAL (entscheidet nicht) | 12 | 11 | −5,96 | −0,497 | 33,3 % | 7,24 |
| UNBEKANNT | 0 | 0 | – | – | – | – |

- BESTÄTIGT hat nur 6 Pläne, verlangt sind mindestens 8. Deshalb **ZU WENIG**.
- Nur zur Einordnung, ohne Urteil: Differenz BESTÄTIGT minus GEGEN +0,223 R je Plan, Band 97,5 % von −0,847 bis +1,250
  (38 von 10 000 Ziehungen ohne eine der beiden Gruppen, ausgelassen); bei doppelten Kosten +0,221 R.
  Das Band schließt die Null weit ein. Alle drei Gruppen sind im Minus.
- Nur beschreibend (35 statt 5 Minuten): gleiche Einteilung, 6 / 12 / 12.

## Vergleich B: Orderflow-Ausstieg

- Alle 30 Pläne haben einen `of_exit`; bei keinem fehlte die Lage beim Fill. Ob die Lage während eines Trades zeitweise fehlte,
  ist aus der Schatten-Datei nicht ablesbar (sie speichert nur die Lage bei Plan, Fill und Ausstieg): **nicht geprüft**.
- Vorab-Prüfung: 0 Fehler. Jeder `of_exit` liegt zwischen Fill und Schluss und über dem damals aktiven Stop.
  Die Regel lässt bei "vor der 1m-Kerze" zwei Lesarten zu (Stop-Eintrag genau auf der Kerzengrenze); beide wurden gerechnet,
  beide ergeben 0 Fehler.
- Einwand aus der Prüfung (studien-pruefer): der Stop nach dem ersten Ziel (Break-even plus Kosten) steht nicht immer in
  `stop_path`, die Regel und das Skript sehen ihn dann nicht. Nachgeprüft an den Daten: bei 29 Plänen kam der `of_exit` vor
  dem ersten Ziel und vor jeder Stop-Verschiebung, dort galt der erste Stop. Bei Plan 25 kam er nach zwei Zielen; der Stop lag
  dann bei etwa 62 686 (Break-even plus Kosten), der `of_exit` bei 63 869,35, also klar darüber. Es bleibt bei 0 Fehlern.
  Die Zeiten stehen in der Tabelle "Vorab-Prüfung einzeln".
- Alle 30 geschlossenen Pläne des Schattens wurden im Journal gefunden; keiner wurde übersprungen.
- Mittlere Differenz (Schatten minus Journal): **+0,272 R je Plan** (Summe +8,17 R).
- Band 97,5 % über Cluster: **−0,037 bis +0,542**. Die untere Grenze liegt unter 0. Deshalb **NICHT BELEGT**.
- Stresstest doppelte Kosten: +0,288 R je Plan (gleiches Vorzeichen).
- Nur beschreibend: das einfache 95-%-Band wäre +0,006 bis +0,510. Es entscheidet nicht; die Regel verlangt wegen zweier Tests 97,5 %.

Pflichtangaben der Regel:

- 26 von 30 Plänen (86,7 %) endeten im Journal an einer Stop-Order (14 am ersten Stop, 12 an nachgezogenem, Kosten- oder
  Break-even-Stop). 3 endeten durch Invalidierung, 1 am dritten Ziel.
- Differenz bei den 19 Verlierern des Journals: +0,651 R je Plan. Bei den 11 Gewinnern: **−0,381 R je Plan**.
  Der frühe Ausstieg kappt also Verluste und kostet bei Gewinnern, wie in einem fallenden Markt zu erwarten.

## Grenzen

- Nur LONG und nur eine Marktphase (fallend). Das Ergebnis gilt für diese Phase, nicht allgemein. Eine Bestätigung bräuchte neue
  Pläne, darunter SHORT, in einer anderen Phase.
- Woche 46 (09.–15.11., Abverkauf nach Nachrichten) liegt im Fenster und wurde nicht herausgenommen; 25 der 30 Pläne schlossen bis 15.11.
- Zwischenstände bis Plan 25 waren beim Einfrieren der Regel bekannt. Die Auswertung ist nicht blind.
- 30 Pläne sind 26 Markt-Trades, davon 14 zeitlich überlappend: wenig unabhängige Beobachtungen.
- Aufteilungen nach Session, Volumen und Timing wurden nicht ausgewertet.
- Kein Holdout 2025, kein Echtgeld, keine Änderung an TIM.

## Pläne einzeln

Zeiten in deutscher Zeit. R netto nach dem Kostenmodell des Journals.

| Nr | Plan | Zeitrahmen | Fill | Schluss | Journal-Ausstieg | Gate | Journal R | Schatten R | Differenz |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0df919 | 15m | 10.11. 16:35 | 10.11. 17:38 | STOP | NEUTRAL | -1,18 | -0,60 | +0,58 |
| 2 | a0f49b | 1h | 10.11. 16:35 | 10.11. 17:38 | STOP | NEUTRAL | -1,18 | -0,58 | +0,60 |
| 3 | f4787d | 15m | 10.11. 18:39 | 11.11. 01:27 | TRAIL_STOP | GEGEN | +1,02 | +0,44 | -0,57 |
| 4 | 15bccc | 1h | 10.11. 18:39 | 11.11. 15:30 | TRAIL_STOP | GEGEN | +1,00 | +0,44 | -0,56 |
| 5 | 11f23b | 15m | 12.11. 12:29 | 12.11. 14:10 | STOP | GEGEN | -1,18 | -0,30 | +0,88 |
| 6 | 52ea94 | 1h | 12.11. 13:08 | 12.11. 15:22 | STOP | GEGEN | -1,18 | -0,18 | +1,00 |
| 7 | 3677f8 | 15m | 12.11. 16:00 | 12.11. 16:45 | INVALIDATION | NEUTRAL | -0,72 | -0,66 | +0,06 |
| 8 | 87a786 | 1h | 12.11. 16:03 | 12.11. 20:41 | COST_STOP | BESTÄTIGT | -0,00 | -0,23 | -0,23 |
| 9 | 2ded1a | 1h | 12.11. 23:51 | 13.11. 02:00 | INVALIDATION | GEGEN | -0,44 | -0,13 | +0,31 |
| 10 | 6213e4 | 15m | 12.11. 23:51 | 13.11. 02:00 | INVALIDATION | GEGEN | -0,44 | -0,13 | +0,31 |
| 11 | c97065 | 1h | 13.11. 03:06 | 13.11. 03:53 | STOP | NEUTRAL | -1,18 | -0,21 | +0,97 |
| 12 | 17772a | 1h | 13.11. 06:30 | 13.11. 06:57 | STOP | BESTÄTIGT | -1,18 | -0,28 | +0,90 |
| 13 | 8a356a | 15m | 13.11. 06:30 | 13.11. 06:57 | STOP | BESTÄTIGT | -1,18 | -0,28 | +0,90 |
| 14 | fcd2a6 | 15m | 14.11. 05:33 | 14.11. 09:54 | TRAIL_STOP | NEUTRAL | +0,31 | +0,35 | +0,04 |
| 15 | 49ed16 | 1h | 14.11. 05:00 | 14.11. 13:59 | TRAIL_STOP | NEUTRAL | +0,25 | -0,40 | -0,65 |
| 16 | d39215 | 15m | 14.11. 15:01 | 14.11. 15:49 | STOP | NEUTRAL | -1,18 | -0,10 | +1,08 |
| 17 | 233e73 | 1h | 14.11. 16:05 | 14.11. 16:30 | STOP | GEGEN | -1,18 | -0,14 | +1,04 |
| 18 | 88e56e | 15m | 14.11. 16:05 | 14.11. 16:30 | STOP | GEGEN | -1,18 | -0,14 | +1,04 |
| 19 | 16cf88 | 15m | 14.11. 17:12 | 14.11. 21:33 | TRAIL_STOP | GEGEN | +0,02 | -0,12 | -0,14 |
| 20 | 58f166 | 15m | 14.11. 22:30 | 14.11. 23:09 | STOP | NEUTRAL | -1,18 | -0,10 | +1,08 |
| 21 | fafc86 | 1h | 14.11. 22:02 | 14.11. 23:09 | STOP | NEUTRAL | -1,18 | -0,42 | +0,76 |
| 22 | 4701c7 | 1h | 15.11. 00:03 | 15.11. 01:53 | BREAK_EVEN_COSTS | BESTÄTIGT | +0,45 | +0,64 | +0,20 |
| 23 | 8c4cde | 15m | 15.11. 00:39 | 15.11. 01:53 | BREAK_EVEN_COSTS | GEGEN | +0,45 | -0,10 | -0,54 |
| 24 | 5a1ca5 | 1h | 15.11. 02:01 | 15.11. 02:09 | STOP | GEGEN | -1,18 | -0,42 | +0,76 |
| 25 | 8249ab | 15m | 15.11. 03:01 | 15.11. 03:18 | TP3 | NEUTRAL | +2,01 | +1,70 | -0,31 |
| 26 | 74f36d | 15m | 17.11. 16:48 | 17.11. 17:17 | COST_STOP | GEGEN | -0,00 | -0,65 | -0,65 |
| 27 | 760279 | 1h | 18.11. 17:01 | 18.11. 17:21 | STOP | NEUTRAL | -1,18 | -0,19 | +0,99 |
| 28 | ca6a75 | 15m | 18.11. 17:45 | 18.11. 21:48 | BREAK_EVEN_COSTS | NEUTRAL | +0,45 | +0,05 | -0,40 |
| 29 | 5291df | 15m | 18.11. 22:41 | 19.11. 02:29 | TRAIL_STOP | BESTÄTIGT | +0,65 | -0,10 | -0,75 |
| 30 | 47f63d | 1h | 18.11. 23:09 | 19.11. 02:35 | BREAK_EVEN_COSTS | BESTÄTIGT | +0,45 | -0,07 | -0,52 |

## Vorab-Prüfung einzeln

Zeiten in deutscher Zeit. "Aktiver Stop" ist der Stop, der zur Zeit des `of_exit` galt (bei Plan 25 Break-even plus Kosten, gerundet).

| Nr | Plan | `of_exit` Zeit | `of_exit` Preis | Aktiver Stop | Erste Stop-Verschiebung | Erstes Ziel |
|---|---|---|---:|---:|---|---|
| 1 | 0df919 | 10.11. 16:40:48 | 73275,5 | 72862,27 | – | – |
| 2 | a0f49b | 10.11. 16:40:48 | 73275,5 | 72847,67 | – | – |
| 3 | f4787d | 10.11. 18:55:27 | 73239,36 | 72072,00 | 10.11. 19:15 | 10.11. 22:01 |
| 4 | 15bccc | 10.11. 18:55:27 | 73239,36 | 72072,00 | 10.11. 20:00 | 10.11. 22:01 |
| 5 | 11f23b | 12.11. 12:30:54 | 73180,01 | 72549,51 | – | – |
| 6 | 52ea94 | 12.11. 13:09:02 | 72788,72 | 72072,00 | – | – |
| 7 | 3677f8 | 12.11. 16:01:27 | 71476,56 | 71115,42 | – | – |
| 8 | 87a786 | 12.11. 16:06:53 | 71313,47 | 70650,88 | 12.11. 18:00 | – |
| 9 | 2ded1a | 12.11. 23:52:15 | 71348,11 | 70613,01 | – | – |
| 10 | 6213e4 | 12.11. 23:52:15 | 71348,11 | 70613,01 | – | – |
| 11 | c97065 | 13.11. 03:13:50 | 70726,59 | 70051,10 | – | – |
| 12 | 17772a | 13.11. 06:39:31 | 68511,93 | 67910,45 | – | – |
| 13 | 8a356a | 13.11. 06:39:31 | 68511,93 | 67910,45 | – | – |
| 14 | fcd2a6 | 14.11. 05:39:28 | 67021,03 | 66013,36 | 14.11. 05:45 | – |
| 15 | 49ed16 | 14.11. 05:13:49 | 66520,95 | 66013,36 | 14.11. 06:00 | – |
| 16 | d39215 | 14.11. 15:07:20 | 66563,21 | 65857,23 | – | – |
| 17 | 233e73 | 14.11. 16:07:00 | 65880,1 | 65209,85 | – | – |
| 18 | 88e56e | 14.11. 16:07:00 | 65880,1 | 65209,85 | – | – |
| 19 | 16cf88 | 14.11. 17:13:40 | 65261,24 | 64582,37 | 14.11. 18:30 | – |
| 20 | 58f166 | 14.11. 22:38:14 | 64612,01 | 63928,77 | – | – |
| 21 | fafc86 | 14.11. 22:19:20 | 64403,95 | 63928,77 | – | – |
| 22 | 4701c7 | 15.11. 00:22:57 | 63892,02 | 62749,49 | 15.11. 01:00 | 15.11. 01:13 |
| 23 | 8c4cde | 15.11. 00:40:50 | 63422,97 | 62749,49 | 15.11. 01:00 | 15.11. 01:13 |
| 24 | 5a1ca5 | 15.11. 02:02:14 | 63219,34 | 62749,49 | – | – |
| 25 | 8249ab | 15.11. 03:14:18 | 63869,35 | 62686 | – | 15.11. 03:07 |
| 26 | 74f36d | 17.11. 16:49:40 | 63652,12 | 63329,23 | 17.11. 17:15 | – |
| 27 | 760279 | 18.11. 17:04:58 | 63042,45 | 62432,44 | – | – |
| 28 | ca6a75 | 18.11. 17:46:55 | 62512,01 | 61758,14 | 18.11. 18:15 | 18.11. 18:29 |
| 29 | 5291df | 18.11. 22:46:04 | 62380,58 | 61718,22 | 19.11. 00:15 | 19.11. 00:52 |
| 30 | 47f63d | 18.11. 23:11:39 | 62397,35 | 61718,22 | – | 19.11. 00:52 |

## Nachweis

- Skript: `scripts/research_lab_of_schatten_auswertung.py` (Commit 98727a1, sha256 `fa488627…d39f4d`), nur lesend.
  Bootstrap über Cluster, 10 000 Ziehungen, Seed 20261116; ein Zufallsgenerator, erst Vergleich A, dann Vergleich B.
- Lauf: 19.11.2026 abends auf dem Mac gegen die Live-Journale, Code des Journals (`plan_journal.py`) aus dem Live-Stand.
- Eingaben (sha256): `tim_orderflow_shadow.json` `a6dc0246…804971`, `tim_plan_journal_short.json` `cbe62e4c…ba0b1`,
  `tim_plan_journal_mid.json` `8c8a5efc…fe6f21`.
- Ergebnisdatei mit allen Zahlen je Plan: am Mac unter `Documents/TIM/worktrees/w3-of-schatten/of_schatten_2026-11-19.json`
  (sha256 `90c802a5…ddb0d`), nicht im Repo.
- Die Schatten-Datei wird laufend fortgeschrieben; die ersten 30 Pläne ändern sich dadurch nicht mehr.
