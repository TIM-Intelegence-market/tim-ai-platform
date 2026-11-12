# Journal-Prüfung 1 – Score, Grade, GARCH, Funding/Broncx, Sichern, Kosten (12.11.2026)

Ich habe nur gelesen. Daten: `~/TIM-live/data/journal/tim_plan_journal*.json`, Stand 12.11. gegen 12:15 UTC. Die Skripte liegen im Scratchpad (`journal_audit.py`). Die Ergebnisse sind **nur Hinweise**: 4 Kalenderwochen, Papier, wenige Fälle.

## Regeln (vorher festgelegt)
- **Einheit:** ein geschlossener Plan (CLOSED) aus allen Plan-Journalen. Die 27 Ausschlüsse aus `plan_journal_corrections.json` sind herausgenommen.
- **Ergebnis:** `net_r`, also nach Gebühr und Slippage laut Protokoll 1.1.
- **Unsicherheit:** Bootstrap über Kalenderwochen (ISO-Woche der Planerstellung), 5000 Ziehungen, Seed 20261112, 90-%-Intervall.
- **Abweichung vom Plan, offen benannt:**
  - Der Median-Split beim Score ging nicht, weil der Score nicht streut (siehe A). Deshalb steht dort nur die Verteilung.
  - Die Empfindlichkeitsrechnung ohne das Level-Journal habe ich nachträglich ergänzt. Sie ist nur ein Hinweis.

## Basis
- **Bestand:** 84 geschlossene Pläne in 4 Wochen.

  | Journal | Pläne |
  |---|---|
  | Haupt (30m) | 32 |
  | 15m | 25 |
  | 1h | 14 |
  | level | 8 |
  | perp_short | 3 |
  | perp_mid | 1 |
  | struct | 1 |

- **Gesamt:** −9,32 R, im Mittel −0,111 R je Plan (KI90 −0,36 bis +0,12).
- **Ohne das Level-Journal** (8 Pläne, −17,71 R, entstanden vor der Kostenprüfung): 76 Pläne, +8,39 R, Mittel +0,110 R (KI90 −0,10 bis +0,18). Das ist nicht von null unterscheidbar.

## A Score gegen Ergebnis: nicht prüfbar
- **Der Score streut nicht.** 60 Pläne haben 0,2363, 16 Pläne (15m) 0,2295, die 8 Level-Pläne haben keinen Score.
- Alle Pläne liegen im untersten Bucket (< 0,4). Die Zuordnung „höherer Score = bessere Trefferquote“ (`SCORE_BUCKETS`) kann darum nie greifen.
- **Funding-Zuschlag (±0,03) und Broncx-Zuschlag (±0,08):**
  - Sie sind im Journal nicht als eigene Felder gespeichert.
  - Da der Score praktisch konstant ist, haben sie in diesen 76 Plänen offenbar **nie** gewirkt. Im Prüfzeitraum hatten sie also keinen Einfluss auf Plan-Ergebnisse.
  - Gegen das Ergebnis prüfen lassen sie sich so nicht.
- **Vorschlag (braucht Uzis Wort, Codeänderung):** Die Bestandteile des Scores künftig je Plan mitschreiben (Basis, Marktzustand, Funding, Broncx, Belege).

## B Grade gegen Ergebnis: nicht prüfbar
- **Alle 76 benoteten Pläne sind Grade C** (Mittel +0,110 R). In 151 von 160 Plänen lauten die grade_reasons nur „scenario_proposed“ und „no_conflicting_evidence“: Kein Szenario war je CONFIRMED.
- Die Note trennt also nichts. Das deckt sich mit dem Wochenbericht W45 („Grade C auslassen würde fast alle streichen“).

## C GARCH-Gewicht: Hinweis positiv, aber unsicher
- **Bestand:** 29 Pläne mit `vol_4h.weight` aus 2 Wochen. Gewichte 0,58–1,32, Mittel 0,92.
- **Ergebnis:**

  | Rechnung | Netto |
  |---|---|
  | pur | +5,76 R |
  | gewichtet | +7,08 R |
  | gewichtet, auf gleiches Gesamtrisiko normiert | +7,66 R |

- **Unterschied:** +1,91 R, KI90 −0,51 bis +4,67. Das Intervall schließt null ein.
- **Gegenbeleg:** S25 (S7b auf Historie) ist nicht bestanden. Die Gewichtung hat dort den Drawdown nicht gesenkt.
- **Fazit:** offen. Mit 29 Plänen aus 2 Wochen ist keine Aussage möglich.

## D Sichern und Nachziehen (beschreibend, ohne Gegenrechnung)

| Ausstieg | n | Mittel R | Summe R |
|---|---|---|---|
| STOP | 24 | −1,66 | −39,82 |
| TRAIL_STOP | 23 | +0,84 | +19,33 |
| COST_STOP | 15 | 0,00 | 0,00 |
| INVALIDATION | 9 | −0,54 | −4,88 |
| TP3 | 6 | +2,02 | +12,13 |
| BREAK_EVEN_COSTS | 4 | +1,12 | +4,49 |
| TIMEOUT | 2 | −0,45 | −0,90 |
| BREAK_EVEN | 1 | +0,33 | +0,33 |

- **Kostenstopp:** Bei 46 Plänen wurde ein Kostenstopp gesetzt (21 Break-even + Kosten, 25 Swing).
- **COST_STOP-Ausstiege:** Die 15 Pläne endeten bei exakt 0 R. Vorher waren sie im Mittel +0,74 R im Plus, höchstens +1,02 R.
- **TIM-Urteil SICHERN:**
  - Häufigste Gründe: Sicherheitsnetz `fallback_mfe_0.75r` (29) und `fallback_4h_in_trade` (12).
  - Strukturgründe sind seltener: 16-mal Bestätigung, 3-mal dagegen.
- **Fazit:** Ob Sichern unterm Strich hilft, lässt sich nur mit einer Gegenrechnung auf den Kursverläufen sagen (was wäre ohne Sichern passiert). Das ist der nächste Schritt (Replay, lesend). Auffällig ist, dass die meisten SICHERN-Urteile aus der Zeit-/MFE-Notbremse kommen, nicht aus Struktur.

## E Kostengrenze

| Kosten je Plan | n | netto Mittel | brutto Mittel | Summe netto |
|---|---|---|---|---|
| 0,10–0,15 R | 25 | +0,123 | +0,246 | +3,08 |
| 0,15–0,25 R | 50 | +0,150 | +0,325 | +7,51 |
| > 0,25 R | 9 (8 davon Level-Journal) | −2,213 | −0,587 | −19,91 |

- **Vergleich über/unter 0,15 R:**
  - Mit allen Plänen: Pläne über 0,15 R schneiden um −0,333 R schlechter ab (KI90 −0,89 bis +0,23).
  - Ohne das Level-Journal liegt der Unterschied bei −0,019 R (KI90 −0,62 bis +0,26).
  - Die 0,15-R-Grenze zeigt hier also **keinen** Vorteil. Der Unterschied kommt fast ganz aus den alten Level-Plänen.
- **Kosten gesamt:** 26,41 R Kosten bei +17,08 R brutto. Die Kosten fressen mehr als den gesamten Bruttogewinn.

## Was daraus folgt (Hinweise, keine Entscheidungen)
1. **Score und Grade** sind im Live-Betrieb Konstanten. Jede Regel, die daran hängt (Buckets, Grade-Filter, Funding/Broncx-Zuschlag), ist praktisch wirkungslos. Testen lässt sie sich nur, wenn die Bestandteile mitgeschrieben werden oder Szenarien tatsächlich CONFIRMED werden.
2. **Kosten** sind der größte einzelne Posten: 26,4 R Kosten gegen 17,1 R brutto.
3. **Level-Journal (level/1):** 8 Pläne, −17,7 R, alle über 0,25 R Kosten. Danach kamen keine Pläne mehr, vermutlich weil die Kostenprüfung sie seitdem ausfiltert.
4. **Sichern:** Gegenrechnung auf den Kursverläufen als nächsten Lesetest vorschlagen.
5. **GARCH-Gewicht:** weiter beobachten. Im Moment spricht nichts dafür, es anzunehmen.
