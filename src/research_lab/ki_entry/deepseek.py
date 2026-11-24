"""R-KI-2: DeepSeek (through Hermes) decides itself at the same strong-zone moments (Uzi 24.11.2026 "go deepseek").

Same picture and prompt as the local model, own append-only log, own Bitunix paper account, fixed guards
(``decide.DEEPSEEK_PROFILE``). DeepSeek runs in the cloud: the prompt holds public market numbers only.
Because its answers swing (replay 24.11.: SHORT, SHORT, then LONG 30 minutes later), it is asked ``ASKS`` times
and a trade is taken only when every answer names the same action; otherwise the decision is NICHTS.
A failed or unreadable answer raises: nothing is written and the next run retries.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from src.research_lab.ki_entry import ACTIONS, READINGS

ASKS = 2
MODEL_NAME = "deepseek (Hermes)"
FORMAT = ("\n\nNutze keine Werkzeuge. Antworte mit genau einem JSON-Objekt mit diesen Schlüsseln und sonst nichts: "
          '{"lesart": "HAELT|BRICHT|UNKLAR", "aktion": "LONG|SHORT|NICHTS", "einstieg": Zahl, "stop": Zahl, "ziel": Zahl, '
          '"vertrauen": Zahl von 0 bis 1, "grund": "ein bis zwei Sätze"}')


def parse(text: str) -> dict[str, Any]:
    """The JSON object in a chat answer (code fences and words around it are ignored)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON in the answer")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise TypeError("answer is not an object")
    action = str(data.get("aktion") or data.get("richtung") or data.get("trade") or "").upper()
    if action not in ACTIONS:
        raise ValueError("answer without a valid aktion")
    reading = str(data.get("lesart") or "").upper()
    confidence = data.get("vertrauen")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        confidence = 0.5   # DeepSeek sometimes leaves it out; the number is not used for the trade
    return {"aktion": action, "lesart": reading if reading in READINGS else None,
            "einstieg": data.get("einstieg", 0), "stop": data.get("stop", 0), "ziel": data.get("ziel", 0),
            "vertrauen": confidence, "grund": str(data.get("grund") or "")}


def decider(ask: Callable[[str], Mapping[str, Any]], asks: int = ASKS) -> Callable[[str], dict[str, Any]]:
    """``ask`` is ``hermes_bridge.ask`` (returns ok/answer/error). The result fits ``decide.check_answer``."""
    def decide_once(prompt: str) -> dict[str, Any]:
        answers = []
        for _ in range(asks):
            reply = ask(prompt + FORMAT)
            if not reply.get("ok"):
                raise RuntimeError(str(reply.get("error") or "no answer")[:200])
            answers.append(parse(str(reply.get("answer") or "")))
        actions = [a["aktion"] for a in answers]
        if len(set(actions)) > 1:
            return {"aktion": "NICHTS", "lesart": "UNKLAR", "einstieg": 0, "stop": 0, "ziel": 0, "vertrauen": 0.0,
                    "grund": "Antworten uneinig (" + " / ".join(actions) + "): kein Trade.", "gefragt": actions}
        return {**answers[0], "gefragt": actions}
    return decide_once
