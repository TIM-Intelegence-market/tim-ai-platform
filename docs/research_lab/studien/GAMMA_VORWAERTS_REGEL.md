# Gamma-Vorwärtsbeobachtung, Regel 1.0 (eingefroren bei Beginn der Aufzeichnung)

Stand: 19.11.2026. Nur Beobachtung, kein Handel, kein Echtgeld, keine Änderung an Plänen oder Scores.

Ergänzt `GEX_WAND_REAKTION_ENTWURF.md` (Wand-Berührungen, 1m-Kerzen, Zufallsvergleich). Diese Regel fügt den Gamma-Zustand
(Preis unter/über Flip) und die Rohdaten-Aufzeichnung hinzu. Bei Widerspruch gilt die strengere Regel.

## Frage
Verhalten sich Gamma-Zonen (Flip, Call/Put-Wall, OI-Wände) und der Gamma-Zustand (Preis unter/über Flip)
so, wie die Theorie sagt? Bisher ist das für Krypto nicht belegt.

## Was festgehalten wird (im Voraus, nicht nachträglich)
- Roh-Optionsdaten stündlich (`src.options_gamma.recorder`, eine Datei je Tag).
- Alle 5 Minuten die berechneten Zonen und der Zustand im Level-Log (`data/options/gamma_levels.jsonl`, Feld `price_vs_flip`).
- Es zählt nur, was zum Zeitpunkt des Eintrags im Log stand. Rückwirkend neu gerechnete Zonen zählen nicht.

## Fälle
- Zonen-Fall: Preis berührt eine Zone (Flip, Call-Wall, Put-Wall, OI-Wand) bis 0,15 % Abstand. Ein Fall je Zone und 4 Stunden.
- Zustands-Fall: je voller Stunde der Zustand (negativ/positiv).

## Messgrößen
1. Hält/bricht: Zone hält, wenn der Preis in den nächsten 4 h nicht mehr als 0,3 % durch die Zone schließt (1h-Kerzenschluss).
2. Bewegungstempo: mittlere absolute 1h-Rendite und 4h-Spanne bei negativem gegen positivem Zustand.
3. Nach Kosten: nur wenn 1 und 2 vorher getrennt ausgewertet sind; Kosten 0,15 R wie im Rest von TIM.

## Urteil
- Ab 30 Zonen-Fällen je Zonenart: Auswertung, vorher nichts. Weniger Fälle heißt „zu wenig“, nicht „bestanden“.
- Belegt nur, wenn Hält-Rate klar über Zufall (Vergleich: gleiche Abstände zu zufälligen Preisen) liegt und nach Kosten positiv ist.
- Training/Validierung/Holdout: reine Vorwärtsdaten ab 19.11.2026, kein Holdout 2025 berührt.

## Grenzen
- Open Interest zeigt nicht, wer long ist; Händler-Annahme ist eine Schätzung.
- Deribit-Optionen decken nur einen Teil des BTC-Marktes ab.
- Änderungen an dieser Regel nur als neue Version mit Datum.
