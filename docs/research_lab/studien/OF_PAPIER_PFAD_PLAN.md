# Plan: OF-Papier-Pfad am Mac (10.11.2026)

## Ziel
Die Orderflow-Engine (OF2 mit Orderflow-Tor) läuft auf Live-Daten mit, ohne Geld. Man sieht täglich: welche Signale,
welche Papier-Trades, der Signaltrichter. Das ist der letzte Beweis-Schritt für einen PS5-Kandidaten und macht die
Engine schon jetzt sichtbar.

## Erfolgskriterium
- Jeden Tag kurz nach 01:00 Ortszeit liegt der Vortag vor: Signale, Trades, Trichter.
- Gleicher Code wie im Backtest (kein zweiter Rechenweg): Nachrechnen eines Tages gibt dieselben Trades.
- Eine Karte auf /forschung zeigt Trades, Netto-R und Trichter seit Start.

## Wie
1. **Tageslauf (Stufe A, klein):** Binance veröffentlicht die Trades des Vortags als Archiv. Ein Job am Mac holt den
   Vortag in einen eigenen Papier-Store (getrennt vom Forschungs-Store, 2025 bleibt dort gesperrt) und lässt die
   Engine darüber laufen. Signale werden also mit bis zu einem Tag Verzögerung sichtbar. Für ein Papier-Journal reicht das.
2. **Welche Einstellung:** Start mit der OFX-Grundeinstellung (OF2 1.0 + Orderflow-Tor). Besteht ein PS5-Kandidat die
   Prüfung, läuft er zusätzlich als zweite Spur. Einstellungen werden beim Start eingefroren.
3. **Anzeige:** Karte auf /forschung (wie S7b-Journal) + JSON.
4. **Stufe B (später, eigenes Go):** echte Live-Signale in der Minute über den vorhandenen Live-Orderflow-Tracker
   (Kraken/Binance-Stream). Größerer Umbau; erst sinnvoll, wenn Stufe A zeigt, dass es sich lohnt.

## Nicht-Ziele
Kein Echtgeld, keine Orders, kein Eingriff in Live-Trader, Plan-Journal oder Kraken-Test. Keine neuen Coins.

## Pakete
| Paket | Inhalt | Prüfung |
|---|---|---|
| A1 | `src/research_lab/forward/of_paper.py`: Vortag holen, Engine fortsetzen (Zustand über Tage), Journal schreiben | Test: 3 Tage einzeln = 3 Tage am Stück |
| A2 | Schritt in der Forschungswerkstatt (täglich), Karte /forschung | Karte zeigt Probetag |
| A3 | Start am Mac, erster echter Tag | Journal-Datei mit Vortag vorhanden |

## Risiken
- Wenige Trades (1–2 pro Woche): 100 Trades dauern rund ein Jahr.
- Binance-Archiv kommt manchmal verspätet oder defekt (ein Tag 2026 war defekt): Tag wird nachgeholt, Lücke vermerkt.
- Spot-Daten, Kosten nach Bitunix gerechnet: Papier-Ergebnis ist eine Näherung.
