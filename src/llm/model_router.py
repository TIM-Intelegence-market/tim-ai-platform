"""Modell-Router: wählt je Aufgabe das billigste passende Modell, stuft nur bei Bedarf hoch.

Reine Funktion ohne Netzwerk und ohne Schlüssel. Regeln stehen in
``config/model_router/routes.json``. Der Router empfiehlt nur; aufrufen muss der Aufrufer.
Vorrang der Regeln: Bild > privat/Geheimnis (nie Cloud) > Mehrstufig/Studie > Aufgabenart
> Masse (viele Aufrufe) > Standard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROUTES_PATH = Path(__file__).resolve().parents[2] / "config" / "model_router" / "routes.json"
_LOCAL = ("lokal_klein", "lokal_gross")
MASSE_AB = 20  # ab so vielen Aufrufen am Stück: lokal statt Cloud


@dataclass(frozen=True)
class Route:
    stufe: str
    modell: str
    ort: str
    grund: str
    hochstufen_auf: str | None = None


def load_routes(path: Path = ROUTES_PATH) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for art, stufe in cfg["aufgabenarten"].items():
        if stufe not in cfg["stufen"]:
            raise ValueError(f"Aufgabenart {art!r}: unbekannte Stufe {stufe!r}")
    if cfg["standard"] not in cfg["stufen"]:
        raise ValueError("unbekannte Standardstufe")
    for a, b in cfg["hochstufen"].items():
        if a not in cfg["stufen"] or b not in cfg["stufen"]:
            raise ValueError(f"Hochstufung {a!r}->{b!r}: unbekannte Stufe")
    return cfg


def route(aufgabe: str = "", *, hat_bild: bool = False, privat: bool = False, schritte: int = 1,
          aufrufe: int = 1, lokal_verfuegbar: bool = True, config: dict[str, Any] | None = None) -> Route:
    """Empfiehlt eine Stufe. ``privat`` (Keys, Strategien, Rohdaten) bleibt immer lokal."""
    cfg = config or load_routes()
    stufen = cfg["stufen"]

    def make(stufe: str, grund: str) -> Route:
        s = stufen[stufe]
        return Route(stufe, s["modell"], s["ort"], grund, cfg["hochstufen"].get(stufe))

    if privat:
        # Privates verlässt das Gerät nie, auch nicht, wenn lokal ausfällt.
        if not lokal_verfuegbar:
            raise RuntimeError("privat verlangt lokal, aber kein lokales Modell verfügbar")
        return make("lokal_gross", "privat: nur lokal")
    if hat_bild:
        return make("vision", "Bild: Vision-fähiges Modell")
    art = cfg["aufgabenarten"].get(aufgabe)
    if art == "reasoning" or schritte >= 4:
        return make("reasoning", "mehrstufige/schwere Analyse: Reasoning")
    if art is None and aufrufe >= MASSE_AB and lokal_verfuegbar:
        return make("lokal_klein", f"Masse (≥{MASSE_AB} Aufrufe): lokal, kostenlos")
    stufe = art or cfg["standard"]
    if stufe in _LOCAL and not lokal_verfuegbar:
        return make("mittel", "lokal nicht verfügbar: Rückfall auf Cloud (nicht privat)")
    return make(stufe, f"Aufgabenart {aufgabe!r}" if art else "Standard")


def escalate(stufe: str, *, config: dict[str, Any] | None = None) -> str | None:
    """Nächsthöhere Stufe oder None am Ende der Leiter."""
    return (config or load_routes())["hochstufen"].get(stufe)
