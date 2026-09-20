"""Graph export (STEP 24): JSON (canonical), Mermaid, DOT, GraphML.
Graphify stays the visualization layer; these exports are its inputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.graph_mcp import SCHEMA_VERSION


def export_json(service) -> dict[str, Any]:
    nodes = service.store.nodes(limit=100000)
    edges = []
    for node in nodes:
        edges.extend(service.store.edges_from(node["id"]))
    return {"schema_version": SCHEMA_VERSION, "nodes": nodes, "edges": edges}


def export_graphify(service) -> dict[str, Any]:
    """Graphify-compatible node-link graph: Graphify's CLI (explain/path/
    diagnose) expects `label` + `source_file` per node and `relation` +
    `confidence` per link (see graphify diagnose warnings). Deterministic."""
    nodes = []
    for node in service.store.nodes(limit=100000):
        nodes.append({
            "id": node["id"], "label": node["name"],
            "source_file": node["path"] or node["id"],
            "ntype": node["type"],
        })
    links = []
    for node in nodes:
        for edge in service.store.edges_from(node["id"]):
            links.append({
                "source": edge["from"], "target": edge["to"],
                "relation": edge["type"],
                "confidence": edge["metadata"].get("confidence", 1.0),
            })
    return {"directed": True, "multigraph": False,
            "graph": {"name": "tim-graph-mcp", "schema": SCHEMA_VERSION},
            "nodes": nodes, "links": links}


def export_mermaid(service, limit: int = 200) -> str:
    lines = ["graph TD"]
    for node in service.store.nodes(limit=limit):
        safe = node["id"].replace('"', "'")
        lines.append(f'  {mermaid_id(node["id"])}["{safe}"]')
    for node in service.store.nodes(limit=limit):
        for edge in service.store.edges_from(node["id"]):
            lines.append(f'  {mermaid_id(edge["from"])} -->|{edge["type"]}| '
                         f'{mermaid_id(edge["to"])}')
    return "\n".join(lines) + "\n"


def export_dot(service, limit: int = 200) -> str:
    lines = ["digraph tim {"]
    for node in service.store.nodes(limit=limit):
        label = f'{node["type"]}: {node["name"]}'.replace('"', "'")
        lines.append(f'  "{node["id"]}" [label="{label}"];')
    for node in service.store.nodes(limit=limit):
        for edge in service.store.edges_from(node["id"]):
            lines.append(f'  "{edge["from"]}" -> "{edge["to"]}" [label="{edge["type"]}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_graphml(service, limit: int = 200) -> str:
    nodes = service.store.nodes(limit=limit)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
             '  <key id="t" for="node" attr.name="type" attr.type="string"/>',
             '  <key id="e" for="edge" attr.name="type" attr.type="string"/>',
             '  <graph id="tim" edgedefault="directed">']
    index = {node["id"]: position for position, node in enumerate(nodes)}
    for node in nodes:
        parts.append(f'    <node id="n{index[node["id"]]}">'
                     f'<data key="t">{node["type"]}</data>'
                     f'<data key="n">{node["name"]}</data></node>')
    counter = 0
    for node in nodes:
        for edge in service.store.edges_from(node["id"]):
            if edge["to"] in index and edge["from"] in index:
                parts.append(f'    <edge id="e{counter}" source="n{index[edge["from"]]}" '
                             f'target="n{index[edge["to"]]}">'
                             f'<data key="e">{edge["type"]}</data></edge>')
                counter += 1
    parts += ["  </graph>", "</graphml>", ""]
    return "\n".join(parts)


def mermaid_id(node_id: str) -> str:
    """Stable across processes (stdlib hash() is seed-randomized)."""
    import hashlib
    return "n" + hashlib.sha256(node_id.encode()).hexdigest()[:10]


def write_exports(service, directory: Path, formats: tuple[str, ...] = ("json", "mmd", "dot", "graphml", "graphify")) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    writers = {
        "json": lambda p: p.write_text(_dumps(export_json(service))),
        "mmd": lambda p: p.write_text(export_mermaid(service)),
        "dot": lambda p: p.write_text(export_dot(service)),
        "graphml": lambda p: p.write_text(export_graphml(service)),
        "graphify": lambda p: p.write_text(_dumps(export_graphify(service))),
    }
    written: dict[str, Path] = {}
    for fmt in formats:
        path = directory / f"tim-graph.{fmt}"
        writers[fmt](path)
        written[fmt] = path
    return written


def _dumps(payload: Any) -> str:
    import json
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
