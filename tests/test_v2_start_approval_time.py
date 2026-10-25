"""An approval record needs a real UTC time at or before the start action."""
from datetime import UTC, datetime

import pytest

from scripts import v2_qualification_start as start


NOW = datetime(2026, 10, 20, 13, 30, 20, tzinfo=UTC)


def arguments(stamp, tmp_path):
    return ["--start-gates", str(tmp_path / "missing-report.json"),
            "--approved-by", "test-owner", "--decision-ref", "test-only",
            "--approved-at", stamp, "--output-dir", str(tmp_path / "qualification")]


@pytest.mark.parametrize("stamp", [
    "Z", "not-a-dateZ", "2026-02-30T12:00:00Z", "2026-10-20T25:00:00Z",
    "2026-10-20Z", "2026-10-20T12:00:00", "2026-10-20T12:00:00+02:00",
])
def test_invalid_approval_time_fails_during_argument_validation(stamp, tmp_path):
    with pytest.raises(SystemExit) as error:
        start.parse_args(arguments(stamp, tmp_path))
    assert error.value.code == 2
    assert not (tmp_path / "qualification").exists()


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def test_future_approval_rejected_before_git_report_or_output(tmp_path, monkeypatch):
    monkeypatch.setattr(start, "datetime", FrozenDateTime)

    def forbidden(*args):
        pytest.fail("future approval must be rejected before checkout inspection")

    monkeypatch.setattr(start, "git", forbidden)
    with pytest.raises(SystemExit, match="approval.*future"):
        start.main(arguments("2026-10-20T13:30:20.000001Z", tmp_path))
    assert not (tmp_path / "qualification").exists()


@pytest.mark.parametrize("stamp", ["2026-10-20T13:30:20Z", "2026-10-20T13:30:19.123456Z"])
def test_valid_approval_reaches_existing_checkout_checks_unchanged(stamp, tmp_path, monkeypatch):
    monkeypatch.setattr(start, "datetime", FrozenDateTime)

    class CheckoutCheckReached(Exception):
        pass

    def inspected(*args):
        raise CheckoutCheckReached

    monkeypatch.setattr(start, "git", inspected)
    assert start.parse_args(arguments(stamp, tmp_path)).approved_at == stamp
    with pytest.raises(CheckoutCheckReached):
        start.main(arguments(stamp, tmp_path))
    assert not (tmp_path / "qualification").exists()
