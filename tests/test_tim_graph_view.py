from __future__ import annotations

import json
from pathlib import Path

from src.dashboard.pages.graphify import graph_csp
from src.tim_graph_view import build as tv


def node(id_: str, file: str) -> dict:
    return {"id": id_, "label": id_, "source_file": file}


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    files = {
        "src/data_ingestion/feed.py": "from src.paper.book import Book\n",
        "src/paper/book.py": "class Book:\n    pass\n",
        "src/paper/only_tested.py": "def f():\n    return 1\n",
        "src/research_lab/cli.py": "if __name__ == '__main__':\n    pass\n",
        "tests/test_only.py": "from src.paper.only_tested import f\n",
        "docs/research_lab/s1.md": "Code: `src/research_lab/cli.py` und src.paper.book, siehe [x](../ops/a.md).\n",
        "docs/ops/a.md": "# A\n",
        "docs/lonely/b.md": "# allein\n",
    }
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    graph = {"built_at_commit": "abc1234def",
             "nodes": [node(f"n{i}", rel) for i, rel in enumerate(files)],
             "links": [{"source": "n0", "target": "n1", "relation": "imports_from"},
                       {"source": "n4", "target": "n2", "relation": "imports_from"},
                       {"source": "n0", "target": "n0", "relation": "contains"}]}
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    return repo, path


def test_build_links_docs_tests_and_reports_gaps(tmp_path: Path):
    repo, graph = make_repo(tmp_path)
    out = tmp_path / "out"
    summary = tv.build(graph, repo, out)
    data = json.loads((out / "tim-graph-areas.json").read_text())
    pairs = {(e["a"], e["b"]) for e in data["edges"]}
    assert ("docs/research_lab", "src/research_lab") in pairs  # path mention
    assert ("docs/research_lab", "src/paper") in pairs          # module mention
    assert ("docs/ops", "docs/research_lab") in pairs           # markdown link
    assert ("src/data_ingestion", "src/paper") in pairs         # graphify import
    areas = {a["id"]: a for a in data["areas"]}
    assert "tests/test_only.py" not in str(areas.get("tests (ohne Code-Bezug)"))
    assert not areas["docs/lonely"]["linked"] and areas["docs/lonely"]["islands"]
    assert data["gaps"]["nur_tests"] == ["src/paper/only_tested.py"]
    assert "src/research_lab/cli.py" not in data["gaps"]["unbenutzt"]  # entry point
    assert summary["area_parts"] == 2  # the lonely doc and everything else
    report = (out / "TIM_GRAPH_LUECKEN.md").read_text()
    assert "`src/paper/only_tested.py`" in report and "`docs/lonely`" in report


def test_page_is_csp_clean_and_escapes(tmp_path: Path):
    repo, graph = make_repo(tmp_path)
    raw = json.loads(graph.read_text())
    raw["nodes"].append(node("evil", "src/paper/x</script>.py"))
    graph.write_text(json.dumps(raw))
    out = tmp_path / "out"
    tv.build(graph, repo, out)
    page = (out / "tim-graph.html").read_text()
    assert page.count("</script>") == 2  # vis + own script, data cannot close the tag
    assert graph_csp(page) is not None


def test_unknown_package_gets_its_own_layer():
    assert tv.layer_of("src/brand_new") == "neu"
    assert tv.layer_of("src/paper") == "trading"
    assert tv.layer_of("src (Kern)") == "werkzeuge"


def test_code_naming_a_schema_file_links_it(tmp_path: Path):
    repo, graph = make_repo(tmp_path)
    (repo / "schemas").mkdir()
    (repo / "schemas/plan.v1.json").write_text("{}", encoding="utf-8")
    (repo / "src/paper/book.py").write_text('SCHEMA = "plan.v1.json"\n', encoding="utf-8")
    raw = json.loads(graph.read_text())
    raw["nodes"].append(node("schema", "schemas/plan.v1.json"))
    graph.write_text(json.dumps(raw))
    out = tmp_path / "out"
    tv.build(graph, repo, out)
    data = json.loads((out / "tim-graph-areas.json").read_text())
    assert ("schemas", "src/paper") in {(e["a"], e["b"]) for e in data["edges"]}
