"""Read-only vault lint against `schemas/obsidian/vault_schema.json`.

Errors (exit code 1): missing frontmatter or required fields, unknown type
or status, type not allowed in its folder, unknown top-level folder, broken
or line-wrapped wikilinks, inbox note without `review: pending`.
Warnings (exit code 0): active notes not updated for `stale_after_days`.

Usage: python -m src.obsidian_vault.lint [--vault PATH] [--json] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.graph_mcp.indexer.obsidian import parse_frontmatter  # noqa: E402
from src.obsidian_vault.schema import (  # noqa: E402
    DEFAULT_VAULT, VaultSchema, load_schema, vault_path)

_FENCE = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_WIKILINK = re.compile(r"\[\[([^\]\n|#]*)(?:#[^\]\n|]*)?(?:\|[^\]\n]*)?\]\]")
_WRAPPED_LINK = re.compile(r"\[\[[^\]\[]*\n[^\]\[]*\]\]")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    path: str
    code: str
    message: str


def strip_code(text: str) -> str:
    return _CODE_SPAN.sub("", _FENCE.sub("", text))


def wikilink_targets(text: str) -> list[str]:
    return [t.strip() for t in _WIKILINK.findall(strip_code(text))]


def _link_index(vault: Path) -> tuple[set[str], set[str]]:
    """Resolvable link targets: note stems / vault-relative paths without
    `.md`, plus attachment names and paths (any other file)."""
    names: set[str] = set()
    paths: set[str] = set()
    for path in vault.rglob("*"):
        if not path.is_file() or any(p.startswith(".") for p in path.relative_to(vault).parts):
            continue
        relative = path.relative_to(vault).as_posix()
        if path.suffix == ".md":
            names.add(path.stem)
            paths.add(relative[:-3])
        names.add(path.name)
        paths.add(relative)
    return names, paths


def _resolves(target: str, names: set[str], paths: set[str], content_root: str) -> bool:
    if not target:  # [[#heading]] links to the same note
        return True
    target = target.removesuffix(".md")
    return (target in names or target in paths
            or f"{content_root}/{target}" in paths
            or target.split("/")[-1] in names)


def lint_vault(vault: Path, schema: VaultSchema | None = None,
               today: date | None = None) -> list[Finding]:
    schema = schema or load_schema()
    today = today or date.today()
    root = vault / schema.content_root
    findings: list[Finding] = []
    if not root.is_dir():
        return [Finding("error", str(root), "no-content-root",
                        f"Ordner {schema.content_root}/ fehlt im Vault")]
    for child in sorted(root.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir() and schema.folder(child.name) is None:
            findings.append(Finding("error", child.relative_to(vault).as_posix(),
                                    "unknown-folder", "Ordner nicht im Schema"))
        elif child.is_file() and child.suffix == ".md":
            findings.append(Finding("error", child.relative_to(vault).as_posix(),
                                    "note-outside-folder",
                                    "Notiz liegt direkt unter dem Inhaltsordner"))
    names, paths = _link_index(vault)
    for path in sorted(root.rglob("*.md")):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts) or len(relative_parts) < 2:
            continue
        rule = schema.folder(relative_parts[0])
        if rule is None:
            continue  # reported once as unknown-folder
        rel = path.relative_to(vault).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        findings.extend(_lint_note(rel, text, rule, schema, today, names, paths))
    return findings


def _lint_note(rel, text, rule, schema, today, names, paths) -> list[Finding]:
    out: list[Finding] = []

    def err(code: str, message: str) -> None:
        out.append(Finding("error", rel, code, message))

    frontmatter = parse_frontmatter(text)
    if not frontmatter:
        err("no-frontmatter", "Frontmatter fehlt")
        return out
    if rule.template_folder:
        if not frontmatter.get("type"):
            err("template-no-type", "Vorlage ohne type")
        elif frontmatter["type"] not in schema.types:
            err("unknown-type", f"type '{frontmatter['type']}' nicht im Schema")
        return out  # templates hold placeholders: no status/date/link checks
    for key in schema.required_fields:
        if not frontmatter.get(key):
            err("missing-field", f"Pflichtfeld '{key}' fehlt oder ist leer")
    note_type = frontmatter.get("type", "")
    status = frontmatter.get("status", "")
    if note_type and note_type not in schema.types:
        err("unknown-type", f"type '{note_type}' nicht im Schema")
    elif note_type and rule.types is not None and note_type not in rule.types:
        err("type-folder-mismatch", f"type '{note_type}' gehört nicht nach '{rule.name}'")
    if status and status not in schema.statuses:
        err("unknown-status", f"status '{status}' nicht erlaubt ({', '.join(schema.statuses)})")
    elif status and rule.statuses is not None and status not in rule.statuses:
        err("status-folder-mismatch", f"status '{status}' in '{rule.name}' nicht erlaubt")
    if rule.review_required and frontmatter.get("review") not in schema.review_values:
        err("inbox-not-pending", "Eingangsnotiz braucht 'review: pending'")
    updated = frontmatter.get("updated", "")
    if updated and not _DATE.match(updated):
        err("bad-date", f"updated '{updated}' ist kein Datum JJJJ-MM-TT")
    elif updated and status == "active":
        age = (today - date.fromisoformat(updated[:10])).days
        if age > schema.stale_after_days:
            out.append(Finding("warning", rel, "stale",
                               f"seit {age} Tagen nicht aktualisiert"))
    body = strip_code(text)
    for _ in _WRAPPED_LINK.findall(body):
        err("wrapped-link", "Zeilenumbruch innerhalb eines [[Links]]")
    for target in sorted(set(wikilink_targets(text))):
        if not _resolves(target, names, paths, schema.content_root):
            err("broken-link", f"[[{target}]] zeigt ins Leere")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--today", default=None)
    args = parser.parse_args(argv)
    vault = vault_path(args.vault) or DEFAULT_VAULT
    today = date.fromisoformat(args.today) if args.today else None
    findings = lint_vault(vault, today=today)
    errors = [f for f in findings if f.level == "error"]
    if args.json:
        print(json.dumps({"vault": str(vault), "errors": len(errors),
                          "warnings": len(findings) - len(errors),
                          "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            print(f"{finding.level.upper():7} {finding.path}: {finding.message} [{finding.code}]")
        print(f"{vault}: {len(errors)} Fehler, {len(findings) - len(errors)} Warnungen")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
