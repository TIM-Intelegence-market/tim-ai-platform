"""Live crypto order book page (/orderbuch): depth chart and liquidity heatmap from a public exchange WebSocket.

Read-only and keyless. The browser connects to the exchange itself (Binance first, Coinbase as
fallback), so the TIM server stores nothing and sends no orders. The page therefore needs its own
CSP: the common policy plus 'self' scripts and exactly the exchange hosts below in connect-src.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.dashboard.layout import _content_security_policy, _hero, _layout, _strip_states

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
CORE_PATH = "/assets/orderbook/orderbook_core.js"
APP_PATH = "/assets/orderbook/orderbook.js"
ORDERBOOK_SCRIPTS = {
    CORE_PATH: (_ASSETS / "orderbook_core.js").read_bytes(),
    APP_PATH: (_ASSETS / "orderbook.js").read_bytes(),
}
# Only these exchange endpoints may be contacted from the page (public market data, no keys).
EXCHANGE_CONNECT = (
    "wss://stream.binance.com:9443",
    "https://api.binance.com",
    "wss://ws-feed.exchange.coinbase.com",
)
ORDERBOOK_CSP = (
    _content_security_policy()
    .replace("script-src ", "script-src 'self' ", 1)
    .replace("connect-src 'self'", "connect-src 'self' " + " ".join(EXCHANGE_CONNECT), 1)
)

# Styles come as a style attribute-free block: the CSP allows only the hashed common stylesheet, so
# the page-specific rules live in extra.css (EXTRA_CSS) and are picked up by the hash automatically.

_BODY = """
<section class='card ob'>
  <div class='ob-bar'>
    <label>Markt <select id='ob-coin'><option value='BTC'>BTC</option><option value='ETH'>ETH</option><option value='SOL'>SOL</option></select></label>
    <label>Quelle <select id='ob-source'><option value='auto'>Binance, sonst Coinbase</option><option value='binance'>nur Binance</option><option value='coinbase'>nur Coinbase</option></select></label>
    <b id='ob-status' data-kind='wait'>Startet …</b>
  </div>
  <div id='ob-metrics' class='ob-metrics'></div>
</section>
<section class='card ob'>
  <h2>Tiefendiagramm</h2>
  <p class='ob-note'>Kumulierte Menge je Preis, ±1 % um die Mitte. Grün = Gebote, rot = Angebote. Steile Wand = viel Liquidität an einem Preis.</p>
  <canvas id='ob-depth' data-h='300' aria-label='Tiefendiagramm'></canvas>
</section>
<section class='card ob'>
  <h2>Liquiditäts-Heatmap</h2>
  <p class='ob-note'>Ruhende Aufträge im Orderbuch über die Zeit (eine Spalte pro Sekunde, rund 8 Minuten), ±1 % um die Mitte. Weiße Linie = Mittelpreis.
  Das ist sichtbare Liquidität, keine Ausführung: Aufträge können jederzeit zurückgezogen werden (Spoofing).</p>
  <canvas id='ob-heat' data-h='380' aria-label='Liquiditäts-Heatmap'></canvas>
</section>
<section class='card ob'>
  <h2>Orderbuch</h2>
  <div class='ob-ladder'><div id='ob-asks'></div><div class='ob-midrow'><b id='ob-mid'>–</b><span id='ob-tick'></span></div><div id='ob-bids'></div></div>
</section>
<p class='ob-note'>Quelle: öffentliche Börsen-WebSockets, ohne Zugangsdaten. Nur Lesen, keine Orders (TRADING bleibt LOCKED). Die Daten gehen direkt vom Browser zur Börse.</p>
<script src='{core}'></script><script src='{app}'></script>
"""


def render_orderbook_page(state: Any) -> str:
    data = state.snapshot()
    body = _hero("Orderbuch live", "Live-Orderbuch per öffentlichem WebSocket mit Tiefendiagramm und Liquiditäts-Heatmap. Nur Lesen.")
    body += _BODY.format(core=CORE_PATH, app=APP_PATH)
    return _layout("Orderbuch", "Orderbuch", body, strip=_strip_states(data), refresh=True)
