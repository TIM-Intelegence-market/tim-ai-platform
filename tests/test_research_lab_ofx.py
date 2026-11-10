"""OFX: holdout release of the S8 store (Uzi 10.11.2026) and the search loop."""
from __future__ import annotations

from datetime import date

import pytest

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.orderflow_ml.store import OFX_RELEASE, MinuteBarStore, guard


def test_holdout_stays_locked_without_release():
    with pytest.raises(HoldoutLocked):
        guard(date(2025, 1, 1))
    with pytest.raises(HoldoutLocked):
        guard(date(2025, 6, 1), "irgendwas")
    guard(date(2024, 12, 31))


def test_release_opens_holdout_up_to_yesterday_only():
    guard(date(2025, 1, 1), OFX_RELEASE, today=date(2026, 11, 10))
    guard(date(2026, 11, 9), OFX_RELEASE, today=date(2026, 11, 10))
    with pytest.raises(HoldoutLocked):
        guard(date(2026, 11, 10), OFX_RELEASE, today=date(2026, 11, 10))


def test_store_rejects_unknown_release_and_plain_store_stays_locked(tmp_path):
    with pytest.raises(ValueError):
        MinuteBarStore(tmp_path, release="OFX")
    with pytest.raises(HoldoutLocked):
        MinuteBarStore(tmp_path).load(date(2025, 3, 1))
    with pytest.raises(FileNotFoundError):
        MinuteBarStore(tmp_path, release=OFX_RELEASE).load(date(2025, 3, 1))
