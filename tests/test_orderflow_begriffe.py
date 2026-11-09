"""The glossary ``docs/knowledge/ORDERFLOW_BEGRIFFE.md`` names every orderflow threshold with its value.

Section 2 of the glossary is a table ``| `NAME` | `module` | value | ... |``. This test reads the
table and compares each value with the constant in the code, so a threshold cannot change in
the code without the glossary (and its "Herkunft" / "Status" columns) changing too. It also
checks that engine and chart use the same numbers where the glossary says they do.
"""

from __future__ import annotations

import importlib
import re
from decimal import Decimal
from pathlib import Path

import pytest

GLOSSARY = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "ORDERFLOW_BEGRIFFE.md"
ROW = re.compile(r"^\|\s*`([A-Z_]+)`\s*\|\s*`([a-z_.]+)`\s*\|\s*([0-9.]+)\s*\|")


def _rows() -> list[tuple[str, str, str]]:
    rows = []
    for line in GLOSSARY.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            rows.append((match.group(1), match.group(2), match.group(3)))
    return rows


def test_glossary_lists_thresholds() -> None:
    rows = _rows()
    names = {(name, module) for name, module, _ in rows}
    assert ("IMBALANCE_RATIO", "src.orderflow_scenario.footprint") in names
    assert ("IMBALANCE_RATIO", "src.dashboard.footprint_data") in names
    assert ("HEAVY_VOLUME_RATIO", "src.orderflow_scenario.engines.orderflow_interpretation") in names
    assert ("BUBBLE_MIN_USD", "src.dashboard.perp_flow") in names
    assert len(rows) >= 14


@pytest.mark.parametrize("name,module,value", _rows(), ids=lambda item: str(item))
def test_glossary_value_matches_code(name: str, module: str, value: str) -> None:
    constant = getattr(importlib.import_module(module), name)
    assert Decimal(str(constant)) == Decimal(value), f"{module}.{name} = {constant!r}, glossary says {value}"


def test_engine_and_chart_share_imbalance_and_bubble_numbers() -> None:
    from src.dashboard import footprint_data, perp_flow
    from src.orderflow_scenario import footprint

    assert Decimal(str(footprint_data.IMBALANCE_RATIO)) == footprint.IMBALANCE_RATIO
    assert footprint_data.STACK_MIN == footprint.STACK_MIN
    assert footprint_data.BUBBLE_MIN_USD == perp_flow.BUBBLE_MIN_USD


def test_glossary_names_the_study_and_the_two_imbalance_readings() -> None:
    text = GLOSSARY.read_text(encoding="utf-8")
    assert "S19" in text
    assert "Zeilenbreite" in text  # the chart's reading of the imbalance diagonal
    assert "UNCALIBRATED_CONFIDENCE" in text
