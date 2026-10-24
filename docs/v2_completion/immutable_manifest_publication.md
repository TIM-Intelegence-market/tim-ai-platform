# Immutable qualification-manifest publication

`write_immutable_json` is shared by campaign activation, daily collection and
the qualification monitor. A published path must retain its first complete
payload, even if two invocations race.

Previously the function checked for an existing path, wrote a shared `.tmp`
file and used `os.replace`. Concurrent writers could clobber the temporary file,
raise `FileNotFoundError`, or replace an already published winner.

Each writer now finishes and flushes its own private temporary file in the
same directory. `os.link` then publishes the complete file only if the final
path is absent. A collision returns `UNCHANGED` only when the published bytes
match; different bytes raise `FileExistsError`. Temporary files are removed
on success, collision and publication failure. The return values and JSON
encoding remain unchanged. No overwrite fallback is used if the filesystem
cannot create hard links: publication fails and preserves existing evidence.

Private temporary directories isolate writers. Published files retain normal
file-creation permissions under the caller's umask; existing manifests and
their permissions are untouched. A regression test compares the published mode
with a normally created reference file. This change does not add directory-journal
fsync or claim a new power-loss durability guarantee.

Tests in `tests/test_v2_completion_qualification.py` synchronize two competing
writers immediately before filesystem publication. Different payloads must
produce exactly one winner and one conflict; identical payloads must produce
one creation and one unchanged result. Both cases verify the final JSON and
absence of temporary files. Existing-evidence and publication-failure tests
verify that old content survives and incomplete output is not left behind.

This is a technical contribution to B03 (artifact integrity).
It does not start a campaign, qualify historical records, supply reviewer
signatures or repair historical provenance under B05 or close the overall V2 readiness blockers. Verification uses only
local temporary directories, with no live database or server access.
