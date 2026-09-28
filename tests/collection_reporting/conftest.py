import pytest


@pytest.fixture(autouse=True)
def synthetic_receipt_clock(monkeypatch):
    # Campaign fixtures carry explicit historical synthetic exchange timestamps.
    monkeypatch.setattr('src.collection_reporting.campaign_writer.utc',lambda:'2026-09-06T12:00:00+00:00')
