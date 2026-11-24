"""Live order book page (/orderbuch): served, CSP limited to exchange hosts, no keys, core logic tested in node."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.navigation import locate
from src.dashboard.pages.orderbook import APP_PATH, CORE_PATH, EXCHANGE_CONNECT, ORDERBOOK_CSP, ORDERBOOK_SCRIPTS

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def port():
    srv = DashboardServer(DashboardState(), port=0)
    srv.start()
    yield srv.server.server_address[1]
    srv.stop()


def test_page_scripts_and_csp(port: int) -> None:
    resp = urlopen(f"http://127.0.0.1:{port}/orderbuch")
    html = resp.read().decode()
    csp = resp.headers["Content-Security-Policy"]
    assert resp.status == 200 and "Orderbuch live" in html and "ob-depth" in html and "ob-heat" in html
    assert csp == ORDERBOOK_CSP
    connect = re.search(r"connect-src ([^;]+)", csp).group(1).split()
    assert connect == ["'self'", *EXCHANGE_CONNECT]  # nothing but the exchange endpoints
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    for path in (CORE_PATH, APP_PATH):
        assert f"src='{path}'" in html
        js = urlopen(f"http://127.0.0.1:{port}{path}")
        assert js.status == 200 and js.read() == ORDERBOOK_SCRIPTS[path]


def test_page_is_in_navigation_and_read_only() -> None:
    assert locate("/orderbuch")[0] == "cockpit"
    source = (ROOT / "src/dashboard/assets/orderbook.js").read_text()
    for forbidden in ("apiKey", "api_key", "secret", "signature", "X-MBX-APIKEY", "/order", "innerHTML", "eval("):
        assert forbidden not in source, forbidden
    assert source.count("new WebSocket(") == 2  # Binance + Coinbase, nothing else


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_core_logic_in_node() -> None:
    result = subprocess.run(["node", "--test", "tests/js/orderbook_core.test.js"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
