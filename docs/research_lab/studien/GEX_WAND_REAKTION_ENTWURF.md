# Entwurf: Reaktion an Call Wall und Put Wall (BTC)

Stand 04.11.2026, Entwurf ohne Registerplatz. Die Nummer wird vergeben, wenn die Studie
registriert wird. Anlass ist Reel DfTgoOTx6Qs (Angel Casapia, Gexbot, QQQ). Uzi hat am
04.11.2026 mit „Go“ zugestimmt. Nur Papier, kein Echtgeld.

## Warum erst sammeln

Deribit liefert nur den aktuellen Optionsbestand. Frühere Walls und Flips kann TIM nicht
nachträglich abrufen. Deshalb schreibt TIM ab dem 04.11.2026 jeden Gamma-Schnappschuss
(alle 5 min) als eine Zeile nach `data/options/gamma_levels.jsonl`. Das erledigt
`src/dashboard/gamma_data.append_level_log`. Erst auf dieser Grundlage lässt sich die Frage
prüfen. Bis dahin wird nichts ausgewertet und nichts angepasst.

## Hypothese H1

Berührt BTC (Binance Spot, 1m-Kerzen) die Call Wall von unten, läuft der Kurs danach häufiger
um mindestens x zurück als an Vergleichs-Levels. Spiegelbildlich gilt das für die Put Wall
von oben.

- **Wall:** Call Wall bzw. Put Wall aus dem letzten Schnappschuss, der vor der Berührung
  vorlag. Er darf höchstens 20 min alt sein. Spätere Schnappschüsse sind tabu (kein Blick
  in die Zukunft).
- **Berührung:** Das Hoch einer 1m-Kerze erreicht die Call Wall, die Kerze davor lag darunter.
  Je Wall und UTC-Tag zählt nur die erste Berührung.
- **Messgröße:** Rücklauf (in % des Preises) und Weiterlauf nach 15, 30 und 60 min. Als
  „abgewiesen“ zählt ein Rücklauf um mindestens 0,3 %, bevor der Kurs 0,3 % weiterläuft.
- **Vergleich:** dieselbe Messung an Zufalls-Levels mit gleichem Abstand zum Kurs (Pool wie
  bei R4), sowie an runden 1000er-Marken.
- **Frühester Termin:** 40 Berührungen je Wall-Art, frühestens am 16.12.2026. Schwellen,
  Zeitfenster und Test werden vor dem ersten Blick in die Daten festgeschrieben.

## Hypothese H2 (Anzeigequalität)

Ein steigendes Gamma an einem Strike entsteht oft allein dadurch, dass der Kurs an den Strike
heranläuft, ohne neue Positionen. TIM soll in der Anzeige später zwei Anteile trennen:

- Gamma-Änderung durch Kursbewegung bei gleichem Open Interest,
- Gamma-Änderung durch neues Open Interest.

Steigendes Gamma darf in TIM nie als „neue Käufe“ beschrieben werden.

## Schon jetzt mitgeschrieben

Jeder Plan der VP-Regel (vp/1, `src/dashboard/vp_plans.py`) bekommt das Feld `gex` mit
folgendem Inhalt: Call Wall, Put Wall, Flip, Regime, Abstand zum berührten Level in % und
`wall_at_level` (Wall höchstens 0,3 % vom Level entfernt). Das Feld ist nur ein Merkmal, kein
Filter. Damit lässt sich später fragen, ob ein Value-Rand mit Wall daneben besser hält.

## Grenzen

- Die Walls sind Schätzungen aus Open Interest. Wer long oder short ist, zeigt Open Interest
  nicht (Konvention in `src/options_gamma/gex.py`).
- Deribit-Optionen beziehen sich auf den BTC-Index, TIM misst auf Binance Spot.
- TIM hat keine Intraday-Daten zum Optionsfluss je Strike wie Gexbot.
