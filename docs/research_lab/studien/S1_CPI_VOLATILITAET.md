# Studie S1 – BTC-Schwankung an CPI-Terminen (Vorregistrierung)

| Feld | Wert |
|---|---|
| Status | **vorab registriert**, vor jeder Auswertung echter Daten |
| Registriert | 2026-10-13, auf Uzis Auftrag im Projekt-Thread („ja mach das go“) |
| Code | `src/research_lab/studies/cpi_volatility.py`, Lauf `scripts/research_lab_cpi_volatility.py` |
| Daten | ALFRED-Bundle `RESEARCH_2017_2024` (BTC Research Engine V1.1), BTCUSDT Spot 1h aus dem Research Lab |
| Zeitraum | 2017-09-01 bis 2024-12-31; Holdout ab 2025-01-01 bleibt zu |
| Bericht | `docs/research_lab/reports/s1_cpi_volatility.md` (+ `.json`) |

## 1. Frage

Schwankt BTC in der Stunde der US-Inflationszahl (CPI, BLS 08:30 New York) stärker als
zur gleichen Uhrzeit an vergleichbaren Tagen ohne CPI? Das ist eine **beschreibende
Messung für einen möglichen Risiko-Kalender**, keine Handelsstrategie und keine Aussage
über die Richtung. Sie bekommt deshalb **keinen Eintrag in `REGISTER.jsonl`**; die Zahl
der registrierten Varianten (m = 48) und die Holdout-Regeln aus `PROTOKOLL.md` bleiben
unverändert.

## 2. Ereignisse

- Quelle: `events.release_events` auf dem gespeicherten Research-Bundle, bis
  `2024-12-31T23:59:59Z`.
- Verwendet werden nur Ereignisse mit Status `OK` und bekannter `event_time`
  (identifizierter Erstdruck, Termin aus dem Release-Kalender).
- `event_time` von 2017-09-01 bis vor 2025-01-01 (Spot-1h-Archiv beginnt 2017-08-17,
  erster voller Monat 2017-09, siehe PROTOKOLL O3).
- Release-Kerze: die 1h-Kerze, in der `event_time` liegt (12:00 oder 13:00 UTC, je nach
  US-Sommerzeit). Sie enthält die 30 Minuten vor der Veröffentlichung; das ist bei
  1h-Auflösung nicht vermeidbar und macht die Messung eher kleiner als größer.

## 3. Kennzahl

Für ein Fenster aus W aufeinanderfolgenden 1h-Kerzen ab der Release-Kerze:

`M = ln(höchstes Hoch / tiefstes Tief)` über alle W Kerzen.

Fenster W ∈ {1h, 4h, 24h}. Fehlt eine Kerze des Fensters (Archivlücke oder nach
`invalid_candles="exclude"` ausgeschlossen), ist das Fenster ungültig.

## 4. Vergleichsfenster

- Je Ereignis acht Vergleichsfenster: gleiche UTC-Startstunde, gleiche Länge, um
  k Wochen verschoben, k ∈ {−4, −3, −2, −1, +1, +2, +3, +4} (gleicher Wochentag).
- Ein Vergleichsfenster entfällt, wenn
  - eine seiner Kerzen fehlt,
  - es an oder nach 2025-01-01 endet (Holdout),
  - ein beliebiges CPI-Ereignis aus `release_events` (jeder Status, gemessen an
    `available_at`) in [Fensterbeginn − 24 h, Fensterende + 24 h) liegt.
- Bleiben weniger als vier gültige Vergleichsfenster, entfällt das Ereignis für dieses W.
- Je Ereignis: `L = ln(M_Ereignis / Median(M_Vergleich))`. Ist ein Wert nicht positiv,
  entfällt das Ereignis für dieses W.

## 5. Test und Entscheidung

- **Primär:** W = 1h, alle Ereignisse. Exakter einseitiger Vorzeichentest auf L > 0
  (Bindungen L = 0 fallen heraus).
- **Sekundär:** W = 4h und W = 24h. Alle drei p-Werte werden nach Holm über die Familie
  {1h, 4h, 24h} mit α = 0,05 korrigiert.
- **Effekt:** Median-Verhältnis `exp(Median L)` mit 95-%-Bootstrap-Intervall
  (Perzentil, 10 000 Ziehungen, Seed 20261013).
- **BESTÄTIGT** heißt für ein Fenster: Holm-korrigiertes p < 0,05 **und** Median-Verhältnis
  ≥ 1,25 **und** Median L > 0 sowohl in Training (`event_time` vor 2023-01-01) als auch in
  Validierung (2023–2024) getrennt. Sonst **NICHT BESTÄTIGT**.
- Maßgeblich für eine Folgerung ist das primäre Fenster 1h.

## 6. Was aus dem Ergebnis folgt

- **BESTÄTIGT (1h):** Kandidat für einen Risiko-Kalender in Phase F (Risk + Paper Trader).
  Umsetzung nur mit eigenem Bauplan; dazu gehört ein zukünftiger BLS-Terminkalender, weil
  die Engine rückblickend arbeitet.
- **NICHT BESTÄTIGT:** keine CPI-Regel in TIM.
- In keinem Fall entsteht daraus ein Kauf- oder Verkaufssignal.

## 7. Bekannte Grenzen

- Andere Makrotermine (FOMC, Arbeitsmarktbericht) werden nicht herausgerechnet; ein
  Vergleichsfenster kann auf einen solchen Termin fallen und den Effekt verkleinern.
- Nur Spot BTCUSDT, nur 1h-Auflösung, etwa 85 bis 90 Ereignisse.
- Die Release-Uhrzeit 08:30 New York ist eine belegte Regel, kein Feld der Quelle
  (`EXTERNAL_DATA.md` Abschnitt 10).

## Änderungsprotokoll

Nur anhängen. Nach dem ersten Lauf auf echten Daten sind Änderungen an Kennzahl,
Fenstern, Vergleich, Test und Schwellen nicht mehr erlaubt.

| Datum | Änderung | Bis dahin gesehene Daten |
|---|---|---|
| 2026-10-13 | Vorregistrierung | keine Auswertung; nur Tests auf dem ALFRED-Fixture 2019–2020 mit synthetischen Kerzen |
| 2026-10-13 | Klarstellung 4: gesperrt wird um jedes Ereignis aus `release_events` (wie im Code), nicht um reine Revisionstermine des Kalenders | keine Auswertung |
