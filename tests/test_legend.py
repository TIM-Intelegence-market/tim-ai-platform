"""Legende (src/dashboard/legend.py): jede Ebene des Charts und jede Kachel muss erklärt sein."""
from __future__ import annotations

import re
from pathlib import Path

from src.dashboard.chart_live import GROUP_NAMES, GROUP_STYLE
from src.dashboard.cockpit.mac import SERVICES
from src.dashboard.cockpit.tiles import STATES
from src.dashboard.legend import LAYERS, STATE_INFO, TILES, chart_legend, render_legend_page, swatch
from src.dashboard.public_en import GROUPS_EN

ROOT = Path(__file__).resolve().parents[1]
TILE_FILES = ("src/dashboard/cockpit/lage.py", "src/dashboard/cockpit/mac.py", "src/dashboard/own_data.py",
              "src/dashboard/cockpit/hermes.py", "src/dashboard/cockpit/markt.py")


def test_every_chart_layer_is_explained_in_both_languages() -> None:
    assert set(LAYERS) == set(GROUP_NAMES) == set(GROUPS_EN)
    assert all(LAYERS[key] for key in LAYERS)
    de, en = chart_legend("de"), chart_legend("en")
    for key in GROUP_NAMES:
        assert GROUP_NAMES[key].replace("&", "&amp;") in de
        assert GROUPS_EN[key].replace("&", "&amp;") in en


def test_line_swatches_use_the_colours_the_chart_draws() -> None:
    for key, marks in LAYERS.items():
        if key in GROUP_STYLE and key not in {"structure", "gamma", "liq", "liqev", "macro", "fib"}:
            assert marks[0][0] == ("line", *GROUP_STYLE[key]), key


def test_every_cockpit_tile_is_explained() -> None:
    explained = {tile_id.split("{")[0] for tile_id, *_ in TILES}
    found: set[str] = {key for _, key, *_ in SERVICES}
    for name in TILE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        found |= set(re.findall(r'(?:make_tile|unavailable)\(\s*f?"([a-z_]+)', text))
        found |= set(re.findall(r'tile_id, name(?:, source)? = f?"([a-z_]+)', text))
    found -= {"runtime_none", "sec_none", "status", "gesperrt"}
    missing = {tile for tile in found if not any(tile == e or tile.startswith(e) for e in explained)}
    assert not missing, f"Kachel ohne Legende: {sorted(missing)}"


def test_states_and_page() -> None:
    assert [key for key, *_ in STATE_INFO] == list(STATES)
    page = render_legend_page()
    assert "<h1>Legende</h1>" in page and "Bybit-Orderflow (Bubbles)" in page and "Liquidationen (echt, Binance + Bybit)" in page
    assert " style=" not in chart_legend("de") and " style=" not in chart_legend("en")  # feste CSP: keine Inline-Styles


def test_english_legend_has_no_german_text() -> None:
    en = chart_legend("en")
    for word in (" und ", " oder ", "Kerze", "Linie", "gestrichelt", "Ortszeit"):
        assert word not in en, word


def test_swatch_escapes_values() -> None:
    assert "<script" not in swatch(("text", "#fff", "<script>"))
