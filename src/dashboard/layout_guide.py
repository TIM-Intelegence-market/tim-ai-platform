"""Guide to the layouts of the TIM chart, in English and German (Uzi 28.11.2026).

Plain words for a reader with little trading knowledge: how to pick a layout, how to keep an own one, and what each
TIM layout shows. The page is open (no login), like the chart itself. One entry per layout in ``tim_chart.js``
(``TIM_LAYOUTS``); ``tests/test_layout_guide.py`` fails when a layout is added there without an entry here.
"""

from __future__ import annotations

from src.dashboard.helpers import _safe

# Layout id in tim_chart.js -> (English name on the page, German name, English: what you see, German, English: good for, German)
LAYOUTS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("tim:read", "Read", "Lesen",
     "The basic lines, the trading hours of Asia, London and New York, the average price (VWAP) and TIM's 1-hour plans.",
     "Grundlinien, Handelszeiten von Asien, London und New York, Durchschnittspreis (VWAP), TIMs Pläne auf 1 Stunde.",
     "A calm overview; the chart starts here.", "Start, ruhiger Überblick."),
    ("tim:orderflow", "Orderflow", "Orderflow",
     "Buying and selling at each price inside a candle (footprint), large single orders as bubbles, whether buyers or "
     "sellers push (CVD), open positions (open interest), real forced closes (liquidations), the average price.",
     "Kauf und Verkauf je Preis in der Kerze (Footprint), große Einzelorders als Blasen, ob Käufer oder Verkäufer drücken "
     "(CVD), offene Positionen (Open Interest), echte Zwangsschließungen (Liquidationen), Durchschnittspreis.",
     "Seeing who is pushing right now.", "Sehen, wer gerade Druck macht."),
    ("tim:footprint", "Footprint", "Footprint",
     "Buying minus selling as bars in every candle, large orders, buying and selling per candle at the bottom, open positions.",
     "Kauf minus Verkauf als Balken in jeder Kerze, große Orders, Kauf und Verkauf je Kerze unten, offene Positionen.",
     "Understanding the market candle by candle.", "Kerze für Kerze verstehen."),
    ("tim:tpo", "TPO", "TPO",
     "Day profiles made of letters: where the price spent how much time; a month profile, trading hours, the range of the first hour.",
     "Tagesprofile aus Buchstaben: wo der Preis wie lange war; Monatsprofil, Handelszeiten, Spanne der ersten Stunde.",
     "Where the market finds its \"fair\" price.", "Wo der Markt seinen \"fairen\" Preis findet."),
    ("tim:vp", "Volume profile", "Volume Profile",
     "How much was traded at each price (bars at the right of each day), the average price with its bands.",
     "Wie viel an jedem Preis gehandelt wurde (Balken rechts am Tag), Durchschnittspreis mit Bändern.",
     "Important prices with a lot of trading.", "Wichtige Preise mit viel Handel."),
    ("tim:positioning", "Positioning", "Positionierung",
     "Open positions, funding (shows whether too many bet on rising or falling prices), the price gap of US buyers "
     "(Coinbase premium), a liquidation map (an estimate only), real liquidations, option levels (gamma).",
     "Offene Positionen, Funding (zeigt, ob zu viele auf steigende oder fallende Kurse setzen), Preisunterschied bei "
     "US-Käufern (Coinbase-Premium), Liquidations-Karte (nur Schätzung), echte Liquidationen, Options-Level (Gamma).",
     "How the other traders are placed.", "Wie die anderen Händler aufgestellt sind."),
    ("tim:macro", "Macro", "Makro",
     "The share of Bitcoin and USDT in the crypto market, important US dates (inflation CPI, rate decision FOMC), quarter and year lines.",
     "Anteil von Bitcoin und USDT am Kryptomarkt, wichtige US-Termine (Inflation CPI, Zinsentscheid FOMC), Quartals- und Jahreslinien.",
     "The big picture and the dates when prices can jump.", "Großes Bild und Termine, an denen es knallen kann."),
    ("tim:trades", "TIM's trades", "TIMs Trades",
     "TIM's paper plans for short (15 min), mid (1 hour) and long (1 day). Visible after logging in.",
     "TIMs Papier-Pläne für kurz (15 Min), mittel (1 Std) und lang (1 Tag). Sichtbar nach dem Anmelden.",
     "Seeing where TIM would have entered (paper only, no real money).", "Sehen, wo TIM eingestiegen wäre (nur Papier, kein Echtgeld)."),
    ("tim:pro", "Orderflow Pro", "Orderflow Pro",
     "Bitcoin 15 min perp: buying and selling as a profile in the candle, large orders, trading per price, buying or "
     "selling pressure, open positions.",
     "Bitcoin 15 Min Perp: Kauf und Verkauf als Profil in der Kerze, große Orders, Handel je Preis, Kauf- oder "
     "Verkaufsdruck, offene Positionen.",
     "A close look at Bitcoin in the short run.", "Genauer Blick auf Bitcoin kurzfristig."),
    ("tim:exo", "Exo workspace", "Exo-Workspace",
     "Bitcoin 15 min perp without the basic lines: average price with bands, large orders, liquidations, open positions, buying and selling.",
     "Bitcoin 15 Min Perp ohne Grundlinien: Durchschnittspreis mit Bändern, große Orders, Liquidationen, offene Positionen, Kauf und Verkauf.",
     "A copy of the Exo template.", "Nachbau der Exo-Vorlage."),
    ("tim:exovp", "Exo profile", "Exo-Profil",
     "Bitcoin 15 min perp: trading per price over the last 240 candles, the price with the most trading in each candle, large orders.",
     "Bitcoin 15 Min Perp: Handel je Preis über die letzten 240 Kerzen, Preis mit dem meisten Handel je Kerze, große Orders.",
     "The Exo template, seen as a profile.", "Nachbau der Exo-Vorlage, Profil-Blick."),
    ("tim:exotpo", "Exo TPO", "Exo-TPO",
     "Bitcoin 30 min perp: letter profiles, trading hours, open trading prices, trading per price.",
     "Bitcoin 30 Min Perp: Buchstaben-Profile, Handelszeiten, offene Handelspreise, Handel je Preis.",
     "The Exo template, seen in time.", "Nachbau der Exo-Vorlage, Zeit-Blick."),
    ("tim:usdtd", "USDT.D", "USDT.D",
     "The share of the stablecoin USDT in the crypto market (1 hour): highs and lows with their value, two average lines, "
     "the latest floor and ceiling.",
     "Anteil der Stablecoin USDT am Kryptomarkt (1 Std): Hochs und Tiefs mit Wert, zwei Durchschnittslinien, letzte "
     "Unter- und Obergrenze.",
     "The mood of the whole crypto market: when USDT.D rises, people often take money out of crypto.",
     "Stimmung im ganzen Kryptomarkt: steigt USDT.D, ziehen Leute oft Geld aus Krypto ab."),
    ("tim:gammazones", "Gamma zones", "Gamma-Zonen",
     "Bitcoin 30 min perp: yellow bands at option prices where a large wall of orders stands in the order book, thin "
     "option lines, the day lines as next targets, buying and selling per candle.",
     "Bitcoin 30 Min Perp: gelbe Bänder an Options-Preisen, an denen im Orderbuch eine große Wand aus Orders steht, "
     "dünne Options-Linien, Tageslinien als nächste Ziele, Kauf und Verkauf je Kerze.",
     "Seeing how the price reacts at these zones.", "Sehen, wie der Preis an diesen Zonen reagiert."),
    ("tim:ai", "TIM AI overlay", "TIM-KI-Deutung",
     "Bitcoin 30 min: TIM's explanation as boxes right on the chart, plus buying and selling per candle and option lines. "
     "Only a logged-in visitor sees the boxes.",
     "Bitcoin 30 Min: TIMs Erklärung als Kästen direkt im Chart, dazu Kauf und Verkauf je Kerze und Options-Linien. "
     "Die Kästen sieht nur, wer angemeldet ist.",
     "Understanding how TIM reads the chart.", "TIMs Lesart des Charts verstehen."),
    ("tim:standard", "TIM standard", "TIM Standard",
     "Every standard layer at once.", "Alle Standard-Ebenen auf einmal.",
     "A large screen; too full on a phone.", "Großer Bildschirm; am Handy zu voll."),
)

TEXT = {
    "en": {
        "title": "Layout guide",
        "intro": "How to use the layouts of the TIM chart and what each one shows. In plain words.",
        "what_h": "What is a layout?",
        "what": ["A layout is a ready-made set of lines and displays for the chart. Instead of ticking many boxes yourself, "
                 "you pick a layout and get, with one click, everything that belongs to one question, for example "
                 "\"Who is buying right now, who is selling?\"."],
        "pick_h": "How to pick a layout",
        "pick": ["Open the <a href='/chart'>chart</a>.",
                 "Above the chart there is <b>Layout</b> with a drop-down list. Tap it and choose a layout.",
                 "Some layouts switch coin, timeframe or market by themselves (for example to Bitcoin, 15 minutes, perp). "
                 "That is on purpose, so the picture fits.",
                 "On your very first visit the chart starts with the layout <b>Read</b>."],
        "market": "<b>Spot or perp:</b> spot is buying Bitcoin itself, perp are futures (trading with leverage). Some "
                  "displays look different on perp, because other people trade there.",
        "own_h": "Change and keep your own layout",
        "own": ["<b>Change single layers:</b> open \"Edit layout\" and switch ticks on or off. The list then says \"changed, not saved\".",
                "<b>Save your own layout:</b> \"Save as…\" and give it a name. It then shows under \"My layouts\". "
                "Rename and Delete work only for your own layouts.",
                "<b>Note:</b> your own layouts live only in this browser. Phone and computer have separate layouts, "
                "and clearing the browser data removes them.",
                "<b>Footprint button next to the layout:</b> switches how buying and selling inside a candle are drawn "
                "(numbers, bars or profile).",
                "<b>2 charts:</b> opens a second chart next to the first, with its own coin, timeframe and layout.",
                "<b>Untick all</b> empties the chart, <b>Reset lines</b> brings back the default."],
        "base_h": "What almost every TIM layout always shows",
        "base_intro": "So you find your way in every layout, these lines are almost always there:",
        "base": ["<b>Important prices of the day, week and month</b>, for example high, low and the price with the most trading.",
                 "<b>Open trading prices</b> (naked POC): prices where a lot was traded before and that the price has not "
                 "reached again since. The price often comes back to them.",
                 "<b>Structure</b> (BOS / MSS): marks when the trend goes on or turns.",
                 "<b>Trend lines</b>."],
        "base_note": "Without these basic lines (\"clean\"): the three Exo layouts, USDT.D, Gamma zones and TIM AI overlay.",
        "table_h": "All layouts at a glance",
        "cols": ("Layout", "What you see", "Good for"),
        "know_h": "Good to know",
        "know": ["<b>No layout is a buy or sell signal.</b> The layouts show and explain.",
                 "The <b>legend</b> below the chart (tap to open) explains every colour and symbol.",
                 "<b>Controls:</b> mouse wheel = zoom, drag = move. Phone: two fingers = zoom, one finger = move. "
                 "\"Go to now\" jumps to the last candle, \"Show all\" shows the whole history.",
                 "<b>Tip to start:</b> Read for the overview, TIM's trades to see TIM's plans, Gamma zones or TIM AI "
                 "overlay for an explanation on Bitcoin."],
    },
    "de": {
        "title": "Layout-Anleitung",
        "intro": "Wie man die Layouts im TIM-Chart benutzt und was jedes zeigt. In einfachen Worten.",
        "what_h": "Was ist ein Layout?",
        "what": ["Ein Layout ist eine fertige Zusammenstellung von Linien und Anzeigen für den Chart. Statt viele einzelne "
                 "Haken zu setzen, wählst du ein Layout und bekommst mit einem Klick alles, was zu einer Frage gehört, "
                 "zum Beispiel \"Wer kauft gerade, wer verkauft?\".",
                 "Die Knöpfe im Chart sind englisch. Die englischen Namen stehen hier in Klammern."],
        "pick_h": "So wählst du ein Layout",
        "pick": ["Öffne den <a href='/chart'>Chart</a>.",
                 "Über dem Chart steht <b>Layout</b> mit einem Auswahlfeld. Antippen und ein Layout wählen.",
                 "Manche Layouts stellen selbst Münze, Zeitrahmen oder Markt um (zum Beispiel auf Bitcoin, 15 Minuten, "
                 "Perp). Das ist gewollt, damit das Bild passt.",
                 "Beim allerersten Besuch startet der Chart mit dem Layout <b>Lesen</b> (Read)."],
        "market": "<b>Spot oder Perp:</b> Spot ist der normale Kauf von Bitcoin, Perp sind die Futures (Handel mit Hebel). "
                  "Manche Anzeigen sehen auf Perp anders aus, weil dort andere Leute handeln.",
        "own_h": "Selbst anpassen und speichern",
        "own": ["<b>Einzelne Ebenen ändern:</b> \"Layout bearbeiten\" (Edit layout) aufklappen und Haken an- oder ausmachen. "
                "Danach steht im Auswahlfeld \"geändert, nicht gespeichert\" (changed, not saved).",
                "<b>Eigenes Layout speichern:</b> \"Speichern unter…\" (Save as…) und einen Namen geben. Es erscheint dann "
                "unter \"Eigene Layouts\" (My layouts). Umbenennen und Löschen geht nur bei eigenen Layouts.",
                "<b>Achtung:</b> Eigene Layouts liegen nur in diesem Browser. Handy und Computer haben getrennte Layouts, "
                "und wer die Browserdaten löscht, verliert sie.",
                "<b>Footprint-Knopf neben dem Layout:</b> wechselt die Darstellung der Kauf- und Verkaufszahlen in der "
                "Kerze (Zahlen, Balken oder Profil).",
                "<b>2 Charts</b> (2 charts): öffnet einen zweiten Chart daneben, mit eigener Münze, eigenem Zeitrahmen und eigenem Layout.",
                "<b>Alles abwählen</b> (Untick all) macht den Chart leer, <b>Linien zurücksetzen</b> (Reset lines) holt die Grundeinstellung zurück."],
        "base_h": "Was fast jedes TIM-Layout immer zeigt",
        "base_intro": "Damit du dich in jedem Layout zurechtfindest, sind diese Linien fast immer dabei:",
        "base": ["<b>Wichtige Preise von Tag, Woche und Monat</b>, zum Beispiel Hoch, Tief und der Preis mit dem meisten Handel.",
                 "<b>Offene Handelspreise</b> (naked POC): Preise, an denen früher sehr viel gehandelt wurde und die der "
                 "Kurs seitdem nicht mehr erreicht hat. Der Kurs läuft oft dorthin zurück.",
                 "<b>Struktur</b> (BOS / MSS): Markierungen, wenn der Trend weiterläuft oder kippt.",
                 "<b>Trendlinien</b>."],
        "base_note": "Ohne diese Grundlinien (\"sauber\"): die drei Exo-Layouts, USDT.D, Gamma-Zonen und TIM-KI-Deutung.",
        "table_h": "Alle Layouts auf einen Blick",
        "cols": ("Layout", "Was du siehst", "Gut für"),
        "know_h": "Wichtig zu wissen",
        "know": ["<b>Kein Layout ist ein Kauf- oder Verkaufssignal.</b> Die Layouts zeigen und erklären.",
                 "Die <b>Legende</b> unter dem Chart (aufklappen) erklärt jede Farbe und jedes Symbol.",
                 "<b>Bedienung:</b> Mausrad = zoomen, ziehen = verschieben. Am Handy: zwei Finger = zoomen, ein Finger = "
                 "verschieben. \"Zu jetzt\" (Go to now) springt zur letzten Kerze, \"Alles zeigen\" (Show all) zeigt den ganzen Verlauf.",
                 "<b>Tipp zum Start:</b> Lesen für den Überblick, TIMs Trades um TIMs Pläne zu sehen, Gamma-Zonen oder "
                 "TIM-KI-Deutung für eine Erklärung an Bitcoin."],
    },
}


def guide_body(lang: str) -> str:
    """The page body (without the frame) in English or German; any other value gives English."""
    de = lang == "de"
    t = TEXT["de" if de else "en"]

    def tab(code: str, label: str, current: bool) -> str:
        return (f"<a class='pj-tab{' pj-tab--active' if current else ''}' href='/guide?lang={code}'"
                + (" aria-current='page'" if current else "") + f"><b>{label}</b></a>")

    def items(rows: list[str], tag: str = "ul") -> str:
        return f"<{tag}>" + "".join(f"<li>{row}</li>" for row in rows) + f"</{tag}>"

    switch = ("<nav class='pj-tabs pj-tabs--small' aria-label='Language'>"
              + tab("en", "English", not de) + tab("de", "Deutsch", de) + "</nav>")
    # One card per layout instead of a table: a table needs sideways scrolling on a phone.
    cards = ""
    see_label, good_label = t["cols"][1], t["cols"][2]
    for _, name_en, name_de, see_en, see_de, good_en, good_de in LAYOUTS:
        name = _safe(name_en)
        if de:
            name = _safe(name_de) + (f" ({_safe(name_en)})" if name_en.lower() != name_de.lower() else "")
        cards += (f"<div class='detail'><h3>{name}</h3><p><b>{_safe(see_label)}:</b> {_safe(see_de if de else see_en)}</p>"
                  f"<p><b>{_safe(good_label)}:</b> {_safe(good_de if de else good_en)}</p></div>")
    paragraphs = "".join(f"<p>{text}</p>" for text in t["what"])
    return (
        f"<div class='hero'><div><h1>{_safe(t['title'])}</h1><p>{_safe(t['intro'])}</p></div></div>"
        f"<section class='cc-section'>{switch}<h2>{t['what_h']}</h2>{paragraphs}</section>"
        f"<section class='cc-section'><h2>{t['pick_h']}</h2>{items(t['pick'], 'ol')}<p>{t['market']}</p></section>"
        f"<section class='cc-section'><h2>{t['own_h']}</h2>{items(t['own'])}</section>"
        f"<section class='cc-section'><h2>{t['base_h']}</h2><p>{t['base_intro']}</p>{items(t['base'])}<p>{t['base_note']}</p></section>"
        f"<section class='cc-section'><h2>{t['table_h']}</h2><div class='detail-grid'>{cards}</div></section>"
        f"<section class='cc-section'><h2>{t['know_h']}</h2>{items(t['know'])}</section>"
    )
