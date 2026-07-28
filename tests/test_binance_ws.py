import json

from src.data_ingestion.binance_ws import BinanceTradeStream


def test_parse_public_aggregate_trade() -> None:
    trade = BinanceTradeStream.parse_message(json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": 42, "p": "65000.1", "q": "0.02", "T": 1767225600000, "m": False}))
    assert trade.symbol == "BTCUSDT"
    assert trade.price == 65000.1
    assert trade.quantity == 0.02
    assert trade.trade_id == 42
