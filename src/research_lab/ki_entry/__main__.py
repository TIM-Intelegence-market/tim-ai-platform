"""R-KI-1 command line (paper only; never places an order, the live trader does not read it).

    python -m src.research_lab.ki_entry run [--api URL] [--log PATH] [--dry-run]
    python -m src.research_lab.ki_entry report [--log PATH]

``run`` reads the chart model from the local dashboard (BTCUSDT, 15m, perp), plays open paper trades forward and
asks the local Ollama model when the newest closed candle touched a strong zone. ``--dry-run`` prints the
prompt and writes nothing.
After the KI step, Hermes (DeepSeek) gives a second opinion on a fresh decision (``hermes.py``; public numbers only,
``--no-hermes`` switches it off). ``report`` adds Hermes' verdicts and the Bitunix paper account.
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
from urllib.parse import urlparse
from urllib.request import urlopen

from src.research_lab.ki_entry import decide, deepseek, hermes
from src.research_lab.ki_filter.decide import read_log

DEFAULT_API = "http://127.0.0.1:8765/api/chart/live?symbol=BTCUSDT&tf=15m&market=perp"
DEFAULT_LOG = Path.home() / "Library/Application Support/TIM/ki-entry/ki_entry_decisions.jsonl"
DEFAULT_MODEL = os.environ.get("TIM_KI_MODEL", "qwen3.5:9b")


def _ask(url: str, model: str):
    from src.llm.ollama_client import OllamaClient
    client = OllamaClient(url, model, timeout=240, observation_only=False,
                          generation_options={"temperature": 0, "seed": 7}, keep_alive="10m")
    return lambda prompt: asyncio.run(client.generate_json(prompt, schema=decide.ANSWER_SCHEMA))


def _hermes(text: str):
    from src.dashboard import hermes_bridge
    return hermes_bridge.ask(text, limit=hermes.MAX_PROMPT, record=False)


def _deepseek_log(log: Path) -> Path:
    return log.with_name(log.stem + "_deepseek" + log.suffix)


def _hermes_long(text: str):
    from src.dashboard import hermes_bridge
    return hermes_bridge.ask(text, limit=len(text) + 1, record=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.ki_entry")
    parser.add_argument("command", choices=("run", "report"))
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=os.environ.get("TIM_OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-hermes", action="store_true", help="no second opinion from Hermes (DeepSeek)")
    parser.add_argument("--no-deepseek", action="store_true", help="no own DeepSeek decision (R-KI-2)")
    args = parser.parse_args(argv)
    if args.command == "report":
        records = read_log(args.log)
        ds = read_log(_deepseek_log(args.log))
        print(json.dumps({**decide.report(records), "hermes": hermes.hermes_summary(records), "bitunix": hermes.bitunix(records),
                          "deepseek": {**decide.report(ds, decide.DEEPSEEK_PROFILE.rule), "bitunix": hermes.bitunix(ds)}},
                         indent=2, ensure_ascii=False))
        return 0
    if urlparse(args.api).hostname not in ("127.0.0.1", "localhost"):
        parser.error("--api must point to the local dashboard (127.0.0.1)")
    with urlopen(args.api, timeout=60) as response:  # local dashboard only
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
        started = time.time()   # one clock for both: the local AI needs minutes, DeepSeek must not find the candle stale after it
        summary = decide.run(model, args.log, _ask(args.ollama_url, args.model), args.model, now=started)
        if not args.no_deepseek:   # before Hermes' second opinion
            summary["deepseek"] = decide.run(model, _deepseek_log(args.log), deepseek.decider(_hermes_long),
                                             deepseek.MODEL_NAME, now=started, profile=decide.DEEPSEEK_PROFILE)
        if not args.no_hermes:
            now = time.time()
            stamp = decide._iso(now)
            summary["hermes"] = hermes.opinions(read_log(args.log), args.log, _hermes, now, stamp)
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
