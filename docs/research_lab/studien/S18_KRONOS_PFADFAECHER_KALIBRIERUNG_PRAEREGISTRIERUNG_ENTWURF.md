# S18: Kronos-Pfadfächer für BTC: Trifft die 24-Stunden-Spanne so oft, wie sie verspricht, und schlägt sie einfache Bänder? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S18 (nächste freie Nummer nach S17, 08.11.2026; vorläufig, falls ein offener PR S18 schon belegt) |
| Version | **1.0, eingefroren mit dem Merge am 08.11.2026 (Uzi „merge“, 13:56 Uhr).** Vorher 0.2: Regeln als Code (`src/research_lab/studies/s18.py`, Skript `scripts/research_lab_s18.py`, Tests `tests/test_research_lab_s18.py`). Kronos am Mac eingerichtet, ein Technik-Probelauf ohne Bewertung (Abschnitt 9). Wird mit dem Merge auf Uzis Wort zu 1.0 eingefroren |
| Anlass | Uzi 08.11.2026 („go“ auf den Vorschlag zum Reel DfcZrH2ijOS von @mykryptotime, Thread „Instagram-Reel für TIM prüfen“) |
| Quelle | Kronos, Foundation Model für Kurskerzen: Paper arXiv 2508.02739 (02.08.2025), Code `github.com/shiyu-coder/Kronos` (MIT), Gewichte `NeoQuasar/Kronos-small` auf Hugging Face |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, kein Archiv wird geladen. S18 ist eine **prospektive** Familie wie S12 und KI1: nur Kerzen ab 32 Tage vor dem ersten Prognosezeitpunkt, vom Skript erzwungen (Abschnitt 3) |
| Einordnung | **Prognosestudie ohne Registerplatz** wie S15 (Uzi per Karte 08.11.2026, 13:56 Uhr): keine Trades, kein Handelssignal, nur die Güte einer Spannen-Prognose. Register bleibt unverändert |

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
- **Hauptprüfung (vorwärts):** Prognosezeitpunkte ab dem ersten vollen UTC-Tag nach dem Einfrieren von 1.0, festgelegt auf **2026-11-10 00:00 UTC** (`FORWARD_START_MS`; liegt der Merge später, wird der Wert vor dem Merge verschoben), alle 4 Stunden (00, 04, …, 20 UTC), jeweils nur mit vor diesem Zeitpunkt geschlossenen Kerzen. Laufzeit mindestens 90 Tage und bis das Gate in 5.1 erreicht ist, höchstens 180 Tage.
- **Technik-Lauf (ohne Urteil):** ein Probelauf am 08.11.2026 auf 512 Kerzen bis 2024-10-01 (Validierungszeit) nur für Laufzeit und Format, ohne Ziel-Kurs, CRPS oder Trefferquote (Abschnitt 9). Ein größerer Rücktest auf 2024-Q4 entfällt, weil er wegen des Trainings-Lecks nichts aussagt.
- Eine Prognose zählt nur, wenn die 745 Vorlauf-Kerzen (512 für Kronos, 31 Tage für B1/B2) und die 24 Ziel-Kerzen lückenlos vorhanden sind, sie höchstens 2 Stunden nach t0 geschrieben wurde und Commit und Prüfsummen zu den Pins passen. Der Schlusskurs bei t0 im Protokoll muss zu den Kerzen der Auswertung passen. Ausgefallene Prognosen werden gezählt und berichtet, nicht nachgeholt.
- Das Prognose-Protokoll enthält nur die Kronos-Pfade. Zielwert und beide Vergleichsbänder rechnet erst die Auswertung aus Kerzen, die vor t0 geschlossen waren (B1, B2) bzw. bei t0 + 24 h (Ziel).

## 4. Modelle (vorab festgelegt, nicht optimiert)

| Modell | Regel | Rolle |
|---|---|---|
| **K Kronos-small** | 24,7 Mio. Parameter, Kontext 512 Stundenkerzen (gut 21 Tage), Eingabe open/high/low/close/volume/Quote-Volumen. 100 Pfade über 24 Stunden mit Temperatur T = 1,0, top_p = 0,9, top_k aus (Werte aus der README), als ein Batch aus 100 Kopien mit `sample_count = 1`, `torch.manual_seed(0)` je Prognose, Gerät M1-GPU (`mps`) | geprüftes Modell |
| **B1 EWMA-Normalband** | σ²_t = 0,94 · σ²_{t−1} + 0,06 · r²_{t−1} auf den 744 1h-Log-Renditen vor t0, Start mit dem Mittel von r² der ersten 14 Tage; 24-Stunden-Verteilung Normal mit Mittel 0 und Varianz 24 · σ² | Hauptvergleich |
| **B2 Historische Simulation** | Verteilung der 24-Stunden-Log-Renditen der letzten 30 Tage (alle 4 Stunden, 180 Werte), auf den aktuellen Kurs gelegt | Vergleich |

Festgelegt:

1. Gewichte und Code sind gepinnt und werden bei jeder Prognose geprüft: Kronos-Commit `67b630e67f6a18c9e9be918d9b4337c960db1e9a`; `NeoQuasar/Kronos-small` Revision `901c26c1…` (`model.safetensors` SHA-256 `b082dfcb…e020`); `NeoQuasar/Kronos-Tokenizer-base` Revision `0e011738…` (SHA-256 `59d85f6a…6bee`), volle Werte in `s18.py`. Kein Update während der Studie.
2. Kronos-mini und -base werden nicht ausgewertet (kein Modell-Shopping). Wenn Kronos-small auf dem Mac zu langsam ist (mehr als 10 Minuten je Prognose mit 100 Pfaden), wird das vor 1.0 entschieden, nicht danach.
3. `sample_count` mittelt die Pfade (geprüft im Code, `auto_regressive_inference`). Deshalb ein Batch aus 100 gleichen Eingaben mit `sample_count = 1`: jede Zeile zieht eigene Zufallswerte. Im Probelauf waren alle 100 Endkurse verschieden.
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

1. ~~Einordnung~~ entschieden: Prognosestudie ohne Registerplatz (Uzi, Karte 08.11.2026, 13:56 Uhr).
2. ~~Code- und Gewichteprüfung, Pins~~ erledigt (Abschnitt 9).
3. ~~Einzelpfade und Laufzeit~~ erledigt (Abschnitt 9).
4. ~~Auswertecode mit Tests~~ erledigt (16 Tests auf synthetischen Daten). Einfrieren mit dem Merge, danach Hintergrundjob am Mac stündlich (`forecast`, schreibt höchstens einmal je 4-Stunden-Slot).

## 9. Einrichtung und Probelauf (08.11.2026, ohne Bewertung)

- **Prüfung Fremdcode:** `model/kronos.py` und `model/module.py` (1249 Zeilen) gelesen: keine Netz-, Datei- oder Prozessaufrufe beim Vorhersagen; Laden der Gewichte über `PyTorchModelHubMixin` aus `model.safetensors` (beide Hugging-Face-Repos enthalten nur diese Gewichtsdatei, kein Pickle).
- **Umgebung:** `~/Documents/TIM/kronos-s18` am Mac (außerhalb von `~/TIM-live`), eigene venv Python 3.13, torch 2.15.0, Versionen aus `requirements.txt` des Repos außer pandas 2.2.3 statt 2.2.2 (2.2.2 stürzt mit numpy 2.5 unter Python 3.13 ab). Kein Zugriff auf Kraken, Keys oder Live-Trader.
- **Probelauf:** 512 BTCUSDT-1h-Kerzen bis 2024-10-01, 100 Pfade × 24 Stunden: M1-GPU 84 s, CPU 132 s; alle Werte endlich, 100 verschiedene Endkurse. Gerechnet und angesehen wurden nur Laufzeit, Form und Endlichkeit, kein Zielwert, keine Spanne, kein CRPS. CPU und GPU dürfen nicht im selben Prozess laufen (Rotary-Puffer bleibt auf dem ersten Gerät).

## Änderungsprotokoll

- 0.1 (08.11.2026): Entwurf auf Uzis „go“. Nichts installiert, keine Kurse ausgewertet, keine Kronos-Ausgabe gesehen.
- 0.2 (08.11.2026): Auf Uzis „merge geprüftes einrichten“: Kronos geprüft und eingerichtet, Pins eingetragen, Regeln als Code mit Tests. Präzisiert vor jedem Ergebnis: Batch statt 100 Einzelaufrufe (4.3), Vorlauf 745 Kerzen, Protokoll enthält nur Kronos-Pfade, Spät-Regel 2 Stunden, Forward-Start 2026-11-10, Rücktest 2024-Q4 gestrichen (Leck). Keine Kronos-Spanne und kein Zielwert gesehen.
- 1.0 (08.11.2026): Einordnung ohne Registerplatz (Uzi), Regeln und Code mit dem Merge dieses Stands auf Uzis „merge“ eingefroren. Kein Ergebnis gesehen.
