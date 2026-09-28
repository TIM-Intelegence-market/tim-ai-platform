import json
from pathlib import Path


def test_paper_demo_is_prepared_with_user_selected_virtual_balance() -> None:
    payload = json.loads((Path("config") / "paper_demo.json").read_text(encoding="utf-8"))
    assert payload["starting_balance_usdt"] == 100.0
    assert payload["status"] == "PREPARED_DATA_QUALITY_GATE_PENDING"
    assert payload["test_only"] is True
    assert payload["broker_connection"] is False
    assert payload["trading_actions"] == 0
