"""Group names survive a Graphify rebuild (src/obsidian_vault/graph_names)."""
from __future__ import annotations

import json
from pathlib import Path

from src.obsidian_vault import graph_names as gn


def graph(groups: dict[int, list[str]]) -> dict:
    nodes = [{"id": m, "label": m, "source_file": f"src/{cid}.py", "community": cid}
             for cid, members in groups.items() for m in members]
    links = [{"source": ms[0], "target": m} for ms in groups.values() for m in ms[1:]]
    return {"directed": False, "nodes": nodes, "links": links}


def members(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


def write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def fake_namer(calls: list):
    def namer(lines: dict[str, str]) -> dict[str, str]:
        calls.append(sorted(lines))
        return {cid: f"Neu {cid}" for cid in lines}
    return namer


def test_names_follow_members_when_numbers_change(tmp_path: Path):
    view = tmp_path / "view"
    view.mkdir()
    write(view / "graph.json", graph({0: members("chart", 6), 1: members("of", 8),
                                      2: ["x", "y"]}))
    write(view / gn.NAMES_FILE, {"0": "Chart-Anzeige", "1": "Orderflow", "2": gn.SMALL_NAME})
    # rebuild: numbers swapped, one member added, a new group appeared
    new = write(tmp_path / "new.json", graph({7: members("of", 8) + ["of_neu"],
                                              3: members("chart", 6),
                                              9: members("gamma", 5),
                                              4: ["x"]}))
    calls: list = []
    summary = gn.refresh(view, new, namer=fake_namer(calls), html=False)
    names = json.loads((view / gn.NAMES_FILE).read_text())
    assert names == {"7": "Orderflow", "3": "Chart-Anzeige", "9": "Neu 9", "4": gn.SMALL_NAME}
    assert calls == [["9"]]  # only the new group went to the model
    assert summary["state"] == "ok" and summary["named"] == 1 and summary["open"] == 0
    named = json.loads((view / "graph.json").read_text())
    by_id = {n["id"]: n for n in named["nodes"]}
    assert by_id["of_neu"]["community_name"] == "Orderflow"
    assert json.loads((view / gn.LABELS_FILE).read_text()) == names


def test_mostly_new_group_is_renamed_not_inherited(tmp_path: Path):
    view = tmp_path / "view"
    view.mkdir()
    write(view / "graph.json", graph({0: members("a", 5)}))
    write(view / gn.NAMES_FILE, {"0": "Alt"})
    # one old member inside a group of 10 new ones: too weak to inherit
    new = write(tmp_path / "new.json", graph({1: ["a0"] + members("b", 10)}))
    summary = gn.refresh(view, new, namer=fake_namer([]), html=False)
    assert json.loads((view / gn.NAMES_FILE).read_text()) == {"1": "Neu 1"}
    assert summary["kept"] == 0


def test_model_down_keeps_graph_and_retries_later(tmp_path: Path):
    view = tmp_path / "view"
    view.mkdir()
    new = write(tmp_path / "new.json", graph({0: members("a", 6), 1: members("b", 6)}))

    def broken(lines):
        raise OSError("connection refused")

    summary = gn.refresh(view, new, namer=broken, html=False)
    assert summary["state"] == "offen" and summary["open"] == 2 and "error" in summary
    assert (view / "graph.json").exists()  # Hermes still gets the fresh graph
    calls: list = []
    again = gn.refresh(view, namer=fake_namer(calls), budget=1, html=False)
    assert again["named"] == 1 and again["open"] == 1 and calls == [["0"]]
    last = gn.refresh(view, namer=fake_namer([]), html=False)
    assert last["state"] == "ok" and last["open"] == 0


def test_no_graph_is_harmless(tmp_path: Path):
    assert gn.refresh(tmp_path, html=False) == {"state": "keine Karte"}
