from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from src.dashboard.pages import graphify
from src.dashboard.server import DashboardServer
from src.dashboard.state import DashboardState

VIS = "https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"
GRAPH = (f"<!DOCTYPE html><html><head><title>graphify - /x/graph.html</title>"
         f"<script src=\"{VIS}\" integrity=\"sha384-x\" crossorigin=\"anonymous\"></script>"
         "<style>body{color:red}</style></head><body>"
         "<input type=\"checkbox\" onchange=\"toggle(this)\">"
         "<script>const RAW = {\"nodes\": []};</script><script>function toggle(e){}</script></body></html>")


def test_csp_hashes_inline_scripts_and_handler_and_pins_vis():
    csp = graphify.graph_csp(GRAPH)
    assert csp is not None
    assert csp.count("'sha256-") == 3 and "'unsafe-hashes'" in csp
    assert VIS in csp and "https://unpkg.com/vis-network@;" not in csp
    assert "connect-src 'none'" in csp and "'unsafe-eval'" not in csp


@pytest.mark.parametrize("bad", [
    "<script src=\"https://evil.example/x.js\"></script>",
    f"<script src=\"{VIS}\">alert(1)</script>",
    "<script src=\"https://unpkg.com/vis-network@9.1.6/../../evil/x.js\"></script>",
])
def test_csp_refuses_foreign_scripts(bad: str):
    assert graphify.graph_csp(GRAPH.replace("</body>", bad + "</body>")) is None


def test_graph_page_states(tmp_path: Path):
    status, page, _ = graphify.graph_page(tmp_path)
    assert status == 404 and "Noch kein Graph" in page
    (tmp_path / "graph.html").write_text(GRAPH, encoding="utf-8")
    status, page, csp = graphify.graph_page(tmp_path)
    assert status == 200 and "<title>TIM Graphify-Graph</title>" in page and VIS in csp
    assert graphify.graph_status(tmp_path)["status"] == "AVAILABLE"
    (tmp_path / "graph.html").write_text(GRAPH.replace("</body>", "<script src='https://evil.example/x.js'></script></body>"))
    assert graphify.graph_page(tmp_path)[0] == 500


def test_routes_serve_graph_report_and_mcp_link(tmp_path: Path, monkeypatch):
    (tmp_path / "graph.html").write_text(GRAPH, encoding="utf-8")
    (tmp_path / "GRAPH_REPORT.md").write_text("# Graph Report\n", encoding="utf-8")
    monkeypatch.setenv(graphify.VIEW_ENV, str(tmp_path))
    server = DashboardServer(DashboardState(), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/graphify") as response:
            assert response.status == 200
            assert VIS in response.headers["Content-Security-Policy"]
            assert "RAW" in response.read().decode()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/graphify/report") as response:
            assert response.read().decode() == "# Graph Report\n"
            assert response.headers["Content-Type"].startswith("text/plain")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/mcp") as response:
            assert "href='/graphify'" in response.read().decode()
    finally:
        server.stop()


def test_tim_view_preferred_and_communities_and_gap_routes(tmp_path: Path, monkeypatch):
    from src.tim_graph_view import build as tim_view

    (tmp_path / "graph.html").write_text(GRAPH, encoding="utf-8")
    view = {"areas": [{"id": "src/a", "layer": "daten", "files": 1, "islands": [],
                       "linked": False, "file_list": ["src/a/x.py"]}],
            "edges": [], "layers": {"daten": {"label": "Daten", "color": "#22C55E"}},
            "stats": {"areas": 1, "files": 1, "file_edges": 0, "document_links": 0,
                      "island_files": 0}}
    (tmp_path / graphify.TIM_VIEW).write_text(tim_view.render_html(view, "jetzt", "abc1234"),
                                              encoding="utf-8")
    (tmp_path / graphify.GAP_REPORT).write_text("# Lücken\n", encoding="utf-8")
    status, page, csp = graphify.graph_page(tmp_path)
    assert status == 200 and "<title>TIM-Graph</title>" in page and VIS in csp
    assert "'unsafe-hashes'" not in csp  # the TIM view has no inline handlers
    assert "RAW" in graphify.graph_page(tmp_path, name="graph.html")[1]
    monkeypatch.setenv(graphify.VIEW_ENV, str(tmp_path))
    server = DashboardServer(DashboardState(), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/graphify/communities") as response:
            assert "RAW" in response.read().decode()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/graphify/luecken") as response:
            assert response.read().decode() == "# Lücken\n"
    finally:
        server.stop()
