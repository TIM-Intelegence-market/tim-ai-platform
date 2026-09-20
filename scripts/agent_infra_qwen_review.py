#!/usr/bin/env python3
"""STEP 32: bounded Qwen review of the agent infrastructure.

Sends a compact evidence pack (no repository, no vault, no secrets) to
qwen2.5:7b via the proven HTTP interface + six-heading contract, stores
the verdict as ledger evidence, and prints the adjudication inputs.
GLM adjudicates findings afterwards — Qwen is read-only reviewer."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
OUT = WORKTREE / ".unlazy/agent-infrastructure-v1/evidence/qwen_review.json"

PACK = """TIM AGENT INFRASTRUCTURE V1 — bounded evidence pack (2026-09-18)

REGISTRATION ARCHITECTURE:
Serena projects: control root ~/Documents/TIM (read context) +
platform repo ~/Documents/TIM/tim (canonical read source) +
isolated worktree (only writable scope). Discovery: control-repo
registration alone cannot index TIM code because tim/ is a nested
repository ignored by the control repo's ignore rules; additive
per-repository registration is therefore required.

TOOL ROUTER V1:
Deterministic intent->tool table: symbol/references/tests->Serena
(secondary TIMGraphMCP, fallback NativeSearch); mission/incident/impact->
TIMGraphMCP; past decision->Obsidian; visualization->Graphify;
implementation->OpenCode/GLM; review->Qwen; code search->NativeSearch.
Primary unavailable -> explicit available secondary/fallback else BLOCKED.
Never fake availability. Router selects context tools only, grants no
write authority (profiles define authority separately).

STABLE-ID BRIDGE:
Serena (relative_path, name_path, kind) -> Graph MCP canonical ids
file:/class:/method:/function:/test: with Serena '/' nesting normalized
to '.'. Serena ids never become canonical.

PACKS + BUDGET:
AgentContextPack bounded: symbols<=10 refs<=20 tests<=10 neighbors<=50
depth<=4 notes<=5 incidents<=5, serialized<=24000 chars (enforced, raises
if impossible after optional-section drop). RepairContextPack: required
fields incident/fingerprint/classification/nodes/symbols/tests/prior
repairs/gates/safety; empty lists allowed (no prior repairs is valid).

FALLBACKS: serena down -> native bounded search; graph down -> honest
BLOCKED for mission context; obsidian down -> historical context
unavailable; qwen down -> review omitted honestly; no fallback
impersonates a primary.

SECURITY: production read-only/out of scope; writes only isolated
worktree; no secrets in packs/logs; serena dashboard auth_secret exists
in serena_config.yml and is excluded from graph/docs/tests/commits.

TESTS: 85/85 pass (router determinism, health, packs, bridge, preflight,
failure modes, secret exclusion). Real acceptance: CandleAggregator +
DurableOutboxWorker via Serena (44/19 references), bridge into Graph MCP.
Controlled edit via serena replace_content in isolated worktree: test
passed, diff scope exact.
"""


def main() -> int:
    prompt = (
        "You are reviewing TIM agent infrastructure. Challenge the design.\n"
        "Answer with EXACTLY these six headings, each on its own line:\n"
        "PROBLEM_SUMMARY\nROOT_CAUSE_HYPOTHESIS\nFILES_RELEVANT\n"
        "PROPOSED_FIX\nTEST_PLAN\nRISK\n"
        "Challenge specifically: routing ambiguity, stale tool-health, "
        "nested project ambiguity, stable-ID collisions, context-budget "
        "overflow, secret leakage, accidental write authority, fallback "
        "correctness, self-healing misuse risk.\n\n" + PACK)
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps({"model": "qwen2.5:7b", "prompt": prompt,
                         "stream": False, "num_predict": 600}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read())
    answer = result.get("response", "")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"model": "qwen2.5:7b",
                               "pack_chars": len(PACK),
                               "answer": answer}, indent=2) + "\n")
    print(answer)
    headings = [h for h in ("PROBLEM_SUMMARY", "ROOT_CAUSE_HYPOTHESIS",
                            "FILES_RELEVANT", "PROPOSED_FIX", "TEST_PLAN",
                            "RISK") if h in answer]
    print(f"\nHEADING_CONTRACT={'PASS' if len(headings) == 6 else 'FAIL'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
