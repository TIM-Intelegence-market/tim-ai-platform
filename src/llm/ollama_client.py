from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.request import Request, urlopen


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 30,
        *,
        observation_only: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/api/generate"
        self.model = model
        self.timeout = timeout
        self.observation_only = observation_only

    async def generate_json(self, prompt: str, *, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ask for one JSON object; with ``schema`` Ollama constrains decoding to that JSON schema."""
        if schema is None:
            return await asyncio.to_thread(self._request, prompt)
        return await asyncio.to_thread(self._request, prompt, schema)

    async def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                   options: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """One non-streaming ``/api/chat`` turn; returns the assistant message (may hold tool_calls).

        ``timeout`` overrides the client timeout for this turn only (tool-loop turns grow with each file read)."""
        return await asyncio.to_thread(self._chat, messages, tools, options, timeout)

    async def available(self) -> bool:
        """Probe the local Ollama API without running a model."""
        return await asyncio.to_thread(self._available)

    async def installed_models(self) -> tuple[str, ...]:
        """Return locally installed Ollama model names without pulling or running anything."""
        return await asyncio.to_thread(self._installed_models)

    async def model_available(self) -> bool:
        """Return True only when the configured model is already installed locally."""
        return self.model in await self.installed_models()

    def _tags_payload(self) -> dict[str, Any]:
        request = Request(f"{self.base_url}/api/tags", method="GET")
        with urlopen(request, timeout=min(self.timeout, 3)) as response:
            payload = json.loads(response.read())
        if response.status != 200 or not isinstance(payload, dict):
            raise ValueError("Ollama tags endpoint returned an invalid response")
        return payload

    def _available(self) -> bool:
        try:
            payload = self._tags_payload()
            return isinstance(payload.get("models"), list)
        except (OSError, ValueError, TypeError, TimeoutError, json.JSONDecodeError):
            return False

    def _installed_models(self) -> tuple[str, ...]:
        try:
            payload = self._tags_payload()
        except (OSError, ValueError, TypeError, TimeoutError, json.JSONDecodeError):
            return ()
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            return ()
        names: list[str] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            value = item.get("name") or item.get("model")
            if isinstance(value, str) and value and value not in names:
                names.append(value)
        return tuple(names)

    def _chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
              options: dict[str, Any] | None, timeout: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False, "think": False}
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        request = Request(f"{self.base_url}/api/chat", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout if timeout is None else timeout) as response:
            body = json.loads(response.read())
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, dict):
            raise ValueError("Ollama chat response has no message")
        return message

    def _request(self, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False,
                           "format": schema if schema is not None else "json", "think": False}).encode()
        request = Request(self.endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())
        result = json.loads(payload.get("response", "{}"))
        if not isinstance(result, dict):
            raise ValueError("Ollama response must be a JSON object")
        if self.observation_only:
            forbidden = ("entry", "target", "stop loss", "position size", "buy", "sell", "order")
            if any(term in json.dumps(result).lower() for term in forbidden):
                raise ValueError("Ollama response violated observation-only policy")
        return result
