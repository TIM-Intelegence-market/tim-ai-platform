# Kalibrierung Bewegungs-Detektor (move-context 0.2)

Stand 16.11.2026. Gerechnet auf der PS5 mit `python -m src.research_lab.studies.move_calibration`, auf Uzis Freigabe.
Der Lauf lief mit `nice -n 19` parallel zum OFX-Lauf. Datenbasis waren die S8-Minutenbalken `orderflow_ml_120`.

- Training: 2020-01-01 bis 2023-12-31.
- Validierung: 2024.
- Holdout 2025: nicht gelesen.
- Ziel: etwa 20 Bewegungen je Jahr, Bereich 10 bis 30. Gewählt wurde nur auf dem Training.
- Gezählt wird nur, wie oft der Detektor anschlägt. Rendite und Trades gehen nicht ein.
- Umfang: 43.814 Stunden, 10.941 4h-Kerzen.

| Regeln | 1h | 4h | Training je Jahr (je Jahr) | Validierung 2024 |
|---|---|---|---|---|
| 0.1 (von Hand) | 3,0 x Median, mind. 0,6 % | 3,0 σ | 388,2 (2020: 374, 2021: 418, 2022: 392, 2023: 369) | 405 |
| 0.2 (gewählt) | 15,0 x Median, mind. 1,5 % | 5,0 σ | 20,0 (2020: 23, 2021: 12, 2022: 13, 2023: 32) | 13 |

In 0.2 werden 7 Trainings-Bewegungen nur über die 4h-Regel ausgelöst.

Ein erster Lauf mit engerem Raster endete am Rand bei 6 x / 1,5 % / 4 σ mit 117 Bewegungen je Jahr. Daraufhin wurde
das Raster erweitert.

Die fünf Punkte am nächsten am Ziel:

- 15 x Median, 1,5 %, 5 σ: 20,0
- 12 x Median, 3,0 %, 7 σ: 20,2
- 12 x Median, 3,0 %, 8 σ: 20,2
- 12 x Median, 3,0 %, 10 σ: 20,2
- 12 x Median, 3,0 %, 12 σ: 20,2

Bei den Punkten mit 12 x ist die 4h-Regel ab 7 σ wirkungslos. Dort bindet nur die 1h-Regel.

Grenzen:

- Die Jahre streuen stark, von 12 bis 32 Bewegungen.
- 2024 liegt mit 13 am unteren Rand des Zielbereichs.
- Die Schwelle legt nur fest, wie oft TIM erklärt. Ob eine Erklärung stimmt, sagt sie nicht.
- Ergebnisse: PS5 `~/tim-research/results/move-calibration-2026-11-16-v2`, Mac `~/Documents/TIM/move-calibration-2026-11-16-v2/`.
