"""R-KI-1 command line (paper only; never places an order, the live trader does not read it).

    python -m src.research_lab.ki_entry run [--api URL] [--log PATH] [--dry-run]
    python -m src.research_lab.ki_entry report [--log PATH]

``run`` reads the chart model from the local dashboard (BTCUSDT, 15m, perp), plays open paper trades forward and
asks the local Ollama model when the newest closed candle touched a strong zone. ``--dry-run`` prints the
prompt and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from src.research_lab.ki_entry import decide
from src.research_lab.ki_filter.decide import read_log

DEFAULT_API = "http://127.0.0.1:8765/api/chart/live?symbol=BTCUSDT&tf=15m&market=perp"
DEFAULT_LOG = Path.home() / "Library/Application Support/TIM/ki-entry/ki_entry_decisions.jsonl"
DEFAULT_MODEL = os.environ.get("TIM_KI_MODEL", "qwen3.5:9b")


def _ask(url: str, model: str):
    from src.llm.ollama_client import OllamaClient
    client = OllamaClient(url, model, timeout=240, observation_only=False,
                          generation_options={"temperature": 0, "seed": 7}, keep_alive="10m")
    return lambda prompt: asyncio.run(client.generate_json(prompt, schema=decide.ANSWER_SCHEMA))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.ki_entry")
    parser.add_argument("command", choices=("run", "report"))
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=os.environ.get("TIM_OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "report":
        print(json.dumps(decide.report(read_log(args.log)), indent=2, ensure_ascii=False))
        return 0
    with urlopen(args.api, timeout=60) as response:  # local dashboard only (default 127.0.0.1)
        model = json.load(response)
    if args.dry_run:
        hit = decide.trigger(model, read_log(args.log), time.time())
        prompt = decide.build_prompt(decide.build_context(model, hit["zone"], time.time())) if hit and "zone" in hit else None
        print(json.dumps({"trigger": hit, "prompt": prompt}, indent=2, ensure_ascii=False, default=str))
        return 0
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with (args.log.parent / (args.log.name + ".lock")).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"status": "busy"}))
            return 0
        summary = decide.run(model, args.log, _ask(args.ollama_url, args.model), args.model)
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
