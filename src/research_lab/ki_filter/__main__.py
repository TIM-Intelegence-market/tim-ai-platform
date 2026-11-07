"""KI1 command line (paper only; never touches the live trader).

    python -m src.research_lab.ki_filter decide [--journal-dir ~/TIM-live/data/journal] [--log PATH] [--dry-run]
    python -m src.research_lab.ki_filter report [--journal-dir ...] [--log PATH]

``decide`` judges new OPEN plans of the 15m, 1h and 1d journals with the local Ollama model.
Market rows come from Postgres only if TIM_KI_MARKET_DSN names a read-only role; without it the
AI sees plan, history and the other strategies only. ``--dry-run`` prints the prompts and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.dashboard import plan_journal
from src.research_lab.ki_filter import decide as decide_mod
from src.research_lab.ki_filter.evaluate import evaluate
from src.research_lab.ki_filter.market import MarketReader

JUDGED = {"15m": "tim_plan_journal_short.json", "1h": "tim_plan_journal_mid.json", "1d": "tim_plan_journal_long.json"}
PEERS = {"30m": "tim_plan_journal.json", "struct": "tim_plan_journal_struct.json",
         "level": "tim_plan_journal_level.json", "vp": "tim_plan_journal_vp.json"}
DEFAULT_DIR = Path.home() / "TIM-live/data/journal"
DEFAULT_LOG = Path.home() / "Library/Application Support/TIM/ki-filter/ki1_decisions.jsonl"
DEFAULT_MODEL = os.environ.get("TIM_KI_MODEL", "qwen3.5:9b")


def _views(directory: Path, names: dict[str, str]) -> dict[str, dict]:
    return {key: plan_journal.load_view(directory / name) for key, name in names.items() if (directory / name).exists()}


def _ask(url: str, model: str):
    from src.llm.ollama_client import OllamaClient
    client = OllamaClient(url, model, timeout=240, observation_only=False,
                          generation_options={"temperature": 0, "seed": 7}, keep_alive="10m")
    return lambda prompt: asyncio.run(client.generate_json(prompt, schema=decide_mod.ANSWER_SCHEMA))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.ki_filter")
    parser.add_argument("command", choices=("decide", "report"))
    parser.add_argument("--journal-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=os.environ.get("TIM_OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    journals = _views(args.journal_dir, JUDGED)
    if args.command == "report":
        print(json.dumps(evaluate(decide_mod.read_log(args.log), journals), indent=2, ensure_ascii=False))
        return 0
    peers = {**journals, **_views(args.journal_dir, PEERS)}
    reader = MarketReader(os.environ.get("TIM_KI_MARKET_DSN"))
    market = (lambda symbol, timeframe, cutoff: reader.candles(symbol, timeframe, cutoff)) if reader.configured \
        else (lambda symbol, timeframe, cutoff: [])
    if args.dry_run:
        prompts: list[str] = []
        def ask(prompt: str):
            prompts.append(prompt)
            raise RuntimeError("dry run")
        scratch = Path(os.devnull)
        summary = decide_mod.run(journals, peers, args.log if args.log.exists() else scratch, ask, args.model, market)
        print(json.dumps({"would_judge": len(prompts), "prompts": prompts}, indent=2, ensure_ascii=False))
        return 0
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with (args.log.parent / (args.log.name + ".lock")).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"status": "busy"}))
            return 0
        summary = decide_mod.run(journals, peers, args.log, _ask(args.ollama_url, args.model), args.model, market,
                                 now=datetime.now(timezone.utc))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
