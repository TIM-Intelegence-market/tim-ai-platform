from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from src.models.market_data import Observation


@dataclass(frozen=True, slots=True)
class NewsItem:
    source_name: str
    source_url: str
    published_at: datetime
    title: str
    summary: str
    tags: tuple[str, ...]
    provenance: str = "AUTHORIZED_NEWS_INPUT"

    @property
    def news_id(self) -> str:
        raw = f"{self.source_name}|{self.source_url}|{self.published_at.isoformat()}|{self.title}"
        return "news_" + hashlib.sha256(raw.encode()).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class NewsLink:
    news_id: str
    observation_id: str
    relevance: float
    shared_tags: tuple[str, ...]
    reason: str


class NewsIntelligence:
    """Links authorized news records to observations; it does not fetch or advise."""

    def __init__(self) -> None:
        self.items: dict[str, NewsItem] = {}

    def ingest(self, item: NewsItem) -> bool:
        if not item.source_url.startswith(("https://", "http://")) or not item.title.strip():
            raise ValueError("News requires a source URL and title")
        if item.published_at.tzinfo is None:
            raise ValueError("News timestamp must be timezone-aware")
        if item.news_id in self.items:
            return False
        self.items[item.news_id] = item
        return True

    def link(self, observation: Observation, window: timedelta = timedelta(hours=24)) -> list[NewsLink]:
        observation_tags = {observation.symbol.lower(), observation.kind.value.lower(), *map(str.lower, observation.evidence.keys())}
        links = []
        for item in self.items.values():
            age = observation.observed_at - item.published_at
            if age < timedelta(0) or age > window:
                continue
            shared = observation_tags & {tag.lower() for tag in item.tags}
            if shared:
                score = round(len(shared) / max(1, len(set(item.tags))), 6)
                links.append(NewsLink(item.news_id, str(observation.observation_id), score, tuple(sorted(shared)), "Deterministic tag overlap within the configured historical window."))
        return sorted(links, key=lambda item: (-item.relevance, item.news_id))
