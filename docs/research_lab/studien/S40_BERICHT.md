# S40 – Bericht (Training, Version 1.0)

Stand 24.11.2026. Präregistrierung `S40_ORDERFLOW_OPTIONSFLOW_HISTORISCH_PRAEREGISTRIERUNG.md` (1.0, eingefroren
24.11.2026, Merge f733f90). Ein Lauf `python -m src.research_lab.studies.s40 --phase train` auf dem Mac,
24.11.2026 10:29–10:36 Ortszeit, einmal gestartet, ohne Fehler. Ausgabe `~/Documents/TIM/s40-out/s40_train.json`
(auf dem Mac, nicht im Repo).

- code_sha256 `8c67d7f1c78f62d3ea3e424b1705d1a6596deb3709fccb5ad2757782eaf5ae57`
- data_sha256 (datenreife.json) `4257c66c5b73712babb12912517e7df77f2ffa4a3d51c51f3d3aa595586f892b`
- Startmonat Optionsflow 2020-01. Ausschlüsse je Markt (1h/4h): ohne Ziel BTC 6/4, ETH 7/4, SOL 7/4; Ziel nach
  Abschnittsende je 1; ungültige Monate 0.

## Urteil

**Alle 12 Haupttests im Training nicht bestanden.** Damit entfällt die Validierung (Abschnitt 12, Paket 4);
2023–2024 bleibt ungesehen, 2025 unberührt. Weder Orderflow aus Perp-Trades noch Deribit-Optionsflow sagt die
Richtung der nächsten 1 h oder 4 h in diesen Daten besser voraus als der Kurs allein.

| Test | Markt | klein → groß | h | n (OOS) | IC klein | IC groß | CW p | Holm p | Jahresregel |
|---|---|---|---|---|---|---|---|---|---|
| T1 | BTC | A0 → A1 | 1h | 20 991 | 0,0121 | −0,0079 | 0,233 | 1,0 | nein |
| T2 | BTC | A0 → A1 | 4h | 5 245 | 0,0249 | 0,0108 | 0,0493 | 0,493 | ja |
| T3 | ETH | A0 → A1 | 1h | 20 990 | 0,0167 | 0,0056 | 0,00553 | 0,0664 | nein |
| T4 | ETH | A0 → A1 | 4h | 5 245 | 0,0504 | 0,0269 | 0,197 | 1,0 | nein |
| T5 | SOL | A0 → A1 | 1h | 14 815 | 0,0100 | 0,0145 | 0,722 | 1,0 | nein |
| T6 | SOL | A0 → A1 | 4h | 3 701 | 0,0502 | 0,0390 | 0,850 | 1,0 | nein |
| T7 | BTC | A0 → A2 | 1h | 20 991 | 0,0121 | 0,0053 | 0,753 | 1,0 | nein |
| T8 | BTC | A0 → A2 | 4h | 5 245 | 0,0249 | 0,0186 | 0,169 | 1,0 | ja |
| T9 | BTC | A1 → A5 | 1h | 20 991 | −0,0079 | −0,0079 | 0,733 | 1,0 | nein |
| T10 | BTC | A1 → A5 | 4h | 5 245 | 0,0108 | 0,0060 | 0,169 | 1,0 | ja |
| T11 | BTC | A0 → A5 | 1h | 20 991 | 0,0121 | −0,0079 | 0,537 | 1,0 | nein |
| T12 | BTC | A0 → A5 | 4h | 5 245 | 0,0249 | 0,0060 | 0,0399 | 0,439 | ja |

IC = Rangkorrelation Vorhersage/Ziel außerhalb der Stichprobe (purged walk-forward), CW = Clark-West mit
Newey-West-Fehler, Holm über 12 Tests, Grenze 0,05.

## Einordnung

- In 11 von 12 Tests ist der IC des größeren Modells **kleiner** als der des Kursmodells: die Zusatzmerkmale
  bringen in einem linearen Modell eher Rauschen. Das passt zur Literatur (Abschnitt Kernbefunde im Forschungsplan):
  Orderflow wirkt gleichzeitig bis Minuten, nicht auf 1–4 h.
- Kleinster bereinigter Wert T3 (ETH, 1h): Holm p 0,066, und der IC fällt trotzdem; kein Hinweis auf einen Effekt.
- Auffällig zum Nachsehen (kein Einfluss aufs Urteil): T9 zeigt für A1 und A5 auf 1h denselben IC auf vier Stellen.
  Bei 4h unterscheiden sie sich (T10). Prüfung, ob A5 auf 1h die Optionsmerkmale wirklich nutzt, als offener Punkt.
- Nicht geprüft und nicht ausgeschlossen: nichtlineare Modelle, kürzere Horizonte (Minuten), L2-Orderbuch,
  Gamma-Level als Zonen. Jede davon wäre eine neue Studie mit eigener Präregistrierung.

## Abschluss
S40 1.0 ist beendet: Training nicht bestanden, keine Validierung, keine Handelsprüfung. Kein Wechsel ins
Papier- oder Echtgeld-Journal. TRADING_AUTHORIZED=NO unverändert.
