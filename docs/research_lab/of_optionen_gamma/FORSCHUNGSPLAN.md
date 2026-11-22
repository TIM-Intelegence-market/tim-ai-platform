# Forschungsprogramm Orderflow × Optionsflow × Gamma (BTC, ETH, SOL)

| Feld | Wert |
|---|---|
| Stand | 23.11.2026, **Entwurf 0.1, nichts eingefroren, nichts gerechnet** |
| Auftrag | Uzi, 23.11.2026 00:38 Ortszeit: "TIM Deep Research – Orderflow × Optionsflow × Gamma Exposure", Start mit Literatur und Forschungsplan |
| Literatur | [LITERATUR_EVIDENZ.md](LITERATUR_EVIDENZ.md) (Phase 1) |
| Grenzen | `TRADING_AUTHORIZED=NO`. Keine Orders, keine Produktionsänderung, kein Holdout 2025 ohne Uzis ausdrückliches Wort, kein Datenkauf ohne Uzis Wort. Orderflow-Regeln nur als eingefrorene Vorwärtsbeobachtung (Uzi, 16.11.2026). |
| Rollen dieses Dokuments | Forschungsplan und Architekturvorschlag. **Es enthält keine Testergebnisse dieses Programms.** Zahlen stammen aus früheren, verlinkten TIM-Berichten oder aus Quellen. |
| Prüfung | Unabhängige Prüfung (`studien-pruefer`) am 23.11.: Urteil NACHBESSERN, 15 Punkte; eingearbeitet in Abschnitt 14. Vor einer S40-Präregistrierung erneut prüfen. |

Kennzeichnung wie in der Literaturdatei: BELEGT, GETESTET, MODELLANNAHME, OFFEN, WIDERSPRUCH.

---

## 1. Executive Summary

1. **Ergebnisse dieses Programms liegen noch nicht vor.** Kein Modell wurde gerechnet. Alle Hypothesen H1–H3 sind OFFEN.
2. **Literatur (BELEGT, teils nur Abstract oder Preprint, siehe Literaturdatei):** Orderflow erklärt Preisbewegungen stark im selben Moment und sagt sie im Bereich Sekunden bis
   Minuten etwas voraus (O1–O9). Ein Vorteil nach Taker-Kosten auf Horizonten von 15 Minuten bis Tagen ist in keiner
   gefundenen Arbeit gezeigt. VPIN ist umstritten (O10/O11, WIDERSPRUCH).
3. **Gamma (BELEGT für Aktienindizes, OFFEN für Krypto):** Händler-Hedging prägt Intraday-Momentum und Volatilität,
   wenn die Händlerposition aus echten Positionsdaten bekannt ist (G2, G3). Bei kurzen Laufzeiten widersprechen sich die
   Befunde (G5, WIDERSPRUCH). Für Deribit gibt es keine Positionsdaten; jede GEX-Zahl ist MODELLANNAHME.
4. **Krypto-Optionsflow (BELEGT, eng):** Netto-Kaufdruck treibt die IV von BTC-Optionen; OTM-Flow trägt Richtungsinformation
   (P6). Das ist ein Preisbildungsbefund, kein getesteter Handelsvorteil für Perps.
5. **TIM selbst (GETESTET, alle nicht bestanden oder nicht belegt):** Orderflow-Familien (OF2, OFX, S35a), Gamma-Wände
   (Training 2020–22: halten 58/88 gegen 81 % Kontrolle; 2024: 19/31 gegen 50 %, Richtung kippt, zusammen kein stabiler Vorteil), Gamma-Regime (zeichnet die 72-h-Rendite nach).
6. **Hauptengpass ist die Datenhistorie, nicht Rechenzeit:** Open Interest je Strike gibt es rückwirkend nur bezahlt
   (Tardis u. a.). TIMs eigene Aufzeichnung läuft erst seit 04.11. (Gamma), 13.11. (Optionsflow, mit Unterbrechung bis
   21.11.) und 17.11. (Orderbuch). H1–H3 sind damit vorerst nur **vorwärts** prüfbar; erste belastbare Stichproben in Monaten.
7. **WIDERSPRUCH zur Annahme "Orderflow-Historie fehlt":** Das öffentliche Binance-Archiv listet am 23.11.2026
   Perp-aggTrades (mit Aggressor-Seite) für BTCUSDT ab 31.12.2019 und SOLUSDT ab 14.09.2020 (ETHUSDT nicht abgefragt), Perp-`metrics` ab 01.09.2020
   und Perp-`bookDepth` ab 01.01.2023 (Verzeichnislisting abgefragt, Inhalt nicht geladen). Deribit-Optionstrades mit
   Seite gibt es gratis rückwirkend (TIM-Check 21.11.). **Trade-basierter** Flow (CVD, Imbalance, Optionsflow-Seite) wäre
   also historisch prüfbar; **nicht** vorhanden sind volle L2-Buchhistorie, Footprint aus eigener Aufzeichnung, Bitunix
   und OI je Strike. Auch S33 §2 ("keine kostenlose Historie für 2020–2024") ist damit für Optionstrades überholt; S33 als neue
   Version vormerken, nichts ändern ohne Uzis Wort. Ob das Uzis Regel "Orderflow nur live" ändert, ist **Uzis Entscheidung** (Abschnitt 11).
8. **75 % Winrate:** als Forschungsziel zulässig, aber nachrangig. Bei Ziel 2 R und Stop 1 R wären 75 % Treffer extrem
   (+1,25 R brutto je Trade); umgekehrt erreicht man hohe Trefferquoten leicht mit weitem Stop und nahem Ziel und
   negativer Erwartung. TIM-Studie S4 (Trefferquote 75 %) und S5/S6 (95 %) sind Vorläufer. Entscheidend bleibt Netto-E[R].

---

## 2. Was TIM schon hat (vor jedem Neubau wiederverwenden)

Geprüft im Repo (`platform-main`, 3916854) und in Projektberichten. Laufstatus der Dienste wurde **heute nicht** geprüft
(nur Read-only im Repo); Angaben zu Diensten sind historisch.

| Baustein | Ort | Inhalt | Status |
|---|---|---|---|
| Gamma/GEX | `src/options_gamma/` (`gex.py`, `greeks.py`, `snapshot.py`, `recorder.py`) | GEX je Strike, Flip, Call/Put Wall, OI-Wände, Max Pain, Expected Move; Vorzeichenannahme im Kopf von `gex.py` offengelegt | GETESTET (Rechnung stimmt, T5) |
| Gamma-Log | `~/TIM-live/data/options/gamma_levels.jsonl` (Mac) | 5-min-Schnappschüsse seit 04.11.2026, BTC | historisch (17.11.: 4.032 Zeilen, Lücken bis 2,4 h) |
| Optionsflow-Recorder | `src/research_lab/options_flow/` (`recorder.py`, `contract.py`, `features.py`) | Deribit BTC-Optionstrades, Summary, DVOL; Merkmale R1–R6, V1–V3 | läuft laut Notiz seit 13.11., Unterbrechung bis 21.11. (TCC) |
| Regelkatalog + Studie | `docs/research_lab/studien/OPTIONSFLOW_REGELKATALOG.md`, `S33_..._ENTWURF.md` | 9 vorab beschriebene Optionsflow-Tests, Vorwärtsdesign 60 Tage Kalibrierung | Entwurf 0.1, nicht eingefroren |
| Orderbuch | `src/research_lab/orderbook/` (`binance.py`, `book.py`, `walls.py`), `src/research_lab/depth/` (`book.py`, `replay.py`, `sync.py`, `tardis.py`) | Binance-USDⓈ-M-Tiefe, Wände, Replay, Tardis-Parser | Recorder-Dienst am Mac seit 17.11. (Notiz) |
| Perp-Orderflow | `src/dashboard/perp_flow.py`, `docs/PERP_ORDERFLOW.md` | Footprint 5 min × 5 USD aus Perp-Trades, eigene Archivdateien | läuft am Mac (Notiz) |
| Orderflow-Engine | `src/research_lab/of2`, `ofx`, `s31`, `forward/of_live.py`, `of_paper.py` | Footprint, Delta, Absorption, Papierbetrieb vorwärts | OF-Live auf PS5 seit 17.11. (Notiz) |
| Liquidationen, Bitunix, Bybit | `src/research_lab/liquidations`, `bitunix`, `forward/futures_recorder.py` | eigene Aufzeichnung | seit 09.11. / 12.11. (Notiz) |
| Prüfwerkzeug | `src/research_lab/konsolidierung`, `stats`, `src/research_lab/protocol.py`, `docs/research_lab/REGISTER.jsonl` | Kosten Bitunix, Bootstrap, Holm, Deflated Sharpe, Präregistrierung | GETESTET (118 Tests in Konsolidierung) |

**Regel:** Neues Modul nur, wenn kein Baustein es mit einer Zusatzfunktion erledigt.

---

## 3. Datenquellen und Datenqualität (Phase 2)

Legende Datenart: **L** live, **V** verzögert, **H** historisch, **M** modelliert/abgeleitet.

| Anbieter | Was | Aggressor-Seite | Orderbuch | Optionen/OI/Greeks | Historie | Kosten, Rechte | Status der Angaben |
|---|---|---|---|---|---|---|---|
| **Binance Spot/Perp** | aggTrades, Trades, Kerzen, Funding, OI, Liquidationen | ja (`m` = Käufer ist Maker) | L2 live per Diff-Stream mit Update-IDs (`U`/`u`, Perp zusätzlich `pu`) + REST-Snapshot | nur Binance-Optionen (`eapi`), klein | **H**: Perp-aggTrades BTC ab 31.12.2019, SOL ab 14.09.2020; `metrics` ab 01.09.2020; `bookDepth` (prozentuale Tiefe, kein L2) ab 01.01.2023; Optionen BVOL ab 20.06.2023, EOHSummary ab 18.05.2023 | gratis; Nutzungsbedingungen Binance (nicht geprüft) | Archiv-Listing am 23.11. abgefragt (BELEGT, Startdatum); Feldinhalte aus früherer TIM-Arbeit |
| **Bitunix** | Futures-Trades, Tiefe | OFFEN (API-Doku nicht geprüft) | OFFEN | keine | keine bekannte Historie; TIM-Recorder seit 12.11. | gratis live | OFFEN; Volumenqualität kleiner Börse ungeprüft (O14) |
| **Bybit** | Trades | ja | L2 live | Optionen vorhanden (nicht genutzt) | TIM-Aufzeichnung | gratis live | historisch belegt in `ARCHITEKTUR_GERAETE.md` |
| **Deribit** | Optionstrades, Buch, Ticker mit Greeks und Mark-IV, OI, DVOL | ja (`direction` des Takers), Blocktrades markiert | L2 je Instrument | ja, alle Laufzeiten; BTC/ETH inverse (1 Coin je Kontrakt, Prämie in Coin), lineare USDC-Optionen (u. a. SOL, Kontraktgröße OFFEN) | **H** Trades gratis über `history.deribit.com` (geprüft ab 06/2019, TIM 21.11.); **kein** OI je Strike rückwirkend | gratis live, kein Key | TIM-Check 21.11.; Hinweis aus Tardis-Doku: OI im Ticker seit 10.11.2026 mit 8 h Verzögerung (**OFFEN**, unbestätigt, kritisch für GEX-Datenalter) |
| **CME** | BTC/ETH-Futures und Optionen auf Futures | Börsen-Ticks (DataMine, bezahlt) | bezahlt | Optionen auf 5-BTC-Futures, Micro 0,1 BTC | bezahlt | Lizenz CME | Kontraktgrößen laut CME-Produktblatt (BELEGT), Preise OFFEN |
| **CFTC COT** | Wochenpositionen CME-Bitcoin nach Händlergruppe | – | – | Futures + Optionen kombiniert | ab 2018, wöchentlich, Dienstag-Stand am Freitag | gratis | **einzige echte Positionsquelle** im Umfeld; Takt zu grob für Intraday. Aus Fachwissen, nicht heute geprüft (OFFEN) |
| **Cboe / OCC / Nasdaq** | Optionen auf Spot-BTC-ETFs (z. B. IBIT), OI täglich | Open-Close-Daten (bezahlt) mit Kundentyp | – | ja | bezahlt | Lizenz | OFFEN (Umfang, Preise nicht geprüft); relevant, weil ETF-Gamma außerhalb Deribit liegt |
| **Tardis.dev** | Rohdaten Deribit/Binance/Bybit u. a., inkl. Optionskette mit OI/Greeks, L2-Updates | ja | ja (inkrementell) | ja, Deribit ab 30.03.2019 | ja; 1. Tag je Monat gratis | ab ~350–1.000 USD/Monat laut früherer Notiz, **nicht wörtlich geprüft**; HTTP 429/Kontingent bei Gratistagen erlebt | TIM-Erfahrung 21.–22.11. |
| Amberdata, Kaiko, Laevitas, Glassnode, CoinGlass, Velo | aufbereitete Daten, fertige GEX/Skew | teils | teils | ja | ja | bezahlt, Preise OFFEN | Anbieter-Kennzahlen = MODELLANNAHME, Methode oft nicht offen (G9) |

**Datenqualitätsregeln (für alle Pakete):**

1. Jede Zeile trägt `exch_ts`, `recv_ms` (Empfangszeit TIM), Quelle, Abruf-ID. Merkmal zum Zeitpunkt t nur aus `recv_ms ≤ t`.
   Historische Daten (Binance-Archiv, `history.deribit.com`) haben kein `recv_ms`: dort gilt vorab fest `exch_ts + Puffer`
   (Vorschlag 2 s für Trades) und für OI je Strike das bekannte Datenalter (ggf. 8 h) als feste Verzögerung.
2. Orderbuch nur mit lückenloser Update-ID-Kette; bei Bruch neu synchronisieren und Lücke zählen (`depth/sync.py`).
3. OI je Strike trägt sein **Datenalter**; Schnappschüsse älter als X (vorab festlegen, Vorschlag 15 min, oder 8 h falls
   die Verzögerung stimmt) werden als "veraltet" geführt, nicht still verwendet.
4. Börsenübergreifend: Uhrzeitversatz je Quelle messen (Median `recv_ms − exch_ts`), Merkmale nur auf gemeinsamem Raster.
5. Live, historisch, synthetisch und abgeleitet getrennt ablegen; Rohdaten unverändert, außerhalb des Repos.
6. Tägliche Zählung: Nachrichten, Lücken, Duplikate (gleiche Trade-ID), Ablehnungen. Ohne Blick auf Ergebnisse.
   Eine Lückenregel für alle Studien der Familie: Lücke = > 10 min ohne Nachricht (wie S33); Merkmalsfenster mit Lücke fallen heraus.
7. Alle Zeitgrenzen (Tag, Vortag, Woche, Wochenende, Verfall 08:00) in UTC.

---

## 4. Orderflow Engine: Signaldefinitionen (Phase 3)

**Zeitregel für alle Signale (Pflicht):** Signalzeit ist der **Schluss der Bar, an der das Signal feststeht**. Ein Swing-Hoch
mit R rechten Bars steht erst R Bars nach dem Hoch fest; ein Sweep/Failed Breakout erst nach Schluss der m-ten Bar.
Einstieg zur Eröffnung der nächsten Kerze (wie S33 §2). Jedes Signal bekommt einen Look-ahead-Test (Abschnitt 8.3).

Bezeichnungen: Trades i mit Menge qᵢ, Preis pᵢ, Seite sᵢ = +1 (Käufer aggressiv) / −1. Fenster w (Minuten).
B_w = Σ qᵢ·1{sᵢ=+1}, S_w = Σ qᵢ·1{sᵢ=−1}. Δ_w = B_w − S_w, CVD_t = Σ_{τ≤t} Δ. ATR, Median und z-Werte nur aus
Vergangenheit (rollierend 30 Tage, bis t−1). Alle Schwellen werden in einer Kalibrierphase festgelegt und dann eingefroren.

| # | Signal | Regel (mathematisch) | Daten | Ungültig, wenn | Testbare Hypothese |
|---|---|---|---|---|---|
| F1 | CVD-Divergenz | Preis macht neues N-Bar-Hoch (p_t > max p_{t−N..t−1}), aber CVD_t < CVD am letzten Swing-Hoch − k·σ(Δ_w) (Short-Fall spiegelbildlich) | Trades mit Seite (Perp) | Daten-Lücke im Fenster; Swing-Definition nicht erfüllt | Rendite r(t, t+h) nach Divergenz < unbedingte Rendite, h ∈ {15 m, 1 h, 4 h} |
| F2 | Aggressor-Imbalance | AI_w = Δ_w / (B_w + S_w); Signal bei z(AI_w) > z* | Trades mit Seite | B+S < Mindestvolumen | Vorzeichen(AI) sagt Vorzeichen r(t, t+h) mit IC > 0 voraus; Fortsetzung vs. Umkehr getrennt |
| F3 | Passive Absorption | Aggressives Volumen V_agg im Preisband [L±b] hoch (z > z*), Preisverschiebung klein: \|p_end − p_start\| / ATR < ε, Seite gegen die Absorption; mit L2: Tiefe am Band wird nachgefüllt (Δdepth + ausgeführt > 0) | Trades; L2 für Nachfüll-Teil | Band nicht vorab definiert (z. B. HTF-Level) | Nach Absorption Umkehr häufiger als bei gleich großem Volumen ohne Absorption (Kontrollgruppe) |
| F4 | Orderbuch-Imbalance / Microprice | OBI_K = (Σ_{k≤K} Q^b_k − Σ Q^a_k)/(Σ Q^b_k + Σ Q^a_k); Microprice p* = (P^a·Q^b + P^b·Q^a)/(Q^a+Q^b); OFI nach Cont et al. (O1) | L2 lückenlos | Sync-Bruch | IC(OBI, r(t,t+h)) fällt mit h; Prüfen, ob bei h ≥ 5 min noch > 0 nach Spread |
| F5 | Liquidity Pulling/Stacking | Löschanteil c_k = −(Δdepth_k + exec_k) innerhalb ±x bp in τ s; Stacking = Δdepth_k > 0 ohne Ausführung | L2 + Trades | Sync-Bruch | Pulling auf einer Seite geht Bewegung zu dieser Seite voraus |
| F6 | Liquidity Sweep | Preis überschreitet Swing-Hoch H um ≥ δ (Ticks/ATR) mit V_agg-Spitze, schließt binnen m Bars wieder unter H | Kerzen + Trades | Swing nicht vorab definiert | Nach Sweep r(t,t+h) in Gegenrichtung > Kontrolle (Überschreitungen ohne Volumenspitze) |
| F7 | Failed Breakout | Ausbruch aus Range [R_lo, R_hi] (vorab: N-Bar-Range), Schluss zurück in Range binnen m Bars, Δ in Gegenrichtung | Kerzen + Trades | Range-Breite < c·ATR | wie F6; TIM-S36 (SFP) und S38 sind Vorläufer, Ergebnisse dort nachlesen |
| F8 | Volumencluster / Footprint | HVN/LVN aus Volumenprofil des Vortags/der Woche; Stacked Imbalance: ≥ n aufeinanderfolgende Preisstufen mit Ask/Bid-Verhältnis > ρ | Trades je Preisstufe | Profil aus unvollständigem Tag | Reaktion an HVN/LVN ≠ Reaktion an Zufallsstufen gleicher Distanz |
| F9 | Spoofing-ähnliches Muster | Order ≥ k × Median-Tiefe innerhalb ±x bp, gelöscht binnen τ s ohne Ausführung, ≥ r Mal in T | L2 (Order-Ebene wäre nötig, L2 nur Aggregat) | nur Aggregat-Ebene → Muster ist "große Mengenänderung", nicht "Order" | **Keine Absichtszuschreibung.** Nur: geht das Muster Bewegungen voraus? |
| F10 | Multi-Exchange-Bestätigung | Signal zählt nur, wenn sign(AI_w) auf ≥ 2 von {Binance Perp, Binance Spot, Bybit, Bitunix} gleich ist | Trades mehrerer Börsen, synchronisiert | Versatz > Fensterbreite/4 | Bestätigte Signale haben höheren IC als unbestätigte (O15, O16) |

Kostenmaßstab für alle: Bitunix Taker 0,06 % je Seite, Schlupf 0,03 %, Stop-Schlupf 0,05 %, Funding (wie S27/S35a).
Ein Signal, dessen erwartete Bewegung kleiner ist als ~0,2 % (Hin + Rück + Schlupf), kann als Taker nicht netto positiv sein.

---

## 5. Optionsflow Engine (Phase 4)

Grundsatz: **Beobachtet** ist nur der Trade (Instrument, Menge, Preis, IV, Taker-Seite, Block-Markierung) und der
OI-Bestand. **Unbekannt** sind Eröffnung vs. Schließung, Endposition, wer der Endkunde ist, und ob ein Bein Teil
einer größeren Struktur oder einer Absicherung ist.

| # | Merkmal | Definition | Beobachtet / Annahme | Vorhanden in TIM |
|---|---|---|---|---|
| Q1 | Put/Call-Verhältnis | Volumen-, Prämien- und OI-Version getrennt: PCR_vol = Σ q_put / Σ q_call (w) | beobachtet | `features.py` (Prämie) |
| Q2 | Volumen relativ zu OI | VOI_k = q_k(24 h) / OI_k je Instrument; hoch = neue Positionierung **oder** Umschichtung | beobachtet; Deutung offen | neu |
| Q3 | Große Trades | Prämie ≥ P95 der Kalibrierung; Ausführung relativ zu Mark (über/unter Mark = aggressiv) | beobachtet | R2 |
| Q4 | Spreads/Strukturen | Trades mit gleicher `block_trade_id`/`combo_id` zusammenfassen; Netto-Delta, Netto-Vega der Struktur statt je Bein | Gruppierung beobachtet, Absicht Annahme | R3 (je Bein), Gruppierung neu |
| Q5 | Delta-adjustierter Flow | DAF_w = Σ sᵢ·Δᵢ·qᵢ·S (USD-Delta, das Taker gekauft haben) | beobachtet × Modell-Delta | neu (Gexbot "Aggregate Dex") |
| Q6 | Gamma-adjustierter Flow | GAF_w = Σ sᵢ·Γᵢ·qᵢ·S²·0,01 | wie Q5 | neu (Gexbot "Net Convexity") |
| Q7 | IV vs. realisierte Vola | VRP_t = DVOL_t² − RV_{30d}²; Kurzform IV_ATM(7 d) − RV(7 d) | beobachtet | DVOL im Recorder |
| Q8 | Term Structure | TS_t = IV_ATM(7 d) − IV_ATM(30 d), interpoliert in Varianz | beobachtet (Mark-IV) | neu |
| Q9 | Skew | RR25_t = IV(25Δ Call) − IV(25Δ Put), 30 d | beobachtet | neu |
| Q10 | Verfall | Anteil OI mit Verfall ≤ 24 h, Stunden bis 08:00 UTC, ATM-OI-Perzentil am Verfallstag **nur gegen vergangene Verfälle bis t−1** (rollierend), nie über die ganze Stichprobe | beobachtet | neu (für G7-Test) |

Überschneidung mit S33 (Q1≈R4, Q3≈R2, Q4≈R3, Q7≈V1, Gamma-Regime≈V2): Diese Merkmale werden **nicht** neu getestet,
sondern als eine gemeinsame Testfamilie mit gemeinsamem Holm-Nenner geführt (Regelkatalog, Abschnitt "Pflege");
S33-Testfenster und S40-Kalibrierung dürfen sich nicht überlappen.

Hypothesen der Engine (vorab, getrennt gezählt): Q5/Q6 sagen Spot-Richtung 1–24 h voraus (P6 stützt nur OTM-Information);
Q7–Q9 sagen **Spanne** voraus, nicht Richtung (S33-V1/V3); Q10: Verfallsumkehr wie G7.

---

## 6. Gamma Engine (Phase 5)

### 6.1 Rechnung (gemeinsam für alle Modelle)

Zwei Varianten, getrennt berichtet:
(a) **Spot-Variante (= heutiges `gex.py`):** GEX_{K,T} = d · Γ_BS(S, K, σ, τ, r=0) · OI_{K,T} · m · S² · 0,01, Flip-Suche über die
Strike-Spanne wie `gex.py`.
(b) **Forward-Variante (neu):** Γ aus Black-76 auf den Forward F_T je Verfall, umgerechnet auf Spot über dF/dS:
GEX_{K,T} = d · Γ_B76(F_T, K, σ, τ) · (dF_T/dS)² · OI_{K,T} · m · S² · 0,01 (T5 zeigte 0,2 % Flip-Versatz gegenüber Index).
Einheit beider: USD Delta-Änderung der Händler je 1 % Spotbewegung.
σ = Mark-IV, τ in Jahren auf 365-Tage-Basis, m = Kontraktgröße (Deribit BTC/ETH 1 Coin; USDC-Optionen je Instrument aus
API lesen, nie fest codieren). Inverse Optionen: Γ in Coin-Delta je USD, Umrechnung mit S dokumentieren und gegen
lineare Rechnung testen. Für Q5 bei inversen Optionen klären, ob Deribits Ticker-Delta die Prämienanpassung (Δ − V/S)
enthält; vorab festlegen, mit Test absichern (OFFEN). d = Händler-Vorzeichen (Modell). OI mit Zeitstempel; bei Alter > Schwelle wird das Modell
"veraltet" gesetzt.

### 6.2 Modelle (Vorzeichenannahmen offen)

| Modell | Händler-Vorzeichen d | Begründung | Status |
|---|---|---|---|
| M0 Standard | Calls +1, Puts −1 (Kunden verkaufen Calls, kaufen Puts) | SqueezeMetrics-Konvention, aktuell in `gex.py` | MODELLANNAHME |
| M1 Alle short | −1 für alle | Kunden netto Optionskäufer | MODELLANNAHME |
| M2 Alle long | +1 für alle | Kunden netto Verkäufer (Yield-Produkte) | MODELLANNAHME |
| M3 Taker-Fluss | d_{K,T} = −sign(Σ sᵢ qᵢ seit Listung); Größe = kumulierter Netto-Taker-Fluss statt OI | Glassnode-Ansatz (G9); Maker = Händler angenommen | MODELLANNAHME; **voll messbar nur für Instrumente, die nach Recorder-Start gelistet wurden** |
| M4 OI-Änderung × Seite | ΔOI je Instrument mit Seite der Trades im selben Intervall zugeordnet | grob; Schließungen verfälschen | MODELLANNAHME |
| B0 Basis | kein Gamma: nur Preis, RV, DVOL | Vergleich | – |

**Wichtig:** Unter M1 ist GEX immer negativ, unter M2 immer positiv. Dort gibt es **kein Regime und keinen Flip**;
nur die stetige Größe |GEX| bzw. |GEX|/ADV ist zulässig. "Annahmeunabhängig" heißt deshalb: gleiche Richtung in
**allen** Modellen mit wechselndem Vorzeichen (M0, M3, M4) **und** gleiche Richtung der |GEX|-Größe unter M1 und M2.

### 6.3 Kennzahlen je Modell
Netto-GEX, Gamma Flip (Nullstelle von GEX(S') über Gitter S' = S·(1 ± 0,1 in 0,25-%-Schritten)), Call/Put Wall (max |GEX|),
OI-Wände, Anteil Gamma aus Verfällen < 3 Tage. **Sensitivität:** dieselben Kennzahlen bei S ± 2/5/10 % und τ − 1 Tag
(Zeitablauf), sowie Vanna (∂Δ/∂σ) und Charm (∂Δ/∂τ) aggregiert wie GEX.

### 6.4 Prüffragen (gegen einfache Modelle)
1. **Vola:** Erklärt sign(GEX) oder |GEX|/ADV die realisierte Spanne der nächsten 4/24 h **über** HAR-RV + DVOL hinaus?
   (Clark-West, OOS-R²). Regime-Fragen nur für M0, M3, M4; für M1/M2 nur |GEX|. Muss für **jedes** Modell getrennt berichtet werden; ein Effekt, der nur unter einer
   Annahme auftaucht, gilt als annahmeabhängig.
2. **Level:** wird **nicht** neu geplant, sondern über den bestehenden Entwurf `GEX_WAND_REAKTION_ENTWURF.md` (frühestens
   16.12.2026) geführt. Ergänzung dort als Vorschlag: "Ziel erreicht" gegen Kontrolllinien (Gexbot-Lesart).
3. **Zirkularität:** Netto-GEX gegen vergangene 24/72-h-Rendite regressieren; nur der **Rest** darf als Gamma-Information
   gelten (T5: r 0,41 mit 72-h-Rendite).
4. **Verfall:** G7 nachrechnen: Spot-Rendite von −2 h bis +2 h um 08:00 UTC, getrennt nach ATM-OI-Perzentil (rollierend, Q10).

---

## 7. Multi-Signal Fusion (Phase 6)

**H1:** Die Vorhersagekraft eines Orderflow-Signals F hängt vom Gamma-Regime ab. Test: r(t,t+h) = a + b·F + c·G + d·F·G + e,
G = Regime-Dummy je Modell M0, M3, M4 (unter M1/M2 stattdessen stetig |GEX|/ADV). H1 gilt, wenn d ≠ 0 (Holm) **und**
Vorzeichen wie G3 (negatives Gamma → mehr Fortsetzung) annahmeunabhängig im Sinn von 6.2. Widerlegt, wenn d in allen Modellen ≈ 0 mit engem Intervall.

**H2:** Optionsflow verbessert Orderflow-Prognosen. Test: verschachtelte Modelle OF vs. OF + Q (Clark-West, OOS),
dann Handelsmetrik mit gleicher Einstiegslogik.

**H3:** Kombinierte Regime- und Signalarchitektur verbessert risikoadjustierten Nettoertrag nach Kosten gegenüber der
besten Einzelkomponente. Test: Netto-E[R], Deflated Sharpe, SPA-Test über alle 7 Modelle.

**Vergleichsmodelle (fest, vorab):**

| Nr | Modell | Eingänge |
|---|---|---|
| A0 | Preis-Baseline | Rendite-Momentum/Reversal 1–24 h, ATR, Tageszeit; zusätzlich Zufallseinstiege |
| A1 | Orderflow-only | F1–F10 (nur verfügbare) |
| A2 | Optionsflow-only | Q1–Q10 |
| A3 | Gamma-only | GEX-Kennzahlen M0–M4 |
| A4 | OF + Gamma | A1 + A3 + Interaktionen |
| A5 | OF + Optionsflow | A1 + A2 |
| A6 | Alle drei | A1 + A2 + A3 |

Modellklasse zuerst **linear/logistisch mit wenigen Merkmalen** (Ridge, feste Regularisierung), Baumverfahren erst, wenn
lineare Modelle einen Hinweis zeigen. Horizonte h ∈ {5 m, 15 m, 1 h, 4 h, 24 h}. Regime: Vola-Terzil (Kalibrierung),
Trend/Range (ADX oder 20-Tage-Rendite), Wochentag/Wochenende, Verfallstag ja/nein, Gamma-Vorzeichen je Modell.
Regime-Definition vorab eindeutig (nicht "ADX oder 20-Tage-Rendite"): Vorschlag 20-Tage-Rendite-Terzil, in S40 festlegen.

**Testzahl:** Ohne Begrenzung entstünden 10 Signale × 5 Horizonte × 5 Gamma-Modelle × Regime × 3 Märkte, also Hunderte
Tests. S40 muss deshalb eine **vollständige Testliste mit Zahl N** enthalten, mit höchstens etwa 12 **Primärtests**
(Holm über N); alles andere ist ausdrücklich explorativ und kann nichts "bestehen". Deflated Sharpe zählt zusätzlich die
Vorgänger derselben Familie (OFX rund 32.100 Konfigurationen, S35a 12, OF2, S31/S31b).

Märkte: BTC zuerst (Optionsdaten nur BTC aufgezeichnet), ETH erst nach Recorder-Erweiterung, SOL nur Orderflow
(Optionsmarkt klein, OFFEN).

---

## 8. Statistische Validierung (Phase 7)

1. **Zwei Wege, nie gemischt:**
   - **Weg V (vorwärts, Hauptweg):** Kalibrierung auf den ersten **60 Tagen** der Aufzeichnung (wie S33), Regeln und
     Neuschätz-Prozedur einfrieren (Hash), dann Testfenster genau einmal auswerten. Achtung: `protocol.py` (`split_of`)
     ordnet jeden Zeitpunkt ab 2025-01-01 dem HOLDOUT zu. Vorwärtsdaten brauchen einen **eigenen, dokumentierten
     Datenweg**, der weder die Sperre auslöst noch sie still umgeht. Diese Frage geht an Uzi (Abschnitt 13); `protocol.py`
     bleibt unverändert.
   - **Weg H (historisch, nur mit Uzis Wort):** Perp-aggTrades + Deribit-Optionstrades (gratis) für A0, A1 (nur
     trade-basierte Signale F1, F2, F6–F8, F10 teilweise), A2 (ohne OI-Merkmale), A5. Fenster nach `protocol.py`: Training 2020–2022, Validierung 2023–2024,
     Holdout ab 2025 gesperrt. Der Lader verwirft Archivdateien ab 2025-01-01 **schon beim Laden** (das Archiv reicht bis 2026). Gamma (A3, A4, A6) ist historisch nur mit gekauften
     Daten oder den 1.-des-Monats-Schnappschüssen möglich (n zu klein für Statistik).
2. **Walk-forward** mit wachsendem Fenster; im Testfenster nur als eingefrorene Prozedur (gleicher Code, gleicher Takt); **Purging + Embargo** mindestens Horizont h plus
   längstes Merkmalsfenster.
3. **Lookahead-Prüfung im Code:** jede Merkmalfunktion bekommt einen Test, der Daten nach t verändert und prüft, dass das
   Merkmal bei t gleich bleibt (Permutation der Zukunft). OI- und Greeks-Schnappschüsse mit Zeitstempel ≤ t.
4. **Kosten:** Bitunix-Modell wie S35a; Pflicht zusätzlich `STRESS_COSTS` aus `protocol.py` (doppelte Kosten ohne
   Funding-Gutschrift), ×1,5 nur berichtet. Funding: Bitunix-Funding getrennt von Binance-Funding benennen (S35a nutzte
   Binance-Funding, stille Annahme).
5. **Unsicherheit:** Block-Bootstrap nach Woche, 90 %/95 %-Intervalle; Zufallseinstiege (1.000 Ziehungen); Verschiebungstest.
6. **Mehrfachtests:** Holm über alle registrierten Tests einer Version; zusätzlich Deflated Sharpe gegen Zahl aller je
   gerechneten Varianten (inkl. dieses Programms und der TIM-Vorgänger der gleichen Familie).
7. **Ablation:** jede Komponente einzeln entfernen; Sensitivität aller Schwellen ±25 %.
8. **Berichtet werden immer:** n, Winrate, Profit Factor, E[R] netto mit Intervall, max. Drawdown in R, Sharpe/Sortino
   (annualisiert, mit Hinweis auf Autokorrelation), Signale/Tag, Anteil Stopps, Stichprobenzeitraum, Lückenanteil.

**Stichprobenbedarf (MODELLANNAHME, einfache Rechnung, vorab):**
- Handelsmetrik: um +0,10 R einseitig (α 5 %, Power 80 %) zu erkennen, braucht es n ≈ (1,645 + 0,84)² · (σ/0,10)².
  Bei Ziel 2 R, Stop 1 R und Trefferquote ~1/3 ist σ ≈ √(9·p·(1−p)) ≈ 1,41 R, also **n ≈ 1.230 Trades**; bei +0,20 R ≈ 310.
  Holm über N Tests erhöht z weiter. σ in S40 aus S27/S35a ableiten.
- Prognosemetrik: um einen IC von 0,02 zu erkennen, braucht es n ≈ (2,49/0,02)² ≈ 15.400 **unabhängige** Beobachtungen,
  bei 1-h-Horizont rund 1,8 Jahre; bei 4-h- oder 24-h-Horizont nur nicht überlappende Fenster, also rund 7 bzw. 42 Jahre.
  Ein IC von 0,05 bräuchte ~2.500 Stunden ≈ 3,4 Monate (1-h-Horizont).
- Gleichzeitige Signale in BTC, ETH und SOL sind korreliert und werden geclustert, nicht als unabhängig gezählt.
- Folge: Vorwärts sind nur **große** Effekte in den ersten Monaten nachweisbar. Kleine Effekte bleiben "nicht prüfbar".

---

## 9. Erwartbare Fehlerquellen

| Fehler | Wo | Gegenmittel |
|---|---|---|
| Händler-Vorzeichen falsch | alle GEX-Kennzahlen | M0–M4 parallel, nur annahmeunabhängige Effekte zählen |
| OI veraltet (evtl. 8 h) | GEX, Wände | Datenalter je Schnappschuss, Modell "veraltet" |
| Zirkularität GEX ↔ Kurs | Regime | Rest nach vergangener Rendite (6.4/3) |
| Gamma außerhalb Deribit (CME, ETF-Optionen) | GEX unvollständig | Abdeckung schätzen und berichten; nicht als vollständig darstellen |
| Aggressor-Fehlklassifizierung | Blocktrades, Combos, Spot-Börsen ohne Seite | Blocks/Combos getrennt; nur Börsen mit Seite |
| Wash-Trading kleiner Börsen | Bitunix-Volumen | Bitunix nur als Bestätigung, nicht als Hauptquelle; Volumenplausibilität gegen Binance |
| Uhrzeitversatz zwischen Börsen | F10, Fusion | Versatz messen, gemeinsames Raster |
| Lücken im Recorder (z. B. Unterbrechung bis 21.11.) | alle Vorwärtsdaten | Lückentage zählen und ausschließen, nie füllen |
| Mehrfachtest über Programme hinweg | Familie Orderflow schon breit gesucht (OFX 32.000 Konfigurationen) | Deflated Sharpe gegen Gesamtzahl |
| Regimewechsel (Marktphase der Aufzeichnung) | Vorwärts nur eine Phase | Ergebnis als "eine Phase" kennzeichnen, Papier-Vorwärtslauf danach |
| Kosten unterschätzt | kurze Horizonte | Kosten ×1,5/×2, Maker-Annahme nie ohne Fill-Modell |
| 75-%-Ziel verleitet zu engem Ziel/weitem Stop | Regelentwurf | Netto-E[R] als Hauptkriterium |

---

## 10. TIM-Architekturvorschlag und Offline-Implementierungsplan (Phase 8)

**Rollen der Geräte** (nach `docs/ARCHITEKTUR_GERAETE.md`, Stand 17.11.; heute nicht neu geprüft):
Mac = einziger Schreiber der Live-Ströme (keine Änderung ohne Freigabe); PS5 = Rechnen auf **Kopien** (Replays,
Walk-forward), Zeuge; Server tim-core-01 = Archivkopie; PS4 = Backup. Neue Pakete laufen **offline** auf Kopien.

**Datenfluss (Vorschlag):** Recorder (bestehend) → Rohdateien → täglicher Export auf PS5/Server → Feature-Store
(Parquet/JSONL je Tag, Spalten mit `recv_ms`) → Label-Bau (Zukunftsrenditen, nur im Forschungsprozess) →
Modelle A0–A6 → Evidence Registry (`REGISTER.jsonl`, Gedächtnis G-Status) → Schatten-Spalte im Journal (nie Order).

**Pakete (je Paket nur auf Uzis "go"; jedes mit Prüfbefehl):**

| Paket | Inhalt | Ort | Prüfbefehl | Produktion berührt? |
|---|---|---|---|---|
| P0 | Datenreife-Bericht: Zählung, Lücken, Datenalter OI, Uhrzeitversatz je Recorder (nur lesen) | neu `src/research_lab/fusion/datenreife.py` | `pytest tests/test_fusion_datenreife.py -q` (Pfad nach Repo-Schema festlegen) + Lauf am Mac lesend | nein (liest Dateien) |
| P1 | Gamma-Modelle M0–M4, Forward je Verfall, USDC-Kontraktgröße aus API, Sensitivitätsgitter, Vanna/Charm | `src/options_gamma/models.py` (neu, `gex.py` unverändert) | Tests mit synthetischer Kette (`tests/fixtures/options_gamma/`), Nachrechnung gegen bestehendes `gex.py` für M0 | nein |
| P2 | Optionsflow-Merkmale Q2, Q4–Q10 | `src/research_lab/options_flow/features.py` erweitern | Unit-Tests + Lookahead-Test | nein |
| P3 | Orderflow-Merkmale F1–F10 als reine Funktionen auf Trades/L2 | `src/research_lab/fusion/of_features.py`, Wiederverwendung `of2`, `orderbook/walls.py`, `depth/replay.py` | Unit-Tests + Lookahead-Test | nein |
| P4 | Feature-Store + Label-Bau + Walk-forward-Gerüst A0–A6 | `src/research_lab/fusion/` | Rauchtest auf synthetischen Daten; keine echten Ergebnisse | nein |
| P5 | Präregistrierung S40 (H1–H3, Weg V) mit Schwellen, Stichprobenzielen, Abbruchkriterien | `docs/research_lab/studien/S40_..._PRAEREGISTRIERUNG.md` | Review `studien-pruefer`, Einfrieren nur auf Uzis Wort | nein |
| P6 | Verfallstest G7 (BTC, vorwärts; historisch nur mit Uzis Wort) | `src/research_lab/fusion/expiry.py` | Unit-Tests | nein |
| P7 | Recorder-Erweiterung ETH-Optionen, Vanna/IV je Strike mitschreiben | `src/research_lab/options_flow/recorder.py` | Tests, dann Mac-Dienst neu starten | **ja (Mac-Dienst)**, eigene Freigabe |
| P8 | Schatten-Anzeige der Regime im Journal/Control Center | Dashboard | `control-center-pruefer` | **ja (Anzeige)**, eigene Freigabe |

Nicht-Ziele: kein Live-Signal, keine Risiko-Engine-Änderung, kein Kauf von Daten, kein Holdout, keine neue
Orderflow-Rückschau ohne Uzis Wort.

---

## 11. Go/No-Go-Gates

| Gate | Phase | GO, wenn | NO-GO / Folge |
|---|---|---|---|
| G-A Datenreife | 2 | ≥ 60 Tage lückenarme Daten (Lücken > 10 min zusammen < 2 % der Zeit) für Gamma-Log, Optionsflow und Perp-Trades; OI-Datenalter geklärt | Recorder reparieren, Uhr läuft neu |
| G-B Gamma-Rechnung | 5 | (a) M0-Spot-Variante reproduziert `gex.py` innerhalb Toleranz; (b) Forward-Variante getrennt berichtet; M1–M4 auf synthetischer Kette plausibel; Inverse/linear-Test grün | nicht weiter zu H1 |
| G-C Gamma-Information | 5 | Mind. ein Gamma-Effekt (Vola) in Kalibrierung **annahmeunabhängig** im Sinn von 6.2 und über Basis B0 hinaus | Gamma nur noch Anzeige; H1/A3/A4 entfallen, Rest läuft |
| G-D Einfrieren S40 | 6 | Präregistrierung geprüft (`studien-pruefer`), Stichprobenziel erreichbar in ≤ 12 Monaten | Umfang verkleinern (weniger Modelle) |
| G-E Test | 7 | Testfenster n erreicht; einmalige Auswertung | "nicht prüfbar" berichten, nicht verlängern ohne neue Version |
| G-F Bestehen | 7 | Netto-E[R] > 0 mit Intervall > 0, Holm p < 0,05 über N, Deflated Sharpe ≥ 0,95, Vorzeichen in Kalibrierung gleich, mit `STRESS_COSTS` (×2, ohne Funding-Gutschrift) noch > 0 | "nicht bestanden", Ergebnis ins Gedächtnis |
| G-G Papier | 8 | Bestandene Regel ≥ 3 Monate Papier/Schatten mit gleichem Vorzeichen | kein Weg zu Echtgeld; `TRADING_AUTHORIZED=NO` bleibt |

---

## 12. Was noch nicht vorliegt (ausdrücklich)

- Keine Ergebnisse zu H1, H2, H3 und keinem der Modelle A0–A6.
- Keine Gamma-Modelle M1–M4 gerechnet; M0 nur als bestehender Indikator (T5–T7).
- Volltexte der Literatur nicht gelesen; G7 und G8 (die zwei Krypto-Gamma-Arbeiten) nicht geöffnet.
- Bitunix-API (Aggressor, Tiefe) nicht geprüft; CME/Cboe/Anbieterpreise nicht geprüft; 8-h-OI-Verzögerung nicht bestätigt.
- Laufstatus der Mac-Recorder heute nicht geprüft.
- Keine Hypothese wurde bestätigt.

## 13. Entscheidungen für Uzi

1. **"go P0–P4"**: Offline-Code bauen (Datenreife-Bericht, Gamma-Modelle, Merkmale, Testgerüst), nur Tests auf
   künstlichen Daten, keine Produktion. Danach Präregistrierung S40 als Entwurf.
2. **Historische Perp-Orderflow-Daten nutzen ja/nein** (Weg H): Binance-Archiv hat Perp-Trades mit Seite ab 2020 und
   Deribit-Optionstrades gratis. Das würde die Regel "Orderflow nur live" für trade-basierte Signale lockern.
   Ohne Uzis Wort bleibt es bei vorwärts.
3. **Datenkauf (Tardis o. ä.)**: weiterhin nein, bis G-C in den Vorwärtsdaten einen Hinweis zeigt.
4. **Vorwärtsdaten und Holdout-Sperre:** Daten ab 2025 sind im Code formal "Holdout". Für die eigene Aufzeichnung ab
   November 2026 braucht es einen getrennten, dokumentierten Weg; das ist eine Protokollfrage für Uzi (und Barti).

## 14. Eingearbeitete Prüfpunkte (studien-pruefer, 23.11.2026)

Bestätigt und geändert: M1/M2 ohne Regime (6.2, 7, G-C); Look-ahead bei Swing/Sweep (4) und Verfalls-Perzentil (5);
Testzahl N und Primärtests (7); Fenster nach `protocol.py` (8.1); Vorwärtsdaten vs. Holdout-Code (8.1, 13); Kostenhürde
`STRESS_COSTS` (8.4, G-F); Spot- vs. Forward-Gamma (6.1, G-B); Stichprobenbedarf mit σ 1,41 R und nicht überlappenden
Fenstern (8); eingefrorene Neuschätzung und 60 Tage Kalibrierung (8.1/8.2); Überschneidung mit S33 und Wand-Entwurf (5, 6.4);
S33 §2 überholt (1.7); `recv_ms` historisch (3); Kennzeichnung der Literatur (Literaturdatei); UTC, Lückenregel, Pfade.
Offen: Delta inverser Optionen (6.1), Grenze `MAX_REGISTER_ENTRIES` vor S40-Registrierung prüfen.
