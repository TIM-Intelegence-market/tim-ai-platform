"""Keep German names on the Graphify groups across the hourly rebuild.

Graphify numbers its groups (communities) anew on every rebuild, so names keyed
by group number go stale. This step keys them by the building blocks instead:

1. Carry over: each new group takes the name that most of its members had in
   the previous graph (at least half of the members that existed before).
2. Small groups (fewer than ``MIN_SIZE`` members) are called "Einzelteile".
3. Groups still without a name are named by the local model (Ollama on the
   Mac, ``think: false``, nothing leaves the machine), at most ``budget`` per
   run so the hourly job stays short; the rest is retried next run.

The names go into ``community_name`` of every node in the view's
``graph.json`` (read by the graphify MCP that Hermes uses), into
``.graphify_labels.json`` next to it (also read by the MCP) and into
``gruppen-namen.json``. Stdlib only; the Mac job has no extra packages.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

MIN_SIZE = 5
SMALL_NAME = "Einzelteile"
NAMES_FILE = "gruppen-namen.json"
LABELS_FILE = ".graphify_labels.json"
HTML_FILE = "graph-benannt.html"
OLLAMA_URL = os.environ.get("TIM_GRAPH_NAMES_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("TIM_GRAPH_NAMES_MODEL", "qwen3.5:9b")
GRAPHIFY_PYTHON = Path.home() / ".local/share/uv/tools/graphifyy/bin/python"
BATCH = 15
PROMPT = (
    "Du benennst Gruppen im Code-Graphen einer Trading-Plattform (TIM). Gib fuer jede "
    "Gruppe einen kurzen, verstaendlichen deutschen Namen (2 bis 4 Woerter), der sagt, "
    "wofuer der Code zustaendig ist, z. B. \"Chart-Anzeige\", \"Orderflow-Berechnung\", "
    "\"Tests Datenqualitaet\". Keine Code-Namen abschreiben. Antworte NUR mit JSON: "
    "{\"<id>\": \"<Name>\", ...}.\n"
)

Namer = Callable[[dict[str, str]], dict[str, str]]


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def groups_of(graph: dict) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for node in graph.get("nodes", []):
        if node.get("community") is not None:
            groups[str(node["community"])].append(str(node["id"]))
    return dict(groups)


def node_names(graph: dict | None, names: dict[str, str]) -> dict[str, str]:
    """Node id -> group name in a previously named graph."""
    if not graph:
        return {}
    result = {}
    for node in graph.get("nodes", []):
        name = names.get(str(node.get("community")))
        if name and name != SMALL_NAME:
            result[str(node["id"])] = name
    return result


def carry_over(groups: dict[str, list[str]], old: dict[str, str]) -> dict[str, str]:
    """New group id -> name, where most known members agree on an old name."""
    names: dict[str, str] = {}
    for cid, members in groups.items():
        if len(members) < MIN_SIZE:
            names[cid] = SMALL_NAME
            continue
        known = [old[m] for m in members if m in old]
        if not known:
            continue
        name, votes = Counter(known).most_common(1)[0]
        if votes * 2 >= len(known) and votes * 4 >= len(members):
            names[cid] = name
    return names


def describe(graph: dict, groups: dict[str, list[str]], cids: list[str]) -> dict[str, str]:
    """Short line per group for the model: busiest members and files."""
    degree: Counter = Counter()
    for link in graph.get("links", graph.get("edges", [])):
        degree[str(link.get("source"))] += 1
        degree[str(link.get("target"))] += 1
    by_id = {str(n["id"]): n for n in graph.get("nodes", [])}
    lines = {}
    for cid in cids:
        members = sorted(groups[cid], key=lambda m: -degree[m])
        labels = [str(by_id[m].get("label", m)) for m in members[:10]]
        files = Counter(str(by_id[m].get("source_file", "")) for m in members)
        top = [f for f, _ in files.most_common(3) if f]
        lines[cid] = f"Bausteine: {', '.join(labels)} | Dateien: {', '.join(top)}"
    return lines


def ollama_namer(lines: dict[str, str], timeout: float = 600) -> dict[str, str]:
    body = {
        "model": OLLAMA_MODEL, "think": False, "stream": False, "format": "json",
        "options": {"temperature": 0.2},
        "messages": [{"role": "user", "content": PROMPT + "\n".join(
            f"{cid}: {line}" for cid, line in lines.items())}],
    }
    request = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        answer = json.loads(response.read().decode())
    parsed = json.loads(answer["message"]["content"])
    return {str(k): str(v).strip()[:60] for k, v in parsed.items()
            if str(k) in lines and str(v).strip()}


def name_missing(graph: dict, groups: dict[str, list[str]], names: dict[str, str],
                 namer: Namer, budget: int) -> tuple[int, str | None]:
    """Name up to `budget` unnamed groups, biggest first. Returns (named, error)."""
    todo = sorted((c for c in groups if c not in names), key=lambda c: -len(groups[c]))
    todo = todo[:budget]
    named = 0
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        try:
            result = namer(describe(graph, groups, batch))
        except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
            return named, f"{type(exc).__name__}: {exc}"[:300]
        for cid in batch:
            if cid in result:
                names[cid] = result[cid]
                named += 1
    return named, None


def apply(graph: dict, names: dict[str, str]) -> None:
    for node in graph.get("nodes", []):
        name = names.get(str(node.get("community")))
        if name:
            node["community_name"] = name


def write_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def render_html(view_dir: Path, python: Path = GRAPHIFY_PYTHON) -> str:
    """graph-benannt.html with graphify's own exporter (only in its uv Python)."""
    if not python.exists():
        return "kein graphify-Python"
    script = (
        "import json,sys\n"
        "from graphify.build import build_from_json\n"
        "from graphify.exporters.html import to_html\n"
        "d=sys.argv[1]; raw=json.load(open(d+'/graph.json'))\n"
        "names={int(k):v for k,v in json.load(open(d+'/" + NAMES_FILE + "')).items()}\n"
        "G=build_from_json(raw, directed=bool(raw.get('directed', False)))\n"
        "com={}\n"
        "for n in raw['nodes']:\n"
        "    if n.get('community') is not None: com.setdefault(int(n['community']),[]).append(n['id'])\n"
        "to_html(G, com, d+'/" + HTML_FILE + "', community_labels=names, node_limit=5000)\n"
    )
    result = subprocess.run([str(python), "-c", script, str(view_dir)], capture_output=True,
                            text=True, check=False, timeout=600)
    return "ok" if result.returncode == 0 else f"error {(result.stderr or '')[-200:]}"


def refresh(view_dir: Path, new_graph: Path | None = None, namer: Namer | None = None,
            budget: int = 120, html: bool = True) -> dict:
    """Name the groups of `new_graph` (default: the view's graph.json) and write
    the named graph to the view. Returns a small summary for the status file."""
    view_json = view_dir / "graph.json"
    old_graph = load_json(view_json)
    old_names = load_json(view_dir / NAMES_FILE) or {}
    graph = load_json(new_graph or view_json)
    if not graph:
        return {"state": "keine Karte"}
    groups = groups_of(graph)
    if new_graph is None:  # same graph, only fill the gaps
        names = {k: v for k, v in old_names.items() if k in groups}
        for cid, members in groups.items():
            if len(members) < MIN_SIZE:
                names[cid] = SMALL_NAME
    else:
        names = carry_over(groups, node_names(old_graph, old_names))
    kept = sum(1 for v in names.values() if v != SMALL_NAME)
    named, error = name_missing(graph, groups, names, namer or ollama_namer, budget)
    apply(graph, names)
    view_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(view_json, graph)
    write_atomic(view_dir / NAMES_FILE, names)
    write_atomic(view_dir / LABELS_FILE, names)
    open_count = sum(1 for c in groups if c not in names)
    summary = {"state": "ok" if not open_count else "offen", "groups": len(groups),
               "kept": kept, "named": named,
               "open": open_count}
    if error:
        summary["error"] = error
    if html:
        summary["html"] = render_html(view_dir)
    return summary
