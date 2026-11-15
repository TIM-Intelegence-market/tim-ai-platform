# Exo-Layout: Abgleich PDF (Resources_PDF) gegen den TIM-Chart

Stand 15.11.2026. Quelle: ExoCharts/TradingView-Workspace eines Dritten. Screenshots: `docs/dashboard/exo-layout/`
(Vorher = `tim:orderflow`, `tim:pro`; Nachher = `tim:exo`, `tim:exovp`, `tim:exotpo`; Desktop und Handy).
**Alle Bilder zeigen ERFUNDENE Testdaten** (`scripts/chart_exo_demo.py`), keinen Marktstand.

| Baustein im PDF | TIM vorher | Jetzt | 1:1? |
|---|---|---|---|
| Wochen-VWAP + ±std-Bänder | Linien (vorhanden) | zusätzlich schattiert (±1σ/±2σ) | ja |
| Periodic VP [Pt] (Lookback 240, VA 70 %, rechts, 130 Zeilen, Breite 40, Offset 13) | Tagesprofil fest 40 Zeilen | neue Ebene `vp_range` mit genau diesen Werten (`EXO.vp`) | Werte ja; Basis sind TIMs Footprint-Zeilen, nicht Börsen-Rohdaten |
| Fixed Range VP mit Node-Detection | fehlte | HVN hell, LVN gepunktet in `vp_range`; der Bereich ist fest die letzten 240 Kerzen, kein Ziehen eines eigenen Bereichs | teilweise |
| Market Order Bubbles (Medium ×3, Large ×4,5, Small aus, Strength-Gradient) | Bubbles relativ zur größten | Ebene `bubbles_exo`: nur ab 3× bzw. 4,5× Schnitt der Orders im Bild, Farbstärke nach Vielfachem | ja im Prinzip; Leviathans Schnitt-Formel ist unbekannt, hier Mittel der gezeigten Orders |
| Volume Bars, Bar-Volume + Delta, CVD | vorhanden (Volumen, `delta`, `cvd`) | unverändert im Layout | ja |
| Open Interest als Fenster | vorhanden | im Layout | ja |
| Liquidationsvolumen | `liqev` (echt, Binance + Bybit) | im Layout | ja, TIMs Quelle |
| VPOC mit Delta-Seite, Schwelle 50 %, Trapped (quantifytools) | fehlte | Ebene `vpoc`: Linie je Kerze, blau Käufer-/pink Verkäuferseite, orange ab 50 %, roter Ring = Trapped | teilweise |
| TPOC (Time-POC), LTF-Staffelung nach Chart-Zeit | fehlte | **nicht gebaut**: TIM speichert Trades in 5-min-Eimern, Zeit je Preis nicht genau genug | fehlt |
| TPO je Session (London, CME, Asia, Pre-Close) mit AMT-Regeln | TPO je Tag + Session-Hoch/Tief | Layout `tim:exotpo` kombiniert beides; **eigene Session-TPO-Profile fehlen** | teilweise |
| Footprint-Heatmap, Stacked Imbalance | vorhanden | `tim:exovp` nutzt Footprint-Stil „Profil" | ja |
| Net Shorts/Longs (ExoCharts-Schalter) | nur `liqev` | nicht eigens | fehlt |
| Velo.xyz, Hyblock, ATAS, ExoCharts, Sierra | – | Quellen des Traders, nicht nachgebaut | – |

Die neuen Ebenen starten ausgeblendet (nicht in `DEFAULT_GROUPS`). Layouts: `tim:exo`, `tim:exovp`, `tim:exotpo`
(ohne TIM-Basisebenen, wie im PDF). Die Einstellungen stehen als `EXO` in `tim_chart.js`.

Nächste Pakete: (1) Session-TPO (London/CME/Asia/Pre-Close) mit Serverseite, (2) TPOC mit feinerer Zeitbasis,
(3) Einstellungsfeld im Browser statt Konstanten.
