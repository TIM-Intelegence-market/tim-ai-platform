"""python -m src.research_lab.learning status --register PATH   (read only: checks the chain, prints state, head hash and overdue challengers)"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Sequence

from src.research_lab.learning.registry import LearningError, ModelRegister


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Learning loop L1: model register (read only).")
    parser.add_argument("command", choices=["status"])
    parser.add_argument("--register", required=True)
    args = parser.parse_args(argv)
    register = ModelRegister(args.register)
    try:
        state = register.state()
        state["head"] = register.head()
        state["overdue"] = register.overdue(datetime.now(timezone.utc))
    except LearningError as error:
        print(f"BROKEN: {error}")
        return 2
    print(json.dumps(state, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
