from datetime import datetime, timedelta, timezone

from src.models.market_data import Observation, ObservationKind
from src.news.intelligence import NewsIntelligence, NewsItem


def test_news_links_only_historical_tag_overlap() -> None:
    at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    observation = Observation(ObservationKind.REJECTION, "BTCUSDT", "1m", at, "context", 60, {"liquidity": True})
    engine = NewsIntelligence()
    engine.ingest(NewsItem("source", "https://example.test/old", at - timedelta(hours=1), "BTC liquidity", "summary", ("btcusdt", "liquidity")))
    engine.ingest(NewsItem("source", "https://example.test/future", at + timedelta(minutes=1), "Future", "summary", ("btcusdt",)))
    links = engine.link(observation)
    assert len(links) == 1
    assert links[0].shared_tags == ("btcusdt", "liquidity")


def test_news_deduplicates() -> None:
    item = NewsItem("source", "https://example.test/a", datetime.now(timezone.utc), "Title", "Summary", ("btc",))
    engine = NewsIntelligence()
    assert engine.ingest(item)
    assert not engine.ingest(item)
