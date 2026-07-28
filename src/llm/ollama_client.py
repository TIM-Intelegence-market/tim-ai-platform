from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.request import Request, urlopen


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 30) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/api/generate"
        self.model, self.timeout = model, timeout

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, prompt)

    async def available(self) -> bool:
        """Probe the local Ollama API without running a model."""
        return await asyncio.to_thread(self._available)

    def _available(self) -> bool:
        request = Request(self.endpoint.rsplit("/api/generate", 1)[0] + "/api/tags", method="GET")
        try:
            with urlopen(request, timeout=min(self.timeout, 3)) as response:
                payload = json.loads(response.read())
            return response.status == 200 and isinstance(payload.get("models"), list)
        except (OSError, ValueError, TypeError, TimeoutError):
            return False

    def _request(self, prompt: str) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False, "format": "json"}).encode()
        request = Request(self.endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())
        result = json.loads(payload.get("response", "{}"))
        if not isinstance(result, dict):
            raise ValueError("Ollama response must be a JSON object")
        forbidden = ("entry", "target", "stop loss", "position size", "buy", "sell", "order")
        if any(term in json.dumps(result).lower() for term in forbidden):
            raise ValueError("Ollama response violated observation-only policy")
        return result
