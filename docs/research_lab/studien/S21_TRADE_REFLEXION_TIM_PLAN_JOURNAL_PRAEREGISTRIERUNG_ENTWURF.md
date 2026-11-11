# S21: Trade-Reflexion tim_plan_journal: AGAINST_TREND (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S21 |
| Version | **Entwurf 0.2 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 1); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-11 01:06 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0003 aus Quelle „Reflexion jedes Papier-Trades“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Generator: Regel-Backtest auf dem Archiv. **0.2: prospektive Prüfung auf den Papier-Plan-Journalen** (Abschnitt 4; ein Archiv-Backtest ist nicht machbar) |
| Spezifikation | SHA-256 `7bf6c79e589158fa36e09e3bdaf9ddfab5de0ee518ba11368fde34f322102332` (gilt für Entwurf 0.1 vom Generator; die Änderungen in 0.2 sind von Hand und vom Hash **nicht** gedeckt) |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | Wird nicht berührt. S21 liest nur Papier-Trades, die nach dem Einfrieren von Version 1.0 geplant werden (alle nach 2025-01-01, aber keine Archivdaten). |
| Register | **Vorschlag: außerhalb des Registers (0 von 60), Uzis Entscheidung offen.** S21 läuft wie S8/S13/S14/S15/S19/OF2 als eigene prospektive Familie und belegt keinen Registerplatz (Register bleibt bei m = 58 von 60). Der Generator-Entwurf 0.1 hätte 2 Plätze belegt (m = 58 → 60, Obergrenze PROTOKOLL.md Abschnitt 10). |

## 1. Fragestellung

Verlieren Papier-Trades, die gegen TIMs Marktzustand geplant werden, auf neuen Trades so viel Geld, dass die Regel „Trades gegen TIMs Marktzustand auslassen“ das Netto-Ergebnis verbessert?

## 2. Hypothese und Herkunft

In tim_plan_journal zeigt sich bei 8 von 20 Trades: Trade gegen TIMs Marktzustand. Eine Regeländerung dagegen verbessert das Netto-Ergebnis auf neuen Daten.

Präzisiert in 0.2: Geprüft wird genau eine Regel, der Filter `MIT_TREND` aus `src/research_lab/workshop/self_improve.py`: **„Trades gegen TIMs Marktzustand auslassen“.** Ein Trade ist „gegen TIMs Marktzustand“, wenn `counter_trend(direction, market_state)` aus `src/dashboard/plan_journal.py` wahr ist, also LONG in `TREND_DOWN` oder SHORT in `TREND_UP`. Die Regel hat keine Parameter. Die Hypothese ist: Die Trades, die der Filter auslässt, bringen im Mittel netto weniger als null R.

Gegenargument: Muster aus wenigen, überlappenden Papier-Trades; die Abhilfe muss auf Archiv und frischen Daten bestehen. Dazu 0.2: Auf dem Archiv geht das nicht (Abschnitt 4). Deshalb prüft S21 nur auf frischen Trades.

## 3. Vorbelastung

- **Die Hypothese stammt aus denselben Trades.** Die Idee I-0003 hat die Trade-Reflexion am 03.11. aus `tim_plan_journal` erzeugt (8 von 20 Reflexionen mit der Lehre `AGAINST_TREND`). Diese Trades und alle anderen bis zum Einfrieren von 1.0 sind **In-Sample**. Sie werden in S21 nur beschreibend berichtet und dürfen nicht als Test dienen.
- **Gegenläufiger Befund vom 31.10.** (FORSCHUNGSBEREICH.md, F11): Im Rückblick auf 29 Trades brachten die Trades gegen den Trend zusammen **+2,50 R**. Der Filter hätte damals geschadet.
- **Rückblick am 11.11.** (nur lesend, `python -m src.research_lab.workshop learn` ohne `--write` auf Kopien der Journale vom 11.11. 01:19 Ortszeit, In-Sample):
  - 66 geschlossene, gezählte Trades in den sechs Journalen der Wochenrunde (`tim_plan_journal` 29, `_short` 23, `_mid` 13, `_struct` 1; `_long` und `_vp` 0), geplant vom 24.10. bis 10.11. an 15 UTC-Kalendertagen. 94 Trades geschlossen, davon 26 ausgeschlossen und 2 mit Datenlücke.
  - **Gruppe A (gegen den Marktzustand): 22 Trades an 9 Tagen, zusammen −0,32 R, Mittel −0,01 R je Trade**, Bootstrap-Band (95 %, einfacher Bootstrap ohne Cluster) −0,41 bis +0,43 R je Trade. Je Journal: `tim_plan_journal` 11 Trades +0,17 R, `_short` 7 Trades −1,20 R, `_mid` 4 Trades +0,71 R.
  - Gruppe B (übrige): 44 Trades, zusammen +7,30 R, Mittel +0,17 R je Trade.
  - Nach Richtung und Zustand: LONG in BALANCE 25, SHORT in BALANCE 19, LONG in TREND_DOWN 17, SHORT in TREND_UP 5. Gruppe A besteht also überwiegend aus LONG in TREND_DOWN.
  - Trade-Reflexionen (`data/research/trade_reflections.jsonl`): 68, davon 22 mit `AGAINST_TREND` (32 %). Je Journal: `tim_plan_journal` 30 (11, 37 %), `_short` 24 (7, 29 %), `_mid` 13 (4, 31 %), `_struct` 1 (0).
  - Das Mittel von A liegt nahe null, weit vom kleinsten Effekt −0,2 R (Abschnitt 6). Der Rückblick stützt die Hypothese nicht und widerlegt sie nicht.
- **F11 beobachtet denselben Filter.** Im Lernprotokoll `data/research/self_improve/log.jsonl` steht bis 11.11. für `MIT_TREND` kein Fenster (einziger Eintrag: `KOSTEN_DECKEL`, Fenster 1 vom 01.11. bis 01.12.). Weil der Rückblick jetzt im Minus ist (22 weggefallene Trades, −0,32 R), würde die nächste Wochenrunde ein 30-Tage-Fenster für `MIT_TREND` starten. Abgrenzung in Abschnitt 6.5.

## 4. Daten

- plan_journal (Papier-Plan-Journal), nur lesend.

`archive_spot_klines` ist gestrichen. Ein Regel-Backtest auf dem Archiv ist nicht machbar: TIMs Marktzustand (`market_state` aus der 30m-Analyse) steht nur zur Planzeit im Plan-Journal und wird im Archiv nicht gespeichert. Ihn für das Archiv nachzurechnen wäre eine andere Regel als die, die TIM beim Planen angewendet hat.

### 4.1 Quellen und Felder

- Journale: die sechs Journale der Wochenrunde (`JOURNALS` in `src/research_lab/workshop/schedule.py`): `tim_plan_journal` (30m, früher auch 15m), `tim_plan_journal_short` (15m), `tim_plan_journal_mid` (1h), `tim_plan_journal_long` (1d), `tim_plan_journal_struct`, `tim_plan_journal_vp`, jeweils `~/TIM-live/data/journal/<name>.json`, geladen mit `load_view`. Journale, die es nicht gibt oder deren Log gebrochen ist, zählen mit null Trades und werden im Bericht genannt. Perp- und Level-Journale gehören nicht dazu (wie F11).
- Gelesene Felder: `status`, `direction`, `market_state`, `net_r`, `created_at`, `closed_at`, `excluded`, `data_gap`.
- Zugriff nur lesend; Auswertung auf einer Kopie der Journale mit Zeitstempel und SHA-256 je Datei im Bericht.

## 5. Fälle, Gruppen und Vergleich

### 5.1 Fall

Ein Fall ist ein Trade mit `status = CLOSED`, nicht `excluded`, mit `net_r` und ohne `data_gap` (wie `self_improve.closed`), dessen `created_at` **nach** dem Commit-Zeitpunkt (UTC) des Einfrier-Commits von Version 1.0 liegt. Alle früheren Trades werden nur beschreibend berichtet (Rückblick, In-Sample, Abschnitt 3).

### 5.2 Gruppen

- **Gruppe A:** Fälle gegen TIMs Marktzustand (`counter_trend(direction, market_state)` wahr). Diese Trades würde der Filter auslassen.
- **Gruppe B:** alle übrigen Fälle.
- Der Filter wird nicht angepasst und hat keine Varianten.

### 5.3 Entclusterung

- Die Zeitrahmen überlappen: Am selben Tag planen mehrere Journale oft Trades aus derselben Marktbewegung. Cluster = **UTC-Kalendertag von `created_at`**.
- Cluster-Bootstrap: 10 000 Ziehungen, je Ziehung werden die Tage mit Zurücklegen gezogen (so viele wie Tage mit Fällen), alle Fälle eines gezogenen Tages kommen mit. Fester Seed **2121**, im Code vor dem Laden der Daten eingefroren. Ziehungen ohne Fall in Gruppe A werden neu gezogen; ihre Zahl wird berichtet.
- Mittel = Summe Netto-R / Zahl der Trades der Gruppe in der Ziehung (Mittel je Trade, nicht Mittel der Tagesmittel).

## 6. Messgröße und Entscheidung

- Messgröße: mittleres Netto-R je Trade in Gruppe A (was der Filter je ausgelassenem Trade gespart hätte) und die Differenz Mittel(B) − Mittel(A), beide in R nach Kosten (wie `net_r` im Journal)
- Kleinster Effekt: Mittel(A) ≤ −0,2 R je Trade
- Mindestzahl Fälle: 40 neue geschlossene Fälle, davon mindestens 10 in Gruppe A (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: genau eine Auswertung (6.2), keine Zwischenauswertung, kein Stopp nach p-Wert. Zeitgrenze 120 Tage ab Einfrieren; sind die Mindestzahlen bis dahin nicht erreicht, lautet das Ergebnis „nicht prüfbar“.

### 6.1 Zähllauf

Vor jeder Auswertung, auch wöchentlich, darf ein Zähllauf laufen. Er gibt nur Zahlen aus: Fälle gesamt, Fälle in A und B, Tage, offene Trades seit dem Einfrieren. Er zeigt **kein** R, kein Mittel und kein Vorzeichen.

### 6.2 Zeitpunkt der einen Auswertung

- Stichtag ist der erste Zähllauf, der die Mindestzahlen erreicht, spätestens Tag 120.
- Gezählt werden nur Trades, die bis zum Stichtag geplant wurden. Damit lang laufende Trades nicht wegfallen, wartet die Auswertung, bis diese Trades geschlossen sind, höchstens 7 Tage. Danach noch offene Trades fehlen; ihre Zahl je Gruppe wird berichtet. Fallen die Mindestzahlen dadurch unter die Grenze, lautet das Ergebnis „nicht prüfbar“.

### 6.3 Test

- Vergleich 1 (Hauptvergleich): Mittel(A) < 0. Einseitiges 95-%-Cluster-Bootstrap-Intervall (Obergrenze = 95-%-Quantil der Ziehungen) und p₁ = (1 + #{Mittel*(A) ≥ 0}) / (1 + 10 000).
- Vergleich 2: Mittel(B) − Mittel(A) > 0. In denselben Ziehungen, p₂ = (1 + #{Δ* ≤ 0}) / (1 + 10 000).
- Mehrfachtest: Holm über die beiden Vergleiche, m = 2, α = 5 %, eigene Familie (kein Holdout-Register).

### 6.4 Entscheidung

- **BESTANDEN** nur, wenn alles gilt: (1) Mindestzahlen erfüllt, (2) einseitiges 95-%-Intervall von Mittel(A) liegt ganz unter 0 und Vergleich 1 ist nach Holm signifikant, (3) Punktwert Mittel(A) ≤ −0,2 R.
- Vergleich 2 zählt für Holm und wird berichtet, ist aber keine Bedingung: Der Filter spart Geld, wenn A verliert, auch wenn B ebenfalls schwach ist.
- Dann heißt es „bereit für Uzis Entscheidung“. Die Regel in TIM ändert sich nur per PR nach Uzis Ja.
- Sonst **NICHT BESTANDEN**; bei verfehlten Mindestzahlen oder abgelaufener Zeitgrenze **nicht prüfbar**.
- S21 liefert keine Setup-Evidenz. Ein BESTANDEN sagt nur, dass das Auslassen dieser Trades das Papier-Ergebnis verbessert hätte.

### 6.5 Abgrenzung zu F11

F11 (`self_improve.py`) beobachtet `MIT_TREND` in 30-Tage-Fenstern mit Bonferroni über vier Filter, ab 20 neuen Trades und 5 weggefallenen. S21 ist die präregistrierte Prüfung **desselben** Filters mit festen Mindestzahlen (40/10), Tages-Clustern, kleinstem Effekt und genau einer Auswertung. F11 läuft unverändert weiter, S21 greift nicht in sein Lernprotokoll ein. Beide können dieselben Trades lesen; im Bericht stehen beide Urteile nebeneinander, und Uzi entscheidet.

### 6.6 Umsetzung (zum Einfrieren in 1.0)

- `src/research_lab/studies/s21.py` mit `count(journals, frozen_at)` (Zähllauf, nur Zahlen) und `evaluate(journals, frozen_at, cutoff)` (Abschnitte 5–6); Seed 2121, 10 000 Ziehungen, Mindestzahlen und Grenzen als Konstanten.
- Gruppe A über `self_improve.FILTERS["MIT_TREND"].drops`, Fälle über `self_improve.closed`. Es gibt keine eigene Kopie der Regel.
- Tests mit kleinen künstlichen Journalen: Zeitgrenze `created_at` nach dem Einfrieren, Ausschlüsse (`excluded`, `data_gap`, ohne `net_r`, offen), Gruppenzuordnung, Tages-Cluster, Zähllauf ohne R, feste Ziehungen bei festem Seed, Entscheidungsregeln.
- Nur lesender Journalzugriff, kein Schreiben unter `~/TIM-live`.

## 7. Bekannte Grenzen

- Die Studie betrachtet nur Papierhandel ohne Echtgeld.
- Gruppe A ist klein; bei etwa einem Drittel Anteil (Rückblick) braucht es rund 30 neue Trades für 10 in A. Bei der Rate vom 24.10.–10.11. (66 Trades in 18 Tagen) ist das in wenigen Wochen erreicht, aber die Rate kann sich ändern.
- Die Journale ändern sich (neue Zeitrahmen, Regeln, Ausschlüsse). Änderungen nach dem Einfrieren werden im Bericht genannt; der Filter bleibt gleich.
- `market_state` stammt aus der 30m-Analyse auch für 15m-, 1h- und 1d-Pläne; das ist TIMs Planungsweise und wird nicht geändert.
- Gruppe A besteht im Rückblick überwiegend aus LONG in TREND_DOWN; das Ergebnis kann vom Marktabschnitt abhängen (z. B. fallender Markt im Prüfzeitraum).
- Kein Archivtest; das Ergebnis gilt nur für den Prüfzeitraum.

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0003 |
| 2026-11-11 | 0.2 | Von Hand ergänzt: Register als Vorschlag außerhalb des Holdout-Registers (0 von 60, Uzis Entscheidung offen); Holdout wird nicht berührt; Archiv-Backtest gestrichen (Marktzustand nur im Plan-Journal), Daten nur Plan-Journale (4); genau eine Regel `MIT_TREND` ohne Parameter statt zweier bedeutungsloser Varianten (2, 5); Vorbelastung mit In-Sample-Herkunft, Befund 31.10. (+2,50 R) und Rückblick 11.11. (3); prospektive Methode mit Fall, Gruppen, Tages-Cluster-Bootstrap, Seed 2121, Mindestzahlen 40/10, Zeitgrenze 120 Tage, Holm m = 2 (5, 6); Messgröße und kleinster Effekt in R statt Prozentpunkten; Abgrenzung zu F11 (6.5); Umsetzungsplan (6.6). Spezifikations-Hash gilt nur für 0.1 |
