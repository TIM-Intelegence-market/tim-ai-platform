"""Macro filters F3/F5 for the S7b shadow run and the weekly influence barometer (observation only).

Uzi, 2026-11-04 (private PR #460, decision A): S7b-D20-T3 runs in shadow mode with two signal filters,
evaluated once after 60 trades of unfiltered S7b and reported as an observation, not as a confirmation.
Study doc: docs/research_lab/studien/S7B_MAKRO_FILTER.md, frozen rules in
docs/research_lab/studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md section 15.

- F5: no new long while the 10-year real yield (FRED DFII10) has risen over 13 weeks. Latest published
  day (at most 10 days old) against the latest day in [latest - 98, latest - 91] days.
- F3: no new long while net liquidity WALCL - WTREGEN - RRPONTSYD (USD bn) has fallen over 13 weeks.
  Latest Wednesday with all three values (RRP at most 4 days earlier) against that Wednesday - 13 weeks.

``log`` appends one row per UTC day with the filter states as published by FRED at that moment;
``barometer`` writes a descriptive weekly table of the drivers with the historical reading from
2017-2024. Neither loads BTC data, touches the holdout 2025+, sends an order or changes a rule.

Units are read from FRED for every series: WTREGEN is published in millions today and was published
in billions in 2024, so every value is scaled to billions before it is combined.

    python -m src.research_lab.forward.macro_filters log [--folder data/research/forward/S7b-makro]
    python -m src.research_lab.forward.macro_filters barometer [--folder ...]

The FRED key comes from ``FredSecretResolver`` (TIM_FRED_SECRET_PROVIDER) and is only placed in the
request URL; nothing here prints or stores it, and stored raw answers contain no URL.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

Series = list[tuple[date, float]]
Fetcher = Callable[[str], bytes]

FOLDER = Path("data/research/forward/S7b-makro")
LOG_NAME = "f35_log.csv"
LOOKBACK_DAYS = 200
STALE_DAYS = 10  # a daily series whose latest value is older than this gives no state
WINDOW = (91, 98)  # the comparison value is the latest day between 98 and 91 days before the latest day
RRP_MAX_LAG_DAYS = 4
MAX_STATE_AGE = timedelta(hours=48)  # an older log row gives no filter state for a signal
F5_SERIES = "DFII10"
F3_SERIES = ("WALCL", "WTREGEN", "RRPONTSYD")
LOG_FIELDS = ["datum_utc", "abruf_utc", "f5_stichtag", "f5_wert", "f5_stichtag_13w", "f5_wert_13w", "f5_sperre_long",
              "f3_mittwoch", "f3_wert_mrd", "f3_mittwoch_13w", "f3_wert_13w_mrd", "f3_sperre_long", "roh_sha256"]

# Barometer drivers: label, FRED id, change unit. History: mean BTC weekly return 2017-09..2024-12 after the
# driver rose / fell over 13 weeks, and the correlation of the 13-week change with BTC over the next 4 weeks
# (barometer part 2, 2026-11-02, register "Register-Pruefungen"). None = not evaluated yet.
DRIVERS: tuple[tuple[str, str, str], ...] = (
    ("Realzins 10J", "DFII10", "bp"),
    ("Dollar-Index", "DTWEXBGS", "pct"),
    ("Rendite 10J", "DGS10", "bp"),
    ("Öl WTI", "DCOILWTICO", "pct"),
    ("Inflationserwartung 10J (Breakeven)", "T10YIE", "bp"),
    ("VIX", "VIXCLS", "diff"),
)
LIQUIDITY = "Netto-Liquidität (Mrd. USD)"
HISTORY: Mapping[str, Mapping[str, float] | None] = {
    "DFII10": {"gestiegen": -0.19, "gefallen": 1.49, "vorlauf": -0.20},
    "DTWEXBGS": {"gestiegen": 0.20, "gefallen": 1.22, "vorlauf": -0.15},
    "DGS10": {"gestiegen": 0.14, "gefallen": 1.26, "vorlauf": -0.18},
    "DCOILWTICO": {"gestiegen": 0.82, "gefallen": 0.39, "vorlauf": 0.06},
    "T10YIE": None,
    "VIXCLS": {"gestiegen": 0.67, "gefallen": 0.59, "vorlauf": 0.01},
    LIQUIDITY: {"gestiegen": 1.05, "gefallen": 0.30, "vorlauf": 0.10},
}
OIL_NOTE = ("Öl wirkt historisch nicht direkt auf BTC (Gleichlauf +0,15, Vorlauf +0,06), möglicherweise aber indirekt "
            "über die Inflationserwartung und damit über Zinsen und Realzins (Hypothese, nicht getestet).")


class MacroDataError(RuntimeError):
    """FRED answered with something the filters cannot use. Messages never contain the key or a URL."""


@dataclass(frozen=True, slots=True)
class Trend:
    day: date
    value: float
    day_before: date
    value_before: float

    @property
    def rose(self) -> bool:
        return self.value > self.value_before

    @property
    def fell(self) -> bool:
        return self.value < self.value_before


def scale_to_billions(series_id: str, units: str) -> float:
    """Factor that brings a dollar series to USD bn; rates and indices stay as they are."""
    if series_id not in F3_SERIES:
        return 1.0
    if "Millions" in units:
        return 1 / 1000
    if "Billions" in units:
        return 1.0
    raise MacroDataError(f"{series_id}: unexpected unit {units!r}")


def parse_observations(payload: bytes, factor: float = 1.0) -> Series:
    try:
        rows = json.loads(payload)["observations"]
    except (ValueError, KeyError, TypeError) as exc:
        raise MacroDataError("observations missing in FRED answer") from exc
    out = []
    for row in rows:
        value = row.get("value")
        if value in ("", ".", None):
            continue
        out.append((date.fromisoformat(row["date"]), float(value) * factor))
    return sorted(out)


def trend(series: Series, today: date) -> Trend | None:
    """13-week change of a daily series, using only values dated before ``today``."""
    known = [(d, v) for d, v in series if d < today]
    if not known or (today - known[-1][0]).days > STALE_DAYS:
        return None
    day, value = known[-1]
    dates = [d for d, _ in known]
    i = bisect_right(dates, day - timedelta(days=WINDOW[0])) - 1
    if i < 0 or dates[i] < day - timedelta(days=WINDOW[1]):
        return None
    return Trend(day, value, dates[i], known[i][1])


def net_liquidity_at(walcl: Series, tga: Series, rrp: Series, wednesday: date) -> float | None:
    walcl_by_day, tga_by_day = dict(walcl), dict(tga)
    rrp_days = [d for d, _ in rrp]
    i = bisect_right(rrp_days, wednesday) - 1
    if wednesday not in walcl_by_day or wednesday not in tga_by_day or i < 0:
        return None
    if (wednesday - rrp_days[i]).days > RRP_MAX_LAG_DAYS:
        return None
    return walcl_by_day[wednesday] - tga_by_day[wednesday] - rrp[i][1]


def net_liquidity_series(walcl: Series, tga: Series, rrp: Series) -> Series:
    out = []
    for day, _ in walcl:
        value = net_liquidity_at(walcl, tga, rrp, day)
        if value is not None:
            out.append((day, value))
    return out


def f5_state(dfii10: Series, today: date) -> Trend | None:
    return trend(dfii10, today)


def f3_state(walcl: Series, tga: Series, rrp: Series, today: date) -> Trend | None:
    """Latest Wednesday before ``today`` with all three values (up to four weeks back) against 13 weeks earlier."""
    wednesday = today - timedelta(days=(today.weekday() - 2) % 7 or 7)
    for _ in range(4):
        now = net_liquidity_at(walcl, tga, rrp, wednesday)
        if now is not None:
            before_day = wednesday - timedelta(weeks=13)
            before = net_liquidity_at(walcl, tga, rrp, before_day)
            return None if before is None else Trend(wednesday, now, before_day, before)
        wednesday -= timedelta(weeks=1)
    return None


def fetch_series(series_ids: Sequence[str], today: date, fetch: Fetcher, api_key: str) -> tuple[dict[str, Series], dict[str, bytes]]:
    """Observations of the last LOOKBACK_DAYS as published now, scaled by the unit FRED reports."""
    from src.research_lab.external.alfred import url_for

    data, raw = {}, {}
    start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    for sid in series_ids:
        try:
            units = json.loads(fetch(url_for({"path": "series", "series_id": sid}, api_key)))["seriess"][0]["units"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise MacroDataError(f"{sid}: series metadata missing") from exc
        payload = fetch(url_for({"path": "series/observations", "series_id": sid, "observation_start": start}, api_key))
        data[sid] = parse_observations(payload, scale_to_billions(sid, units))
        raw[sid] = payload
    return data, raw


def log_row(today: date, now: datetime, data: Mapping[str, Series], raw_sha256: str) -> dict[str, Any]:
    row: dict[str, Any] = {"datum_utc": today.isoformat(), "abruf_utc": now.replace(microsecond=0).isoformat(),
                           "roh_sha256": raw_sha256}
    f5 = f5_state(data[F5_SERIES], today)
    if f5 is None:
        row["f5_sperre_long"] = "unbekannt"
    else:
        row.update(f5_stichtag=f5.day.isoformat(), f5_wert=f5.value, f5_stichtag_13w=f5.day_before.isoformat(),
                   f5_wert_13w=f5.value_before, f5_sperre_long="ja" if f5.rose else "nein")
    f3 = f3_state(data["WALCL"], data["WTREGEN"], data["RRPONTSYD"], today)
    if f3 is None:
        row["f3_sperre_long"] = "unbekannt"
    else:
        row.update(f3_mittwoch=f3.day.isoformat(), f3_wert_mrd=round(f3.value, 1), f3_mittwoch_13w=f3.day_before.isoformat(),
                   f3_wert_13w_mrd=round(f3.value_before, 1), f3_sperre_long="ja" if f3.fell else "nein")
    return row


def read_log(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def append_log(path: Path, row: Mapping[str, Any]) -> bool:
    """Append ``row`` unless its UTC day is already logged. Returns whether a row was written."""
    if any(r.get("datum_utc") == row["datum_utc"] for r in read_log(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LOG_FIELDS})
    return True


def state_at(rows: Sequence[Mapping[str, str]], signal_time: datetime) -> Mapping[str, str] | None:
    """The log row a shadow signal is judged by (point in time).

    The latest row fetched strictly before the signal. ``None`` ("ohne Filterstand") when there is no such
    row or when it is older than MAX_STATE_AGE, so a failed daily fetch never lets an old state judge a signal."""
    best, best_time = None, None
    for row in rows:
        fetched = datetime.fromisoformat(row["abruf_utc"])
        if fetched < signal_time and (best_time is None or fetched >= best_time):
            best, best_time = row, fetched
    if best_time is None or signal_time - best_time > MAX_STATE_AGE:
        return None
    return best


def _change(kind: str, before: float, now: float) -> str:
    if kind == "pct":
        return f"{(now / before - 1) * 100:+.1f} %"
    if kind == "bp":
        return f"{(now - before) * 100:+.1f} bp"
    return f"{now - before:+.1f}"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:+.2f} %"


def history_from_report(path: Path) -> Mapping[str, Mapping[str, float] | None]:
    """Barometer history from an influence report (src.research_lab.influence) instead of the fixed HISTORY.

    Drivers the report does not cover keep their fixed numbers."""
    from src.research_lab.influence.catalog import LIQUIDITY_KEY
    from src.research_lab.influence.report import history_for_barometer

    found = history_for_barometer(json.loads(path.read_text()))
    merged = dict(HISTORY)
    for key, values in found.items():
        merged[LIQUIDITY if key == LIQUIDITY_KEY else key] = values
    return merged


def barometer_markdown(today: date, data: Mapping[str, Series],
                       history_table: Mapping[str, Mapping[str, float] | None] = HISTORY) -> str:
    year, week, _ = today.isocalendar()
    lines = [f"# Barometer live, Woche {year}-{week:02d} (Stand {today.isoformat()})", "",
             ("Rein beschreibend, keine Prognose, kein Handelssignal. Stand: Treiber über 13 Wochen, wie heute bei FRED "
              "veröffentlicht. Historisch: mittlere BTC-Wochenrendite 2017–2024, wenn der Treiber über 13 Wochen gestiegen "
              "bzw. gefallen war, und Vorlauf-Korrelation auf die 4 Wochen danach (Barometer Teil 2)."), "",
             "| Treiber | Stand (Datum) | vor 13 W | Veränderung | Richtung | BTC/Woche hist. so | … Gegenrichtung | Vorlauf hist. |",
             "|---|---:|---:|---:|---|---:|---:|---:|"]
    rows = [(label, sid, kind, data.get(sid, [])) for label, sid, kind in DRIVERS]
    rows.append((LIQUIDITY, LIQUIDITY, "diff", net_liquidity_series(data.get("WALCL", []), data.get("WTREGEN", []),
                                                                     data.get("RRPONTSYD", []))))
    for label, key, kind, series in rows:
        t = trend(series, today)
        history = history_table.get(key)
        if t is None:
            lines.append(f"| {label} | – | – | – | unbekannt | – | – | – |")
            continue
        direction, other = ("gestiegen", "gefallen") if t.rose else ("gefallen", "gestiegen")
        if history is None or any(history.get(k) is None for k in ("gestiegen", "gefallen", "vorlauf")):
            hist_cells = "noch nicht ausgewertet | noch nicht ausgewertet | noch nicht ausgewertet"
        else:
            hist_cells = f"{_pct(history[direction])} | {_pct(history[other])} | {history['vorlauf']:+.2f}"
        lines.append(f"| {label} | {t.value:.2f} ({t.day.isoformat()}) | {t.value_before:.2f} ({t.day_before.isoformat()}) | "
                     f"{_change(kind, t.value_before, t.value)} | {direction} | {hist_cells} |")
    lines += ["", OIL_NOTE, "", "Keine BTC-Daten ab 2025 geladen; der Holdout bleibt unberührt."]
    return "\n".join(lines) + "\n"


def _download(series_ids: Sequence[str], today: date, folder: Path) -> tuple[dict[str, Series], str]:
    from src.research_lab.external.fred_secret import FredSecretResolver
    from src.research_lab.external.live import http_fetcher

    key = FredSecretResolver().api_key().reveal()
    data, raw = fetch_series(series_ids, today, http_fetcher(), key)
    raw_dir = folder / "roh" / today.isoformat()
    raw_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    for sid in series_ids:
        (raw_dir / f"{sid}.json").write_bytes(raw[sid])
        digest.update(raw[sid])
    return data, digest.hexdigest()


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description="F3/F5 forward log and weekly barometer (observation only)")
    parser.add_argument("command", choices=("log", "barometer"))
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--history", type=Path, help="influence report JSON; replaces the fixed history numbers")
    args = parser.parse_args(argv)
    moment = now or datetime.now(timezone.utc)
    today = moment.date()
    if args.command == "log":
        path = args.folder / LOG_NAME
        if any(r.get("datum_utc") == today.isoformat() for r in read_log(path)):
            print(f"{today}: schon geloggt")
            return 0
        data, sha = _download((F5_SERIES, *F3_SERIES), today, args.folder)
        row = log_row(today, moment, data, sha)
        append_log(path, row)
        print(json.dumps(row, ensure_ascii=False))
        return 0
    data, _ = _download(tuple(sid for _, sid, _ in DRIVERS) + F3_SERIES, today, args.folder / "barometer")
    year, week, _ = today.isocalendar()
    out = args.folder / "barometer" / f"barometer_{year}-{week:02d}.md"
    table = HISTORY if args.history is None else history_from_report(args.history)
    out.write_text(barometer_markdown(today, data, table))
    print(f"geschrieben: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
