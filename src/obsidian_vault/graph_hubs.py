"""One connected TIM graph in Obsidian: TIM Home -> area MOCs -> notes.

Each area folder has exactly one hub note (Map of Content). This tool keeps a
marked block in every hub that links all notes of its folder, and a block in
`TIM Home` that links every hub. New notes are therefore attached to the graph
on the next run, and nothing outside the markers is ever changed:

    <!-- tim-graph:start -->
    ...generated links...
    <!-- tim-graph:end -->

Missing hubs (e.g. `Decisions MOC`) are created. `settings` writes the TIM
graph view (filters, colour per area, forces) from `docs/obsidian/graph.json`
into `.obsidian/graph.json` and keeps the current zoom.

Usage:
  python -m src.obsidian_vault.graph_hubs sync      # write blocks (add --dry-run)
  python -m src.obsidian_vault.graph_hubs check     # orphans + outdated blocks, exit 1 if any
  python -m src.obsidian_vault.graph_hubs settings  # apply the graph view
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.obsidian_vault.lint import wikilink_targets  # noqa: E402
from src.obsidian_vault.schema import DEFAULT_VAULT, load_schema, vault_path  # noqa: E402

HOME = "TIM Home"
HOME_FOLDER = "01 Home"
START = "<!-- tim-graph:start -->"
END = "<!-- tim-graph:end -->"
AUTO_TAG = "automatisch"
AUTO_OVERVIEW = "TIM Stand automatisch"
GRAPH_TEMPLATE = Path(__file__).resolve().parents[2] / "docs/obsidian/graph.json"
KEEP_VIEW_KEYS = ("scale", "close")

# folder -> (hub note, German label shown in TIM Home). Order = order in TIM Home.
HUBS: dict[str, tuple[str, str]] = {
    "10 Architektur": ("Architecture MOC", "Architektur"),
    "20 Incidents": ("Incidents MOC", "Incidents"),
    "30 Missionen": ("Missions MOC", "Missionen"),
    "40 Systeme": ("Systems MOC", "Systeme"),
    "50 Daten & QA": ("Data QA MOC", "Daten & QA"),
    "60 Agenten & Tools": ("Agents & Tools MOC", "Agenten & Tools"),
    "70 Entscheidungen": ("Decisions MOC", "Entscheidungen"),
    "75 Research": ("Research MOC", "Research"),
    "80 Runbooks": ("Runbooks MOC", "Runbooks"),
    "90 Berichte": ("Reports MOC", "Berichte"),
}
# Not attached: archive and templates are filtered out of the graph view.
NOT_IN_GRAPH = ("95 Archiv", "99 Vorlagen")


@dataclass(frozen=True)
class Note:
    name: str  # link target (stem for .md, file name for other files)
    folder: str
    path: Path


def _is_hidden(parts: tuple[str, ...]) -> bool:
    return any(p.startswith(".") or p.startswith("._") for p in parts)


def _auto_generated(path: Path) -> bool:
    if path.suffix != ".md" or path.stem == AUTO_OVERVIEW:
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
    return f"\n  - {AUTO_TAG}\n" in head + "\n"


def collect(vault: Path) -> dict[str, list[Note]]:
    """Folder -> notes that belong into its hub block (hub itself excluded).
    `.base` dashboards count as notes; weekly auto notes are reached through
    `TIM Stand automatisch` and are left out to keep hubs short."""
    root = vault / load_schema().content_root
    out: dict[str, list[Note]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).parts
        if not path.is_file() or len(rel) < 2 or _is_hidden(rel):
            continue
        if path.suffix not in (".md", ".base") or rel[0] in NOT_IN_GRAPH:
            continue
        if _auto_generated(path):
            continue
        name = path.stem if path.suffix == ".md" else path.name
        out.setdefault(rel[0], []).append(Note(name, rel[0], path))
    return out


def root_notes(vault: Path) -> list[Note]:
    """Notes directly in the vault root, outside the content folder."""
    return [Note(p.stem, "", p) for p in sorted(vault.glob("*.md"))
            if not p.name.startswith(".")]


def _links(names: list[str]) -> list[str]:
    return [f"- [[{name}]]" for name in sorted(set(names), key=str.casefold)]


def render_hub_block(folder: str, notes: list[Note]) -> str:
    hub, label = HUBS[folder]
    names = [n.name for n in notes if n.name != hub]
    lines = [START, f"## Alle Notizen: {label}", "",
             f"Zurück zu [[{HOME}]]. Automatisch gepflegt (`graph_hubs sync`), "
             "zwischen den Markierungen nichts von Hand ändern.", ""]
    lines += _links(names) or ["- (noch keine Notizen)"]
    return "\n".join(lines + [END])


def render_home_block(notes: dict[str, list[Note]], extra: list[Note],
                      folders: list[str] | None = None) -> str:
    """`folders`: area folders that exist (default: all), only their hubs are linked."""
    lines = [START, "## TIM-Graph", "",
             "Automatisch gepflegt (`graph_hubs sync`), zwischen den Markierungen "
             "nichts von Hand ändern.", "", "### Bereiche", ""]
    lines += [f"- {HUBS[f][1]}: [[{HUBS[f][0]}]]" for f in HUBS if folders is None or f in folders]
    start = sorted({n.name for n in notes.get(HOME_FOLDER, []) if n.name != HOME},
                   key=str.casefold)
    if start:
        lines += ["", "### Start", ""] + _links(start)
    if extra:
        lines += ["", "### Anleitungen", ""] + _links([n.name for n in extra])
    inbox = load_schema().inbox
    if notes.get(inbox):
        lines += ["", "### Eingang (prüfen)", ""] + _links([n.name for n in notes[inbox]])
    return "\n".join(lines + [END])


def upsert_block(text: str, block: str) -> str:
    begin, end = text.find(START), text.find(END)
    if begin != -1 and end > begin:
        return text[:begin] + block + text[end + len(END):]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def new_hub(folder: str, today: str) -> str:
    hub, label = HUBS[folder]
    return ("---\ntype: moc\nproject: TIM\nstatus: active\n"
            f"created: {today}\nupdated: {today}\nrelated:\n  - \"[[{HOME}]]\"\n---\n\n"
            f"# {hub}\n\nKnoten für den Bereich {label} im TIM-Graph.\n")


def plan(vault: Path, today: str | None = None) -> dict[Path, str]:
    """Path -> new full text for every hub whose content would change."""
    today = today or date.today().isoformat()
    root = vault / load_schema().content_root
    notes = collect(vault)
    changes: dict[Path, str] = {}
    present = [folder for folder in HUBS if (root / folder).is_dir()]
    targets = [(root / HOME_FOLDER / f"{HOME}.md",
                render_home_block(notes, root_notes(vault), present), None)]
    for folder in HUBS:
        if (root / folder).is_dir():
            targets.append((root / folder / f"{HUBS[folder][0]}.md",
                            render_hub_block(folder, notes.get(folder, [])), folder))
    for path, block, folder in targets:
        if path.exists():
            current = path.read_text(encoding="utf-8")
        elif folder is not None:
            current = new_hub(folder, today)
        else:
            continue  # never invent TIM Home
        updated = upsert_block(current, block)
        if not path.exists() or updated != current:
            changes[path] = updated
    return changes


def sync(vault: Path, dry_run: bool = False) -> list[Path]:
    changes = plan(vault)
    if not dry_run:
        for path, text in changes.items():
            path.write_text(text, encoding="utf-8")
    return sorted(changes)


def orphans(vault: Path) -> list[str]:
    """Notes in graph folders with neither outgoing nor incoming wikilinks."""
    notes = [n for items in collect(vault).values() for n in items]
    names = {n.name for n in notes}
    linked: set[str] = set()
    for note in notes + root_notes(vault):
        if note.path.suffix != ".md":
            continue
        targets = {t.removesuffix(".md").split("/")[-1]
                   for t in wikilink_targets(note.path.read_text(encoding="utf-8",
                                                                 errors="replace"))}
        if targets & names:
            linked.add(note.name)
        linked |= targets & names
    return sorted(names - linked)


def apply_settings(vault: Path, template: Path = GRAPH_TEMPLATE,
                   dry_run: bool = False) -> bool:
    target = vault / ".obsidian/graph.json"
    wanted = json.loads(template.read_text(encoding="utf-8"))
    try:
        current = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    merged = dict(wanted)
    for key in KEEP_VIEW_KEYS:
        if key in current:
            merged[key] = current[key]
    if merged == current:
        return False
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("sync", "check", "settings"))
    parser.add_argument("--vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    vault = vault_path(args.vault) or DEFAULT_VAULT
    if args.command == "sync":
        for path in sync(vault, args.dry_run):
            print(("würde schreiben: " if args.dry_run else "geschrieben: ")
                  + path.relative_to(vault).as_posix())
        return 0
    if args.command == "settings":
        changed = apply_settings(vault, dry_run=args.dry_run)
        print("Graph-Ansicht " + ("aktualisiert" if changed else "unverändert"))
        return 0
    outdated = [p.relative_to(vault).as_posix() for p in plan(vault)]
    lonely = orphans(vault)
    for rel in outdated:
        print(f"veraltet: {rel}")
    for name in lonely:
        print(f"unverbunden: {name}")
    print(f"{len(outdated)} veraltete Knoten-Blöcke, {len(lonely)} unverbundene Notizen")
    return 1 if outdated or lonely else 0


if __name__ == "__main__":
    raise SystemExit(main())
