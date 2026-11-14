# Optionsflow: Regelkatalog (Kandidaten, alle ungeprüft)

Stand 13.11.2026, Paket A3 aus `../SELBSTVERBESSERNDE_KI_PLAN.md`. Uzi am 13.11.2026: „Mehr Daten und Regeln sammeln, dann
testen“. **Keine dieser Regeln wird benutzt.** Sie sind Kandidaten für die Studie S33 (`S33_OPTIONSFLOW_FILTER_PRAEREGISTRIERUNG_ENTWURF.md`).
Herkunft: allgemeines Wissen über Optionsmärkte und Dealer-Hedging, keine eigene Messung. Ein Eintrag hier ist eine Hypothese,
kein Beleg. Merkmale: `src/research_lab/options_flow/features.py`.

Vorzeichen eines Trades (Taker-Sicht): Call gekauft oder Put verkauft = bullisch (+1), Call verkauft oder Put gekauft = bärisch (−1).
Alle Schwellen (Terzile, „groß“) werden nur aus dem Kalibrierfenster bestimmt und vor dem Testfenster eingefroren.

## Familie R: Richtung (Filter für vorhandene Trades)

| Nr | Regel (Richtung fest) | Merkmal | Begründung | Bekannte Schwäche |
|---|---|---|---|---|
| R1 | Netto-Prämie der letzten 4 h im oberen Terzil → Long-Trades nehmen, Shorts auslassen; unteres Terzil spiegelbildlich | `signed_premium_usd` (4 h) | Informierte Käufer nutzen Optionen als Hebel | Viel Flow ist Absicherung oder Volatilitätshandel ohne Richtung |
| R2 | Richtung der großen Trades (≥ Kalibrier-P95 Prämie) in den letzten 4 h stimmt mit dem Trade überein → nehmen | `big_signed` | Große Tickets eher von Profis | Wenige Ereignisse, Aggressor bei Großen unsicher |
| R3 | Blocktrade-Netto-Prämie der letzten 24 h stimmt mit dem Trade überein → nehmen | `block_signed_usd` | Blöcke außerbörslich verhandelt, oft institutionell | Blöcke sind häufig Spreads (mehrere Beine), Vorzeichen je Bein irreführend |
| R4 | Put/Call-Prämie der letzten 24 h im oberen Terzil (viel Angst) → Long nehmen (Gegensignal) | `put_call_premium` | Extreme Absicherung oft nahe Tiefs | Gegenrichtung zu R1, beide nur getrennt gezählt |
| R5 | Kurzläufer-Anteil (≤ 7 Tage) im oberen Terzil und Netto-Prämie gleiche Richtung wie der Trade → nehmen | `short_share`, `signed_share` | Kurzläufer = spekulativer, schneller Flow | Verfallstage verzerren den Anteil |
| R6 | Put-OI steigt in 24 h stärker als Call-OI (oberes Terzil der Differenz) → Short nehmen | `put_oi_change − call_oi_change` | Neue Absicherung = Erwartung fallender Kurse | OI sagt nicht, wer Käufer ist |

## Familie V: Volatilität statt Richtung

| Nr | Regel | Merkmal | Begründung | Bekannte Schwäche |
|---|---|---|---|---|
| V1 | DVOL steigt in 4 h im oberen Terzil → in den nächsten 24 h größere Spanne (ATR-normiert) als im Rest | `dvol_change` | Implizite Vola läuft realisierter oft voraus | Gegenseitige Abhängigkeit, Vola clustert ohnehin (GARCH-Basis nötig) |
| V2 | Gamma-Regime negativ (Kurs unter Gamma-Flip) → größere Spanne in 24 h | vorhandenes Gamma-Log | Dealer short Gamma verstärken Bewegungen | Flip aus Bestand geschätzt, Dealer-Seite angenommen, nicht bekannt |

V-Regeln ändern keinen Trade. Wenn sie halten, wären sie ein Kandidat für Stop-Weite oder Positionsgröße, nicht für Richtung.

## Nicht aufgenommen (mit Grund)

- **Max-Pain-Anziehung am Verfallstag:** schwache Grundlage, als Anzeige vorhanden; ein eigener Test lohnt erst mit Jahren an Verfällen.
- **Call/Put-Wall-Reaktion:** schon als eigener Entwurf `GEX_WAND_REAKTION_ENTWURF.md` (frühestens 16.12.2026), nicht doppeln.
- **Einzelne „Whale“-Trades als Signal:** zu wenige Ereignisse, nur über R2 gezählt.

## Pflege

Neue Kandidaten kommen hier hinzu, bevor sie gerechnet werden, und zählen ab dann im Nenner der Mehrfachtest-Korrektur.
Ergebnisse gehen als Aussagen ins Gedächtnis (`docs/research_lab/gedaechtnis/`), auch Misserfolge.
