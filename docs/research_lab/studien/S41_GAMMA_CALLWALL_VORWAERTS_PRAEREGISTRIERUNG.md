# S41: Call-Wall als Widerstand, Vorwärtsbeobachtung

Version **1.0, eingefroren** am 24.11.2026 auf Uzis Wort "einfrieren". Code: `src/research_lab/forward/gamma_callwall.py`
(`FROZEN = True`). Nur Papier und nur lesend. Kein Handel, keine Order, kein Echtgeld.

## Hintergrund (Erkundung, kein Beleg)

Die Auswertung der Gexbot-Videos (21.–24.11.) prüfte TIMs Gamma-Level mit einer Halte-oder-Bruch-Regel gegen
Vergleichslinien im 0,7- und 1,3-fachen Abstand:

- Tardis-Monatstage 2020–2024 und 2026: insgesamt kein Vorteil (65 % gegen 75 %).
- TIMs eigenes Log 04.–24.11.2026 im 4-Stunden-Takt: **Call-Wall 17/18 gehalten, Kontrollen 12/27**. Diese Stände
  überlappen und stammen alle aus einer Fallphase (78k → 61k). Die Hypothese ist also an diesen Daten entstanden.
  Sie gelten deshalb nicht als Beleg, und keiner dieser Stände wird hier mitgezählt.

## Hypothese

H1: Die Call-Wall (Strike mit dem größten Call-OI über dem Kurs, Feld `call_wall`) hält den BTC-Kurs bei Berührung
öfter als Vergleichslinien im gleichen Stand und auf der gleichen Seite.

## Daten

- Gamma-Level: `data/options/gamma_levels.jsonl` (TIM, alle 5 Minuten, Deribit, eigene Rechnung).
- Kurs: Binance BTCUSDT, 1h-Kerzen, nur geschlossene.
- Zeitraum: ab **25.11.2026 00:00 UTC** (`START`). Ältere Stände werden nie gelesen. Holdout 2025 nicht berührt.

## Regel (eingefroren)

1. Stichprobe: erster Log-Eintrag je 4-Stunden-Block (00, 04, …, 20 UTC).
2. Nur Stände mit `call_wall` 0,3 % bis 10 % über `spot`.
3. Bewertung ab der nächsten vollen Stunde. **Berührung:** Hoch ≥ Wand − 0,1 % innerhalb von 168 h.
   Danach, innerhalb von 48 h und ab der Berührungskerze:
   - **hält:** Das Tief fällt zuerst 1,5 % unter die Wand.
   - **bricht:** Eine Kerze schließt zuerst 1 % über der Wand.
   - sonst **offen**. Ohne Berührung: **unberührt**.
4. **Ereignis:** Paar aus Wandpreis und Berührungskerze. Mehrere Stände mit derselben Wand und derselben Berührung
   zählen einmal.
5. **Kontrolle:** Linien bei 0,7× und 1,3× Abstand. Gleiche Regel, gleiche Entdoppelung.
6. Noch nicht entschiedene Fälle ("pending") zählen erst, wenn ihr Fenster abgelaufen ist.

## Urteil

- Erst ab **30 entschiedenen Ereignissen** (hält plus bricht), sonst `ZU_WENIG_DATEN`.
- **BESTANDEN**, wenn beides gilt:
  - Haltequote echt minus Haltequote Kontrolle ≥ 15 Prozentpunkte.
  - Die untere 95-%-Wilson-Grenze der echten Haltequote liegt über 50 %.
- Sonst **NICHT_BESTANDEN**. Sind nach 120 Tagen keine 30 Ereignisse erreicht: `NICHT_BESTANDEN_ZEIT`.
- Einmal ausgewertet wird, sobald die Schwelle erreicht ist. Kein Nachschärfen. Eine Änderung bedeutet Version 2.0
  mit neuem Start.
- Mehrfachtest: Dies ist ein zusätzlicher Versuch. Er wird in der Versuchszahl der Deflated-Sharpe-Rechnung
  mitgezählt.

## Was ein Bestehen bedeutet

Nur, dass die Call-Wall als **Ziel oder Widerstand** taugt, etwa als Ziel für Longs oder als Warnung vor Longs
direkt darunter. Ein Einstiegssignal oder eine Handelsfreigabe ergibt sich daraus nicht. Jede Nutzung im Handel
braucht eine eigene Studie mit Kosten.

## Abfrage

`python -m src.research_lab.forward.gamma_callwall --log data/options/gamma_levels.jsonl` (am Mac, liest nur).
