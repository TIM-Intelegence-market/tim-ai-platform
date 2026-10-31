"""F10: run one rule (schema tim_rule/1) on training and validation for a registered study.

    python scripts/research_lab_rule.py --spec regel.json [--archive DIR] [--random-runs 1000] [--seed 0]

Started by the job runner (F4) after Uzi's approval; writes ``result.json`` (result contract F5) and
``ergebnis.md`` into ``$TIM_RESEARCH_OUT`` (or ``--out``). The holdout is never loaded: a period that reaches
2025 is refused, and the archive store refuses holdout files anyway. For a quick exploration without a
study use ``python -m src.research_lab.workshop rule-test`` instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore  # noqa: E402
from src.research_lab.workshop import rules  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--random-runs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    out = args.out or Path(os.environ.get("TIM_RESEARCH_OUT", "out"))
    rule = json.loads(args.spec.read_text(encoding="utf-8"))
    try:
        store = ArchiveStore(args.archive)
        bars, funding, notes, refs = rules.load_data(store, rule)
        outcome = rules.evaluate(rule, bars, funding, random_runs=args.random_runs, seed=args.seed, notes=notes)
        outcome["metrics"]["data_hash"] = store.dataset_hash(refs)
    except (rules.RuleError, FileNotFoundError, ValueError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "ergebnis.md").write_text(rules.render_markdown("Studienlauf", rule, outcome, ""), encoding="utf-8")
    print(outcome["result"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
