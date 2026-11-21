"""Datenprüfer: unsere Binance-Archivdateien gegen die offiziellen Prüfsummen von data.binance.vision abgleichen.

Prüft je Eintrag: Datei vorhanden, Prüfsumme der Datei = Manifest, Manifest = aktuelle offizielle .CHECKSUM.
Für Tages-Aggregate (aggTrades) zusätzlich: fehlende Tage zwischen erstem und letztem Tag.
Nur Trainings- und Validierungszeit bis 2024-12-31; Holdout (ab 2025) wird übersprungen und nicht gelesen.
Der Prüfer schreibt nur seinen Bericht, nie in die Datenordner.

    python -m src.research_lab.ps4.datenpruefer --klines-root data/research_lab --aggtrades-root data/research_lab/aggtrades \
        --bericht datenstatus.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from src.research_lab.data.store import http_fetch
from src.v2_readiness.backfill import parse_official_checksum

Fetcher = Callable[[str], bytes]
PERIOD = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?\.zip$")
LAST_ALLOWED = date(2024, 12, 31)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _official(fetch: Fetcher, url: str, filename: str) -> tuple[str | None, str | None]:
    try:
        return parse_official_checksum(fetch(url + ".CHECKSUM").decode("utf-8"), expected_filename=filename), None
    except Exception as exc:  # noqa: BLE001 - jeder Fehler wird als Befund gemeldet, nicht verschluckt
        return None, f"{type(exc).__name__}: {exc}"


def _in_scope(name: str) -> bool:
    m = PERIOD.search(name)
    if not m:
        return False
    first = date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    return first <= LAST_ALLOWED


def pruefe_klines(root: Path, fetch: Fetcher) -> dict:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    befunde, ok, uebersprungen = [], 0, 0
    for local_path, entry in sorted(manifest.items()):
        name = local_path.rsplit("/", 1)[-1]
        if not _in_scope(name):
            uebersprungen += 1
            continue
        datei = root / local_path
        if not datei.exists():
            befunde.append({"datei": local_path, "art": "fehlt"})
            continue
        if _sha(datei) != entry["sha256"]:
            befunde.append({"datei": local_path, "art": "datei_geaendert"})
            continue
        offiziell, fehler = _official(fetch, entry["url"], name)
        if offiziell is None:
            befunde.append({"datei": local_path, "art": "offizielle_summe_nicht_lesbar", "detail": fehler})
        elif offiziell != entry["sha256"]:
            befunde.append({"datei": local_path, "art": "weicht_von_binance_ab"})
        else:
            ok += 1
    return {"geprueft_ok": ok, "uebersprungen_holdout": uebersprungen, "befunde": befunde, "eintraege": len(manifest)}


def pruefe_aggtrades(root: Path, fetch: Fetcher, symbol: str = "BTCUSDT") -> dict:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    befunde, ok, uebersprungen = [], 0, 0
    tage = sorted(date.fromisoformat(k) for k in manifest)
    for tag in tage:
        if tag > LAST_ALLOWED:
            uebersprungen += 1
            continue
        entry = manifest[tag.isoformat()]
        agg = root / "agg" / f"{symbol}-{tag.isoformat()}.csv"
        if not agg.exists():
            befunde.append({"tag": tag.isoformat(), "art": "fehlt"})
            continue
        if _sha(agg) != entry["agg_sha256"]:
            befunde.append({"tag": tag.isoformat(), "art": "datei_geaendert"})
            continue
        name = entry["url"].rsplit("/", 1)[-1]
        offiziell, fehler = _official(fetch, entry["url"], name)
        if offiziell is None:
            befunde.append({"tag": tag.isoformat(), "art": "offizielle_summe_nicht_lesbar", "detail": fehler})
        elif offiziell != entry["archive_sha256"]:
            befunde.append({"tag": tag.isoformat(), "art": "weicht_von_binance_ab"})
        else:
            ok += 1
    luecken = []
    gepruefte = [t for t in tage if t <= LAST_ALLOWED]
    if gepruefte:
        vorhanden = set(gepruefte)
        tag = gepruefte[0]
        while tag <= gepruefte[-1]:
            if tag not in vorhanden:
                luecken.append(tag.isoformat())
            tag += timedelta(days=1)
    return {"geprueft_ok": ok, "uebersprungen_holdout": uebersprungen, "befunde": befunde, "luecken_tage": luecken,
            "eintraege": len(manifest)}


def datenstatus(klines_root: Path | None, aggtrades_root: Path | None, fetch: Fetcher = http_fetch) -> dict:
    status: dict = {"erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "quelle": "data.binance.vision"}
    if klines_root is not None:
        status["kerzen_und_funding"] = pruefe_klines(klines_root, fetch)
    if aggtrades_root is not None:
        status["aggtrades_tage"] = pruefe_aggtrades(aggtrades_root, fetch)
    teile = [v for v in status.values() if isinstance(v, dict)]
    probleme = sum(len(t["befunde"]) + len(t.get("luecken_tage", [])) for t in teile)
    status["probleme"] = probleme
    status["urteil"] = "Daten stimmen mit Binance überein, keine Lücken." if probleme == 0 else f"{probleme} Auffälligkeit(en), siehe Bericht."
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klines-root", type=Path)
    ap.add_argument("--aggtrades-root", type=Path)
    ap.add_argument("--bericht", type=Path)
    args = ap.parse_args(argv)
    if not (args.klines_root or args.aggtrades_root):
        ap.error("mindestens --klines-root oder --aggtrades-root angeben")
    status = datenstatus(args.klines_root, args.aggtrades_root)
    if args.bericht:
        args.bericht.write_text(json.dumps(status, indent=1, ensure_ascii=False) + "\n")
    print(status["urteil"])
    return 0 if status["probleme"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
