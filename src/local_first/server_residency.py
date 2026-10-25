"""Keep the configured server model resident without generating artificial work."""

from __future__ import annotations

import json
import os
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SERVER_OPTIONS = {"num_ctx": 65536, "num_batch": 256}


def configured_server() -> tuple[str, str] | None:
    url = os.getenv("TIM_QWEN_HARD_URL", "").strip().rstrip("/")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "127.0.0.2"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment or parsed.port == 0):
            return None
    except ValueError:
        return None
    return url, os.getenv("TIM_QWEN_HARD_MODEL", "").strip() or "qwen3-coder:30b"


def warm_server(url: str, model: str) -> str:
    # A pure keep-warm tick must not reload a resident diagnosis runner with
    # SERVER_OPTIONS, or evict another model. Real tasks own their own options.
    with urlopen(Request(f"{url}/api/ps", method="GET"), timeout=30) as response:
        resident = json.load(response)
    if not isinstance(resident, dict) or not isinstance(resident.get("models"), list):
        raise ValueError("server residency is unknown")
    names = []
    for item in resident["models"]:
        name = (item.get("name") or item.get("model")) if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("server residency contains an invalid model")
        names.append(name)
    if names:
        return "WARM" if model in names else "RESIDENT_OTHER"
    # Empty prompt: load only. No token generation, model download or server shell.
    payload = {"model": model, "stream": False, "keep_alive": -1, "options": SERVER_OPTIONS}
    request = Request(f"{url}/api/generate", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=900) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get("done") is not True:
        raise ValueError("server model did not finish loading")
    return "WARM"


def residency_loop(stop: threading.Event) -> None:
    server = configured_server()
    if server is None:
        return
    while not stop.is_set():
        try:
            state, interval = warm_server(*server), 300
        except Exception:  # A broken tunnel must not stop the coordinator.
            state, interval = "UNAVAILABLE", 60
        print(json.dumps({"TIM_SERVER_MODEL": state, "model": server[1]}), flush=True)
        stop.wait(interval)


def start_residency() -> threading.Event:
    stop = threading.Event()
    if os.getenv("TIM_QWEN_SERVER_KEEP_WARM") == "1" and configured_server() is not None:
        threading.Thread(target=residency_loop, args=(stop,), name="tim-server-residency", daemon=True).start()
    return stop
