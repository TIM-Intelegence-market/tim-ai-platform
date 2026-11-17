"""S7b forward journal by hand (paper only). The research workshop steps it every 15 minutes on the Mac.

    python -m src.research_lab.forward step      # fetch new closed 4h bars, re-run S7b, append to the journal
    python -m src.research_lab.forward status    # last status (read only)
    python -m src.research_lab.forward verify    # check the journal's hash chain (read only)

Orderflow paper journal (OF2 with the orderflow gate on current data, paper only):

    python -m src.research_lab.forward of-start  # fix the start (signals count from the next full UTC day)
    python -m src.research_lab.forward of-step   # fetch finished days and re-run the engine (the workshop does this)
    python -m src.research_lab.forward of-status # last status (read only)

M8 shadow journal (Fabervaale model M8 + management variants, shares the OF store; the workshop starts it):

    python -m src.research_lab.forward of-m8-step | of-m8-status

Orderflow paper journal on live trades (stage B, own folder OF_LIVE; recorder and step loop end on a STOP file):

    python -m src.research_lab.forward of-record     --trades DIR [--seconds N]
    python -m src.research_lab.forward of-live-step  --trades DIR [--folder DIR]
    python -m src.research_lab.forward of-live-run   --trades DIR [--folder DIR] [--every 300]
    python -m src.research_lab.forward of-live-status [--folder DIR]
    python -m src.research_lab.forward of-live-pull   # Mac: copy the PS5 journal and compare with stage A
"""
from __future__ import annotations

import argparse
import json
import sys

from src.research_lab.forward.s7b import FOLDER, ForwardJournal


def _stage_b(args: argparse.Namespace) -> int:
    from pathlib import Path

    from src.research_lab.forward import of_live
    from src.research_lab.forward.live_recorder import TradeRecorder

    folder = Path(args.folder or of_live.FOLDER)
    if args.command == "of-live-status":
        out = of_live.LiveJournal(folder, trades_root=args.trades or ".").status() or {"status": "noch kein Lauf"}
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.trades:
        print("--trades fehlt", file=sys.stderr)
        return 2
    if args.command == "of-record":
        recorder = TradeRecorder(args.trades)
        out = recorder.run(stop_after=args.seconds, stop_file=Path(args.trades) / "STOP")
    elif args.command == "of-live-step":
        out = of_live.LiveJournal(folder, trades_root=args.trades).step()
    else:
        out = {"steps": of_live.run(of_live.LiveJournal(folder, trades_root=args.trades),
                                    every=args.every or of_live.STEP_EVERY, stop_after=args.seconds)}
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("step", "status", "verify", "of-start", "of-step", "of-status",
                                                "of-m8-step", "of-m8-status", "of-record", "of-live-step",
                                                "of-live-run", "of-live-status", "of-live-pull"))
    parser.add_argument("--folder")
    parser.add_argument("--trades", help="recorder root (stage B)")
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--every", type=float)
    args = parser.parse_args(argv)
    if args.command == "of-live-pull":
        from src.research_lab.forward import of_live_mirror

        print(json.dumps(of_live_mirror.pull(args.folder or "."), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "of-record" or args.command.startswith("of-live-"):
        return _stage_b(args)
    if args.command.startswith("of-m8-"):
        from src.research_lab.forward import of_paper

        root = args.folder or "."
        out = of_paper.step_m8(root) if args.command == "of-m8-step" else (
            of_paper.m8_journal(root).status() or {"status": "noch kein Lauf"})
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
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
