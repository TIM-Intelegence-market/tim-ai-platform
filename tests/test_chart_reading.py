"""TIM chart reading (Uzi 23.11.2026): plain sentences from the chart model, English and German, login only."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from src.dashboard import chart_reading
from src.dashboard.chart_reading import build_reading, render, svg

NOW = datetime(2026, 11, 23, 16, 30, tzinfo=timezone.utc)
START = int(datetime(2026, 11, 23, 4, 30, tzinfo=timezone.utc).timestamp())
STEP = 50.0


def _model(prices, deltas, thin=None, levels=()):
    """24 bars of 30m; footprint rows every 50 USDT, the rows inside ``thin`` almost empty."""
    candles, bars = [], []
    for i, ((o, h, l, c), d) in enumerate(zip(prices, deltas)):
        t = START + i * 1800
        candles.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 100.0, "closed": True})
        rows = []
        p = (l // STEP) * STEP
        while p <= h:
            volume = 0.1 if thin and thin[0] <= p < thin[1] else 40.0
            rows.append([p, volume / 2 - d / 40, volume / 2 + d / 40])
            p += STEP
        bars.append({"time": t, "levels": rows, "delta": d})
    drawings = [{"group": g, "label": label, "price": price, "finished": False} for g, label, price in levels]
    return {"symbol": "BTCUSDT", "timeframe": "30m", "interval_seconds": 1800, "candles": candles,
            "footprint": {"step": STEP, "bars": bars}, "drawings": drawings}


def _pump_then_sell():
    prices, deltas = [], []
    for i in range(10):  # quiet base around 61.2k
        prices.append((61200, 61300, 61100, 61250))
        deltas.append(5.0 if i % 2 else -5.0)
    prices.append((61250, 63900, 61200, 63800))  # the pump
    deltas.append(6900.0)
    prices.append((63800, 64500, 62900, 63300))  # top, sellers next
    deltas.append(300.0)
    for i in range(12):
        top = 63300 - i * 50
        prices.append((top, top + 60, top - 120, top - 50))
        deltas.append(-40.0)
    return prices, deltas


def test_reading_tells_the_story_in_english():
    prices, deltas = _pump_then_sell()
    model = _model(prices, deltas, thin=(62000, 62400),
                   levels=(("gamma", "Opt Call Wall", 64550.0), ("day", "1D VAL", 62400.0), ("day", "1D VAH", 63400.0),
                           ("structure", "BOS", 60000.0)))
    reading = build_reading(model, NOW)
    text = " ".join(s["text"] for s in reading["sentences"])
    assert reading["ok"] and reading["has_delta"]
    assert "price up" in text and "Buyers were stronger" in text
    assert "Top 64.5k" in text and "right at the Opt Call Wall" in text
    assert "Sellers in control" in text
    assert reading["support"]["label"] == "1D VAL" and reading["resistance"]["price"] > reading["price"]
    assert reading["thin"] and 61900 <= reading["thin"]["low"] < reading["thin"]["high"] <= 62500
    assert "Thin zone" in text and reading["now_text"].startswith("Now ~")
    assert 3 <= len(reading["sentences"]) <= 5
    assert "BOS" not in text  # only live levels of the allowed groups


def test_reading_in_german_uses_german_words_and_numbers():
    prices, deltas = _pump_then_sell()
    model = _model(prices, deltas, levels=(("gamma", "Opt Call Wall", 64550.0), ("day", "1D VAL", 62400.0)))
    reading = build_reading(model, NOW, lang="de")
    text = " ".join(s["text"] for s in reading["sentences"]) + reading["now_text"]
    assert "Preis gestiegen" in text and "Hoch 64,5k" in text and "Call-Wand" in text and "Verkäufer führen" in text
    assert "Jetzt ~" in text
    for english in ("Buyers", "Sellers", "price up", "Top "):
        assert english not in text, english
    html = render(reading)
    assert "Keine Anlageberatung" in html and "deutsche Zeit" in html


def test_without_trades_the_delta_parts_are_left_out():
    prices, deltas = _pump_then_sell()
    model = _model(prices, deltas, levels=(("day", "1D VAL", 62400.0),))
    model["footprint"] = {"step": None, "bars": []}
    reading = build_reading(model, NOW)
    text = " ".join(s["text"] for s in reading["sentences"])
    assert reading["ok"] and not reading["has_delta"] and reading["thin"] is None
    assert "bought" not in text and "in control" not in text
    assert "No trade data" in render(reading)


def test_too_few_candles_say_so():
    reading = build_reading({"candles": [{"time": START, "open": 1, "high": 1, "low": 1, "close": 1}]}, NOW, lang="de")
    assert not reading["ok"] and "zu wenige Kerzen" in render(reading)


def test_drawing_is_plain_svg_without_script_and_escapes_labels():
    prices, deltas = _pump_then_sell()
    model = _model(prices, deltas, levels=(("day", "<script>x</script>", 62400.0),))
    reading = build_reading(model, NOW)
    picture = svg(reading)
    assert picture.startswith("<svg") and "<script" not in picture and "style=" not in picture
    assert len(re.findall(r"<circle", picture)) == len(reading["points"])
    assert "<script>" not in render(reading)


def test_rules_are_fixed_numbers():
    assert chart_reading.WINDOW == 24 and chart_reading.CONTROL_BARS == 3 and chart_reading.SCHEMA == "chart_reading/1"


def test_overlay_has_boxes_in_both_languages_and_never_raises():
    from src.dashboard.chart_reading import overlay

    prices, deltas = _pump_then_sell()
    model = _model(prices, deltas, thin=(62000, 62400),
                   levels=(("gamma", "Opt Call Wall", 64550.0), ("gamma", "Opt Gamma Flip", 66000.0), ("day", "1D VAL", 62400.0)))
    out = overlay(model, NOW)
    assert set(out) >= {"en", "de"}
    en, de = out["en"], out["de"]
    assert [b["title"][:2] for b in en["boxes"][:3]] == ["1)", "2)", "3)"]
    assert any(b["title"].startswith("Gamma flip") for b in en["boxes"]) and any(b["title"].startswith("Gamma-Flip") for b in de["boxes"])
    assert en["boxes"][-1]["title"].startswith("Now ~") and de["boxes"][-1]["title"].startswith("Jetzt ~")
    assert {line["tone"] for line in en["lines"]} >= {"sell", "wall"} and en["thin"]
    assert "not financial advice" in en["head"] and "keine Anlageberatung" in de["head"]
    for box in en["boxes"]:
        assert box["time"] is None or box["time"] in {c["time"] for c in model["candles"]}
    assert overlay({"candles": []}, NOW) is None
    assert overlay({"candles": "broken"}, NOW) is None



def test_one_reading_for_every_timeframe():
    """Uzi 24.11.2026: 4 timeframes explained 4 different things; now the boxes are the same on every timeframe."""
    from src.dashboard.chart_reading import build_unified, unified_overlay

    prices, deltas = _pump_then_sell()
    base = _model(prices, deltas, levels=(("day", "1D VAL", 62400.0),))
    big = _model([(60000 + i * 100, 60200 + i * 100, 59900 + i * 100, 60100 + i * 100) for i in range(24)], [1.0] * 24)
    big.update({"timeframe": "4h", "interval_seconds": 14400})
    for i, c in enumerate(big["candles"]):
        c["time"] = START - (23 - i) * 14400
    built = []

    def build(tf):
        built.append(tf)
        return {"30m": base, "4h": big}[tf]

    reading = build_unified(base, big, NOW, lang="de")
    assert reading["sentences"][0]["title"] == "Das große Bild" and reading["sentences"][0]["text"].startswith("Letzte 4 Tage")
    assert [s["n"] for s in reading["sentences"]] == list(range(1, len(reading["sentences"]) + 1))
    shown_1h = {"timeframe": "1h", "candles": [{"time": START + i * 3600} for i in range(12)]}
    shown_15m = {"timeframe": "15m", "candles": [{"time": START + i * 900} for i in range(48)]}
    one, two = unified_overlay(shown_1h, build, NOW), unified_overlay(shown_15m, build, NOW)
    titles = lambda out: [b["title"] for b in out["de"]["boxes"]]
    assert titles(one) == titles(two) and titles(one)[0].startswith("1) Das große Bild")
    times_1h = {c["time"] for c in shown_1h["candles"]}
    assert all(b["time"] is None or b["time"] in times_1h for b in one["en"]["boxes"])
    assert set(built) == {"30m", "4h"}
    assert unified_overlay(shown_1h, lambda tf: (_ for _ in ()).throw(RuntimeError("down")), NOW) is None
