# R-KI-1: KI entscheidet an starken Zonen (Papier) – Präregistrierung, Entwurf 0.1

Stand 23.11.2026. Auslöser: Uzi 23.11.2026 ("wenn viele Sachen übereinander lappen muss gewichtet werden …
TIM muss verstehen und nicht einzelne Regeln testen, wir haben ja theoretisch die KI"; danach "go KI").
Nur Papier, nur vorwärts (live). Kein Echtgeld, der Live-Trader liest das Protokoll nicht. Kein Holdout.

## Frage

Trifft die lokale KI (Ollama, `qwen3.5:9b`, wie KI1), die an einer starken Zone das ganze Bild sieht, nach
Kosten bessere Papier-Entscheidungen als die festen Kreis-Regeln R-ABS-2 0.6 (mit Zone / ohne Zone)?

## Ablauf (Code `src/research_lab/ki_entry/`)

1. **Zonen-Stärke** (`zones.py`, fest, nicht angepasst): jede aktuelle Chart-Marke im Umkreis von 4 % bekommt
   ein Gewicht: Gamma-Zone mit Orderbuch-Mauer 4; Call/Put Wall 3; OI-Wand und Gamma-Flip 2; Max Pain und
   erwartete Spanne 1; Jahr/Quartal/Monat 3; Woche 2; naked POC 2; Tag 1,5; Liquidations-Cluster 1,5;
   Strong/Weak High/Low 1,5; laufender POC, Session, IB, VWAP je 1; meistgehandelter Preis der letzten
   48 Footprint-Kerzen 2. Marken innerhalb 0,4 % bilden eine Zone. Früheres Abprallen (Docht in die Zone,
   Schluss zurück; letzte 96 Kerzen) +0,5 je Mal, höchstens +1,5. **Stark ab 6.**
2. **Auslöser**: die neueste geschlossene 15m-Perp-Kerze berührt eine starke Zone; kein Papier-Trade offen;
   dieselbe Zone (auf 100 USD gerundet) nicht in den letzten 6 Stunden gefragt; jede Kerze höchstens einmal.
3. **KI-Entscheidung**: die KI sieht Zone (Marken, Stärke, Annäherung von oben/unten, frühere Abpraller),
   die nächsten Zonen darüber/darunter, die letzten 12 Kerzen mit Delta und Volumen, große Orders ≥50 BTC
   der letzten 3 Stunden, Trend (4 h, 24 h, 3 Tage, letzter Strukturbruch), Funding, OI-Änderung 24 h.
   Antwort LONG/SHORT/NICHTS mit Einstieg, Stop, Ziel, Vertrauen, Grund.
4. **Prüfung**: Einstieg ≤0,5 % vom Preis, Stop 0,15–3 %, Stop und Ziel auf der richtigen Seite, Ziel ≥1,5× Stop.
   Sonst UNGUELTIG (wird geschrieben, nie gehandelt).
5. **Papier**: Limit-Einstieg binnen 4 Kerzen (1 h), sonst "nicht gefüllt". Berührt eine Kerze Stop und Ziel,
   zählt der Stop; in der Füll-Kerze zählt nur der Stop. Spätestens nach 24 h Schluss zum Kerzenschluss.
   Kosten 0,10 % vom Einstieg (Bitunix, Maker rein, Taker raus, Spread/Schlupf), in R abgezogen.
6. **Protokoll**: append-only mit Hash-Kette und Kopf-Datei (wie KI1). Entscheidung wird geschrieben, bevor das
   Ergebnis bekannt ist; das Ergebnis kommt als eigener Eintrag. Ein Fehler der KI schreibt nichts.

## Urteil (Entwurf, wird vor dem ersten Urteil eingefroren)

- Frühestens ab **30 gefüllten Papier-Trades**.
- Bestanden, wenn Mittel netto ≥ +0,10 R und die untere Grenze des 90-%-Bootstrap-Intervalls > 0.
- Vergleich mit R-ABS-2 0.6 (mit Zone, ohne Zone) im selben Zeitraum; drei Läufe = Mehrfachtest, so berichtet.
- NICHTS und UNGUELTIG werden mitgezählt und berichtet (wie oft die KI auslässt).

## Grenzen

- Ein kleines lokales Modell, Temperatur 0. Seine Antworten können schwanken, wenn sich Ollama oder das Modell
  ändern; Modellname steht in jedem Eintrag.
- Zonen-Gewichte sind eine Setzung vor jedem Ergebnis, kein Optimum. Änderungen nur als neue Version mit neuem PR.
- 15m-Kerzen: innerhalb einer Kerze ist die Reihenfolge von Stop und Ziel unbekannt, daher Stop zuerst (vorsichtig).
- Das Chart-Modell zeigt die Marken von jetzt; der Auslöser nutzt nur die neueste geschlossene Kerze, also nichts aus
  der Zukunft.

## Betrieb

Mac-Agent `com.tim.ki-entry` (Vorlage `ops/launchd/com.tim.ki-entry.plist`, alle 5 Minuten), Protokoll
`~/Library/Application Support/TIM/ki-entry/ki_entry_decisions.jsonl`. Auswertung:
`python -m src.research_lab.ki_entry report`. Einrichten erst auf Uzis "einrichten".
