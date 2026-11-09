# Perp-Orderflow im TIM-Chart (F5 aus dem Beirat vom 29.10.2026)

Broncx liest Orderflow auf dem BTC-Perp (Binance Futures). Dort läuft 8- bis 12-mal so viel Volumen wie
auf Spot, und das Delta kann gegen Spot laufen (27.10.2026: Spot +2534 BTC, Perp −1844 BTC). Bis F5 sah
TIM nur Spot. Alles hier ist Anzeige, nichts davon handelt, schreibt einen Plan oder ändert eine Bewertung.

## Was der Chart zeigt

- **Umschalter Spot / Perp** neben „Footprint“: wählt die Trades für Volume Profile, Footprint, Delta und
  Volume Bubbles. Die Level (Tag, Woche, naked POCs) bleiben auf Spot. Die Wahl merkt sich der Browser.
- **CVD Spot vs. Perp** (Ebene „CVD Spot vs. Perp“): kumuliertes Delta beider Märkte über die gezeigten
  Kerzen, beide ab derselben Kerze. Jede Linie hat ihre eigene Skala, weil Perp viel mehr Volumen hat.
  Zu lesen ist die Richtung: läuft Perp gegen Spot, kauft oder verkauft der Hebel gegen die Kasse.
  Ab 5m, auf 1m nicht (die Trades liegen in 5-Minuten-Fächern).
- **Open Interest + Z-Score (7,5 T)**: OI des BTC-Perps je Stunde (Linie) und sein Z-Score über die
  letzten 180 Stunden (Balken). Orange ab +2, blau ab −2: ungewöhnlich viel bzw. wenig offene Positionen.
- **Statuszeile:** „Perp-Prüfung: x/y h gleich mit Binance, n Lücken“.

## Wie gesammelt wird (`src/dashboard/perp_flow.py`)

- Die Runtime liest `/fapi/v1/aggTrades` mit `fromId`. Jede Id folgt auf die letzte, deshalb merkt der
  Sammler jede Lücke. Er hält höchstens 60 Abrufe pro Minute (Gewicht 1200 von 2400), eingeholt alle 2 s.
- Die Trades werden sofort in dieselben Zeilen wie der Spot-Speicher verdichtet (5-Minuten-Fach, 5-$-Stufe,
  Bid = Verkäufer aggressiv, Ask = Käufer aggressiv) plus große Taker-Orders ab 100.000 $ für die Bubbles.
  Rohtrades bleiben nicht liegen.
- Gespeichert wird jede Minute unter `data/perp_flow/` (ein gzip-JSON je UTC-Tag plus `state.json` mit der
  nächsten Id), 14 Tage. Nach einem Neustart liest die Runtime ab dieser Id weiter, so entsteht keine Lücke.
  Ist der Stand älter als 13 Tage, beginnt sie neu ab 00:00 UTC des Vortags und vermerkt das als Lücke.
- Erster Start: ab 00:00 UTC des Vortags. Das Einholen dauert je nach Markt ein bis zwei Stunden; bis dahin
  zeigt der Umschalter Spot und einen Hinweis.
- Ein Tag gilt als vollständig, wenn er ohne Lücke von 00:00 bis 24:00 UTC gelesen wurde.
- Alle 10 Minuten vergleicht der Sammler die letzten drei vollen Stunden mit der 1h-Kerze von Binance
  (Volumen und Taker-Kaufvolumen, Toleranz 0,01 BTC).
- Open Interest: `/futures/data/openInterestHist`, 1h, 500 Werte (etwa 20 Tage), alle 5 Minuten.
- Zweite Börse (seit 09.11.2026, Issue #162): Bybit `GET /v5/market/open-interest` (`category=linear`,
  `intervalTime=1h`, 200 Stunden), alle 5 Minuten im selben Takt, nur BTCUSDT. Der Chart zeigt im Band
  „Open Interest“ je Börse eine Linie in BTC (Binance grau, Bybit orange) und die Summe als `total_last`;
  der Z-Score bleibt auf Binance, dessen Historie länger ist. Archiv `data/perp_flow/oi-BTCUSDT-bybit-1h.jsonl`.
  Fällt Bybit aus, bleibt Binance allein stehen (Hinweis „Open Interest nur Binance“).
- Zweite Börse für die Bubbles (seit 09.11.2026, Issue #162): `src/dashboard/bybit_flow.py` liest den
  öffentlichen Websocket `publicTrade.BTCUSDT` (`wss://stream.bybit.com/v5/public/linear`, derselbe Host
  wie der S12-Sammler), fasst die Trades wie der Binance-Sammler zu Zeilen und Bubbles zusammen (5-$-Stufen,
  5-Minuten-Eimer, Taker-Order = gleiche Millisekunde und Seite, ab 100 000 $) und speichert je UTC-Tag unter
  `data/bybit_flow/`. Ein Websocket hat keine Id zum Wiederaufsetzen: `segments` hält die verbundenen
  Strecken, ein Tag gilt nur als vollständig, wenn eine Strecke ihn deckt; nach 3 Minuten ohne Trade wird
  neu verbunden. Im Perp-Modus mischt der Chart die Bybit-Bubbles unter die Binance-Bubbles (`venue` je
  Bubble, Bybit hohl mit gestricheltem Rand); Footprint, CVD, Volume Profile und Level bleiben Binance.
  Betriebsseite: Kachel „Bybit-Orderflow (Bubbles)“.
  Älter als 3 Stunden wird es ausgeblendet.

## Nachweis vor dem Bau (F4, 29.10.2026)

Testsammler auf dem Mac, 29.10. 10:40 bis 18:31 Ortszeit: 525.663 Trades, 0 Id-Lücken, alle 7 vollen
Stunden in Volumen und Taker-Delta gleich mit den Binance-Kerzen (höchstens 0,00003 %). Plattenplatz etwa
20 MB pro Tag als CSV.gz, verdichtet deutlich weniger. Der Testsammler lief als nohup-Prozess und endete
nach knapp 8 Stunden ohne Fehlermeldung. Deshalb läuft der Sammler jetzt in der TIM-Runtime selbst
(launchd mit KeepAlive) und setzt nach jedem Neustart fort.
