# Orderflow × Optionsflow × Gamma: Literatur und Evidenztabelle (Phase 1)

Stand: 23.11.2026, Entwurf 0.1. Auftrag: Uzi, 23.11.2026 00:38 Ortszeit ("TIM Deep Research").
Gehört zu [FORSCHUNGSPLAN.md](FORSCHUNGSPLAN.md).

## Wie diese Liste entstanden ist (ehrlich)

- Bekannte Grundlagenarbeiten aus dem Fachwissen zusammengestellt; Existenz, Zeitschrift und Jahrgang der
  Kernarbeiten am 23.11.2026 per Websuche gegengeprüft (Treffer bei RePEc, SSRN, arXiv, Verlagsseiten).
- **Volltexte wurden nicht gelesen.** Inhaltsangaben stammen aus Abstract, Verlagsseite oder Fachwissen.
  Zahlen aus Arbeiten stehen nur dort, wo sie auf einer gelesenen Seite standen, und sind dann so markiert.
- Drei krypto-spezifische Gamma-Arbeiten wurden gefunden, ließen sich aber nicht öffnen (Verlag/SSRN blockt
  automatischen Abruf). Sie stehen als OFFEN in der Tabelle.
- TIMs eigene Befunde sind als GETESTET markiert, mit Verweis auf den Bericht. GETESTET heißt "gerechnet und
  dokumentiert", nicht "bestanden".

Kennzeichnung: **BELEGT** = begutachtete oder reproduzierte Arbeit mit klarer Aussage; **GETESTET** = TIM hat es selbst
gerechnet; **MODELLANNAHME** = Annahme eines Modells, nicht beobachtbar; **OFFEN** = nicht geprüft oder Datenlage fehlt;
**WIDERSPRUCH** = Quellen widersprechen sich.
Unterstufen: **BELEGT (Preprint)** = nicht begutachtet; **BELEGT (nur Abstract)** = begutachtet, aber nur Abstract/Teilseite
gelesen, Details ungeprüft.

## 1. Orderflow und Mikrostruktur

| # | Aussage | Quelle | Markt | Status | Was es für TIM heißt |
|---|---|---|---|---|---|
| O1 | Preisänderungen über kurze Intervalle hängen fast linear von der Order-Flow-Imbalance (OFI, Änderung von Best-Bid/Ask-Mengen) ab; Steigung umgekehrt proportional zur Markttiefe. | Cont, Kukanov, Stoikov (2014), *J. Financial Econometrics* 12(1) | US-Aktien | BELEGT | Gilt **gleichzeitig** (OFI erklärt die Bewegung im selben Intervall), nicht als Vorhersage über Stunden. |
| O2 | Mehrstufige OFI (mehrere Buchebenen) erklärt mehr als nur Best Bid/Ask. | Xu, Gould, Howison (2019), arXiv 1907.06230 | Nasdaq-Aktien | BELEGT (Preprint) | Braucht L2-Historie; TIM hat Binance-Tiefe erst seit 17.11. selbst aufgezeichnet. |
| O3 | Queue Imbalance am Best Bid/Ask sagt die Richtung der nächsten Preisänderung um einen Tick besser als Zufall voraus. | Gould, Bonart (2016), *Market Microstructure and Liquidity* 2(2) | Nasdaq-Aktien | BELEGT | Horizont: nächster Tick. Für Taker-Handel mit 0,06 % Gebühr je Seite ohne direkten Nutzen. |
| O4 | Microprice (mengengewichteter Mittelkurs) ist ein besserer Schätzer des "fairen" Kurses als der Mittelkurs. | Stoikov (2018), *Quantitative Finance* 18(12) | Aktien | BELEGT | Gutes Feature, kein Handelssignal an sich. |
| O5 | Buch-Imbalance verbessert Ausführung und kurzfristige Strategien (Marktmacher-Sicht). | Cartea, Donnelly, Jaimungal (2018), *Applied Mathematical Finance* 25(1) | Nasdaq | BELEGT | Wirkt vor allem für passive (Maker-)Strategien. TIM handelt in den Plänen als Taker. |
| O6 | Tiefe Netze auf OFI-Merkmalen sagen Renditen über mehrere kurze Horizonte vorher; Vorhersagekraft fällt mit dem Horizont stark ab. | Kolm, Turiel, Westray (2023), *Mathematical Finance* 33(4) | 115 Nasdaq-Aktien | BELEGT | Signal lebt im Bereich Sekunden bis Minuten. Ab Stunden kaum. |
| O7 | Universelle Merkmale der Preisbildung aus Orderbuchdaten, über Aktien übertragbar. | Sirignano, Cont (2019), *Quantitative Finance* 19(9) | US-Aktien | BELEGT | Nur Richtung des nächsten Mid-Wechsels; kein Nettoertrag nach Kosten. |
| O8 | DeepLOB: CNN/LSTM auf L2-Daten sagt kurzfristige Mid-Bewegung voraus. | Zhang, Zohren, Roberts (2019), *IEEE Trans. Signal Processing* 67(11) | LSE, FI-2010 | BELEGT | Wie O6/O7; Kosten nicht berücksichtigt. |
| O9 | OFI erklärt auch in Krypto (BitMEX XBTUSD) einen großen Teil kurzfristiger Preisänderungen; Trade-Imbalance schwächer als Buch-OFI. | Silantyev (2019), *Digital Finance* 1 | BitMEX | BELEGT (nur Abstract) | Einzige gefundene Krypto-OFI-Arbeit dieser Art; gleichzeitiger Zusammenhang. |
| O10 | VPIN (volumengetaktete Toxizität) steigt vor dem Flash Crash 2010. | Easley, López de Prado, O'Hara (2012), *Review of Financial Studies* 25(5) | E-mini S&P | BELEGT, aber siehe O11 | |
| O11 | VPIN sagt Turbulenz nicht zuverlässig voraus; Ergebnis hängt an Klassifizierung und Taktung, Spitze lag nach dem Crash-Beginn. | Andersen, Bondarenko (2014), *J. Financial Markets* 17 | E-mini S&P | **WIDERSPRUCH** zu O10 | VPIN höchstens als Volatilitäts-Kontext prüfen, nicht als Richtungssignal. |
| O12 | Order Flow hat lange Erinnerung (Vorzeichen von Market Orders sind über lange Zeit korreliert); Preiswirkung folgt etwa der Quadratwurzel der Menge. | Lillo, Farmer (2004), *Studies in Nonlinear Dynamics & Econometrics* 8(3); Bouchaud, Bonart, Donier, Gould (2018), *Trades, Quotes and Prices*, Cambridge UP | Aktien, Futures | BELEGT | Erklärt, warum "Imbalance hält an" oft schon eingepreist ist. |
| O13 | Spoofing-Händler erzielen Gewinne durch schnell gelöschte Orders; Erkennung über Lösch- und Platzierungsmuster. | Lee, Eom, Park (2013), *J. Financial Markets* 16(2) | Korea (KRX) | BELEGT | Muster beschreibbar; **Absicht** ist aus Daten nicht ableitbar. TIM benennt nur "spoofing-ähnlich". |
| O14 | Auf unregulierten Krypto-Börsen ist ein erheblicher Teil des gemeldeten Volumens Wash-Trading. | Cong, Li, Tang, Yang (2023), *Management Science* 69(11) | ~29 Krypto-Börsen | BELEGT | Datenqualität: Volumen kleiner Börsen (auch Bitunix, ungeprüft) nicht ungeprüft als echten Flow werten. |
| O15 | Preisunterschiede zwischen Börsen sind teils groß und hängen an Kapitalverkehrsgrenzen; gemeinsame Orderflow-Komponente treibt Preise. | Makarov, Schoar (2020), *J. Financial Economics* 135(2) | 34 Börsen | BELEGT | Begründet Multi-Exchange-Bestätigung (Signal 10), sagt aber nichts zu Nettoertrag. |
| O16 | Preisfindung bei BTC läuft vor allem über Derivate (Perps). | Alexander, Choi, Park, Sohn (2020), *J. Futures Markets* 40(1); Aleti, Mizrach (2021), *J. Futures Markets* 41(2) | BitMEX, CME, Spot | BELEGT | Perp-Flow wichtiger als Spot-Flow. PS5 hat live nur Spot (Lücke). |
| O17 | Absorption, Footprint, "Stacked Imbalances", Delta-Divergenz als Handelsregeln. | Händlerliteratur, Kurse (u. a. Bootcamp-Unterlagen im TIM-Ordner) | – | **OFFEN** (keine begutachtete Studie gefunden) | Nur als Hypothesen mit fester Regel prüfen. |

TIM-eigene Orderflow-Befunde (GETESTET, alle "nicht belegt"):

| # | Befund | Quelle in TIM |
|---|---|---|
| T1 | OF2 (Bootcamp-Regeln B1–B5), Training: 56 Trades in 3 Jahren, +0,27 R, nicht signifikant. | Gedächtnis, Studienregister |
| T2 | OFX-Suche: 27.597 (PS5) + 4.516 (PS4) Konfigurationen, 0 Kandidaten; am 16.11. gestoppt. | `docs/ARCHITEKTUR_GERAETE.md` |
| T3 | S35a Level + Orderflow-Bestätigung, 12 Konfigurationen, n 2.218–5.248: brutto −0,06 bis +0,06 R, netto −0,25 bis −0,41 R, nicht bestanden. Delta nur aus Minutenvolumen. | `docs/research_lab/studien/S35A_ZAEHLLAUF_ERGEBNIS.md` |
| T4 | Konsolidierung 16.11.: Orderflow-Familie "kein belastbarer Vorteil". | `docs/research_lab/konsolidierung/` |

**Zwischenurteil Orderflow:** BELEGT ist ein starker **gleichzeitiger** Zusammenhang zwischen Flow und Preis und eine
kurze Vorhersagekraft im Sekunden- bis Minutenbereich. **Nicht belegt** (in keiner gefundenen Arbeit) ist ein Vorteil
nach Taker-Kosten auf Horizonten von 15 Minuten bis Tagen, wie TIM ihn handeln will. TIMs eigene Tests passen dazu.

## 2. Optionsflow, Volatilität, Skew

| # | Aussage | Quelle | Markt | Status | Was es für TIM heißt |
|---|---|---|---|---|---|
| P1 | Optionsvolumen enthält Information über künftige Aktienkurse (informierte Händler nutzen Optionen). | Easley, O'Hara, Srinivas (1998), *J. Finance* 53(2) | US-Aktien | BELEGT | |
| P2 | Put/Call-Verhältnis aus **eröffnenden Käufen** sagt Aktienrenditen der nächsten Tage/Wochen vorher; öffentlich sichtbares Gesamtverhältnis kaum. | Pan, Poteshman (2006), *Review of Financial Studies* 19(3) | US-Aktien (CBOE Open/Close-Daten) | BELEGT | Wirkung hängt an "eröffnend und Käufer". Deribit veröffentlicht nicht, ob ein Trade eröffnet oder schließt. |
| P3 | Abweichungen von der Put-Call-Parität (Vol-Spread) und steiler Skew sagen Aktienrenditen vorher. | Cremers, Weinbaum (2010), *JFQA* 45(2); Xing, Zhang, Zhao (2010), *JFQA* 45(3) | US-Aktien | BELEGT | Querschnitt vieler Aktien; für einen einzelnen Markt (BTC) nicht übertragbar ohne eigenen Test. |
| P4 | Varianzrisikoprämie (implizit − realisiert) sagt Index-Renditen über Monate vorher. | Bollerslev, Tauchen, Zhou (2009), *Review of Financial Studies* 22(11) | S&P 500 | BELEGT | Horizont Monate, nicht Intraday. |
| P5 | Optionspreise werden von Nachfragedruck der Endkunden bestimmt (Händler können nicht perfekt absichern). | Gârleanu, Pedersen, Poteshman (2009), *Review of Financial Studies* 22(10) | S&P, Aktien | BELEGT | Grundlage, warum Flow die IV verschiebt; nicht Spot-Richtung. |
| P6 | Bei Deribit-BTC-Optionen treibt Netto-Kaufdruck die IV; bei OTM-Optionen deutet er auf Händler mit Richtungsinformation. | Alexander, Deng, Feng, Wan (2023), *J. Financial Markets*; arXiv 2109.02776 | Deribit BTC | BELEGT (nur Abstract) | Wichtigste Krypto-Quelle. Preisbildungsbefund, **kein** getesteter Futures-Handelsvorteil. |
| P7 | BTC-Volatilitätsindex und Varianzrisikoprämie lassen sich aus Deribit-Optionen bauen; VRP meist positiv, schwankt stark. | Alexander, Imeraj (2021), *J. Alternative Investments* 23(4) | Deribit BTC | OFFEN (aus Fachwissen, nicht gelesen) | DVOL ist so ein Index; V1/V3 im S33-Katalog prüfen genau das. |
| P8 | Gamma-Inventar der Market Maker hängt mit der **Liquidität der Optionen** zusammen (weniger Gamma-Inventar → breitere Spreads; laut Verlagsseite 1 Standardabw. weniger → +0,12 % bzw. +0,19 % Spread bei OTM-Calls/-Puts). | Atanasova, Miao, Segarra, Willeboordse (2025), *Finance Research Letters* 85, 108003 | Deribit BTC 2021–2024 | BELEGT (nur Abstract; Teil der Seite gelesen) | Wirkung auf **Optionsspreads**, nicht auf Spot-Richtung. Zeigt aber, dass MM-Positionen aus Daten geschätzt werden können. |
| P9 | Kurs-Richtung aus Put/Call-Meldungen, "Wal-Käufe", Skew-Kommentaren. | Medienberichte, Anbieter-Blogs | – | **OFFEN** (keine Statistik) | Nicht übernehmen ohne Test. |

## 3. Gamma Exposure, Dealer-Hedging, Verfall

| # | Aussage | Quelle | Markt | Status | Was es für TIM heißt |
|---|---|---|---|---|---|
| G1 | Aktienkurse "kleben" am Verfallstag an Strikes (Pinning); Mechanismus über Delta-Hedging der Optionsinhaber. | Ni, Pearson, Poteshman (2005), *J. Financial Economics* 78(1); Avellaneda, Lipkin (2003), *Quantitative Finance* 3(6) | US-Aktien | BELEGT | Verfallseffekt messbar, aber in Aktien mit bekannten Positionsdaten. |
| G2 | Delta-Hedging von Optionen beeinflusst die Volatilität der Basiswerte breit (Netto-Gamma der Händler negativ → mehr Vola). | Ni, Pearson, Poteshman, White (2021), *Review of Financial Studies* 34(4) | US-Aktien (mit Positionsdaten nach Händlertyp) | BELEGT | Nutzt **echte** Positionsdaten (Open/Close nach Kundentyp). Die hat Deribit nicht. |
| G3 | Hedging-Bedarf (Gamma der Händler negativ) erklärt Intraday-Momentum in Aktienindex-Futures: letzte halbe Stunde folgt der Tagesrendite. | Baltussen, Da, Lammers, Martens (2021), *J. Financial Economics* 142(1) | 60+ Index-Futures | BELEGT | Wichtigster Beleg für H1 (Regime ändert Flow-Wirkung). Index-Markt mit Börsenschluss; BTC handelt 24/7 ohne Schluss. |
| G4 | "Gamma Fragility": Gamma-Imbalance mal Illiquidität hängt mit Intraday-Momentum/Umkehr und Flash Crashes zusammen. | Barbon, Buraschi (2021), Working Paper | US-Aktien | BELEGT (Preprint; Abstract gelesen, Autoren aus Dateiname) | Stützt H1; nicht begutachtet. |
| G5 | 0DTE-Optionen (S&P) verstärken die Volatilität **nicht** messbar; Market Maker sind häufig netto long Gamma und dämpfen. | Dim, Eraker, Vilkov (2024), SSRN; Adams, Fontaine, Ornthanalai (2024), Working Paper; Cboe-Analysen | S&P 500 | **WIDERSPRUCH** zu verbreiteter Annahme "kurze Laufzeiten = Gamma-Verstärker" | Vorzeichen der Händler ist eine empirische Frage, nicht gegeben. |
| G6 | Ordervolatilität ist der Haupttreiber von 0DTE-Spreads; Gamma-Hedging nur zweitrangig. | Working Paper "Risky Intraday Order Flow and Option Liquidity" (Mai 2025, Autoren auf gelesener Seite nicht genannt) | S&P 500 | BELEGT (Preprint) | Wie G5. |
| G7 | Bei Deribit-BTC-Optionen 2021–2023: an Verfallstagen mit sehr hohem OI fällt der Spot ab etwa 1 h vor Verfall und kehrt binnen ~90 min um; signifikant nur bei ATM-OI über dem 90. Perzentil. | Weiss et al. (2026), *Finance Research Letters* 107, 110340, "Bitcoin option expiration, gamma exposure, and intraday price reversals" | Deribit BTC | **OFFEN** (nur Zusammenfassung einer Nachrichtenseite gelesen, Originalseite nicht abrufbar) | Einziger gefundener Krypto-Verfallsbefund. Testbar mit TIMs Daten (Deribit-Verfall 08:00 UTC). |
| G8 | "Do Gamma Walls Actually Move Bitcoin Prices at Deribit?" | Lachowicz, SSRN 5782822 | Deribit BTC | **OFFEN** (Seite nicht abrufbar, Inhalt unbekannt) | Vor S40-Freeze lesen (Mac-Browser). |
| G9 | Taker-Flow-basierte GEX: Händlerposition als Spiegel des kumulierten Taker-Flusses je Strike. | Glassnode Research (18.12.2025), Blog | Deribit | **MODELLANNAHME**, keine Statistik ("limited case study"), Methode nicht öffentlich | Methode ist mit TIMs Recorder nachbaubar (Gamma-Modell M3 im Plan). |
| G10 | GEX-Level als Support/Resistance, Gamma Flip als Regimegrenze. | SqueezeMetrics-Whitepaper (2017/2020), SpotGamma, Gexbot, Glassnode | Aktien/Krypto | **MODELLANNAHME** (Vorzeichen "Händler long Calls, short Puts" ist Annahme) | TIM nutzt dieselbe Annahme in `src/options_gamma/gex.py` (Kopfkommentar sagt das). |

TIM-eigene Gamma-Befunde (GETESTET):

| # | Befund | Quelle |
|---|---|---|
| T5 | Rechnung stimmt (Nachrechnung = TIM). Put Wall läuft dem Preis nach (49 % der Zeit ≤ 1,6 % unter Spot, 11 Wechsel/Tag); 36 Berührungen: 17 gebrochen, 11 gehalten, 8 offen. Regime 87 % negativ, folgt der 72-h-Rendite (r 0,41); 4-h-Spanne positiv/negativ kein belastbarer Unterschied. 14 Tage, beschreibend. | `/mnt/project-files/analysen/gamma-kritik-2026-11-17/gamma-kritik.md` |
| T6 | Mit Annahme "Händler short Calls und Puts" verschwindet der Flip, GEX −289 statt −126 Mio USD je 1 %. Der Flip hängt an der Vorzeichenannahme. | wie T5 |
| T7 | Historisch (Tardis-Gratistage, ein Schnappschuss je Monat): Training 01/2020–09/2022 Wände halten 66 % (58/88), Kontrolllinien auf 0,7×/1,3× Abstand 81 %; 2024 (11 Monate) 61 % (19/31) gegen 50 %. Richtung kippt, zusammen kein stabiler Vorteil; kleine n. | `/mnt/project-files/analysen/gexbot-playlists-2026-11-21/auswertung.md`, Nachtrag G |
| T8 | Gexbot-Videos (36): keine Statistik; Anbieter nutzt Level als Ziel, nicht als Einstieg. | wie T7 |

**Zwischenurteil Gamma:** In Aktienindizes ist BELEGT, dass Händler-Hedging Intraday-Muster und Volatilität mitprägt,
**wenn** die Händlerposition aus Positionsdaten bekannt ist. Bei kurzen Laufzeiten widersprechen sich die Befunde.
Für BTC fehlt diese Positionsinformation; jede GEX-Zahl ist eine Modellannahme. TIMs eigene Tests zeigen bisher
keinen Haltevorteil der Wände und ein Regime, das vor allem den vergangenen Kurs nachzeichnet.

## 4. Aktienindex- vs. Kryptooptionen (Unterschiede, die Übertragung erschweren)

| Punkt | S&P 500 / SPX | BTC/ETH auf Deribit | Status |
|---|---|---|---|
| Positionsdaten nach Kundentyp | Cboe Open-Close, OCC; Forschung nutzt sie (G2) | nicht veröffentlicht; nur OI und Trade-Seite (Taker) | BELEGT (Datenlage) |
| Wer ist Endkunde? | viele Covered-Call-/Put-Käufer, Fonds | großer Anteil Profis, Basis-/Vola-Händler, Strukturprodukte; Mischung unbekannt | OFFEN |
| Abrechnung | USD, bar | inverse Optionen in BTC/ETH (Prämie und Abrechnung in Coin), zusätzlich lineare USDC-Optionen | BELEGT (Deribit-Doku, TIM-Code) |
| Handelszeit | Börsenzeiten, Schlussauktion | 24/7, Verfall täglich/wöchentlich/monatlich/quartalsweise 08:00 UTC | BELEGT |
| Hedge-Instrument | Futures, ETFs | Perps auf vielen Börsen, Futures | BELEGT |
| Größe Optionsmarkt vs. Basis | SPX-Optionen groß gegen Futures-Volumen | 126 Mio USD GEX je 1 % gegen ~12,4 Mrd USD Binance-Perp-Tagesvolumen (T5, grob) | GETESTET (grob) |
| Neuer Faktor | 0DTE | Spot-ETF-Optionen (IBIT u. a.) seit Ende 2024: Teil des BTC-Gammas liegt außerhalb von Deribit | OFFEN (nicht erfasst) |

## 5. Methodik (für Phase 7)

| Thema | Quelle | Status |
|---|---|---|
| Purged/Embargoed CV, Kombinatorisches Purging | López de Prado (2018), *Advances in Financial Machine Learning*, Wiley | BELEGT |
| Deflated Sharpe Ratio | Bailey, López de Prado (2014), *J. Portfolio Management* 40(5) | BELEGT |
| Mehrfachtests, Schwelle t > 3 | Harvey, Liu, Zhu (2016), *Review of Financial Studies* 29(1) | BELEGT |
| Reality Check / SPA-Test | White (2000), *Econometrica* 68(5); Hansen (2005), *JBES* 23(4) | BELEGT |
| Test verschachtelter Prognosemodelle | Clark, West (2007), *J. Econometrics* 138(1) | BELEGT |
| Realisierte-Vola-Basis (HAR-RV) | Corsi (2009), *J. Financial Econometrics* 7(2) | BELEGT |
| Block-Bootstrap für abhängige Daten | Politis, Romano (1994), *JASA* 89(428) | BELEGT |
| Perps, Funding, Basis | He, Manela, Ross, von Wachter (2022), "Fundamentals of Perpetual Futures", arXiv 2212.06888 | BELEGT (Preprint) |

## 6. Geprüfte Links (23.11.2026)

- Barbon/Buraschi: https://abarbon.com/papers/gamma-fragility
- Baltussen et al.: https://econpapers.repec.org/RePEc:eee:jfinec:v:142:y:2021:i:1:p:377-403
- Ni/Pearson/Poteshman/White: https://ideas.repec.org/a/oup/rfinst/v34y2021i4p1952-1986..html
- Alexander et al.: https://arxiv.org/abs/2109.02776
- Atanasova et al.: https://www.sciencedirect.com/science/article/pii/S1544612325012619
- Weiss et al. (nicht geöffnet): https://www.sciencedirect.com/science/article/pii/S1544612326008688, Zusammenfassung: https://www.securities.io/bitcoin-options-expiration-spot-price-reversals/
- Lachowicz (nicht geöffnet): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5782822
- Glassnode Taker-Flow-GEX: https://research.glassnode.com/gamma-exposure/
- Kolm et al.: https://ideas.repec.org/a/bla/mathfi/v33y2023i4p1044-1081.html
- Silantyev: https://link.springer.com/doi/10.1007/s42521-019-00007-w
- Andersen/Bondarenko: https://econpapers.repec.org/RePEc:eee:finmar:v:17:y:2014:i:c:p:1-46
- 0DTE-Papiere: https://bauer.uh.edu/hdoshi/docs/DPS_May_2025.pdf, https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/
- CME Bitcoin-Optionen: https://www.cmegroup.com/markets/cryptocurrencies/files/bitcoin-product-comparison-guide.pdf
