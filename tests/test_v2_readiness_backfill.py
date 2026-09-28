from datetime import date
import hashlib

import pytest

from src.v2_readiness.backfill import (
    BinanceArchiveRef,
    parse_official_checksum,
    verify_archive,
)


def test_archive_reference_is_fixed_to_official_spot_aggtrades() -> None:
    ref = BinanceArchiveRef(date(2026, 7, 23))
    assert ref.filename == "BTCUSDT-aggTrades-2026-07-23.zip"
    assert ref.url == "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-07-23.zip"
    with pytest.raises(ValueError, match="BTCUSDT"):
        BinanceArchiveRef(date(2026, 7, 23), "ETHUSDT")


def test_checksum_parser_binds_hash_to_exact_filename() -> None:
    digest = "a" * 64
    assert parse_official_checksum(
        f"{digest}  BTCUSDT-aggTrades-2026-07-23.zip\n",
        expected_filename="BTCUSDT-aggTrades-2026-07-23.zip",
    ) == digest
    with pytest.raises(ValueError, match="filename"):
        parse_official_checksum(
            f"{digest}  ETHUSDT-aggTrades-2026-07-23.zip",
            expected_filename="BTCUSDT-aggTrades-2026-07-23.zip",
        )


def test_archive_hash_verification_fails_closed() -> None:
    payload = b"official immutable fixture"
    digest = hashlib.sha256(payload).hexdigest()
    assert verify_archive(payload, digest)
    assert not verify_archive(payload + b"changed", digest)
    with pytest.raises(ValueError, match="lowercase"):
        verify_archive(payload, digest.upper())
