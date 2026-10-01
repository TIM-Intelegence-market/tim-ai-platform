"""Migrate the 2026-09 TIM vault (schema 0) into vault schema 1.0.0.

Never touches the source vault. `plan` prints what would happen; `apply`
writes a complete new vault into an empty or missing target directory.
Swapping the new vault into place is a separate, manual step.

What changes per note: folder (old -> new name), `type` and `status`
mapped onto the schema vocabulary, path-style wikilinks reduced to the note
name (folders are renamed), wikilinks broken across a line joined, and
links whose target exists nowhere turned into plain text. Note names and
bodies stay otherwise unchanged.

Usage:
  python -m src.obsidian_vault.migrate plan  --source OLD [--markdown]
  python -m src.obsidian_vault.migrate apply --source OLD --target NEW
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.graph_mcp.indexer.obsidian import parse_frontmatter  # noqa: E402
from src.obsidian_vault.schema import VaultSchema, load_schema  # noqa: E402

FOLDER_MAP = {
    "00 HOME": "01 Home",
    "10 Architecture": "10 Architektur",
    "40 Architecture": "10 Architektur",
    "20 Incidents": "20 Incidents",
    "30 Missions": "30 Missionen",
    "40 Systems": "40 Systeme",
    "50 Data & QA": "50 Daten & QA",
    "60 Agents & Tools": "60 Agenten & Tools",
    "70 Decisions": "70 Entscheidungen",
    "80 Runbooks": "80 Runbooks",
    "90 Reports": "90 Berichte",
    "95 Archive": "95 Archiv",
    "Templates": "99 Vorlagen",
}
# old type -> new type; folder-specific overrides below
TYPE_MAP = {"index": "moc", "navigation": "moc", "decision-log": "moc"}
TYPE_IN_FOLDER = {
    ("01 Home", "gate"): "home",  # "TIM Current Status" is a status page
    ("50 Daten & QA", "architecture"): "data-qa",
    ("99 Vorlagen", "report"): "daily",  # Template Daily Status
}
# a report filed under missions belongs to the reports area
FOLDER_FOR_TYPE = {("30 Missionen", "report"): "90 Berichte"}
STATUS_MAP = {
    "active": "active", "blocked": "blocked",
    "completed": "done", "pass": "done", "resolved": "done", "done": "done",
    "not_started": "planned", "proposed": "planned", "draft": "planned",
    "unknown": "planned", "planned": "planned", "archived": "archived",
}
# old statuses that carry a result, not only progress
KEEP_AS_VERDICT = {"pass"}
OBSIDIAN_SKIP = {"workspace.json", "workspace-mobile.json", "workspaces.json"}

_FM = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_LINK = re.compile(r"(!?)\[\[([^\]\[]*?)\]\]", re.DOTALL)
_CODE = re.compile(r"(^(?:```|~~~)[^\n]*\n.*?^(?:```|~~~)[ \t]*$|`[^`\n]*`)",
                   re.DOTALL | re.MULTILINE)


@dataclass
class NotePlan:
    source: str
    target: str
    old_type: str
    new_type: str
    old_status: str
    new_status: str
    link_fixes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (self.source != self.target or self.old_type != self.new_type
                or self.old_status != self.new_status or bool(self.link_fixes))


def _set_field(text: str, key: str, value: str) -> str:
    match = _FM.match(text)
    if not match:
        return text
    lines = match.group(1).split("\n")
    for i, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == key and not line.startswith((" ", "-", "\t")):
            lines[i] = f"{key}: {value}"
            break
    else:
        lines.append(f"{key}: {value}")
    return f"---\n{chr(10).join(lines)}\n---\n" + text[match.end():]


class Migration:
    def __init__(self, source: Path, schema: VaultSchema | None = None) -> None:
        self.source = Path(source)
        self.schema = schema or load_schema()
        self.root = self.source / self.schema.content_root
        if not self.root.is_dir():
            raise FileNotFoundError(f"{self.root} fehlt")
        self.notes = [p for p in sorted(self.root.rglob("*.md"))
                      if not any(part.startswith(".") for part in p.relative_to(self.source).parts)]
        self.stems = {p.stem for p in self.notes} | {
            p.name for p in self.source.rglob("*") if p.is_file() and p.suffix != ".md"}

    def _target_folder(self, rel: Path, note_type: str) -> str:
        top = rel.parts[0]
        folder = FOLDER_MAP.get(top)
        if folder is None:
            raise ValueError(f"Ordner '{top}' hat keine Zuordnung")
        return FOLDER_FOR_TYPE.get((folder, note_type), folder)

    def _fix_links(self, text: str, fixes: list[str]) -> str:
        def repl(match: re.Match) -> str:
            bang, inner = match.group(1), match.group(2)
            parts = re.match(r"([^#|]*)(.*)\Z", inner, re.DOTALL)
            target, suffix = parts.group(1), parts.group(2)
            new_target = " ".join(target.split())  # joins line-wrapped links
            if "/" in new_target:
                new_target = new_target.rsplit("/", 1)[-1]
            new_target = new_target.removesuffix(".md")
            shown = target.replace("\n", "⏎")
            if new_target and new_target not in self.stems:
                if "{{" in new_target:
                    return match.group(0)  # template placeholder
                fixes.append(f"[[{shown}]] -> Text (Ziel fehlt)")
                return suffix[1:] if suffix.startswith("|") else new_target
            if new_target != target:
                fixes.append(f"[[{shown}]] -> [[{new_target}]]")
            return f"{bang}[[{new_target}{suffix}]]"

        # rewrite links outside code only: fences and inline spans stay as is
        pieces = _CODE.split(text)
        return "".join(piece if i % 2 else _LINK.sub(repl, piece)
                       for i, piece in enumerate(pieces))

    def plan(self) -> tuple[list[NotePlan], dict[str, str]]:
        plans: list[NotePlan] = []
        rendered: dict[str, str] = {}
        for path in self.notes:
            rel = path.relative_to(self.root)
            text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
            fm = parse_frontmatter(text)
            old_type, old_status = fm.get("type", ""), fm.get("status", "")
            folder = self._target_folder(rel, old_type)
            new_type = TYPE_MAP.get(old_type, old_type)
            new_type = TYPE_IN_FOLDER.get((folder, new_type), new_type)
            new_status = STATUS_MAP.get(old_status, old_status)
            if folder == "95 Archiv":
                new_status = "archived"
            if folder in self.schema.template_folders:
                new_status = "planned"
            if new_type not in self.schema.types:
                raise ValueError(f"{rel}: type '{old_type}' hat keine Zuordnung")
            if new_status not in self.schema.statuses:
                raise ValueError(f"{rel}: status '{old_status}' hat keine Zuordnung")
            target = Path(self.schema.content_root, folder, *rel.parts[1:]).as_posix()
            plan = NotePlan(rel.as_posix(), target, old_type, new_type, old_status, new_status)
            new_text = _set_field(_set_field(text, "type", new_type), "status", new_status)
            if old_status in KEEP_AS_VERDICT and not fm.get("verdict"):
                # "pass" and "done" share one status now; keep the gate result
                new_text = _set_field(new_text, "verdict", old_status)
            if folder in self.schema.template_folders:
                rendered[target] = new_text
            else:
                rendered[target] = self._fix_links(new_text, plan.link_fixes)
            if target in {p.target for p in plans}:
                raise ValueError(f"Namenskollision: {target}")
            plans.append(plan)
        return plans, rendered

    def apply(self, target: Path) -> list[NotePlan]:
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise FileExistsError(f"{target} ist nicht leer")
        if target.resolve() == self.source.resolve():
            raise ValueError("Ziel darf nicht die Quelle sein")
        plans, rendered = self.plan()
        for rel, text in rendered.items():
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        for folder in self.schema.folders:
            (target / self.schema.content_root / folder).mkdir(parents=True, exist_ok=True)
        (target / self.schema.content_root / "90 Berichte" / "Daily").mkdir(parents=True, exist_ok=True)
        for path in self.source.rglob("*"):  # attachments, keep relative place
            rel = path.relative_to(self.source)
            if (path.is_file() and path.suffix != ".md" and rel.parts[0] != ".obsidian"
                    and path.name != ".DS_Store"):
                parts = list(rel.parts)
                if len(parts) > 2 and parts[0] == self.schema.content_root:
                    parts[1] = FOLDER_MAP.get(parts[1], parts[1])
                dest = target.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        self._copy_settings(target)
        return plans

    def _copy_settings(self, target: Path) -> None:
        src = self.source / ".obsidian"
        dst = target / ".obsidian"
        if not src.is_dir():
            return
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*OBSIDIAN_SKIP))
        root = self.schema.content_root
        templates = f"{root}/99 Vorlagen"
        _update_json(dst / "templates.json", {"folder": templates})
        _update_json(dst / "daily-notes.json", {"folder": f"{root}/90 Berichte/Daily",
                                                "template": f"{templates}/Template Daily Status"})
        core = dst / "core-plugins.json"
        if core.is_file():
            data = json.loads(core.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["sync"] = False
            else:
                data = [name for name in data if name != "sync"]
            core.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _update_json(path: Path, values: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data.update(values)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_plan(plans: list[NotePlan], markdown: bool) -> str:
    if not markdown:
        return "\n".join("\t".join([p.source, p.target, f"{p.old_type}->{p.new_type}",
                                    f"{p.old_status}->{p.new_status}", "; ".join(p.link_fixes)])
                         for p in plans)
    rows = ["| Alt | Neu | type | status | Links |", "|---|---|---|---|---|"]
    for p in plans:
        rows.append(f"| {p.source} | {p.target} | {p.old_type} → {p.new_type} | "
                    f"{p.old_status} → {p.new_status} | {'; '.join(p.link_fixes)} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["plan", "apply"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--target")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    migration = Migration(Path(args.source).expanduser())
    if args.mode == "plan":
        plans, _ = migration.plan()
        print(render_plan(plans, args.markdown))
        return 0
    if not args.target:
        parser.error("apply braucht --target")
    plans = migration.apply(Path(args.target).expanduser())
    print(f"{len(plans)} Notizen nach {args.target} geschrieben")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
