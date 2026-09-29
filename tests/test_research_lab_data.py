from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.parse import check_completeness, parse_funding, parse_klines
from src.research_lab.data.store import ArchiveStore, HoldoutLocked, HoldoutPermission, months

HOUR = 3_600_000
JAN_2024 = 1_704_067_200_000


def kline_row(open_time: int, close: float = 100.0, taker_buy: float = 4.0) -> str:
    return f"{open_time},100,101,99,{close},10,{open_time + HOUR - 1},1000,5,{taker_buy},400,0"


def zipped(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, text)
    return buffer.getvalue()


class FakeArchive:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []

    def add(self, ref: ArchiveRef, text: str, *, corrupt_checksum: bool = False) -> None:
        payload = zipped(ref.filename.replace(".zip", ".csv"), text)
        digest = hashlib.sha256(payload).hexdigest()
        if corrupt_checksum:
            digest = "0" * 64
        self.files[ref.url] = payload
        self.files[ref.checksum_url] = f"{digest}  {ref.filename}\n".encode()

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.files[url]


def usdm_hour(year: int = 2024, month: int = 1) -> ArchiveRef:
    return ArchiveRef(Market.USDM, Dataset.KLINES, year, month, "1h")


def test_urls_follow_binance_archive_layout() -> None:
    assert usdm_hour().url == "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2024-01.zip"
    spot = ArchiveRef(Market.SPOT, Dataset.KLINES, 2017, 9, "1d")
    assert spot.url == "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2017-09.zip"
    funding = ArchiveRef(Market.USDM, Dataset.FUNDING, 2024, 1)
    assert funding.url.endswith("/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.zip")
    assert funding.checksum_url == funding.url + ".CHECKSUM"


def test_invalid_refs_are_rejected() -> None:
    with pytest.raises(ValueError):
        ArchiveRef(Market.USDM, Dataset.KLINES, 2024, 1, "7m")
    with pytest.raises(ValueError):
        ArchiveRef(Market.SPOT, Dataset.FUNDING, 2024, 1)
    with pytest.raises(ValueError):
        ArchiveRef(Market.USDM, Dataset.KLINES, 2024, 1, "1h", symbol="ETHUSDT")


def test_fetch_verifies_checksum_and_loads(tmp_path) -> None:
    ref = usdm_hour()
    fake = FakeArchive()
    fake.add(ref, "\n".join(kline_row(JAN_2024 + i * HOUR) for i in range(744)))
    store = ArchiveStore(tmp_path, fake)
    store.fetch(ref)
    klines = store.load_klines([ref])
    assert len(klines) == 744
    report = check_completeness(klines, HOUR, ref.start_ms, ref.end_ms)
    assert report.complete and report.expected == 744
    store.fetch(ref)  # second fetch reuses the verified file
    assert len(fake.calls) == 2


def test_checksum_mismatch_is_refused(tmp_path) -> None:
    ref = usdm_hour()
    fake = FakeArchive()
    fake.add(ref, kline_row(JAN_2024), corrupt_checksum=True)
    with pytest.raises(ValueError, match="checksum mismatch"):
        ArchiveStore(tmp_path, fake).fetch(ref)
    assert not (tmp_path / ref.local_path).exists()


def test_file_changed_on_disk_is_refused(tmp_path) -> None:
    ref = usdm_hour()
    fake = FakeArchive()
    fake.add(ref, kline_row(JAN_2024))
    store = ArchiveStore(tmp_path, fake)
    path = store.fetch(ref)
    path.write_bytes(zipped("x.csv", kline_row(JAN_2024, close=100.5)))
    with pytest.raises(ValueError, match="changed on disk"):
        store.load_klines([ref])


def test_holdout_months_are_locked(tmp_path) -> None:
    ref = usdm_hour(2025, 1)
    fake = FakeArchive()
    fake.add(ref, kline_row(1_735_689_600_000))
    store = ArchiveStore(tmp_path, fake)
    with pytest.raises(HoldoutLocked):
        store.fetch(ref)
    assert fake.calls == []
    permission = HoldoutPermission("test")
    store.fetch(ref, permission)
    with pytest.raises(HoldoutLocked):
        store.load_klines([ref])
    assert len(store.load_klines([ref], permission)) == 1


def test_gaps_duplicates_and_order_are_counted() -> None:
    times = [JAN_2024, JAN_2024 + HOUR, JAN_2024 + 4 * HOUR, JAN_2024 + 4 * HOUR, JAN_2024 + 3 * HOUR]
    klines = parse_klines("\n".join(kline_row(t) for t in times))
    report = check_completeness(klines, HOUR, JAN_2024, JAN_2024 + 6 * HOUR)
    assert report.duplicates == 1
    assert report.out_of_order == 1
    assert report.missing == 2  # hour 2 and hour 5
    assert [(g.after_open_time, g.missing) for g in report.gaps] == [(JAN_2024 + HOUR, 1), (JAN_2024 + 4 * HOUR, 1)]
    assert not report.complete


def test_header_rows_and_microsecond_timestamps() -> None:
    header = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
    micro = f"{JAN_2024 * 1000},100,101,99,100,10,{(JAN_2024 + HOUR - 1) * 1000},1000,5,7,700,0"
    (kline,) = parse_klines(header + "\n" + micro)
    assert kline.open_time == JAN_2024
    assert kline.delta == 4.0  # 2 * 7 - 10


def test_invalid_candles_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_klines(f"{JAN_2024},100,99,98,100,10,{JAN_2024 + 1},1,1,1,1,0")  # high below open
    with pytest.raises(ValueError):
        parse_klines(kline_row(JAN_2024, taker_buy=11.0))  # taker volume above volume


def test_funding_parsing() -> None:
    rates = parse_funding("calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.00010000\n1704096000000,8,-0.00002\n")
    assert [(r.time, r.rate) for r in rates] == [(1704067200000, 0.0001), (1704096000000, -0.00002)]


def test_dataset_hash_is_stable_and_order_independent(tmp_path) -> None:
    fake = FakeArchive()
    refs = [usdm_hour(2024, 1), usdm_hour(2024, 2)]
    for ref in refs:
        fake.add(ref, kline_row(ref.start_ms))
    store = ArchiveStore(tmp_path, fake)
    for ref in refs:
        store.fetch(ref)
    assert store.dataset_hash(refs) == store.dataset_hash(list(reversed(refs)))
    assert len(store.dataset_hash(refs)) == 64


def test_months_range() -> None:
    assert months((2023, 11), (2024, 2)) == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]
