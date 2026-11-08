# S18: Kronos-Pfadfächer für BTC: Trifft die 24-Stunden-Spanne so oft, wie sie verspricht, und schlägt sie einfache Bänder? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S18 (nächste freie Nummer nach S17, 08.11.2026; vorläufig, falls ein offener PR S18 schon belegt) |
| Version | **0.1, Entwurf.** Nichts installiert, nichts gerechnet, keine Kronos-Prognose gesehen |
| Anlass | Uzi 08.11.2026 („go“ auf den Vorschlag zum Reel DfcZrH2ijOS von @mykryptotime, Thread „Instagram-Reel für TIM prüfen“) |
| Quelle | Kronos, Foundation Model für Kurskerzen: Paper arXiv 2508.02739 (02.08.2025), Code `github.com/shiyu-coder/Kronos` (MIT), Gewichte `NeoQuasar/Kronos-small` auf Hugging Face |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nicht geladen. Die Hauptprüfung läuft **vorwärts** auf Kerzen ab dem Einfrieren (Abschnitt 3) |
| Einordnung (Vorschlag) | **Prognosestudie ohne Registerplatz** wie S15: keine Trades, kein Handelssignal, nur die Güte einer Spannen-Prognose. Entscheidet Uzi vor 1.0 |

## 1. Fragestellung

Kronos erzeugt aus den letzten Kurskerzen viele mögliche Verläufe (Pfade) für die nächsten Stunden. Das Reel zeigt 100 Pfade für BTC über 24 Stunden.

1. **Kalibrierung:** Landet der echte BTC-Schlusskurs nach 24 Stunden so oft in der 80-%- bzw. 95-%-Spanne der Pfade, wie es die Spanne verspricht?
2. **Güte gegen einfache Bänder:** Ist die Kronos-Verteilung für den 24-Stunden-Schlusskurs besser (CRPS, Abschnitt 5) als ein Band aus EWMA-Schwankung und als die einfache historische Simulation?

Nutzen für TIM: Ein gut kalibrierter Fächer könnte Stop-Abstände, Ziele und Positionsgrößen stützen (Risikoschicht, wie GARCH-4h aus S15). S18 prüft **keinen** Richtungs- oder Gewinn-Edge.

## 2. Vorbelastung und das Hauptproblem

- **Gesehen:** nur die Bildunterschrift des Reels (Werbung für ein Dashboard, im gezeigten Test lag der Kurs einmal außerhalb der Spanne), die Kurzfassung des Papers und die README des Repos. Keine Kronos-Ausgabe, keine Auswertung.
- **Trainingsdaten-Leck:** Kronos wurde auf über 12 Mrd. Kerzen von 45 Börsen vortrainiert. Weder Paper-Kurzfassung noch README nennen ein Enddatum der Trainingsdaten (geprüft 08.11.2026). Das Paper erschien im August 2025, also hat das Modell **sehr wahrscheinlich BTC-Kerzen aus 2020 bis mindestens Anfang 2025 gesehen**. Ein Rücktest auf 2023–2024 (unsere Validierung) wäre damit kein sauberer Test, weil das Modell diese Zeit auswendig kennen kann.
- **Folge für das Design:** Die Hauptprüfung ist **vorwärts gerichtet** auf Kerzen, die es beim Einfrieren noch nicht gab. Der Rücktest 2023–2024 ist nur ein Technik- und Plausibilitätslauf, ausdrücklich ohne Urteil.
- Was TIM schon hat: GARCH-4h aus S15 (feste Parameter, Papier-Journal), EWMA als Vergleich, 1h-Kerzen in der Marktdatenbank. Eine Kronos-Anbindung gibt es nicht (Suche nach „kronos“ im Repo ohne Treffer, 08.11.2026).

## 3. Daten

- **Instrument:** BTCUSDT USD-M Perpetual, 1h-Kerzen (OHLCV), Quelle Binance (`/fapi/v1/klines`, wie S12), UTC. ETHUSDT und SOLUSDT laufen beschreibend mit, ohne Urteil.
- **Hauptprüfung (vorwärts):** Prognosezeitpunkte ab dem ersten vollen UTC-Tag nach dem Einfrieren von 1.0, alle 4 Stunden (00, 04, …, 20 UTC), jeweils nur mit vor diesem Zeitpunkt geschlossenen Kerzen. Laufzeit mindestens 90 Tage und bis das Gate in 5.1 erreicht ist, höchstens 180 Tage.
- **Technik-Lauf (rückwärts, ohne Urteil):** 2024-10-01 bis 2024-12-31, gleiche Taktung. Dient nur dazu, Laufzeit, Speicher und Formate zu prüfen. Ergebnisse werden berichtet, aber mit dem Vermerk „vermutlich im Training gesehen“.
- Eine Prognose zählt nur, wenn die 512 Vorlauf-Kerzen und die 24 Ziel-Kerzen lückenlos vorhanden sind. Ausgefallene Prognosen werden gezählt und berichtet, nicht nachgeholt.

## 4. Modelle (vorab festgelegt, nicht optimiert)

| Modell | Regel | Rolle |
|---|---|---|
| **K Kronos-small** | 24,7 Mio. Parameter, Kontext 512 Stundenkerzen (gut 21 Tage), Eingabe open/high/low/close/volume. 100 Pfade über 24 Stunden mit Temperatur T = 1,0 und top_p = 0,9 (Werte aus der README), feste Startwerte (Seeds 0 bis 99) | geprüftes Modell |
| **B1 EWMA-Normalband** | σ²_t = 0,94 · σ²_{t−1} + 0,06 · r²_{t−1} auf 1h-Log-Renditen, 24-Stunden-Verteilung Normal mit Mittel 0 und Varianz 24 · σ² | Hauptvergleich |
| **B2 Historische Simulation** | Verteilung der 24-Stunden-Log-Renditen der letzten 30 Tage (alle 4 Stunden, 180 Werte), auf den aktuellen Kurs gelegt | Vergleich |

Festgelegt:

1. Gewichte und Code werden auf einen festen Stand gepinnt (Git-Commit des Repos, Hugging-Face-Revision der Gewichte, SHA-256 der Dateien) und im Einfrier-Commit eingetragen. Kein Update während der Studie.
2. Kronos-mini und -base werden nicht ausgewertet (kein Modell-Shopping). Wenn Kronos-small auf dem Mac zu langsam ist (mehr als 10 Minuten je Prognose mit 100 Pfaden), wird das vor 1.0 entschieden, nicht danach.
3. Die README beschreibt `sample_count` als „generate and average“. Für S18 braucht es die **einzelnen Pfade**. Vor 1.0 wird geprüft, ob die Pfade einzeln abgreifbar sind; sonst 100 Aufrufe mit `sample_count = 1` und je eigenem Seed.
4. Gewertet wird der Schlusskurs nach genau 24 Stunden. Die Pfade selbst (Hoch/Tief unterwegs) sind beschreibend.

## 5. Erfolgskriterien

**CRPS** (Continuous Ranked Probability Score) misst, wie gut eine ganze Verteilung den echten Wert trifft; kleiner ist besser. Für K und B2 aus den Stichproben (Energieform), für B1 in geschlossener Form. Alles auf der 24-Stunden-Log-Rendite in Prozent.

d je Prognose = CRPS(B1) − CRPS(K), d > 0 heißt Kronos ist besser. Test: Diebold-Mariano mit Newey-West-Varianz. Weil sich die 24-Stunden-Fenster alle 4 Stunden überlappen, ist der Lag mindestens 6, sonst ⌊4 · (n/100)^(2/9)⌋, je nachdem was größer ist. p einseitig aus der Normalverteilung.

Kronos **besteht** nur, wenn alle Punkte erfüllt sind (nur Vorwärts-Teil, nur BTC):

| # | Kriterium |
|---|---|
| 1 | ≥ 500 gewertete Prognosen (gut 83 Tage bei 6 je Tag) |
| 2 | Ø d > 0 gegen B1, p < 0,05 |
| 3 | Ø CRPS(K) < Ø CRPS(B2) (nur Richtung, ohne p-Schwelle) |
| 4 | Kalibrierung: Trefferquote der 80-%-Spanne zwischen 72 % und 88 %, der 95-%-Spanne zwischen 90 % und 99 % |
| 5 | Ø d > 0 in jeder der beiden Hälften der Laufzeit (Stabilität) |

Fällt Kriterium 4 durch, heißt das Urteil „nicht kalibriert“, auch wenn CRPS besser ist. Ein Fächer, der zu eng ist, darf in TIM keine Stops setzen.

### 5.1 Machbarkeits-Gate (vor jedem Ergebnis)

Ergebnisblinder Zähllauf: nur die Zahl gewerteter und ausgefallener Prognosen, keine Spanne, kein CRPS. Ausgewertet wird erst ab 500 gewerteten BTC-Prognosen. Das Gate wird nicht gelockert. Zwischenstände der Fehlermaße werden vorher nicht angesehen (kein vorzeitiges Abbrechen bei gutem Lauf).

### 5.2 Beschreibend, ohne Urteil

- Trefferquote der 50-, 80- und 95-%-Spanne je Stunde 1 bis 24 (Kalibrierkurve), für K, B1, B2.
- Breite der 80-%-Spanne in Prozent im Vergleich, Anteil der Pfade in Kursrichtung (nur zur Einordnung, nicht als Signal).
- Gleiches für ETH und SOL, und der Technik-Lauf 2024-Q4 mit Leck-Vermerk.
- Laufzeit je Prognose auf dem Mac.

## 6. Sicherheit und Betrieb

- Fremdcode und fremde Gewichte gelten als nicht vertrauenswürdig, bis geprüft (CLAUDE.md). Vor 1.0: Quelltext des gepinnten Commits lesen (besonders Laden der Gewichte, keine Netzaufrufe beim Vorhersagen), Gewichte nur als `safetensors` laden, eigene virtuelle Umgebung außerhalb von `~/TIM-live`.
- Läuft auf dem Mac als eigener Hintergrundjob mit nur lesendem Zugriff auf Kerzen. Kein Zugriff auf Kraken, Keys oder den Live-Trader. Prognosen werden mit Zeitstempel **vor** dem Zielzeitpunkt in eine eigene Datei geschrieben (Append-only), damit nachträgliches Schönen ausgeschlossen ist.
- Installation und Hintergrundjob sind ein eigener Schritt und brauchen Uzis „einrichten“.

## 7. Was danach käme (nicht Teil von S18)

Ein bestandenes S18 ändert nichts automatisch. Ob TIM den Fächer für Stops, Ziele oder Größen nutzt, ist ein eigener Schritt mit eigener Freigabe, zuerst im Papier-Journal und im Vergleich mit GARCH-4h aus S15.

## 8. Offene Punkte vor Version 1.0

1. Einordnung als Prognosestudie ohne Registerplatz (Uzi).
2. Code- und Gewichteprüfung nach Abschnitt 6, Commit und Revision pinnen.
3. Einzelpfade abgreifbar? (4.3) und Laufzeit auf dem Mac (4.2), im Technik-Lauf ohne Blick auf CRPS.
4. Auswertecode mit Tests auf synthetischen Daten (CRPS-Formeln, DM-Test, Kalibrierung), dann einfrieren.

## Änderungsprotokoll

- 0.1 (08.11.2026): Entwurf auf Uzis „go“. Nichts installiert, keine Kurse ausgewertet, keine Kronos-Ausgabe gesehen.
