"""Build the TIM graph view from graphify's `graph.json`.

graphify clusters 18 000 nodes into ~900 communities; above 5000 nodes its
HTML only shows those communities, and about half of them have no edge to any
other (the ring of loose dots). This module rebuilds one connected TIM graph:

* nodes are code areas (`src/<package>`, `docs/<folder>`, `scripts`, ...),
  grouped into layers (Daten, Research, Betrieb, ...) around one `TIM` node;
* edges between areas come from graphify's file-to-file links (imports, calls,
  uses) plus links graphify does not make: documents that name code paths or
  modules (`src/x/y.py`, `src.x.y`), and Markdown links between documents;
* tests are counted with the area they import;
* a wiring check (AST imports over the repository) lists modules that only
  tests use and files without any connection.

Outputs (into --out): `tim-graph.html` (vis-network page, same pinned script
as graphify), `TIM_GRAPH_LUECKEN.md` (gap report) and `tim-graph-areas.json`.

Usage:
  python -m src.tim_graph_view.build --graph graphify-out/graph.json --repo . --out OUT
"""
from __future__ import annotations

import argparse
import ast
import html
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

VIS_SCRIPT = ('<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js" '
              'integrity="sha384-Ux6phic9PEHJ38YtrijhkzyJ8yQlH8i/+buBR8s3mAZOJrP1gwyvAcIYl3GWtpX1" '
              'crossorigin="anonymous"></script>')
CODE_RELATIONS = {"calls", "imports", "imports_from", "uses", "extends", "inherits",
                  "indirect_call", "re_exports", "method", "triggers", "references"}

LAYERS: dict[str, tuple[str, str]] = {  # key -> (label, colour)
    "daten": ("Daten", "#22C55E"),
    "research": ("Research", "#FACC15"),
    "trading": ("Trading (Papier)", "#F97316"),
    "v2": ("V2-Plattform", "#EC4899"),
    "betrieb": ("Betrieb", "#38BDF8"),
    "ki": ("KI & Agenten", "#A855F7"),
    "ui": ("Oberfläche", "#2563EB"),
    "werkzeuge": ("Werkzeuge & Konfiguration", "#14B8A6"),
    "doku": ("Doku", "#94A3B8"),
    "tests": ("Tests ohne Code-Bezug", "#64748B"),
    "neu": ("Noch keiner Schicht zugeordnet", "#F5F5F4"),
}
PACKAGE_LAYER = {
    "daten": ("data_ingestion", "database", "market_data", "multi_symbol", "observation",
              "quality", "sources", "news", "models"),
    "research": ("analysis", "analytics", "insights", "orderflow", "orderflow_scenario",
                 "options_gamma", "research", "research_intelligence", "research_lab",
                 "research_ops", "benchmark"),
    "trading": ("paper",),
    "v2": ("tim_v2", "v2_completion", "v2_readiness"),
    "betrieb": ("operational", "acceptance", "collection_reporting", "tim_incident", "ops_mcp",
                "local_first", "task_engine", "task_governance", "orchestration"),
    "ki": ("agents", "agent_infra", "llm", "assistant", "bugfixer", "repair_diagnosis",
           "repair_gates", "repair_registry", "repair_repro", "tim_manager", "graph_mcp",
           "obsidian_vault", "tim_graph_view", "knowledge", "memory", "reflection"),
    "ui": ("dashboard", "control_portal"),
}
_PKG_TO_LAYER = {pkg: layer for layer, pkgs in PACKAGE_LAYER.items() for pkg in pkgs}
_PATH_REF = re.compile(r"(?<![\w/.-])((?:src|scripts|tools|tests|schemas|config|docs|TIM_MASTER_PROMPTS)"
                       r"/[A-Za-z0-9_./-]*[A-Za-z0-9_])")
_DATA_SUFFIXES = (".json", ".sql", ".yaml", ".yml", ".toml")
_MODULE_REF = re.compile(r"(?<![\w.])(src(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_MD_LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")


def area_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] in ("src", "docs", "tests") and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    if parts[0] == "src":
        return "src (Kern)"  # files directly in src/
    if parts[0] == "docs":
        return "docs (Hauptordner)"
    return parts[0] if len(parts) > 1 else "(Wurzel)"


def layer_of(area: str) -> str:
    if area.startswith("src/"):
        return _PKG_TO_LAYER.get(area[4:], "neu")
    if area.startswith("docs") or area == "TIM_MASTER_PROMPTS":
        return "doku"
    if area.startswith("tests"):
        return "tests"
    return "werkzeuge"


@dataclass
class Model:
    files: set[str]
    file_edges: Counter = field(default_factory=Counter)  # (a, b) sorted -> count
    kinds: Counter = field(default_factory=Counter)
    area: dict[str, str] = field(default_factory=dict)


def load_graphify(graph: dict) -> Model:
    nodes = {n["id"]: n.get("source_file") or "" for n in graph.get("nodes", [])}
    model = Model(files={f for f in nodes.values() if f})
    for link in graph.get("links", []):
        a, b = nodes.get(link.get("source"), ""), nodes.get(link.get("target"), "")
        if a and b and a != b and link.get("relation") in CODE_RELATIONS:
            model.file_edges[tuple(sorted((a, b)))] += 1
            model.kinds["graphify"] += 1
    return model


def _resolve(ref: str, files: set[str]) -> str | None:
    ref = ref.rstrip("./")
    for candidate in (ref, f"{ref}.py", f"{ref}/__init__.py"):
        if candidate in files:
            return candidate
    return None


def add_document_links(model: Model, repo: Path) -> None:
    """Edges graphify does not make: docs naming code, Markdown links."""
    for doc in sorted(f for f in model.files if f.endswith(".md")):
        try:
            text = (repo / doc).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        targets: set[str] = set()
        for ref in _PATH_REF.findall(text):
            hit = _resolve(ref, model.files)
            if hit:
                targets.add(hit)
        for ref in _MODULE_REF.findall(text):
            hit = _resolve(ref.replace(".", "/"), model.files)
            if hit:
                targets.add(hit)
        for ref in _MD_LINK.findall(text):
            if "://" in ref:
                continue
            path = (Path(doc).parent / ref).as_posix()
            parts: list[str] = []
            for part in path.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part not in ("", "."):
                    parts.append(part)
            hit = "/".join(parts)
            if hit in model.files:
                targets.add(hit)
        for target in targets - {doc}:
            model.file_edges[tuple(sorted((doc, target)))] += 1
            model.kinds["dokument"] += 1


def add_data_file_links(model: Model, repo: Path) -> None:
    """Code that names a schema/config/SQL file (by unique file name) uses it."""
    by_name: dict[str, list[str]] = defaultdict(list)
    for path in model.files:
        if path.endswith(_DATA_SUFFIXES):
            by_name[path.rsplit("/", 1)[-1]].append(path)
    names = {name: paths[0] for name, paths in by_name.items() if len(paths) == 1}
    if not names:
        return
    pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
    for code in sorted(f for f in model.files if f.endswith(".py")):
        try:
            text = (repo / code).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for hit in set(pattern.findall(text)):
            target = names[hit]
            if target != code:
                model.file_edges[tuple(sorted((code, target)))] += 1
                model.kinds["dokument"] += 1


def assign_areas(model: Model) -> None:
    """Tests join the area they touch most; everything else by path."""
    neighbours: dict[str, Counter] = defaultdict(Counter)
    for (a, b), count in model.file_edges.items():
        neighbours[a][b] += count
        neighbours[b][a] += count
    for path in model.files:
        model.area[path] = area_of(path)
    for path in model.files:
        if not path.startswith("tests/"):
            continue
        votes = Counter()
        for other, count in neighbours[path].items():
            if not other.startswith(("tests/", "docs/")) and other.endswith(".py"):
                votes[area_of(other)] += count
        if votes:
            model.area[path] = votes.most_common(1)[0][0]
        else:
            model.area[path] = "tests (ohne Code-Bezug)"


# ---------- wiring check (who imports whom, from the repository itself) ----------

def _module(path: str) -> str:
    mod = path[:-3].replace("/", ".")
    return mod[:-9] if mod.endswith(".__init__") else mod


def import_users(repo: Path, files: list[str]) -> dict[str, set[str]]:
    users: dict[str, set[str]] = defaultdict(set)
    for path in files:
        try:
            tree = ast.parse((repo / path).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    pkg = _module(path).split(".")
                    if not path.endswith("__init__.py"):
                        pkg = pkg[:-1]
                    pkg = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                    base = ".".join([*pkg, base] if base else pkg)
                names = [base] + [f"{base}.{alias.name}" for alias in node.names]
            for name in names:
                parts = name.split(".")
                for i in range(1, len(parts) + 1):
                    users[".".join(parts[:i])].add(path)
    return users


def wiring(repo: Path, py_files: list[str], text_blob: str) -> dict[str, list[str]]:
    users = import_users(repo, py_files)
    out: dict[str, list[str]] = {"nur_tests": [], "unbenutzt": []}
    for path in sorted(f for f in py_files if f.startswith("src/") and not f.endswith("__init__.py")):
        mod = _module(path)
        who = users.get(mod, set()) - {path}
        if any(not u.startswith("tests/") for u in who):
            continue
        try:
            source = (repo / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
        entry = "__main__" in source or mod in text_blob or path in text_blob
        if entry:
            continue
        out["nur_tests" if who else "unbenutzt"].append(path)
    return out


# ---------- view ----------

def build_view(model: Model) -> dict:
    files_by_area: dict[str, list[str]] = defaultdict(list)
    for path, area in model.area.items():
        files_by_area[area].append(path)
    degree = Counter()
    area_edges = Counter()
    for (a, b), count in model.file_edges.items():
        degree[a] += 1
        degree[b] += 1
        x, y = model.area[a], model.area[b]
        if x != y:
            area_edges[tuple(sorted((x, y)))] += count
    linked_areas = {a for pair in area_edges for a in pair}
    linked_areas |= {area for area, paths in files_by_area.items()  # only package markers
                     if all(p.endswith("__init__.py") for p in paths)}
    areas = []
    for area, paths in sorted(files_by_area.items()):
        islands = sorted(p for p in paths if degree[p] == 0 and not p.endswith("__init__.py"))
        areas.append({"id": area, "layer": layer_of(area), "files": len(paths),
                      "islands": islands, "linked": area in linked_areas,
                      "file_list": sorted(paths)})
    return {"areas": areas,
            "edges": [{"a": a, "b": b, "n": n} for (a, b), n in sorted(area_edges.items())],
            "layers": {k: {"label": v[0], "color": v[1]} for k, v in LAYERS.items()},
            "stats": {"files": len(model.files), "file_edges": len(model.file_edges),
                      "graphify_links": model.kinds["graphify"],
                      "document_links": model.kinds["dokument"],
                      "areas": len(areas), "area_edges": len(area_edges),
                      "island_files": sum(len(a["islands"]) for a in areas),
                      "island_areas": sum(not a["linked"] for a in areas)}}


def components(view: dict) -> int:
    """Connected parts among areas (without the TIM/layer hub)."""
    parent = {a["id"]: a["id"] for a in view["areas"]
              if not all(p.endswith("__init__.py") for p in a.get("file_list", ["x"]))}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for edge in view["edges"]:
        if edge["a"] in parent and edge["b"] in parent:
            parent[find(edge["a"])] = find(edge["b"])
    return len({find(a) for a in parent})


def layout(view: dict) -> dict[str, tuple[float, float]]:
    """Fixed sun layout: TIM in the middle, layers on an inner ring, each
    layer's areas fanned out in its own sector (big areas first, two rows)."""
    by_layer: dict[str, list[dict]] = defaultdict(list)
    for area in view["areas"]:
        by_layer[area["layer"]].append(area)
    order = [k for k in view["layers"] if by_layer.get(k)]
    weights = {k: max(3.0, len(by_layer[k])) for k in order}
    total = sum(weights.values()) or 1.0
    pos: dict[str, tuple[float, float]] = {"TIM": (0.0, 0.0)}
    angle = -math.pi / 2
    for key in order:
        span = 2 * math.pi * weights[key] / total
        mid = angle + span / 2
        pos[f"layer:{key}"] = (420 * math.cos(mid), 420 * math.sin(mid))
        areas = sorted(by_layer[key], key=lambda a: (-a["files"], a["id"]))
        rows = 1 if len(areas) <= 6 else 2
        per_row = math.ceil(len(areas) / rows)
        for i, area in enumerate(areas):
            row, col = divmod(i, per_row)
            count = min(per_row, len(areas) - row * per_row)
            step = span * 0.86 / max(count, 1)
            theta = angle + span * 0.07 + step * (col + 0.5)
            radius = 820 + row * 260 + (col % 2) * 70
            pos[area["id"]] = (radius * math.cos(theta), radius * math.sin(theta))
        angle += span
    return pos


def render_html(view: dict, built_at: str, commit: str) -> str:
    nodes, edges = [{"id": "TIM", "label": "TIM", "shape": "dot", "size": 46,
                     "color": {"background": "#FFFFFF", "border": "#FFFFFF"},
                     "font": {"size": 34, "color": "#FFFFFF"}, "kind": "tim"}], []
    used_layers = {a["layer"] for a in view["areas"]}
    for key, layer in view["layers"].items():
        if key not in used_layers:
            continue
        nodes.append({"id": f"layer:{key}", "label": layer["label"], "size": 28, "kind": "layer",
                      "color": {"background": layer["color"], "border": "#FFFFFF"},
                      "font": {"size": 22, "color": "#FFFFFF"}})
        edges.append({"from": "TIM", "to": f"layer:{key}", "width": 4,
                      "color": {"color": "#E5E7EB", "opacity": 0.55}, "length": 220})
    for area in view["areas"]:
        color = view["layers"][area["layer"]]["color"]
        nodes.append({"id": area["id"], "label": area["id"].removeprefix("src/"),
                      "size": 8 + 4 * math.sqrt(area["files"]), "kind": "area",
                      "layer": area["layer"],
                      "color": {"background": color,
                                "border": "#EF4444" if not area["linked"] else color},
                      "borderWidth": 4 if not area["linked"] else 1,
                      "font": {"size": 16, "color": "#E5E7EB"}})
        edges.append({"from": f"layer:{area['layer']}", "to": area["id"], "width": 1.5,
                      "color": {"color": color, "opacity": 0.35}, "length": 120})
    for edge in view["edges"]:
        edges.append({"from": edge["a"], "to": edge["b"], "n": edge["n"],
                      "width": min(6, 0.5 + math.log10(1 + edge["n"])),
                      "color": {"color": "#CBD5E1", "opacity": 0.18}})
    pos = layout(view)
    for item in nodes:
        item["x"], item["y"] = (round(v, 1) for v in pos.get(item["id"], (0.0, 0.0)))
        item["fixed"] = True
    detail = {a["id"]: {"files": a["file_list"], "islands": a["islands"], "layer": a["layer"],
                        "linked": a["linked"]} for a in view["areas"]}
    data = json.dumps({"nodes": nodes, "edges": edges, "detail": detail,
                       "layers": view["layers"], "stats": view["stats"]},
                      ensure_ascii=False).replace("</", "<\\/")
    stats = view["stats"]
    head = (f"{stats['areas']} Bereiche · {stats['files']} Dateien · "
            f"{stats['file_edges']} Datei-Verbindungen ({stats['document_links']} aus Doku) · "
            f"{stats['island_files']} Dateien ohne Verbindung · Stand {html.escape(commit[:7])}, "
            f"{html.escape(built_at)}")
    return _PAGE.replace("@@HEAD@@", head).replace("@@VIS@@", VIS_SCRIPT).replace("@@DATA@@", data)


def render_report(view: dict, gaps: dict[str, list[str]], commit: str, built_at: str,
                  parts: int) -> str:
    stats = view["stats"]
    lines = ["# TIM-Graph: Verknüpfung und Lücken", "",
             f"Stand `{commit[:7]}`, erzeugt {built_at} (automatisch, `src/tim_graph_view`).", "",
             "## Zahlen", "",
             f"- Bereiche: {stats['areas']}, davon ohne Verbindung zu anderen Bereichen: "
             f"{stats['island_areas']}",
             f"- Zusammenhängende Teile zwischen den Bereichen: {parts} (Ziel: 1)",
             f"- Dateien: {stats['files']}, Datei-Verbindungen: {stats['file_edges']} "
             f"(davon {stats['document_links']} Doku→Code/Doku→Doku)",
             f"- Dateien ohne jede Verbindung: {stats['island_files']}", "",
             "## Module, die nur Tests benutzen", "",
             "Kein Laufzeitcode, kein Skript und keine Doku ruft sie auf. Entweder fehlt die "
             "Verdrahtung oder sie sind Bibliothek für spätere Schritte.", ""]
    lines += [f"- `{p}`" for p in gaps["nur_tests"]] or ["- keine"]
    lines += ["", "## Module ohne jeden Nutzer", ""]
    lines += [f"- `{p}`" for p in gaps["unbenutzt"]] or ["- keine"]
    lines += ["", "## Bereiche ohne Verbindung", ""]
    lone = [a for a in view["areas"] if not a["linked"]]
    lines += [f"- `{a['id']}` ({a['files']} Dateien)" for a in lone] or ["- keine"]
    lines += ["", "## Dateien ohne Verbindung (je Bereich)", ""]
    for area in view["areas"]:
        if area["islands"]:
            lines.append(f"- `{area['id']}`: " + ", ".join(f"`{p.rsplit('/', 1)[-1]}`"
                                                           for p in area["islands"]))
    return "\n".join(lines) + "\n"


def build(graph_path: Path, repo: Path, out: Path) -> dict:
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    commit = str(graph.get("built_at_commit") or "")
    model = load_graphify(graph)
    add_document_links(model, repo)
    add_data_file_links(model, repo)
    assign_areas(model)
    view = build_view(model)
    py_files = sorted(f for f in model.files if f.endswith(".py"))
    blob_parts = []
    for path in sorted(model.files):
        if not path.endswith(".py"):
            try:
                blob_parts.append((repo / path).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    for folder in ("ops", "deploy", ".github"):
        for path in sorted((repo / folder).rglob("*")) if (repo / folder).is_dir() else []:
            if path.is_file() and path.stat().st_size < 1_000_000:
                blob_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    for path in py_files:  # `python -m src.x` strings inside code (jobs, subprocess)
        try:
            blob_parts.append("\n".join(re.findall(r"""["'](src\.[\w.]+)["']""",
                                                   (repo / path).read_text(encoding="utf-8",
                                                                           errors="replace"))))
        except OSError:
            pass
    repo_py = sorted(p.relative_to(repo).as_posix() for folder in ("src", "scripts", "tools", "tests")
                     if (repo / folder).is_dir() for p in (repo / folder).rglob("*.py")
                     if "__pycache__" not in p.parts)
    gaps = wiring(repo, repo_py or py_files, "\n".join(blob_parts))
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = components(view)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tim-graph.html").write_text(render_html(view, built_at, commit), encoding="utf-8")
    (out / "TIM_GRAPH_LUECKEN.md").write_text(render_report(view, gaps, commit, built_at, parts),
                                              encoding="utf-8")
    summary = dict(view["stats"], area_parts=parts, only_tests=len(gaps["nur_tests"]),
                   unused=len(gaps["unbenutzt"]), commit=commit)
    (out / "tim-graph-areas.json").write_text(
        json.dumps({"summary": summary, "areas": [{k: v for k, v in a.items() if k != "file_list"}
                                                  for a in view["areas"]],
                    "edges": view["edges"], "gaps": gaps}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return summary


_PAGE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TIM-Graph</title>
@@VIS@@
<style>
body{margin:0;background:#0f0f1a;color:#E5E7EB;font-family:-apple-system,system-ui,sans-serif;display:flex;height:100vh;overflow:hidden}
#graph{flex:1;min-width:0}
#side{width:340px;max-width:45vw;border-left:1px solid #2a2a3a;padding:14px;overflow:auto;box-sizing:border-box;background:#141424}
h1{font-size:18px;margin:0 0 4px}
.muted{color:#94A3B8;font-size:12px;line-height:1.4}
h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#94A3B8;margin:18px 0 8px}
label{display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0;cursor:pointer}
.dot{width:12px;height:12px;border-radius:50%;flex:none}
input[type=search]{width:100%;box-sizing:border-box;padding:7px 9px;border-radius:6px;border:1px solid #333;background:#0f0f1a;color:#E5E7EB}
ul{padding-left:18px;margin:6px 0;font-size:12px}
li.island{color:#FCA5A5}
.warn{color:#FCA5A5}
@media (max-width:700px){body{flex-direction:column}#side{width:auto;max-width:none;height:45vh;border-left:0;border-top:1px solid #2a2a3a}}
</style></head><body>
<div id="graph"></div>
<aside id="side">
<h1>TIM-Graph</h1>
<div class="muted">@@HEAD@@</div>
<p class="muted">Mitte TIM → Schichten → Bereiche. Linien zwischen Bereichen = Imports, Aufrufe und Doku-Verweise.
Roter Rand = Bereich ohne Verbindung. <a href="/graphify/communities" style="color:#93C5FD">Rohansicht (graphify)</a> ·
<a href="/graphify/luecken" style="color:#93C5FD">Lückenbericht</a></p>
<input id="q" type="search" placeholder="Bereich oder Datei suchen">
<h2>Schichten</h2><div id="layers"></div>
<h2>Auswahl</h2><div id="info" class="muted">Bereich anklicken.</div>
</aside>
<script>
const D = @@DATA@@;
const nodes = new vis.DataSet(D.nodes);
const edges = new vis.DataSet(D.edges.map((e,i)=>Object.assign({id:i},e)));
const net = new vis.Network(document.getElementById('graph'), {nodes, edges}, {
  nodes:{shape:'dot',borderWidth:1},
  edges:{smooth:false,selectionWidth:2},
  physics:false,
  interaction:{hover:true,tooltipDelay:120,dragNodes:false}
});
net.fit();
net.on('selectNode',p=>{ const id=p.nodes[0]; edges.update(D.edges.map((e,i)=>({id:i, color: e.n ? {color: (e.from===id||e.to===id)?'#F8FAFC':'#CBD5E1', opacity: (e.from===id||e.to===id)?0.9:0.06} : e.color}))); });
net.on('deselectNode',()=>{ edges.update(D.edges.map((e,i)=>({id:i,color:e.color}))); });
const hidden = new Set();
const box = document.getElementById('layers');
for (const [key, l] of Object.entries(D.layers)) {
  if (!D.nodes.some(n=>n.id==='layer:'+key)) continue;
  const lab = document.createElement('label');
  const cb = document.createElement('input'); cb.type='checkbox'; cb.checked=true;
  const dot = document.createElement('span'); dot.className='dot'; dot.style.background=l.color;
  const n = D.nodes.filter(x=>x.layer===key).length;
  lab.append(cb, dot, document.createTextNode(l.label+' ('+n+')'));
  cb.addEventListener('change',()=>{ if(cb.checked) hidden.delete(key); else hidden.add(key); apply(); });
  box.append(lab);
}
function apply(){
  nodes.update(D.nodes.map(n=>({id:n.id, hidden: (n.layer && hidden.has(n.layer)) || (n.kind==='layer' && hidden.has(n.id.slice(6)))})));
}
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function show(id){
  const d = D.detail[id]; const info = document.getElementById('info');
  if(!d){ info.textContent = id==='TIM' ? 'Mitte des Graphen.' : 'Schicht: '+(nodes.get(id)||{}).label; return; }
  const links = D.edges.filter(e=>e.n && (e.from===id||e.to===id)).sort((a,b)=>b.n-a.n);
  const isl = new Set(d.islands);
  info.innerHTML = '<b style="color:#fff">'+esc(id)+'</b><br>'+d.files.length+' Dateien · '+links.length+' verbundene Bereiche'
    + (d.linked?'':'<br><span class="warn">Keine Verbindung zu anderen Bereichen.</span>')
    + (d.islands.length?'<br><span class="warn">'+d.islands.length+' Dateien ohne Verbindung (rot)</span>':'')
    + '<h2>Stärkste Verbindungen</h2><ul>'+links.slice(0,12).map(e=>'<li>'+esc(e.from===id?e.to:e.from)+' ('+e.n+')</li>').join('')+'</ul>'
    + '<h2>Dateien</h2><ul>'+d.files.map(f=>'<li class="'+(isl.has(f)?'island':'')+'">'+esc(f)+'</li>').join('')+'</ul>';
}
net.on('click',p=>{ if(p.nodes.length) show(p.nodes[0]); });
document.getElementById('q').addEventListener('input',ev=>{
  const q = ev.target.value.trim().toLowerCase(); if(q.length<2) return;
  const hit = D.nodes.find(n=>n.id.toLowerCase().includes(q)) ||
    D.nodes.find(n=>D.detail[n.id] && D.detail[n.id].files.some(f=>f.toLowerCase().includes(q)));
  if(hit){ net.selectNodes([hit.id]); net.focus(hit.id,{scale:1.2,animation:true}); show(hit.id); }
});
</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", required=True, help="graphify graph.json")
    parser.add_argument("--repo", required=True, help="repository the graph was built from")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    summary = build(Path(args.graph).expanduser(), Path(args.repo).expanduser(),
                    Path(args.out).expanduser())
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
