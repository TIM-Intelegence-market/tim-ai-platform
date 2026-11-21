# PS4: Nachrechner und Datenprüfer (17.11.2026)

Uzi 17.11.2026: "Go 2-3". Die PS4 rechnet fertige Studien nach und prüft unsere Binance-Daten. Sie schreibt keine Live-Daten und kein Journal. Ist sie aus, geht nichts verloren, sie holt danach nach. Die Rolle der PS4 in `ARCHITEKTUR_GERAETE.md` ändert dieses Paket nicht.

## Werkzeuge (nur Standardbibliothek)

| Werkzeug | Aufgabe | Urteil |
|---|---|---|
| `src/research_lab/ps4/nachrechner.py` | Studie mit gleichem Code und Seed auf den Trainingstagen 2020–2023 neu rechnen, Ergebnis exakt mit dem alten vergleichen | gleiche Zahlen = reproduzierbar; Abweichung = Fehler, Bericht nennt die Stellen |
| `src/research_lab/ps4/datenpruefer.py` | Archivdateien (Kerzen, Funding) und Tages-Aggregate gegen die offiziellen Binance-Prüfsummen abgleichen, fehlende Tage melden | "stimmt überein" oder Liste der Auffälligkeiten |

## Schutz vor Holdout

- Nachrechner lehnt ab: Referenz mit Phase `valid`, Referenz mit Ende nach 2023-12-31, Befehle mit `valid`, `holdout`, 2024, 2025 oder 2026. Kein neuer Test, nur Wiederholung.
- Datenprüfer überspringt alles ab 2025-01-01 und liest es nicht. Er schreibt nur seinen Bericht.

## Aufruf (Beispiel S37, Training)

```
python -m src.research_lab.ps4.nachrechner lauf --referenz <alte_train.json> --bericht <ps4_bericht.json> -- \
  python -m src.research_lab.studies.s37 --phase train --btc-root <..> --multi-root <..> --out {OUT}
python -m src.research_lab.ps4.datenpruefer --klines-root data/research_lab \
  --aggtrades-root data/research_lab/aggtrades --bericht <datenstatus.json>
```

Exit-Code 0 = alles gleich, 1 = Abweichung oder Auffälligkeit, 3 = abgelehnt (Schutz). Prüfung: `pytest tests/test_research_lab_ps4.py`.

## Offen

- Einsatz auf der PS4 braucht Code dort (kein git: Archiv per Mac, wie bei PS5) und einen Zeitplan erst auf Uzis "Zeitplan an".
- Mac-LaunchAgent `com.tim.ps4-ofx-waechter` nicht anfassen; Doku-Änderung zur PS4-Rolle liegt in PR #319.
- Nicht gebaut: Wächter von außen (4), Rohdaten-Archiv (5), Backup/Restore (1, anderer Thread).
