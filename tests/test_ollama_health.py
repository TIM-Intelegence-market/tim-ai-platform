import json

from src.llm.ollama_client import OllamaClient


def test_ollama_availability_accepts_models_endpoint(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self): return json.dumps({"models":[]}).encode()
    monkeypatch.setattr("src.llm.ollama_client.urlopen", lambda *_, **__: Response())
    assert OllamaClient("http://127.0.0.1:11434","qwen")._available() is True


def test_ollama_availability_handles_unreachable_service(monkeypatch):
    def fail(*_, **__): raise OSError("offline")
    monkeypatch.setattr("src.llm.ollama_client.urlopen", fail)
    assert OllamaClient("http://127.0.0.1:11434","qwen")._available() is False
