# Volatilität und Kontraktbewertung: Bestandsaufnahme und Forschungsplan (Entwurf 0.1)

Stand 24.11.2026, Uzi "TIM RESEARCH – VOLATILITY & CONTRACT PRICING ENGINE" (#372). **Nur Plan, keine Ergebnisse,
keine Implementierung.** Code nur gelesen (platform-main `e580732`), keine Daten geladen, kein Holdout berührt.
Mission 07 hat Vorrang. Codex prüft Formeln, Datenverträge und Methodik; ChatGPT priorisiert.

Kennzeichnung: **BEOBACHTET** = Marktdaten wie geliefert (Preis, Trade, Funding, OI, Börsen-IV als Zahl).
**MODELLIERT** = von TIM oder der Börse aus Annahmen gerechnet (HV-Schätzer, BS/B76-Preise, Greeks, GEX,
Surface-Interpolation, GARCH-Prognose). Deribit `mark_iv` und DVOL sind Börsen-Modellgrößen: als Datenpunkt
beobachtet, inhaltlich modelliert.

## 1. Bestandsaufnahme (Phase 1)

### 1.1 Was existiert

| Baustein | Ort | Inhalt | Nachweis |
|---|---|---|---|
| BS-Gamma, BS-Delta | `src/options_gamma/greeks.py` | ohne Dividende, Zins frei wählbar | Unit-Tests; kein Abgleich mit Börsen-Greeks |
| B76-Gamma, Vanna, Charm | `src/options_gamma/models.py` | auf Forward je Verfall, Zins 0 | Unit-Tests |
| GEX je Strike, Flip, Walls, Händler-Modelle M0–M4 | `src/options_gamma/gex.py`, `models.py`, `snapshot.py` | Vorzeichen sind offene Annahmen | Kritik 17.11.: Put Wall läuft dem Preis nach; kein belegter Handelswert |
| Expected Move | `snapshot.py::_expected_move` | `spot × ATM-IV × √T` bis Hauptverfall | kein Kalibrierungstest (Trefferquote des Bandes) |
| Realisierte Vol, Varianzprämie, Term Structure 7/30 d, Risk Reversal 25Δ | `src/research_lab/options_flow/features_q.py` | Q7–Q9, Total-Varianz-Interpolation ohne Extrapolation | nur Unit-Tests; in keiner Studie ausgewertet |
| Trade-Greeks-Fluss (Delta-/Gamma-Fluss) | `features_q.py::greek_flow` | aus Trade-IV der Deribit-Trades | Teil von S40 (A5), nicht bestanden |
| DVOL-Änderung | `features.py::dvol_change` | Deribit-Volatilitätsindex | **kein Aufrufer**; siehe Befund 1.3 |
| GARCH(1,1), EWMA, rollierende Varianz | `src/research_lab/studies/s15.py` | QMLE, QLIKE, Diebold-Mariano | S15: 4h **bestanden**, 1d nicht; BTC-Persistenz an der Grenze (IGARCH) |
| GARCH-4h im Papier | `src/research_lab/vol_4h.py` | feste Parameter, Gewicht σ_ref/σ | S25: GARCH-Größe bringt bei S7b nichts (nicht bestanden) |
| ATR | `src/research_lab/backtest/indicators.py` | kausal | Stop-Logik der Studien |
| Funding | `backtest/funding.py`, `forward/futures_recorder.py`, `protocol.py` | Kosten im Backtest, live 1m-Aufnahme Perp | S16 Funding-Extreme nur Entwurf |
| Liquidationen | `src/research_lab/liquidations/` (S12) | Rohaufnahme, Heatmap-Stände | S12 Kalibrierung offen |
| Optionsflow-Rohdaten | `src/research_lab/options_flow/` | Datenvertrag mit `recv_ms`, Trade-`iv` | S33 Entwurf; S40 Training: **alle 12 Tests nicht bestanden** |
| Zeitaufteilung | `src/research_lab/protocol.py` | Training bis 2022, Validierung 2023–2024, Holdout ab 2025 gesperrt | greift im Code |

### 1.2 Was fehlt

- **Bewertung:** kein BS-/B76-Preis, kein IV-Löser, keine Vega/Theta/Rho; keine Put-Call-Parität als Datenprüfung.
- **HV-Familie:** keine HV 7/14/30/90 als einheitliche Funktion (Close-to-Close, Parkinson, Garman-Klass, Yang-Zhang fehlen).
- **Surface:** keine Volatilitätsfläche (Strike × Laufzeit), keine Arbitrage-Prüfung (Kalender, Butterfly), kein SABR/SVI.
- **Basis:** keine Futures-Basis (Quartals-Futures oder Perp-Prämienindex) als Merkmal; Funding nur als Kosten.
- **Regime:** keine Vol-Regime-Definition; keine Studie bedingt Signale auf ein Regime.
- **Kalibrierung:** Expected Move und GARCH-Prognose nie als Intervall auf Trefferquote geprüft (außer QLIKE in S15).
- **Historische Optionsfläche:** OI je Strike gibt es nur live (Book Summary); historisch nur Trades mit Trade-IV und DVOL.

### 1.3 Befunde der Bestandsaufnahme

1. **POSSIBLE Look-ahead in `dvol_change`:** nimmt Kerzen mit Zeitstempel ≤ t und deren Schlusskurs. Ist der
   Zeitstempel der Kerzen-Beginn (bei Deribit-OHLC üblich), ist der Schluss erst nach Ende der Kerze bekannt.
   Derzeit ungenutzt; vor jeder Nutzung Zeitstempel-Bedeutung belegen und auf `ts + Auflösung ≤ t` umstellen.
2. **MODELLIERT, als beobachtet missverständlich:** Expected Move und GEX erscheinen im Chart als Linien; die
   Legende sagt "Schätzung" (PR #306), ein Kalibrierungsnachweis fehlt.
3. **Zinsannahme 0** in B76 und bei Zins-Default der Greeks: bei Krypto-Basis von mehreren Prozent p. a. nicht neutral;
   der Forward je Verfall ist besser aus Futures/Put-Call-Parität zu nehmen (in `models.py` als Variante angelegt).
4. **Zeit bis Verfall** mit 365-Tage-Jahr und Kalenderzeit; Deribit verfällt 08:00 UTC; Konvention festschreiben.

## 2. Forschungsplan (Phase 2)

Je Größe: Definition, Datenquelle, BEOBACHTET/MODELLIERT, Prüfung.

| Größe | Definition (Vorschlag, vor Einfrieren zu prüfen) | Quelle | Art | Prüfung |
|---|---|---|---|---|
| HV 7/14/30/90 | annualisierte Std. der Log-Renditen geschlossener 1d-Kerzen, Fenster n, Faktor √365 | Binance Spot/Perp-Klines | MODELLIERT aus BEOBACHTET | Gleichheit mit Referenzrechnung; Schätzervergleich Parkinson/GK/YZ als Nebenfrage |
| Realized Vol | Summe quadrierter 5m-Log-Renditen je Periode (wie S15) | Binance 5m | MODELLIERT | Mikrostruktur-Rauschen: 5m vs. 15m |
| Implied Vol | ATM-IV je Verfall (Deribit `mark_iv`), konstante Laufzeit 7/30 d per Total-Varianz | Deribit Book Summary (live), Trade-IV (historisch), DVOL | BEOBACHTET (Börsenmodell) | Abgleich Trade-IV vs. Mark-IV; Lücken |
| IV/HV-Verhältnis | IV_30d / HV_30 | wie oben | MODELLIERT | – |
| Varianzrisikoprämie | IV_30d² − **künftige** RV_30d (ex post, nur als Ziel) bzw. IV² − HV² (ex ante, als Merkmal) | wie oben | MODELLIERT | strikte Trennung ex ante / ex post |
| Vol-Regime | Terzile von HV_30 bzw. IV_30d, Schwellen **nur aus Training** fest; Alternative: GARCH-σ | wie oben | MODELLIERT | Stabilität der Schwellen über Jahre |
| Expected Move | S·IV·√T bis Verfall | Deribit | MODELLIERT | Trefferquote des 1σ-Bandes (Soll ≈ 68 %), Kalibrierungskurve |
| Black-Scholes / Black-76 | Preis, IV-Löser (Newton + Bisektion), B76 auf Forward | – | MODELLIERT | Put-Call-Parität, Rückrechnung von Deribit-Mark-Preisen (Fehler in Vol-Punkten) |
| Greeks | Delta, Gamma, Vega, Theta, Vanna, Charm | – | MODELLIERT | Vergleich mit Deribit-Greeks aus `ticker` (live), finite Differenzen |
| Surface / Skew / Term Structure | IV(Δ, T); 25Δ-Risk-Reversal, Butterfly; 7d−30d | Deribit | MODELLIERT | Arbitrage-Prüfung; nur gemessene Punkte, keine Extrapolation |
| Futures-Basis und Funding | annualisierte (F−S)/S je Quartal; Perp-Prämienindex; Funding 8h | Binance/Deribit Futures, Funding-Archiv | BEOBACHTET | Datenreife, Lücken |
| EWMA / GARCH | wie S15; Erweiterung GJR/Student-t nur als Kandidat | Binance 5m | MODELLIERT | QLIKE/MSE gegen rollierend, DM-Test (S15 vorhanden) |
| SABR (experimentell) | Kalibrierung je Verfall (β fest) | Deribit live | MODELLIERT | Fit-Fehler, Stabilität; **nur beschreibend**, keine Handelsregel |

## 3. Zentrale Forschungsfrage (Phase 3)

**Frage:** Hängt die Vorhersagekraft bestehender Signale (Orderflow, Optionsflow, Gamma, Liquidationen) vom
Volatilitätsregime ab, und bringt das Regime zusätzliche Information über einfache Baselines hinaus?

Wichtig zur Ehrlichkeit: S40 hat Orderflow und Optionsflow im **Training bereits gesehen** und alle 12 Tests
verfehlt. Eine Regime-Aufteilung derselben Trainingsdaten ist eine nachträgliche Teilgruppenanalyse und kann
nur Hypothesen erzeugen, nie bestätigen. Bestätigung nur auf ungesehenen Daten nach Einfrieren.

Vorgeschlagener Aufbau (eine Präregistrierung je Signalfamilie, vor jedem Lauf eingefroren):

- **Baselines:** B0 kein Signal (Null), B1 Kursmodell (Rendite-Lags wie S40 A0), B2 Kursmodell + Regime-Dummy.
- **Kandidat:** Signal + Signal×Regime-Interaktion. Mehrwert = Kandidat gegen B2 (nicht gegen B0).
- **Ziele:** Richtung und Betrag der Rendite 1h/4h/1d; für Vol-Prognosen QLIKE.
- **Regime:** nur aus Daten vor t, Schwellen aus dem Trainingsabschnitt fest.
- **Signalfamilien und Datenlage:** Perp-Orderflow (historisch ab 2020, erlaubt), Deribit-Optionsflow (historisch),
  Gamma (nur live seit 10/2026: **nur vorwärts**, keine Rückrechnung, weil OI je Strike historisch fehlt),
  Liquidationen (nur live seit 11/2026: vorwärts).
- **Test:** Clark-West mit Newey-West, Holm über alle Tests einer Familie, gemeinsame Versuchszahl für Deflated Sharpe (zuletzt 65 nach S25).

## 4. Wissenschaftliche Absicherung (Phase 4)

- **Point-in-Time:** gemeinsamer Vertrag `pit-contract/1` (#381): jedes Merkmal nur mit Event- *und*
  Verfügbarkeitszeit ≤ t; Kerzen erst nach Schluss; IV-Stände mit Empfangszeit; fehlende Zeit = UNKNOWN.
- **Datenherkunft:** je Lauf Manifest (Code-SHA, Quelldateien mit Hash, Parser-Version, Flag-Typen); B2 (#383) zeigt die Lücken.
- **Reproduzierbarkeit:** reine Funktionen, feste Konventionen (Jahr 365 d, Verfall 08:00 UTC, Zins), Testvektoren aus Lehrbuch und Put-Call-Parität.
- **Modellannahmen offen benennen:** Lognormalität, konstante Vol in BS, Händler-Vorzeichen bei GEX, Zins 0.
- **Walk-forward:** wachsendes Fenster mit Purge/Embargo wie S40; Training bis 2022, Validierung 2023–2024.
- **Holdout ab 2025 gesperrt:** nur mit Uzis ausdrücklichem Wort, einmalig, nie in der Suche.
- **Kosten und Slippage:** nur bei Handelsregeln; Vol-Prognosen ohne Kosten, als Prognosestudie gekennzeichnet.
- **Unsicherheit:** Konfidenzintervalle (Block-Bootstrap), Mehrfachtest-Korrektur, Mindeststichprobe vor jeder Aussage.
- **Beobachtet vs. modelliert:** jede Ausgabe trägt das Feld `kind: observed | modelled`.

## 5. Vorgeschlagene Pakete (je eigene Freigabe nötig)

| Paket | Inhalt | Art | Abhängigkeit |
|---|---|---|---|
| V0 | Referenz-Bibliothek: BS/B76-Preis, IV-Löser, alle Greeks, HV-Schätzer; nur Funktionen + Testvektoren | Code, kein Datenzugriff | – |
| V1 | Datenreife: Deribit-Trade-IV und DVOL historisch, Binance-Basis/Funding (nur Training-Zeitraum) | Lesen, Bericht | V0 |
| V2 | Kalibrierung Expected Move und GARCH-Intervalle (Training) | Prognosestudie | V0, V1 |
| V3 | Präregistrierung Regime-Abhängigkeit (Orderflow, Optionsflow), einfrieren, dann ein Lauf auf Validierung | Studie | V1, Mission 07 |
| V4 | Vorwärts-Beobachtung Gamma/Liquidation × Regime | Schatten | E1/E2 |
| V5 | SABR/Surface beschreibend | experimentell | V0 |

Empfohlene Reihenfolge: V0 → V1 → V2, V3 erst nach Codex-PASS von Mission 07.
