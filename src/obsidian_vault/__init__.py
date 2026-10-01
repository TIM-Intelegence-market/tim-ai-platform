"""TIM Obsidian vault tooling: schema, lint, migration and draft writer.

The vault is TIM's human-readable, verified knowledge layer. Tools here
read it to check it against `schemas/obsidian/vault_schema.json`; the only
writing paths are the migration into a fresh, empty target directory and
the draft writer, which writes new notes into `00 Inbox` only."""
