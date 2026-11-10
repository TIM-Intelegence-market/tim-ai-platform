"""S7b forward journal by hand (paper only). The research workshop steps it every 15 minutes on the Mac.

    python -m src.research_lab.forward step      # fetch new closed 4h bars, re-run S7b, append to the journal
    python -m src.research_lab.forward status    # last status (read only)
    python -m src.research_lab.forward verify    # check the journal's hash chain (read only)

Orderflow paper journal (OF2 with the orderflow gate on current data, paper only):

    python -m src.research_lab.forward of-start  # fix the start (signals count from the next full UTC day)
    python -m src.research_lab.forward of-step   # fetch finished days and re-run the engine (the workshop does this)
    python -m src.research_lab.forward of-status # last status (read only)
"""
from __future__ import annotations

import argparse
import json
import sys

from src.research_lab.forward.s7b import FOLDER, ForwardJournal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("step", "status", "verify", "of-start", "of-step", "of-status"))
    parser.add_argument("--folder")
    args = parser.parse_args(argv)
    if args.command.startswith("of-"):
        from src.research_lab.forward.of_paper import FOLDER as OF_FOLDER
        from src.research_lab.forward.of_paper import PaperJournal

        paper = PaperJournal(args.folder or OF_FOLDER)
        if args.command == "of-start":
            paper.folder.mkdir(parents=True, exist_ok=True)
            out = paper.start()
        elif args.command == "of-step":
            out = paper.step()
        else:
            out = paper.status() or {"status": "noch kein Lauf"}
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    args.folder = args.folder or str(FOLDER)
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
