"""Nachrechner: eine fertige Studie mit gleichem Code und Seed noch einmal rechnen und die Zahlen vergleichen.

Gleiche Zahlen = reproduzierbar. Abweichung = Fehler gefunden (Bericht nennt die Stellen).
Kein neuer Test: nur Trainingstage (bis 2023-12-31). Validierung 2024 und Holdout 2025 werden abgelehnt.

    python -m src.research_lab.ps4.nachrechner lauf --referenz REF.json --bericht OUT.json -- \
        python -m src.research_lab.studies.s37 --phase train --btc-root ... --multi-root ... --out {OUT}
    python -m src.research_lab.ps4.nachrechner vergleich REF.json NEU.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TRAIN_LAST = date(2023, 12, 31)
# Felder, die von Natur aus je Lauf anders sind (Uhrzeit, Dauer, Pfade) und keine Studienzahl sind.
VOLATILE = frozenset({"erstellt", "zeit", "timestamp", "dauer", "dauer_s", "laufzeit", "laufzeit_s", "created_at",
                      "generated_at", "started_at", "finished_at", "host", "pfad", "path", "out"})
MAX_DIFFS = 50


class Abgelehnt(ValueError):
    """Der Lauf würde Validierungs- oder Holdout-Daten berühren."""


def pruefe_referenz(ref: dict) -> None:
    phase = ref.get("phase")
    if phase not in (None, "train"):
        raise Abgelehnt(f"Referenz hat Phase {phase!r}: nur Training wird nachgerechnet")
    bis = ref.get("bis")
    if bis is not None:
        try:
            letzter = date.fromisoformat(str(bis)[:10])
        except ValueError as exc:
            raise Abgelehnt(f"Referenz-Ende {bis!r} nicht lesbar") from exc
        if letzter > TRAIN_LAST:
            raise Abgelehnt(f"Referenz reicht bis {bis}: Nachrechnen nur bis {TRAIN_LAST.isoformat()}")


def pruefe_befehl(befehl: list[str]) -> None:
    text = " ".join(befehl).lower()
    for verboten in ("valid", "holdout", "2024", "2025", "2026"):
        if verboten in text:
            raise Abgelehnt(f"Befehl enthält {verboten!r}: nur Trainingsläufe erlaubt")


def vergleiche(a: Any, b: Any, pfad: str = "$", diffs: list[dict] | None = None) -> list[dict]:
    """Exakter Vergleich (keine Toleranz: gleicher Code und Seed müssen bitgleiche Zahlen geben)."""
    diffs = [] if diffs is None else diffs
    if len(diffs) >= MAX_DIFFS:
        return diffs
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key in VOLATILE:
                continue
            if key not in a:
                diffs.append({"pfad": f"{pfad}.{key}", "referenz": None, "neu": "<nur neu>"})
            elif key not in b:
                diffs.append({"pfad": f"{pfad}.{key}", "referenz": "<nur Referenz>", "neu": None})
            else:
                vergleiche(a[key], b[key], f"{pfad}.{key}", diffs)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append({"pfad": f"{pfad}.länge", "referenz": len(a), "neu": len(b)})
        for i, (x, y) in enumerate(zip(a, b)):
            vergleiche(x, y, f"{pfad}[{i}]", diffs)
    elif a != b or type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        diffs.append({"pfad": pfad, "referenz": a, "neu": b})
    return diffs


def _lade(path: Path) -> Any:
    return json.loads(path.read_text())


def vergleich_dateien(referenz: Path, neu: Path) -> dict:
    ref = _lade(referenz)
    if isinstance(ref, dict):
        pruefe_referenz(ref)
    diffs = vergleiche(ref, _lade(neu))
    zusatz = []
    # Begleitdatei mit den Einzel-Trades, falls vorhanden (S37-Muster: NAME.trades.json)
    ref_t, neu_t = referenz.with_suffix(".trades.json"), neu.with_suffix(".trades.json")
    if ref_t.exists() and neu_t.exists():
        zusatz = vergleiche(_lade(ref_t), _lade(neu_t), "$trades")
    alle = (diffs + zusatz)[:MAX_DIFFS]
    return {"reproduzierbar": not alle, "abweichungen": alle, "trades_verglichen": bool(zusatz) or (ref_t.exists() and neu_t.exists())}


def lauf(referenz: Path, befehl: list[str], bericht: Path | None) -> dict:
    ref = _lade(referenz)
    if isinstance(ref, dict):
        pruefe_referenz(ref)
    pruefe_befehl(befehl)
    if not any("{OUT}" in teil for teil in befehl):
        raise Abgelehnt("Befehl braucht den Platzhalter {OUT} für die Ausgabedatei")
    with tempfile.TemporaryDirectory(prefix="ps4-nachrechner-") as tmp:
        neu = Path(tmp) / "neu.json"
        cmd = [teil.replace("{OUT}", str(neu)) for teil in befehl]
        start = datetime.now(timezone.utc)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603 - Befehl kommt vom Aufrufer
        if proc.returncode != 0 or not neu.exists():
            result = {"reproduzierbar": None, "fehler": f"Lauf endete mit Code {proc.returncode}", "stderr_ende": proc.stderr[-800:]}
        else:
            result = vergleich_dateien(referenz, neu)
    result.update({"referenz": referenz.name, "befehl": " ".join(befehl)[:300], "gestartet": start.isoformat(timespec="seconds"),
                   "urteil": urteil(result)})
    if bericht is not None:
        bericht.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    return result


def urteil(result: dict) -> str:
    if result.get("reproduzierbar") is True:
        return "Nachgerechnet: gleiche Zahlen, reproduzierbar."
    if result.get("reproduzierbar") is False:
        return f"ABWEICHUNG: {len(result['abweichungen'])} Stelle(n) anders, Fehler suchen."
    return "Lauf fehlgeschlagen, nichts verglichen."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vergleich")
    v.add_argument("referenz", type=Path)
    v.add_argument("neu", type=Path)
    run = sub.add_parser("lauf")
    run.add_argument("--referenz", type=Path, required=True)
    run.add_argument("--bericht", type=Path)
    run.add_argument("befehl", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "vergleich":
            res = vergleich_dateien(args.referenz, args.neu)
            res["urteil"] = urteil(res)
        else:
            befehl = args.befehl[1:] if args.befehl[:1] == ["--"] else args.befehl
            res = lauf(args.referenz, befehl, args.bericht)
    except Abgelehnt as exc:
        print(f"ABGELEHNT: {exc}", file=sys.stderr)
        return 3
    print(res["urteil"])
    for d in res.get("abweichungen", [])[:10]:
        print(f"  {d['pfad']}: Referenz {d['referenz']!r}, neu {d['neu']!r}")
    return 0 if res.get("reproduzierbar") else 1


if __name__ == "__main__":
    raise SystemExit(main())
