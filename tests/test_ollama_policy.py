import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.llm.ollama_client import OllamaClient
from src.llm.prompts import observation_prompt
from src.models.market_data import Observation, ObservationKind


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_prompt_is_observation_only() -> None:
    observation = Observation(ObservationKind.REJECTION, "BTCUSDT", "1m", datetime.now(timezone.utc), "Rejection context.", 60, {"level": 65000})
    prompt = observation_prompt(observation)
    assert "Never create setups" in prompt
    assert str(observation.observation_id) in prompt


def test_forbidden_llm_output_is_rejected() -> None:
    client = OllamaClient("http://127.0.0.1:11434", "test")
    with patch("src.llm.ollama_client.urlopen", return_value=_Response({"response": json.dumps({"summary": "buy now"})})):
        with pytest.raises(ValueError, match="violated"):
            client._request("safe input")
