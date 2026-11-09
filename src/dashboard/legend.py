"""Legende für TIM-Chart und Control Center: was jede Ebene, Farbe, jedes Symbol und jede Kachel bedeutet.

Eine Quelle für drei Stellen (Uzi 09.11.2026):

* aufklappbare Legende unter dem Chart (``chart_legend("de")`` im Control Center,
  ``chart_legend("en")`` auf der öffentlichen Seite),
* die Seite ``/legende`` im Control Center (``render_legend_page``) mit Chart, Ampelfarben und Kacheln.

Die Farben kommen, wo es sie gibt, direkt aus dem Code (``GROUP_STYLE``, ``gamma_data.LEVEL_STYLE``,
``liquidation_data.LEVEL_COLOR``); ``tests/test_legend.py`` prüft, dass jede Ebene des Charts und jede
Kachel hier steht. Kommt eine neue Ebene oder Kachel dazu, wird die Suite rot, bis sie erklärt ist.
Begriffe wie Imbalance, Absorption oder CVD sind in ``docs/knowledge/ORDERFLOW_BEGRIFFE.md`` definiert;
die Legende sagt nur, wie sie im Bild aussehen.

Die Swatches sind kleines Inline-SVG mit Präsentationsattributen (kein ``style=``), damit die feste
Content-Security-Policy der Seiten gilt.
"""

from __future__ import annotations

from typing import Any

from src.dashboard.chart_live import GROUP_NAMES, GROUP_STYLE
from src.dashboard.gamma_data import LEVEL_STYLE as GAMMA
from src.dashboard.helpers import _safe
from src.dashboard.liquidation_data import LEVEL_COLOR as LIQ

GREEN, RED = "#26a69a", "#ef5350"
BUY, SELL = "#26dc96", "#ff5c58"  # Ringfarben der Bubbles und Liquidations-Dreiecke
PLAN_ENTRY, PLAN_STOP, PLAN_TARGET = "#70a7ff", "#ff6577", "#35d39a"
GLOSSARY = "https://github.com/TIM-Intelegence-market/tim-ai-platform/blob/platform-main/docs/knowledge/ORDERFLOW_BEGRIFFE.md"

Swatch = tuple[Any, ...]
Mark = tuple[Swatch, str, str]  # (Swatch, Deutsch, Englisch)


def _line(group: str) -> Swatch:
    color, style = GROUP_STYLE[group]
    return ("line", color, style)


# Grundlagen, die immer zu sehen sind.
BASICS: list[Mark] = [
    (("candle", GREEN), "Kerze grün: Schluss über Eröffnung", "Green candle: close above open"),
    (("candle", RED), "Kerze rot: Schluss unter Eröffnung", "Red candle: close below open"),
    (("bar", "rgba(38,166,154,0.5)"), "Balken unten: Volumen der Kerze (Farbe wie die Kerze)", "Bars at the bottom: candle volume (colour of the candle)"),
    (("text", "#c3cad6", "1D"), "Linienname = Zeitrahmen + Name, z. B. 1D VAH, 1W POC; ← = Beginn links außerhalb", "Line label = timeframe + name, e.g. 1D VAH, 1W POC; ← = starts left of the loaded candles"),
    (("text", "#c3cad6", "↔"), "Zeilen oben: Werte unter dem Fadenkreuz; Zeiten in deutscher Ortszeit", "Top row: values under the crosshair; times in Central European time"),
]

# Je Ebene (Haken über dem Chart) die Zeichen, die sie malt. Schlüssel = chart_live.GROUP_NAMES.
LAYERS: dict[str, list[Mark]] = {
    "day": [(_line("day"), "Vortag: Hoch, Tief, POC, VAH, VAL (blau, durchgezogen)", "Prior day: high, low, POC, VAH, VAL (blue, solid)")],
    "week": [(_line("week"), "Vorwoche: Hoch, Tief, POC, VAH, VAL (lila)", "Prior week: high, low, POC, VAH, VAL (purple)")],
    "month": [(_line("month"), "Vormonat: Hoch, Tief, POC, VAH, VAL (orange)", "Prior month: high, low, POC, VAH, VAL (orange)")],
    "quarter": [(_line("quarter"), "Vorquartal: Hoch, Tief, POC, VAH, VAL (dunkleres Orange)", "Prior quarter: high, low, POC, VAH, VAL (darker orange)")],
    "year": [(_line("year"), "Vorjahr: Hoch, Tief, POC, VAH, VAL (pink)", "Prior year: high, low, POC, VAH, VAL (pink)")],
    "vwap": [(_line("vwap"), "VWAP der laufenden Woche, des Monats, Quartals und Jahres (türkis)", "VWAP of the running week, month, quarter and year (teal)")],
    "vwap_bands": [(_line("vwap_bands"), "Bänder um den Wochen-VWAP: ±1σ und ±2σ (türkis gepunktet)", "Bands around the weekly VWAP: ±1σ and ±2σ (teal, dotted)")],
    "naked": [(_line("naked"), "naked POC: alter POC, den der Kurs seitdem nicht berührt hat (gelb gestrichelt, Magnet)", "Naked POC: an old POC price has not touched since (yellow, dashed; a magnet)")],
    "running": [(_line("running"), "laufender POC von Tag und Woche, wandert noch (hellblau gepunktet)", "Running POC of day and week, still moving (light blue, dotted)")],
    "session": [(_line("session"), "Hoch und Tief der Sessions Asien, London, New York (grau gepunktet)", "High and low of the Asia, London and New York sessions (grey, dotted)")],
    "ib": [(_line("ib"), "Initial Balance: Hoch und Tief der ersten 90 Minuten des Handelstags ab 01:00 (Sommerzeit 02:00)", "Initial balance: high and low of the first 90 minutes of the trading day from 00:00 UTC")],
    "structure": [
        (("arrow_up", "#35d39a"), "BOS / MSS nach oben (grün), zählt nur per Schlusskurs", "BOS / MSS up (green), counts only on a close"),
        (("arrow_down", "#ff5c6c"), "BOS / MSS nach unten (rot)", "BOS / MSS down (red)"),
        (("line", "#ffb020", "dashed"), "offenes Strong Low/High und BOS-Ziel (gestrichelt bis jetzt)", "Open strong low/high and BOS target (dashed, up to now)"),
    ],
    "trend": [(_line("trend"), "Trendlinie über Hochs oder Tiefs, endet am Bruch (pink)", "Trend line through highs or lows, ends at its break (pink)")],
    "fib": [
        (("line", "#ff9800", "solid"), "Fibonacci auf dem letzten großen Swing: 1 = Start, 0 = Ende", "Fibonacci on the last big swing: 1 = start, 0 = end"),
        (("box", "rgba(76,175,80,0.25)", "#4caf50"), "Zonen 0,236 bis 1 farbig wie in TradingView, dazu 0,886 / 0,941 / 1,618", "Zones 0.236 to 1 coloured as in TradingView, plus 0.886 / 0.941 / 1.618"),
    ],
    "tpo": [
        (("box", "rgba(94,200,216,0.38)", "none"), "TPO-Tagesprofil aus 30-min-Perioden (Buchstaben A, B, C …), Value Area heller", "TPO day profile from 30-min periods (letters A, B, C …), value area lighter"),
        (("box", "rgba(245,197,66,0.70)", "none"), "POC gelb", "POC yellow"),
        (("box", "rgba(255,159,67,0.55)", "none"), "Single Prints orange (nur eine Periode)", "Single prints orange (one period only)"),
    ],
    "vp": [
        (("box", "rgba(76,141,255,0.42)", "none"), "Volume Profile je Tag rechts am Tagesende, Value Area kräftiger (70 % des Volumens)", "Volume profile per day at the day's right edge, value area stronger (70 % of volume)"),
        (("box", "rgba(245,197,66,0.75)", "none"), "POC gelb", "POC yellow"),
        (("bar", "rgba(38,166,154,0.9)"), "grüner / roter Strich je Stufe = Delta (Käufer / Verkäufer)", "Green / red tick per row = delta (buyers / sellers)"),
    ],
    "fp": [
        (("box", "rgba(38,166,154,0.45)", "none"), "mittlerer Zoom: Farbsäule je Kerze, grün/rot = Delta, kräftig = viel Volumen", "Medium zoom: colour column per candle, green/red = delta, strong = high volume"),
        (("text", "#3ee6c4", "4:1"), "nah: Bid × Ask je Stufe; Imbalance 4:1 fett, türkis = Käufer", "Close up: bid × ask per row; 4:1 imbalance bold, teal = buyers"),
        (("text", "#ff6b6b", "4:1"), "Imbalance der Verkäufer fett rot", "Seller imbalance bold red"),
        (("bar", "#3ee6c4"), "Balken an der Seite: gestapelte Imbalances (3 und mehr in Folge)", "Bar at the side: stacked imbalances (3 or more in a row)"),
        (("box", "none", "#f5c542"), "POC der Kerze gelb umrandet", "Candle POC framed yellow"),
        (("line", "#ffa726", "dotted"), "unfertige Auktion am Hoch/Tief (orange gepunktet)", "Unfinished auction at the high/low (orange, dotted)"),
    ],
    "bubbles": [
        (("dot", "rgba(38,200,140,0.30)", BUY, False), "große Market Order Käufer, Binance (grün gefüllt)", "Large market buy order, Binance (filled green)"),
        (("dot", "rgba(239,83,80,0.30)", SELL, False), "große Market Order Verkäufer, Binance (rot gefüllt)", "Large market sell order, Binance (filled red)"),
        (("dot", "none", BUY, True), "hohl mit gestricheltem Ring = Bybit (nur Perp)", "Hollow with dashed ring = Bybit (perp only)"),
        (("text", "#e8edf5", "12"), "Fläche = Größe gegenüber der größten im Bild, Zahl = Größe in BTC; ab 100.000 $", "Area = size against the largest in view, number = size in BTC; from 100,000 $"),
    ],
    "plans_short": [(("line", PLAN_ENTRY, "solid"), "Pläne der 15m-Regel (SHORT-Horizont), Zeichen wie unten", "Plans of the 15m rule (SHORT horizon), marks as below")],
    "plans_mid": [(("line", PLAN_ENTRY, "solid"), "Pläne der 1h-Regel (MID-Horizont)", "Plans of the 1h rule (MID horizon)")],
    "plans_long": [(("line", PLAN_ENTRY, "solid"), "Pläne der 1D-Regel (LONG-Horizont)", "Plans of the 1D rule (LONG horizon)")],
    "plans_old": [(("line", PLAN_ENTRY, "dashed"), "frühere Testversionen auf 30m (TIM-, Struktur-, VP-Regel)", "Earlier test versions on 30m (TIM, structure, VP rule)")],
    "gamma": [
        (("line", *GAMMA["call_wall"]), "Call Wall (grün): größter Call-Bestand, oft Widerstand", "Call wall (green): largest call open interest, often resistance"),
        (("line", *GAMMA["put_wall"]), "Put Wall (rot): größter Put-Bestand, oft Unterstützung", "Put wall (red): largest put open interest, often support"),
        (("line", *GAMMA["flip"]), "Gamma Flip (gelb): darüber dämpfen Händler, darunter verstärken sie", "Gamma flip (yellow): above it dealers dampen moves, below they amplify"),
        (("line", *GAMMA["max_pain"]), "Max Pain (grau gestrichelt)", "Max pain (grey, dashed)"),
        (("line", *GAMMA["em_high"]), "erwartete Spanne oben/unten aus den Optionspreisen (gepunktet)", "Expected move up/down from option prices (dotted)"),
    ],
    "liq": [
        (("line", LIQ["above"], "dashed"), "Schätzung: Liquidations-Cluster über dem Kurs (Shorts), orange", "Estimate: liquidation cluster above price (shorts), orange"),
        (("line", LIQ["below"], "dashed"), "Schätzung: Cluster unter dem Kurs (Longs), blau; Modell, keine echten Ereignisse", "Estimate: cluster below price (longs), blue; a model, not real events"),
    ],
    "liqev": [
        (("tri_down", "rgba(239,83,80,0.55)", SELL), "echte Long-Liquidation = Zwangsverkauf (rotes Dreieck nach unten)", "Real long liquidation = forced sell (red triangle pointing down)"),
        (("tri_up", "rgba(38,200,140,0.55)", BUY), "echte Short-Liquidation = Zwangskauf (grünes Dreieck nach oben)", "Real short liquidation = forced buy (green triangle pointing up)"),
        (("tri_down", "none", SELL), "hohles Dreieck = Bybit, gefüllt = Binance; Zahl = Betrag in $", "Hollow triangle = Bybit, filled = Binance; number = size in $"),
    ],
    "cvd": [
        (("line", "#5ec8d8", "solid"), "CVD Spot (hellblau): laufende Summe des Deltas", "CVD spot (light blue): running sum of delta"),
        (("line", "#ffb020", "solid"), "CVD Perp (orange); Spot und Perp nie addiert", "CVD perp (orange); spot and perp never added"),
    ],
    "delta": [
        (("line", "#5b7cfa", "solid"), "Delta je Kerze: blau = mehr Marktkäufe, rot = mehr Marktverkäufe", "Delta per candle: blue = more market buys, red = more market sells"),
        (("line", "#e8ecf3", "solid"), "weiße Linien = Schwelle für ungewöhnlich großes Delta (90 % der Kerzen liegen darunter)", "White lines = threshold for unusually large delta (90% of candles stay below)"),
    ],
    "oi": [
        (("line", "#c3cad6", "solid"), "Open Interest Binance (grau), Band unter dem Chart", "Open interest Binance (grey), band below the chart"),
        (("line", "#f7a35c", "solid"), "Open Interest Bybit (orange), gleiche Skala in BTC", "Open interest Bybit (orange), same scale in BTC"),
        (("bar", "rgba(255,107,61,0.85)"), "Z-Score-Säulen: orange ≥ +2 (ungewöhnlich viel), blau ≤ −2, grau dazwischen", "Z-score columns: orange ≥ +2 (unusually high), blue ≤ −2, grey in between"),
    ],
    "funding": [(("bar", "rgba(255,107,61,0.85)"), "Funding je 8 h: orange = hoch (Longs zahlen viel), blau = negativ, grau = normal", "Funding per 8 h: orange = high (longs pay a lot), blue = negative, grey = normal")],
    "premium": [(("box", "rgba(38,166,154,0.28)", GREEN), "Coinbase-Premium: grün über 0 (US-Käufer zahlen mehr), rot unter 0", "Coinbase premium: green above 0 (US buyers pay more), red below 0")],
    "dominance": [
        (("line", "#f7931a", "solid"), "BTC-Dominanz (orange), täglich", "BTC dominance (orange), daily"),
        (("line", "#26a17b", "solid"), "USDT-Dominanz (grün): steigt meist, wenn Geld aus Krypto in Stablecoins geht", "USDT dominance (green): usually rises when money leaves crypto for stablecoins"),
    ],
    "macro": [
        (("square", "#f0b429"), "US-CPI oder FOMC, bereits veröffentlicht (gelbes Quadrat über der Kerze)", "US CPI or FOMC, already released (yellow square above the candle)"),
        (("square", "#8491a3"), "kommender Termin (graues Quadrat rechts der letzten Kerze, bis 14 Tage voraus)", "Upcoming release (grey square right of the last candle, up to 14 days ahead)"),
    ],
}

# Zeichen, die alle Plan-Ebenen gemeinsam haben.
PLAN_MARKS: list[Mark] = [
    (("line", PLAN_ENTRY, "solid"), "Einstieg (blau; gestrichelt = wartet noch auf Füllung)", "Entry (blue; dashed = still waiting for a fill)"),
    (("line", PLAN_STOP, "dashed"), "Stop-Loss SL (rot gestrichelt)", "Stop loss SL (red, dashed)"),
    (("line", PLAN_TARGET, "dotted"), "Ziele TP1, TP2 … (grün gepunktet)", "Targets TP1, TP2 … (green, dotted)"),
    (("box", "rgba(38,166,154,0.22)", "rgba(38,166,154,0.8)"), "Positionsbox: grün bis zum Ziel, rot bis zum Stop; blass = geschlossen", "Position box: green to target, red to stop; faded = closed"),
    (("arrow_up", PLAN_TARGET), "Pfeil = gefüllt (grün nach oben Long, rot nach unten Short)", "Arrow = filled (green up long, red down short)"),
    (("dot", PLAN_TARGET, PLAN_TARGET, False), "Kreis = geschlossen, mit Ergebnis in R (grün Gewinn, rot Verlust, grau ±0)", "Circle = closed, with result in R (green win, red loss, grey ±0)"),
    (("line", "#ffb020", "solid"), "orange Stufenlinie = nachgezogener Stop (Läufer)", "Orange step line = trailing stop (runner)"),
]

# Ampelfarben der Kacheln (cockpit.tiles.STATES).
STATE_INFO: list[tuple[str, str, str]] = [
    ("ok", "Grün · OK", "geprüft gesund und frisch."),
    ("warn", "Gelb · Prüfen", "bitte ansehen: veraltet, wartet, teilweise oder eingeschränkt. Der Grund steht in der Kachel."),
    ("fail", "Rot · Fehler", "ein gemessener Fehler. Der Grund steht in der Kachel, ein Klick führt zu den Details."),
    ("unknown", "Grau · Keine Daten", "keine Daten oder bewusst aus. Auch hier steht immer der Grund dabei."),
]
STATE_COLOR = {"ok": "#35d39a", "warn": "#f0b429", "fail": "#ff5c6c", "unknown": "#8491a3"}

# Kacheln im Control Center: (id, Name wie in der Kachel, Bereich, was sie zeigt).
# Ids mit {sym} gibt es je Coin (BTC ohne Endung, sonst _eth, _sol …).
TILES: list[tuple[str, str, str, str]] = [
    ("runtime", "TIM-Laufzeit", "System", "Läuft TIMs Hauptprozess, seit wann, und welche Prüfungen gerade scheitern."),
    ("market_data", "Marktdaten", "System", "Wie alt die letzten Binance-Spot-Daten sind; gelb/rot, wenn der Datenstrom stockt."),
    ("database", "Datenbank", "System", "Ist PostgreSQL verbunden."),
    ("watchdog", "Watchdog", "System", "Ergebnis des Wächters, der TIM alle 30 s prüft und bei drei roten Runden neu startet."),
    ("deploy", "Deploy-Stand", "System", "Welcher Commit läuft und ob der Dashboard-Agent ihn sauber nachgezogen hat."),
    ("ci", "CI-Test", "System", "Ergebnis des letzten vollen Testlaufs zum laufenden Stand (grün/rot gezählt)."),
    ("backup", "Backup", "System", "Größe und Alter der letzten Sicherung; gelb, wenn sie zu alt ist."),
    ("price", "BTC-Preis", "Markt", "Letzter BTC-Schlusskurs aus TIMs Kerzen."),
    ("market_state", "Marktzustand", "Markt", "Was TIMs Analyse auf 30m sieht (z. B. Trend, Range) und der Auktionszustand."),
    ("setup", "Setup-Pfad", "Markt", "Entscheidung der 30m-Pipeline: Plan, warten oder kein Trade, und was noch fehlt."),
    ("block", "Nächste Sperrzeit", "Markt", "Nächste Handelssperre um die NY-Eröffnung (15 min davor bis 30 min danach)."),
    ("bias", "Übergeordneter Bias", "Markt", "Richtung aus der Vorbereitung: 1h-Struktur, Tages- und Wochen-Value."),
    ("orderflow", "Orderflow", "Markt", "Live-Orderflow-Lage: Delta, Absorption, Imbalances der letzten Kerzen (nur Beobachtung)."),
    ("plan_journal", "Plan-Journal", "Journale", "Papier-Pläne von TIM: offen, gefüllt, Ergebnis in R. Rot = Ereignislog beschädigt."),
    ("trader_journal", "Trader-Journal", "Journale", "Deine eigenen eingetragenen Trades."),
    ("own_data", "Eigene Daten", "System", "Zusammenfassung von TIMs eigener Datensammlung (Trades, OI, Gamma, Bybit)."),
    ("own_perp{sym}", "Perp-Orderflow", "Betrieb", "Sammler der Binance-Perp-Trades je Coin: Tage gespeichert, Neuverbindungen."),
    ("own_oi{sym}", "Open Interest 1h", "Betrieb", "Gespeicherte Stunden Open Interest je Coin."),
    ("own_bybit", "Bybit-Orderflow (Bubbles)", "Betrieb", "Sammler der Bybit-Perp-Trades für die hohlen Bubbles: Tage gespeichert, Neuverbindungen in 24 h."),
    ("own_liq_{venue}", "Liquidationen Binance / Bybit", "Betrieb", "Rohdaten der echten Liquidationen je Börse (Quelle der Dreiecke im Chart)."),
    ("own_gamma", "Gamma-Walls", "Betrieb", "Gespeicherte Schnappschüsse von Call/Put Wall und Gamma Flip (alle 5 min)."),
    ("own_backup", "Kopie eigene Daten", "Betrieb", "Tägliche Kopie der eigenen Daten: wann zuletzt, wie groß, ob vollständig."),
    ("own_gaps", "Datenlücken (Nachholer)", "Betrieb", "Offene Lücken in den eigenen Daten und ob der Nachholer sie füllt."),
    ("hermes", "TIM-KI (Hermes)", "Cockpit", "Läuft der lokale KI-Agent Hermes (liest TIM nur, kann nicht handeln)."),
    ("hermes_mcp", "TIM-Anbindung", "TIM-KI", "Ob Hermes TIMs Daten lesen kann."),
    ("hermes_model", "Modell", "TIM-KI", "Welches Sprachmodell Hermes gerade nutzt."),
    ("worker", "Issue-Worker", "Mac", "Der Mac-Worker, der GitHub-Issues abarbeitet: frei, arbeitet, hängt."),
    ("ci_runner", "CI-Runner", "Mac", "Ob auf dem Mac gerade ein Testlauf läuft."),
    ("queue", "Warteschlange", "Mac", "Issues, die bereit sind, und alle offenen."),
    ("last_done", "Zuletzt erledigt", "Mac", "Letztes vom Worker erledigtes Issue mit PR."),
    ("model", "Lokales Modell", "Mac", "Lokales Sprachmodell (Ollama) des Workers."),
    ("trading_team", "Trading-Team", "Mac", "Papier-Trading-Team: offene Papier-Trades und Schatten-Einträge."),
    ("validator", "Validator", "Mac", "Forschungs-Validator: letzter Prüflauf der Research-Fälle."),
    ("server_health", "Server-Health", "Mac", "Sammelbericht der Systemprüfungen (CPU, Speicher, Dienste)."),
    ("history_recovery", "Lückenreparatur", "Mac", "Holt fehlende Kerzen nach Ausfällen nach."),
    ("readiness_inputs", "Readiness-Eingaben", "Mac", "Eingaben der früheren V2-Bereitschaft (Archiv)."),
    ("dashboard_refresh", "Dashboard-Agent", "Mac", "Zieht nach einem Merge den neuen Stand auf den Mac und startet die Seiten neu."),
]


# --- Zeichnen ------------------------------------------------------------------

_DASH = {"solid": "", "dashed": " stroke-dasharray='5 3'", "dotted": " stroke-dasharray='1.5 2.5'"}


def swatch(spec: Swatch) -> str:
    """Kleines SVG-Zeichen (28 × 14) für eine Legendenzeile."""
    kind = spec[0]
    c = [_safe(str(v)) for v in spec[1:]]
    if kind == "line":
        inner = f"<line x1='1' y1='7' x2='27' y2='7' stroke='{c[0]}' stroke-width='2'{_DASH.get(spec[2], '')}/>"
    elif kind == "box":
        inner = f"<rect x='3' y='2' width='22' height='10' rx='1' fill='{c[0]}' stroke='{c[1]}'/>"
    elif kind == "bar":
        inner = f"<rect x='10' y='2' width='8' height='11' fill='{c[0]}'/>"
    elif kind == "candle":
        inner = f"<line x1='14' y1='0' x2='14' y2='14' stroke='{c[0]}'/><rect x='10' y='3' width='8' height='8' fill='{c[0]}'/>"
    elif kind == "dot":
        dash = " stroke-dasharray='3 2'" if spec[3] else ""
        inner = f"<circle cx='14' cy='7' r='5.5' fill='{c[0]}' stroke='{c[1]}' stroke-width='1.3'{dash}/>"
    elif kind in ("tri_up", "tri_down"):
        points = "14,2 20,12 8,12" if kind == "tri_up" else "14,12 20,2 8,2"
        inner = f"<polygon points='{points}' fill='{c[0]}' stroke='{c[1]}' stroke-width='1.3'/>"
    elif kind in ("arrow_up", "arrow_down"):
        points = "14,1 20,8 16,8 16,13 12,13 12,8 8,8" if kind == "arrow_up" else "14,13 20,6 16,6 16,1 12,1 12,6 8,6"
        inner = f"<polygon points='{points}' fill='{c[0]}'/>"
    elif kind == "square":
        inner = f"<rect x='9' y='2' width='10' height='10' fill='{c[0]}'/>"
    elif kind == "state":
        inner = f"<circle cx='14' cy='7' r='5' fill='{c[0]}'/>"
    else:  # text
        inner = f"<text x='14' y='11' text-anchor='middle' font-size='10' font-weight='700' fill='{c[0]}'>{c[1]}</text>"
    return f"<svg class='lg-sw' width='28' height='14' viewBox='0 0 28 14' aria-hidden='true'>{inner}</svg>"


def _rows(marks: list[Mark], en: bool) -> str:
    return "".join(f"<li>{swatch(sw)}<span>{_safe(text_en if en else text_de)}</span></li>" for sw, text_de, text_en in marks)


def _layer_title(key: str, en: bool) -> str:
    if en:
        from src.dashboard.public_en import GROUPS_EN

        return GROUPS_EN.get(key, key)
    return GROUP_NAMES.get(key, key)


def chart_blocks(lang: str = "de") -> str:
    """Alle Chart-Abschnitte als Liste von Blöcken (für Chart-Legende und Seite /legende)."""
    en = lang == "en"
    blocks = [f"<div class='lg-block'><h4>{'Basics' if en else 'Grundlagen'}</h4><ul>{_rows(BASICS, en)}</ul></div>"]
    for key in GROUP_NAMES:
        blocks.append(f"<div class='lg-block'><h4>{_safe(_layer_title(key, en))}</h4><ul>{_rows(LAYERS[key], en)}</ul></div>")
        if key == "plans_old":
            title = "TIM plans: marks" if en else "TIM-Pläne: Zeichen"
            blocks.append(f"<div class='lg-block'><h4>{title}</h4><ul>{_rows(PLAN_MARKS, en)}</ul></div>")
    return "".join(blocks)


def chart_legend(lang: str = "de") -> str:
    """Aufklappbare Legende unter dem Chart; zu, damit sie am Handy nicht im Weg ist."""
    en = lang == "en"
    if en:
        head = "Legend: what every line, colour and symbol means"
        foot = (f"Terms such as delta, imbalance or absorption: <a href='{GLOSSARY}' rel='noopener noreferrer'>orderflow glossary</a>. "
                "Display only, no orders.")
    else:
        head = "Legende: was jede Linie, Farbe und jedes Symbol bedeutet"
        foot = ("Ganze Legende mit Ampelfarben und Kacheln: <a href='/legende'>Legende</a>. "
                "Begriffe wie Delta, Imbalance, Absorption: Orderflow-Glossar <code>docs/knowledge/ORDERFLOW_BEGRIFFE.md</code>.")
    return (f"<details class='cc-section tc-lgd' id='legende'><summary>{head}</summary>"
            f"<div class='lg-grid'>{chart_blocks(lang)}</div><p class='cc-note'>{foot}</p></details>")


def render_legend_page() -> str:
    """Seite /legende im Control Center: Ampel, Kacheln, Chart."""
    from src.dashboard.layout import _layout

    states = "".join(
        f"<li>{swatch(('state', STATE_COLOR[key]))}<span><b>{_safe(name)}</b>: {_safe(text)}</span></li>" for key, name, text in STATE_INFO)
    tiles = "".join(
        f"<tr><td><b>{_safe(label)}</b></td><td>{_safe(area)}</td><td>{_safe(text)}</td></tr>" for _, label, area, text in TILES)
    body = (
        "<div class='hero'><div><h1>Legende</h1><p>Was die Farben, Kacheln, Ebenen und Symbole in Control Center und TIM-Chart bedeuten. "
        "Begriffe wie Delta, Imbalance oder Absorption sind im Orderflow-Glossar definiert "
        "(<code>docs/knowledge/ORDERFLOW_BEGRIFFE.md</code>).</p></div></div>"
        "<section class='cc-section'><h2>Ampelfarben</h2><p class='cc-note'>Jede Kachel und jeder Punkt im Control Center folgt derselben Regel. "
        "Eine Kachel, die nicht grün ist, nennt immer den Grund; zu alte Daten machen sie mindestens gelb.</p>"
        f"<ul class='lg-list'>{states}</ul></section>"
        "<section class='cc-section'><h2>Kacheln</h2><p class='cc-note'>Wert oben, Grund darunter, Quelle und Alter klein. "
        "Ein Klick auf die Kachel öffnet die Detailseite.</p>"
        f"<div class='table-wrap lg-tiles'><table><thead><tr><th>Kachel</th><th>Bereich</th><th>Was sie zeigt</th></tr></thead><tbody>{tiles}</tbody></table></div></section>"
        "<section class='cc-section'><h2>TIM-Chart</h2><p class='cc-note'>Jede Ebene lässt sich über die Haken über dem Chart ein- und ausblenden. "
        "Spot/Perp wählt, aus welchen Trades Profil, Footprint und Delta kommen. Nur Anzeige, keine Order.</p>"
        f"<div class='lg-grid'>{chart_blocks('de')}</div></section>"
    )
    return _layout("Legende", "Legende", body, refresh=False)
