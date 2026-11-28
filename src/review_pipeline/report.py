"""Validierung des Prüfberichts `tim-pruefbericht/1` und einfacher Secret-Scan."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

SCHEMA = "tim-pruefbericht/1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
URTEILE = {"PASS", "FAIL", "INCONCLUSIVE"}
PFLICHT = ("schema", "pr", "head_sha", "base_sha", "umgebung", "befehle", "ergebnis_tests", "urteil", "gruende")
ZAEHLER = ("passed", "failed", "skipped", "errors")

SECRET_PATTERNS = {
    "github-token": re.compile(r"ghp_[A-Za-z0-9]{10,}"),
    "github-pat": re.compile(r"github_pat_[A-Za-z0-9_]{10,}"),
    "api-key": re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    "private-key": re.compile(r"-----BEGIN"),
    "ip-192.168": re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    "ip-10": re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "ip-cgnat": re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    "tailnet": re.compile(r"[A-Za-z0-9.-]+\.ts\.net\b"),
}


def scan_for_secrets(text: str) -> list[str]:
    """Namen der Muster, die in text treffen."""
    return [name for name, rx in SECRET_PATTERNS.items() if rx.search(text)]


def _is_count(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def validate_report(d: Any) -> list[str]:
    """Liste der Fehler; leer = gültig."""
    if not isinstance(d, dict):
        return ["Bericht ist kein Objekt"]
    err: list[str] = []
    for k in PFLICHT:
        if k not in d:
            err.append(f"Pflichtfeld fehlt: {k}")
    if d.get("schema", SCHEMA) != SCHEMA:
        err.append("schema falsch")
    for k in ("head_sha", "base_sha"):
        if k in d and not (isinstance(d[k], str) and SHA_RE.match(d[k])):
            err.append(f"{k} ist keine 40-stellige Hex-SHA")
    if "urteil" in d and d["urteil"] not in URTEILE:
        err.append("urteil ungültig")
    if "pr" in d and not (isinstance(d["pr"], int) and not isinstance(d["pr"], bool) and d["pr"] > 0):
        err.append("pr ungültig")
    if "gruende" in d and not isinstance(d["gruende"], list):
        err.append("gruende muss Liste sein")
    if "befehle" in d and not (isinstance(d["befehle"], list) and all(isinstance(x, str) for x in d["befehle"])):
        err.append("befehle muss Liste von Strings sein")
    et = d.get("ergebnis_tests")
    failed_or_err = False
    if "ergebnis_tests" in d:
        if not isinstance(et, dict) or not et:
            err.append("ergebnis_tests muss nichtleeres Objekt sein")
        else:
            steps = et.values() if not any(k in et for k in ZAEHLER) else [et]
            for step in steps:
                if not isinstance(step, dict):
                    err.append("ergebnis_tests-Schritt kein Objekt")
                    continue
                for z in ZAEHLER:
                    if not _is_count(step.get(z)):
                        err.append(f"Zähler {z} fehlt oder keine Ganzzahl >= 0")
                if _is_count(step.get("failed")) and step["failed"] > 0:
                    failed_or_err = True
                if _is_count(step.get("errors")) and step["errors"] > 0:
                    failed_or_err = True
    if d.get("urteil") == "PASS" and failed_or_err:
        err.append("urteil PASS bei failed/errors > 0 ungültig")
    try:
        treffer = scan_for_secrets(json.dumps(d, ensure_ascii=False))
    except (TypeError, ValueError):
        treffer = []
        err.append("Bericht nicht serialisierbar")
    if treffer:
        err.append("Secret-/Adress-Treffer: " + ", ".join(treffer))
    return err


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Aufruf: python -m src.review_pipeline.report DATEI.json", file=sys.stderr)
        return 1
    try:
        with open(argv[1], encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"UNGÜLTIG: {exc}")
        return 1
    errors = validate_report(data)
    for e in errors:
        print(f"UNGÜLTIG: {e}")
    if not errors:
        print("GÜLTIG")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
