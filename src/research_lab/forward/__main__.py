"""S7b forward journal by hand (paper only). The research workshop steps it every 15 minutes on the Mac.

    python -m src.research_lab.forward step      # fetch new closed 4h bars, re-run S7b, append to the journal
    python -m src.research_lab.forward status    # last status (read only)
    python -m src.research_lab.forward verify    # check the journal's hash chain (read only)
"""
from __future__ import annotations

import argparse
import json
import sys

from src.research_lab.forward.s7b import FOLDER, ForwardJournal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("step", "status", "verify"))
    parser.add_argument("--folder", default=str(FOLDER))
    args = parser.parse_args(argv)
    journal = ForwardJournal(args.folder)
    if args.command == "step":
        out = journal.step()
    elif args.command == "status":
        out = journal.status() or {"status": "noch kein Lauf"}
    else:
        events = journal.events()
        out = {"events": len(events), "chain": "ok", "head": events[-1]["hash"] if events else None}
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
