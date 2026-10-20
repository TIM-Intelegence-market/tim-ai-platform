# Studie S1 – BTC-Schwankung an CPI-Terminen (Ergebnis)

Vorregistrierung: `docs/research_lab/studien/S1_CPI_VOLATILITAET.md`. Beschreibende Messung, kein Signal, Holdout zu.

| Feld | Wert |
|---|---|
| bundle_id | `d8e5477ad99b1d32f1c20ba0e3069c6fe26f1e32e171477889dfd4f4453ee70b` |
| replay_at | `2024-12-31T23:59:59+00:00` |
| sha256 observations | `d68bbbd8738f36671bdf91e2e17064468152627ec6e2c798368386b153ca73c5` |
| sha256 release_dates | `e515b7d853a41ba0908367fe9e54ecc61c7c26f44b0cf6f6db0ac2f8f96d4d8f` |
| sha256 series | `90bab80744c992336277a46b5a880937796e72b2b38ebd2c0bdf9a5476c360e0` |
| Ereignisse gesamt / verwendbar | 107 / 88 |
| BTC-Kerzen 1h (ausgeschlossen) | 64467 (57) |
| **Primärurteil (1h)** | **BESTAETIGT** |

| Fenster | n | über Vergleich | p (Vorzeichen) | Holm | Median-Verhältnis | 95-%-Intervall | Anteil ≥ 2× | Training | Validierung | Urteil |
|---|---|---|---|---|---|---|---|---|---|---|
| 1h | 88 | 56 | 6.88e-03 | ja | 1.40 | 1.13–1.66 | 35% | 1.07 (n=64) | 2.20 (n=24) | BESTAETIGT |
| 4h | 88 | 55 | 1.23e-02 | ja | 1.17 | 1.06–1.35 | 22% | 1.09 (n=64) | 1.48 (n=24) | NICHT_BESTAETIGT |
| 24h | 87 | 47 | 2.60e-01 | nein | 1.07 | 0.93–1.31 | 17% | 0.99 (n=63) | 1.39 (n=24) | NICHT_BESTAETIGT |

Ausgefallene Ereignisse je Fenster:

- 1h: {'OK': 88}
- 4h: {'OK': 88}
- 24h: {'EVENT_WINDOW_INCOMPLETE': 1, 'OK': 87}
