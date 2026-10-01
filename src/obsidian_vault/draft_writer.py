"""Draft writer: the only path by which TIM tools add notes to the vault.

Every note lands in the inbox folder (`00 Inbox`) with `review: pending`;
moving it into the verified area is a human step in Obsidian. The writer
never overwrites an existing file and refuses any name that would leave
the inbox. Bodies come from the caller; the writer adds frontmatter only.

Usage:
  python -m src.obsidian_vault.draft_writer decision --title T --source URL [--body-file F]
  python -m src.obsidian_vault.draft_writer research --title T --source URL [--body-file F]
  python -m src.obsidian_vault.draft_writer daily [--date YYYY-MM-DD] [--body-file F]
  add --dry-run to print the note instead of writing it.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.obsidian_vault.schema import (  # noqa: E402
    DEFAULT_VAULT, VaultSchema, load_schema, vault_path)

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
_SOURCE = re.compile(r"^https?://\S+$")

KIND_TYPES = {"decision": "decision", "research": "research", "daily": "daily",
              "incident": "incident", "report": "report"}


@dataclass(frozen=True)
class Draft:
    kind: str
    title: str
    body: str
    source: str = ""
    today: date | None = None


def safe_title(title: str) -> str:
    cleaned = " ".join(_UNSAFE.sub(" ", title).split()).strip(" .")
    if not cleaned:
        raise ValueError("Titel ist nach Bereinigung leer")
    return cleaned[:120]


def render(draft: Draft, schema: VaultSchema) -> str:
    note_type = KIND_TYPES.get(draft.kind)
    if note_type is None or note_type not in schema.types:
        raise ValueError(f"unbekannte Art '{draft.kind}'")
    if draft.source and not _SOURCE.match(draft.source):
        raise ValueError("source muss eine http(s)-URL sein")
    if draft.kind in ("decision", "research", "incident") and not draft.source:
        raise ValueError(f"{draft.kind} braucht eine Quelle (source)")
    day = (draft.today or date.today()).isoformat()
    lines = ["---", f"type: {note_type}", "status: planned", "review: pending",
             "project: TIM", f"created: {day}", f"updated: {day}"]
    if draft.source:
        lines.append(f"source: {draft.source}")
    lines.append("---")
    body = draft.body.replace("\r\n", "\n")
    if body.startswith("---"):
        raise ValueError("Body darf kein eigenes Frontmatter mitbringen")
    return "\n".join(lines) + f"\n# {safe_title(draft.title)}\n\n{body.rstrip()}\n"


def write_draft(vault: Path, draft: Draft, schema: VaultSchema | None = None,
                dry_run: bool = False) -> tuple[Path, str]:
    schema = schema or load_schema()
    text = render(draft, schema)
    inbox = (vault / schema.content_root / schema.inbox).resolve()
    path = (inbox / f"{safe_title(draft.title)}.md").resolve()
    if path.parent != inbox:
        raise ValueError("Ziel liegt außerhalb des Eingangsordners")
    if dry_run:
        return path, text
    if not (vault / schema.content_root).is_dir():
        raise FileNotFoundError(f"kein Vault unter {vault}")
    inbox.mkdir(exist_ok=True)
    with open(path, "x", encoding="utf-8") as handle:  # "x": never overwrite
        handle.write(text)
    return path, text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=sorted(KIND_TYPES))
    parser.add_argument("--title")
    parser.add_argument("--source", default="")
    parser.add_argument("--body-file")
    parser.add_argument("--date")
    parser.add_argument("--vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.date) if args.date else date.today()
    title = args.title or (f"{today.isoformat()} Tagesstatus" if args.kind == "daily" else None)
    if not title:
        parser.error("--title fehlt")
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
    vault = vault_path(args.vault) or DEFAULT_VAULT
    path, text = write_draft(vault, Draft(args.kind, title, body, args.source, today),
                             dry_run=args.dry_run)
    print(text if args.dry_run else f"Entwurf geschrieben: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
