"""TIM's own market data history: is every collector still writing? (read only, 04.11.2026)

TIM collects data that cannot be fetched again later, or only for a short time:

* Perp orderflow (Binance USD-M aggTrades as footprint rows), ``data/perp_flow/`` plus its archive,
* open interest per hour (Binance keeps 30 days), ``data/perp_flow/oi-BTCUSDT-1h.jsonl``,
* the same two for Monero (XMRUSDT perp, since 04.11.2026) in ``data/perp_flow/XMRUSDT/``,
* options gamma walls and flip (Deribit snapshot every 5 min), ``data/options/gamma_levels.jsonl``,
* real liquidations (Binance and Bybit streams, study S12), ``research-lab/liquidations/raw/``,
* the daily copy of these files (``tim_db_backup.py files``), ``backup_files.json``,
* the background gap filler of TIM's own aggTrades (issue #82), ``gap_filler.json``.

Every month of this history makes it more valuable, and a collector that stops quietly loses
days that never come back. ``status`` reads only what the collectors already write and says per
source how old the newest record is, so a stop shows up within minutes. Nothing here fetches,
writes or changes a collector.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dashboard.cockpit.tiles import Tile, make_tile, unavailable, worst

SCHEMA = "tim_own_data/1"
# Freshness limits in seconds: the collector's own rhythm plus slack.
PERP_MAX_AGE = 10 * 60  # saves every 60 s while it runs
OI_MAX_AGE = 3 * 3600  # one point per hour, Binance publishes it a few minutes late
GAMMA_MAX_AGE = 20 * 60  # snapshot every 5 min
LIQ_MAX_AGE = 5 * 60  # an "alive" line every 60 s even when nothing is liquidated
FILES_BACKUP_MAX_AGE = 26 * 3600  # daily at 03:15 plus slack
GAP_FILLER_MAX_AGE = 15 * 60  # a round at least every few minutes while the runtime runs
GAP_STALL_SECONDS = 6 * 3600  # open gaps without progress this long: yellow
LIQ_VENUES = ("binance", "bybit")
TAIL_BYTES = 8192


def _iso(seconds: float | None) -> str | None:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat() if seconds else None


def _last_json_line(path: Path) -> dict[str, Any] | None:
    """The last complete JSON line of a file, read from its end only."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _days(directory: Path) -> list[str]:
    names = [p.name[5:15] for p in directory.glob("perp-*.json.gz")]
    names += [p.name[5:15] for p in (directory / "archive").glob("perp-*.json.gz")]
    return sorted(set(names))


def _mb(paths: list[Path]) -> float:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return round(total / 1e6, 1)


def _perp_names(symbol: str) -> tuple[str, str, str]:
    """Tile id suffix, label suffix and folder below data/ (BTC keeps its original names)."""
    if symbol == "BTCUSDT":
        return "", "", "perp_flow"
    return f"_{symbol.removesuffix('USDT').lower()}", f" {symbol.removesuffix('USDT')}", f"perp_flow/{symbol}"


def perp_tile(data_root: Path, now: datetime, symbol: str = "BTCUSDT") -> Tile:
    suffix, label, folder = _perp_names(symbol)
    tile_id, name = f"own_perp{suffix}", f"Perp-Orderflow{label}"
    directory = data_root / folder
    source = f"data/{folder}/state.json"
    try:
        state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return unavailable(tile_id, name, "Sammler hat noch nichts gespeichert (state.json fehlt)", source)
    except (OSError, ValueError) as exc:
        return make_tile(tile_id, name, "—", state="fail", reason=f"state.json unlesbar: {type(exc).__name__}", source=source, now=now)
    days = _days(directory)
    problems = []
    checks = [c for c in state.get("checks") or [] if isinstance(c, dict) and c.get("ok") is not None]
    if checks and not checks[-1]["ok"]:
        problems.append(f"Stundenprüfung {checks[-1].get('hour', '')[:13]} weicht von Binance ab")
    gaps = [g for g in state.get("gaps") or [] if isinstance(g, dict)]
    recent = [g for g in gaps if _age_of(g.get("at"), now) is not None and _age_of(g.get("at"), now) <= 86400]
    if recent:
        problems.append(f"{len(recent)} Lücke(n) in 24 h, zuletzt {recent[-1].get('reason', '')}")
    value = f"{len(days)} Tage seit {days[0]}" if days else "noch kein Tag"
    return make_tile(tile_id, name, value, "WARN" if problems else "PASS", reason=" · ".join(problems),
                     source=source, as_of=state.get("updated_at"), max_age_seconds=PERP_MAX_AGE, now=now,
                     extra={"days": len(days), "first_day": days[0] if days else None, "gaps_total": len(gaps),
                            "mb": _mb(list(directory.glob("perp-*.json.gz")) + list((directory / "archive").glob("perp-*.json.gz")))})


def _age_of(value: Any, now: datetime) -> int | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int((now - moment).total_seconds())


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b""))
    except OSError:
        return 0


def oi_tile(data_root: Path, now: datetime, symbol: str = "BTCUSDT") -> Tile:
    suffix, label, folder = _perp_names(symbol)
    tile_id, name = f"own_oi{suffix}", f"Open Interest 1h{label}"
    path = data_root / folder / f"oi-{symbol}-1h.jsonl"
    source = f"data/{folder}/oi-{symbol}-1h.jsonl"
    last = _last_json_line(path) if path.exists() else None
    if last is None:
        return unavailable(tile_id, name, "Noch keine Stunde gespeichert", source)
    hours = _count_lines(path)
    return make_tile(tile_id, name, f"{hours} Stunden", "PASS", source=source,
                     as_of=_iso(float(last.get("t") or 0)), max_age_seconds=OI_MAX_AGE, now=now, extra={"hours": hours})


def bybit_tile(data_root: Path, now: datetime) -> Tile:
    """Bybit perp trades over the websocket (src/dashboard/bybit_flow.py, Issue #162): second venue of the bubbles."""
    tile_id, name = "own_bybit", "Bybit-Orderflow (Bubbles)"
    directory = data_root / "bybit_flow"
    source = "data/bybit_flow/state.json"
    try:
        state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return unavailable(tile_id, name, "Sammler hat noch nichts gespeichert (state.json fehlt)", source)
    except (OSError, ValueError) as exc:
        return make_tile(tile_id, name, "—", state="fail", reason=f"state.json unlesbar: {type(exc).__name__}", source=source, now=now)
    days = sorted(p.name[6:16] for p in directory.glob("bybit-*.json.gz"))
    segments = state.get("segments") or []
    recent = [s for s in segments if isinstance(s, list) and len(s) == 2 and now.timestamp() * 1000 - s[1] <= 86_400_000]
    reason = f"{len(recent) - 1} Neuverbindung(en) in 24 h" if len(recent) > 1 else ""
    value = f"{len(days)} Tage seit {days[0]}" if days else "noch kein Tag"
    return make_tile(tile_id, name, value, "WARN" if len(recent) > 3 else "PASS", reason=reason, source=source,
                     as_of=state.get("updated_at"), max_age_seconds=PERP_MAX_AGE, now=now,
                     extra={"days": len(days), "sessions": state.get("sessions"), "trades": state.get("trades")})


def gamma_tile(data_root: Path, now: datetime) -> Tile:
    path = data_root / "options" / "gamma_levels.jsonl"
    source = "data/options/gamma_levels.jsonl"
    last = _last_json_line(path) if path.exists() else None
    if last is None:
        return unavailable("own_gamma", "Gamma-Walls", "Noch kein Schnappschuss gespeichert", source)
    count = _count_lines(path)
    return make_tile("own_gamma", "Gamma-Walls", f"{count} Schnappschüsse", "PASS", source=source,
                     as_of=last.get("as_of"), max_age_seconds=GAMMA_MAX_AGE, now=now, extra={"snapshots": count})


def liquidation_tile(liq_root: Path, venue: str, now: datetime) -> Tile:
    directory = liq_root / "raw" / venue
    label = f"Liquidationen {venue.capitalize()}"
    source = f"research-lab/liquidations/raw/{venue}/"
    files = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
    if not files:
        return unavailable(f"own_liq_{venue}", label, "Keine Rohdaten gefunden", source)
    last = _last_json_line(files[-1])
    received = last.get("receive_ns") if last else None
    as_of = _iso(received / 1e9) if isinstance(received, (int, float)) and not isinstance(received, bool) else None
    kind = str(last.get("kind")) if last else ""
    problem = f"letzter Eintrag: {kind}" if kind in {"disconnect", "connect_failed"} else ""
    return make_tile(f"own_liq_{venue}", label, f"{len(files)} Tage seit {files[0].stem}", "WARN" if problem else "PASS",
                     reason=problem, source=source, as_of=as_of, max_age_seconds=LIQ_MAX_AGE, now=now,
                     extra={"days": len(files), "mb": _mb(files)})


def files_backup_tile(operational: Path, now: datetime) -> Tile:
    path = operational / "backup_files.json"
    source = "data/operational/backup_files.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return unavailable("own_backup", "Kopie eigene Daten", "Noch keine tägliche Kopie gelaufen", source)
    except (OSError, ValueError) as exc:
        return make_tile("own_backup", "Kopie eigene Daten", "—", state="fail", reason=f"Bericht unlesbar: {type(exc).__name__}", source=source, now=now)
    status = str(report.get("status") or "UNKNOWN").upper()
    size = report.get("bytes")
    value = f"{size / 1e6:.1f} MB".replace(".", ",") if isinstance(size, (int, float)) and not isinstance(size, bool) else "—"
    reason = "" if status == "PASS" else str(report.get("reason") or f"Kopie meldet {status}")
    if status == "PASS" and report.get("mirror") is False:
        reason = "Nur auf dem Mac-Laufwerk, keine zweite Kopie außerhalb"
    return make_tile("own_backup", "Kopie eigene Daten", value, status, reason=reason, source=source,
                     as_of=report.get("completed_at"), max_age_seconds=FILES_BACKUP_MAX_AGE, now=now)


def _thousands(value: Any) -> str:
    return f"{int(value):,}".replace(",", ".") if isinstance(value, int) and not isinstance(value, bool) else "—"


def gap_filler_tile(operational: Path, now: datetime) -> Tile:
    """Background gap filler of the aggTrades (issue #82): open gaps and whether they shrink."""
    tile_id, name, source = "own_gaps", "Datenlücken (Nachholer)", "data/operational/gap_filler.json"
    try:
        report = json.loads((operational / "gap_filler.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return unavailable(tile_id, name, "Nachholer hat noch keine Runde gemeldet", source)
    except (OSError, ValueError) as exc:
        return make_tile(tile_id, name, "—", state="fail", reason=f"Bericht unlesbar: {type(exc).__name__}", source=source, now=now)
    open_gaps = report.get("open_gaps") if isinstance(report.get("open_gaps"), int) else 0
    missing = report.get("missing_trades")
    state = str(report.get("state") or "UNKNOWN").upper()
    if state == "ERROR":
        return make_tile(tile_id, name, f"{open_gaps} offen", state="fail", reason=str(report.get("last_error") or "Fehler"),
                         source=source, as_of=report.get("checked_at_utc"), max_age_seconds=GAP_FILLER_MAX_AGE, now=now)
    if not open_gaps:
        return make_tile(tile_id, name, "keine Lücke offen", "PASS", source=source, as_of=report.get("checked_at_utc"),
                         max_age_seconds=GAP_FILLER_MAX_AGE, now=now,
                         detail=f"{_thousands(report.get('resolved_total'))} geschlossen seit Start")
    progress = _age_of(report.get("last_progress_at_utc"), now)
    stalled = progress is None or progress > GAP_STALL_SECONDS
    reason = ("Seit über 6 h kein Fortschritt" + (f": {report.get('last_error')}" if report.get("last_error") else "")) if stalled else ""
    return make_tile(tile_id, name, f"{open_gaps} offen, {_thousands(missing)} Trades", "WARN" if stalled else "PASS",
                     reason=reason, source=source, as_of=report.get("checked_at_utc"), max_age_seconds=GAP_FILLER_MAX_AGE,
                     now=now, detail="wird im Hintergrund nachgeholt")


def status(data_root: Path, liq_root: Path, now: datetime | None = None) -> list[Tile]:
    """One tile per own data source, newest record against its freshness limit."""
    now = now or datetime.now(timezone.utc)
    tiles = [perp_tile(data_root, now), oi_tile(data_root, now),
             perp_tile(data_root, now, "XMRUSDT"), oi_tile(data_root, now, "XMRUSDT"), bybit_tile(data_root, now), gamma_tile(data_root, now)]
    tiles += [liquidation_tile(liq_root, venue, now) for venue in LIQ_VENUES]
    tiles.append(files_backup_tile(data_root / "operational", now))
    tiles.append(gap_filler_tile(data_root / "operational", now))
    return tiles


def summary_tile(tiles: list[Tile], now: datetime | None = None) -> Tile:
    """The one tile on the Lage page: worst source decides, the reason names the sources."""
    collectors = [t for t in tiles if t.id not in {"own_backup", "own_gaps"}]
    fresh = sum(t.state == "ok" for t in collectors)
    bad = [t for t in tiles if t.state in {"fail", "warn"}]
    state = worst([t.state for t in tiles if t.state != "unknown"]) if any(t.state != "unknown" for t in tiles) else "unknown"
    reason = " · ".join(f"{t.label}: {t.reason}" for t in bad)[:400]
    if state == "unknown":
        reason = "Keine Sammlerdaten gefunden"
    return make_tile("own_data", "Eigene Daten", f"{fresh}/{len(collectors)} Sammler frisch", state=state,
                     reason=reason, source="own_data.status", href="/neu/betrieb", now=now)


def default_liq_root() -> Path:
    from src.research_lab.liquidations.store import data_root

    return data_root()
