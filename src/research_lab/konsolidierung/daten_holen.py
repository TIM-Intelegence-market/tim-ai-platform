"""Beschafft die Binance-Archivdateien der Konsolidierung nach einem Manifest und prüft jede Datei gegen die SHA-256 des Manifests.

Aufruf (aus dem Repo-Wurzelordner)::

    python3 -m src.research_lab.konsolidierung.daten_holen <manifest.json> <zielordner> [--ohne 1m,15m] [--nur teilpfad,...] [--checksum-datei]

Das Manifest bildet relative Pfade auf ``{"url": ..., "sha256": ...}`` ab (Format von ``eingaben/manifest_binance_archiv_2020_2024.json`` und
``eingaben/manifest_t15.json``). Der Zielordner bekommt dieselben relativen Pfade und ist danach ein gültiger Archivordner für ``daten.laden``.

Regeln:
- Vorhandene Dateien mit passender Prüfsumme werden übersprungen. Eine vorhandene Datei mit abweichender Prüfsumme wird nicht überschrieben, sondern gemeldet.
- Eine geladene Datei wird nur behalten, wenn ihre SHA-256 mit dem Manifest übereinstimmt (bei ``--checksum-datei`` zusätzlich mit der ``.CHECKSUM``-Datei
  des Archivs). Sonst wird sie verworfen und der Lauf endet mit Rückgabewert 1.
- Monate ab dem Holdout (2025-01) werden nie geladen (Schranke wie in ``daten``).
- ``--ohne`` lässt Serien aus, deren Pfad eines der Wörter als Pfadteil enthält (Standard: ``1m,15m``, für die 4h-Konsolidierung nicht benötigt);
  ``--nur`` lädt nur Pfade, die einen der Teilpfade enthalten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HOLDOUT_MONAT = "2025-01"
STANDARD_OHNE = ("1m", "15m")
_MONAT = re.compile(r"(\d{4}-\d{2})\.zip$")


def lies_manifest(pfad: Path) -> dict[str, dict]:
    m = json.loads(Path(pfad).read_text(encoding="utf-8"))
    for k, v in m.items():
        if not isinstance(v, dict) or "url" not in v or "sha256" not in v:
            raise ValueError(f"Manifest-Eintrag ohne url/sha256: {k}")
    return m


def monat_von(pfad: str) -> str | None:
    t = _MONAT.search(pfad)
    return t.group(1) if t else None


def auswahl(manifest: dict[str, dict], ohne: tuple[str, ...] = STANDARD_OHNE, nur: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Gibt (zu bearbeitende Pfade, wegen Holdout verweigerte Pfade) zurück."""
    ok, verweigert = [], []
    for pfad in sorted(manifest):
        teile = pfad.split("/")
        if any(w in teile for w in ohne):
            continue
        if nur and not any(n in pfad for n in nur):
            continue
        monat = monat_von(pfad)
        if monat is not None and monat >= HOLDOUT_MONAT:
            verweigert.append(pfad)
            continue
        ok.append(pfad)
    return ok, verweigert


def sha256_datei(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _lade(url: str, ziel: Path, versuche: int = 3, timeout: float = 60.0) -> str:
    """Lädt ``url`` nach ``ziel`` (über eine .part-Datei) und gibt die SHA-256 zurück. Netzfehler werden mit Wartezeit wiederholt."""
    teil = ziel.with_name(ziel.name + ".part")
    letzter: Exception | None = None
    for v in range(versuche):
        try:
            h = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=timeout) as antwort, open(teil, "wb") as f:
                for block in iter(lambda: antwort.read(1 << 20), b""):
                    h.update(block)
                    f.write(block)
            teil.replace(ziel)
            return h.hexdigest()
        except Exception as e:  # Netz, Zeitüberschreitung, 404 und Ähnliches
            letzter = e
            teil.unlink(missing_ok=True)
            time.sleep(2 * (v + 1))
    raise RuntimeError(f"Laden fehlgeschlagen: {url}: {letzter}")


def _checksum_der_gegenstelle(url: str, timeout: float = 60.0) -> str:
    with urllib.request.urlopen(url + ".CHECKSUM", timeout=timeout) as antwort:
        return antwort.read().decode("ascii", "replace").split()[0].strip().lower()


def hole(manifest: dict[str, dict], ziel: Path, ohne: tuple[str, ...] = STANDARD_OHNE, nur: tuple[str, ...] = (), checksum_datei: bool = False) -> dict:
    """Beschafft alle ausgewählten Dateien. Rückgabe: Zähler und Listen der Probleme."""
    pfade, verweigert = auswahl(manifest, ohne, nur)
    out = {"ausgewaehlt": len(pfade), "geladen": 0, "vorhanden": 0, "abweichend": [], "fehler": [], "wegen_holdout_verweigert": verweigert}
    for rel in pfade:
        erwartet = manifest[rel]["sha256"].lower()
        datei = Path(ziel) / rel
        if datei.exists():
            if sha256_datei(datei) == erwartet:
                out["vorhanden"] += 1
            else:
                out["abweichend"].append({"pfad": rel, "grund": "vorhandene Datei weicht vom Manifest ab (nicht überschrieben)"})
            continue
        datei.parent.mkdir(parents=True, exist_ok=True)
        try:
            ist = _lade(manifest[rel]["url"], datei)
        except RuntimeError as e:
            out["fehler"].append({"pfad": rel, "grund": str(e)})
            continue
        if ist != erwartet:
            datei.unlink(missing_ok=True)
            out["abweichend"].append({"pfad": rel, "grund": f"SHA-256 weicht vom Manifest ab (geladen {ist[:12]}…, erwartet {erwartet[:12]}…); verworfen"})
            continue
        if checksum_datei:
            try:
                gegenstelle = _checksum_der_gegenstelle(manifest[rel]["url"])
            except Exception as e:
                datei.unlink(missing_ok=True)
                out["fehler"].append({"pfad": rel, "grund": f"CHECKSUM-Datei nicht lesbar: {e}"})
                continue
            if gegenstelle != ist:
                datei.unlink(missing_ok=True)
                out["abweichend"].append({"pfad": rel, "grund": f"SHA-256 weicht von der CHECKSUM-Datei ab ({gegenstelle[:12]}…); verworfen"})
                continue
        out["geladen"] += 1
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="daten_holen", description="Binance-Archivdateien nach Manifest beschaffen und gegen SHA-256 prüfen")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("zielordner", type=Path)
    ap.add_argument("--ohne", default=",".join(STANDARD_OHNE), help="Serien (Pfadteile) auslassen, Komma-getrennt; leer = nichts auslassen")
    ap.add_argument("--nur", default="", help="nur Pfade laden, die einen dieser Teilpfade enthalten (Komma-getrennt)")
    ap.add_argument("--checksum-datei", action="store_true", help="zusätzlich gegen die .CHECKSUM-Datei des Archivs prüfen")
    a = ap.parse_args(argv[1:])
    teilen = lambda s: tuple(w for w in s.split(",") if w)
    erg = hole(lies_manifest(a.manifest), a.zielordner, teilen(a.ohne), teilen(a.nur), a.checksum_datei)
    print(json.dumps({k: (v[:20] if isinstance(v, list) else v) for k, v in erg.items()}, ensure_ascii=False, indent=1))
    return 0 if not (erg["abweichend"] or erg["fehler"]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
