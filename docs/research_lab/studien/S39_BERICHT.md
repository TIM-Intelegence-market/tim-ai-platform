# S39 – Bericht (Präregistrierung 1.0, Lauf 16.11.2026)

Gerechnet auf der PS5 mit dem eingefrorenen Stand ce9419a (Worktree `~/tim-research/wt-s39`, `nice -n 15` neben dem OFX-Lauf) auf Uzis Freigabe "go: S39 auf der PS5 per ssh starten". Datenspeicher `~/tim-research/data/orderflow_ml_120` (S8 1.2.0). Kein Code geändert, Holdout 2025 nicht gelesen. Ausgaben auf der PS5: `~/tim-research/out/s39/` (s39_train.json/.md, s39_valid.json/.md).

- dataset_hash Training (2020–2023): `377354cf2fcfcc268bd5cbbbc5a038e00d1f43904b816dfd04a94a3df1eae542`
- dataset_hash Validierungslauf (2020–2024, 2023 nur als Detektor-Historie): `bc0e59e86a4cc025d79f527af71d725bab556490c3ee16ecfb6fed382f8bfe8d`
- Bewegungen: Training 69 (11 wegen Überlappung weggelassen), Validierung 11 (2 weggelassen). Zufallsstunden-Pool Training 34 972.

## Training 2020–2023 (Hauptmaß: 24h-Rendite in Richtung der Bewegung, ab Bekanntwerden ihres Endes)

| Typ | n | Ø 24h | Zufall | Überschuss | Holm-p | Anteil Fortsetzung | Ø 4h | Urteil |
|---|---|---|---|---|---|---|---|---|
| UP_FLOW | 14 | −1,46 % | +0,50 % | −1,97 % | 0,224 | 0,29 | −0,28 % | nicht prüfbar |
| UP_OHNE | 16 | +1,56 % | +0,17 % | +1,39 % | 0,444 | 0,69 | −0,37 % | nicht prüfbar |
| DOWN_FLOW | 22 | −0,37 % | −0,10 % | −0,27 % | 1,0 | 0,32 | −0,01 % | nicht belegt |
| DOWN_OHNE | 17 | +0,12 % | −0,07 % | +0,19 % | 1,0 | 0,59 | −0,32 % | nicht prüfbar |

## Validierung 2024 (einmal, aus dem eingefrorenen Training)

| Typ | n | Überschuss | Urteil |
|---|---|---|---|
| UP_FLOW | 4 | −0,64 % | nicht prüfbar |
| UP_OHNE | 0 | – | nicht prüfbar |
| DOWN_FLOW | 4 | −0,77 % | nicht belegt |
| DOWN_OHNE | 3 | +0,97 % | nicht prüfbar |

## Ergebnis

Kein Typ ist belegt. Kein Holm-p liegt unter 0,05. Drei Typen bleiben unter der Mindestzahl von 20, einer wird geprüft und nicht bestätigt. Nach einer großen Bewegung lässt sich aus Richtung und Spot-Taker-Fluss also keine systematische Fortsetzung oder Umkehr über 24 h ablesen. Die Stichproben sind dafür zu klein, rund 17 Ereignisse je Typ in vier Jahren.

Auffällig, aber nicht belegt: UP_FLOW lief im Training eher zurück (−2 Prozentpunkte gegen Zufall, 4 von 14 setzten fort), UP_OHNE eher weiter (+1,4). Das ist ein Hinweis für spätere Beobachtung und keine Regel. Mit 2024 sind das nur 4 bzw. 0 weitere Fälle.

Folge: TIM bleibt bei der Erklärung im Chart und dem Etikett am Papier-Trade (P4), das prospektiv Fälle mit Liquidationen, Open Interest und Schlagzeilen sammelt, die es für 2020–23 nicht gibt. Eine Neuauflage mit anderen Schwellen wäre eine neue Studie mit eigener Präregistrierung.
