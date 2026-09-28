from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from config.secrets import DatabaseEndpoint, DatabaseSecretResolver


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    database_host: str = field(default_factory=lambda: os.getenv("TIM_DATABASE_HOST", "127.0.0.1"))
    database_port: int = field(default_factory=lambda: int(os.getenv("TIM_DATABASE_PORT", "5432")))
    database_name: str = field(default_factory=lambda: os.getenv("TIM_DATABASE_NAME", "tim"))
    database_user: str = field(default_factory=lambda: os.getenv("TIM_DATABASE_USER", "tim"))
    binance_ws_url: str = field(default_factory=lambda: os.getenv("TIM_BINANCE_WS_URL", "wss://stream.binance.com:9443/ws"))
    symbol: str = field(default_factory=lambda: os.getenv("TIM_SYMBOL", "BTCUSDT").upper())
    timeframes: tuple[str, ...] = field(default_factory=lambda: _csv("TIM_TIMEFRAMES", "1m,5m,15m,1h"))
    ollama_url: str = field(default_factory=lambda: os.getenv("TIM_OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("TIM_OLLAMA_MODEL", "qwen2.5:7b"))
    enable_ollama: bool = field(default_factory=lambda: os.getenv("TIM_ENABLE_OLLAMA", "false").lower() == "true")
    dashboard_host: str = field(default_factory=lambda: os.getenv("TIM_DASHBOARD_HOST", "127.0.0.1"))
    dashboard_port: int = field(default_factory=lambda: int(os.getenv("TIM_DASHBOARD_PORT", "8765")))
    allowed_news_hosts: tuple[str, ...] = field(default_factory=lambda: _csv("TIM_ALLOWED_NEWS_HOSTS", ""))
    allowed_knowledge_roots: tuple[Path, ...] = field(default_factory=lambda: tuple(Path(item).expanduser() for item in _csv("TIM_ALLOWED_KNOWLEDGE_ROOTS", "")))
    source_snapshot_root: Path = field(default_factory=lambda: Path(os.getenv("TIM_SOURCE_SNAPSHOT_ROOT", "data/source_snapshots")).expanduser())
    log_level: str = field(default_factory=lambda: os.getenv("TIM_LOG_LEVEL", "INFO").upper())

    @property
    def database_endpoint(self) -> DatabaseEndpoint:
        return DatabaseEndpoint(
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
            user=self.database_user,
        )

    @property
    def database_url(self) -> str:
        # Resolution is intentionally lazy: importing read-only TIM modules does
        # not need a secret, while every database-using process fails closed.
        return DatabaseSecretResolver().database_url(self.database_endpoint)


settings = Settings()
