"""Layout guide on the public view (Uzi 28.11.2026): open without login, English and German, one entry per TIM layout."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from urllib.request import Request, urlopen

from src.dashboard.layout_guide import LAYOUTS, guide_body
from src.dashboard.public_en import NAV
from tests.test_public_dashboard import server  # noqa: F401 - fixture

CHART_JS = Path(__file__).resolve().parents[1] / "src" / "dashboard" / "assets" / "tim_chart.js"


def _open(url: str):
    with urlopen(Request(url, headers={}), timeout=10) as response:  # no login header at all
        return response.status, dict(response.headers), response.read().decode()


def test_every_tim_layout_has_an_entry():
    block = CHART_JS.read_text().split("const TIM_LAYOUTS = [", 1)[1].split("];", 1)[0]
    in_chart = re.findall(r"id: '(tim:[a-z]+)'", block)
    assert in_chart and [item[0] for item in LAYOUTS] == in_chart


def test_guide_is_in_the_menu_next_to_the_chart():
    assert NAV[:2] == (("/chart", "Chart"), ("/guide", "Layout guide"))


def test_guide_is_open_in_both_languages_with_a_matching_csp(server):  # noqa: F811
    _, base = server
    for path, title, word in (("/guide", "Layout guide", "What is a layout?"), ("/guide?lang=de", "Layout-Anleitung", "Was ist ein Layout?")):
        status, headers, body = _open(base + path)
        assert status == 200 and f"<title>{title} · TIM</title>" in body and word in body, path
        style = re.search(r"<style>(.*?)</style>", body, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
        assert f"style-src 'sha256-{digest}'" in headers["Content-Security-Policy"] and "<script" not in body
        assert "href='/guide'" in body and "aria-current='page'>Layout guide" in body
    assert _open(base + "/guide?lang=xx")[0] == 200


def test_german_body_names_both_and_english_stays_english():
    de, en = guide_body("de"), guide_body("en")
    assert "Gamma-Zonen (Gamma zones)" in de and "Lesen (Read)" in de and "Kein Layout ist ein Kauf- oder Verkaufssignal" in de
    assert "Gamma zones" in en and "Gamma-Zonen" not in en and "No layout is a buy or sell signal" in en
    assert en.count("<h3>") == de.count("<h3>") == len(LAYOUTS)
    assert "Volume Profile (Volume profile)" not in de
