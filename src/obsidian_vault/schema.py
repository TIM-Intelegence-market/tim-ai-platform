"""Vault schema loader (folders, note types, status vocabulary)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/obsidian/vault_schema.json"
DEFAULT_VAULT = Path.home() / "Documents/TIM/TIM OBSIDIAN"
_PREFIX = re.compile(r"^(\d+)\s")


def vault_path(explicit: str | os.PathLike | None = None) -> Path | None:
    """One resolution order for every TIM tool: explicit argument, then
    TIM_OBSIDIAN_VAULT, then TIM_GRAPH_MCP_VAULT (legacy name). None when
    nothing is configured; callers decide whether a default applies."""
    for value in (explicit, os.environ.get("TIM_OBSIDIAN_VAULT"),
                  os.environ.get("TIM_GRAPH_MCP_VAULT")):
        if value:
            return Path(value).expanduser()
    return None


@dataclass(frozen=True)
class FolderRule:
    name: str
    types: tuple[str, ...] | None  # None means any type
    statuses: tuple[str, ...] | None = None
    review_required: bool = False
    template_folder: bool = False

    @property
    def prefix(self) -> str | None:
        match = _PREFIX.match(self.name)
        return match.group(1) if match else None


@dataclass(frozen=True)
class VaultSchema:
    version: str
    content_root: str
    statuses: tuple[str, ...]
    required_fields: tuple[str, ...]
    types: dict[str, str]
    folders: dict[str, FolderRule]
    review_values: tuple[str, ...] = ("pending",)
    stale_after_days: int = 60
    optional_fields: tuple[str, ...] = field(default_factory=tuple)

    def folder(self, name: str) -> FolderRule | None:
        return self.folders.get(name)

    @property
    def inbox(self) -> str:
        return next(name for name, rule in self.folders.items() if rule.review_required)

    @property
    def template_folders(self) -> tuple[str, ...]:
        return tuple(name for name, rule in self.folders.items() if rule.template_folder)


def load_schema(path: Path = SCHEMA_PATH) -> VaultSchema:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    folders: dict[str, FolderRule] = {}
    for name, rule in raw["folders"].items():
        types = rule.get("types", "*")
        statuses = rule.get("status")
        folders[name] = FolderRule(
            name=name,
            types=None if types == "*" else tuple(types),
            statuses=tuple(statuses) if statuses else None,
            review_required=bool(rule.get("review_required", False)),
            template_folder=bool(rule.get("template_folder", False)))
    schema = VaultSchema(
        version=raw["schema_version"], content_root=raw["content_root"],
        statuses=tuple(raw["statuses"]), required_fields=tuple(raw["required_fields"]),
        types=dict(raw["types"]), folders=folders,
        review_values=tuple(raw.get("review_values", ["pending"])),
        stale_after_days=int(raw.get("stale_after_days", 60)),
        optional_fields=tuple(raw.get("optional_fields", [])))
    _validate(schema)
    return schema


def _validate(schema: VaultSchema) -> None:
    prefixes = [rule.prefix for rule in schema.folders.values()]
    duplicates = sorted({p for p in prefixes if p is not None and prefixes.count(p) > 1})
    if duplicates:
        raise ValueError(f"duplicate folder prefixes: {duplicates}")
    if sum(rule.review_required for rule in schema.folders.values()) != 1:
        raise ValueError("exactly one review (inbox) folder is required")
    for rule in schema.folders.values():
        unknown = set(rule.types or ()) - set(schema.types)
        if unknown:
            raise ValueError(f"{rule.name}: unknown types {sorted(unknown)}")
        bad = set(rule.statuses or ()) - set(schema.statuses)
        if bad:
            raise ValueError(f"{rule.name}: unknown statuses {sorted(bad)}")
