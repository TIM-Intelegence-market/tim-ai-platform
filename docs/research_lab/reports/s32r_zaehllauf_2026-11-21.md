# S32-R Zähllauf (ergebnisblind), 21.11.2026

Version 0.1, 55 Tardis-Tage (Training 2020-06 bis 2022-12: 31 Tage, Validierung 2023–24: 24 Tage), Holdout ab 2025
gesperrt. Gezählt wurde nur, **wie viele Ranges** je Gruppe entstehen und wie oft das Buch oben dünner ist. Was danach
passiert (Ausbruch oben/unten/bleibt), wurde **nicht** angesehen.

| Gruppe | Training (oben dünner) | Validierung (oben dünner) | Urteil möglich |
|---|---|---|---|
| 10–20 bp | 309 (142) | 372 (179) | ja |
| 20–60 bp | 656 (315) | 417 (205) | ja |
| 60–100 bp | 328 (154) | 114 (59) | ja |
| 100–150 bp | 127 (59) | 48 (24) | ja |
| 10–20 Asien / London / New York / spät | 96 / 86 / 69 / 58 | 124 / 119 / 73 / 56 | ja (alle vier) |
| 20–60 Asien / London / New York / spät | 197 / 171 / 185 / 103 | 123 / 104 / 119 / 71 | ja (alle vier) |
| 60–100 Asien / London / New York / spät | 87 / 81 / 105 / 55 | 23 / 12 / 58 / 21 | nur New York |
| 100–150 Asien / London / New York / spät | 30 / 31 / 47 / 19 | 8 / 6 / 24 / 10 | keine |

„Urteil möglich“ heißt: mindestens 30 Ranges in Training **und** Validierung, also prüfbar für A2 (bricht ein schiefes
Buch häufiger aus?). A1 (in welche Richtung) braucht zusätzlich 30 **Ausbrüche**; wie viele das sind, zeigt erst die
Auswertung nach dem Einfrieren. Gruppen ohne Urteil werden trotzdem gezeigt.

Das Buch ist in jeder Gruppe etwa zur Hälfte oben dünner, also kein einseitiger Datensatz.

Rohzählung: `/mnt/project-files/s32-orderbuch/S32R-Zaehllauf-2026-11-21.json` (nicht im Repo). Tardis-Rohdaten nicht
eingecheckt (Lizenz 9.2).
