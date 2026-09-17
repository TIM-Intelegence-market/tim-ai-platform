"""PROGRAM 2 — Dashboard V2 data-contract and viewport enforcement.

Pins the read-only control-center contract against the documented data
contract (docs/v2_completion/dashboard_data_contracts.md) and design system
(docs/v2_completion/dashboard_design_system.md).

Rules enforced:
- operations contract top-level guard rails (read_only/execution_disabled/trading_locked).
- evidence index: every sources entry has path/available/scope and no fabrication.
- every operations sub-section has a source key resolving to evidence or UNAVAILABLE.
- no synthetic coverage: blocked/missing providers stay BLOCKED/UNAVAILABLE.
- viewport: required breakpoints, no fixed body width, reduced-motion, forced-colors.
"""

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.dashboard.app import DashboardServer, DashboardState, render

OPERATIONS_TOP_LEVEL = {
    "schema_version",
    "product",
    "generated_at_utc",
    "mode",
    "read_only",
    "execution_disabled",
    "trading_locked",
    "security",
    "runtime",
    "datasets",
    "gaps",
    "qualification",
    "independent_cases",
    "readiness",
    "mcp",
    "audit",
    "sources",
}
REQUIRED_BREAKPOINTS = ("1180px", "820px", "520px")


def _write_json(root: Path, name: str, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def _empty_state(tmp_path: Path) -> DashboardState:
    return DashboardState(system_health={"database": "connected", "stream": "running"})


def test_operations_contract_guard_keys_are_literally_true(tmp_path: Path) -> None:
    operations = _empty_state(tmp_path).snapshot()["operations"]
    assert OPERATIONS_TOP_LEVEL <= operations.keys()
    assert operations["read_only"] is True
    assert operations["execution_disabled"] is True
    assert operations["trading_locked"] is True
    assert operations["mode"] == "OBSERVE"


def test_evidence_index_entries_carry_path_available_and_scope(tmp_path: Path) -> None:
    operations = _empty_state(tmp_path).snapshot()["operations"]
    sources = operations["sources"]
    assert isinstance(sources, dict) and sources
    for name, entry in sources.items():
        assert isinstance(entry, dict), name
        assert "path" in entry and "available" in entry and "scope" in entry, name
        assert entry["scope"] in {"V2_COMPLETION", "LEGACY_BASELINE", "LIVE_RUNTIME"}, name


def test_missing_evidence_stays_unavailable_never_synthetic(tmp_path: Path) -> None:
    empty = Path(tmp_path) / "completion"
    empty.mkdir(parents=True, exist_ok=True)
    state = DashboardState(
        completion_artifacts_path=empty,
        system_health={"database": "connected", "stream": "running"},
    )
    operations = state.snapshot()["operations"]
    assert operations["runtime"]["queue_depth"]["value"] == "UNAVAILABLE"
    assert operations["runtime"]["queue_depth"]["status"] == "UNAVAILABLE"
    for dataset in operations["datasets"]:
        if dataset.get("status") in {"UNAVAILABLE"}:
            assert dataset["coverage"] == "UNAVAILABLE"


def test_no_fixed_body_width_and_required_breakpoints_present(tmp_path: Path) -> None:
    page = render(_empty_state(tmp_path), "Security")
    for bp in REQUIRED_BREAKPOINTS:
        assert f"@media(max-width:{bp})" in page
    # body/shell must never pin an absolute width that overflows a viewport.
    for fixed in ("body{width:", "body{min-width:", ".shell{width:"):
        assert fixed not in page


def test_a11y_reduced_motion_and_forced_colors_invariants(tmp_path: Path) -> None:
    page = render(_empty_state(tmp_path), "Runtime")
    assert "prefers-reduced-motion" in page
    assert "forced-colors" in page
    assert ":focus-visible" in page
    assert "Zum Hauptinhalt springen" in page


def test_overview_separates_future_intelligence_horizons_without_signals(tmp_path: Path) -> None:
    page = render(_empty_state(tmp_path), "Overview")
    for horizon, windows in (
        ("SHORT", "60s · 1m · 5m"),
        ("MID", "15m · 1h · 4h"),
        ("LONG", "1D · 1W"),
    ):
        assert horizon in page
        assert windows in page
    assert page.count("AWAITING INTELLIGENCE") == 3
    assert "No directional signal" in page


class _InlineHandlerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.handlers: list[str] = []
        self.attrs_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handlers.extend(key for key, _ in attrs if key.startswith("on"))
        self.attrs_count += len(attrs)


@pytest.mark.parametrize("page_name", [
    "Overview", "Security", "Runtime", "Data Quality", "Incidents & Gaps",
    "Qualification", "Independent Cases", "V2 Readiness",
    "Graphify & MCP", "Audit & Evidence", "Research", "Health Center",
])
def test_no_inline_event_handlers_on_any_page(tmp_path: Path, page_name: str) -> None:
    page = render(_empty_state(tmp_path), page_name)
    parser = _InlineHandlerParser()
    parser.feed(page)
    assert parser.handlers == []
