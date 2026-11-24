"""Abgleich der Logbuch-Zahlen mit den Ergebnisdateien der Studien (Konsistenzprüfung, keine Neuberechnung).

Für jede Logbuchzeile wird geprüft, ob die dort genannten Zahlen (Dezimalzahlen mit Komma, ganze Zahlen ab 100) als Wert
in der zugehörigen Ergebnisdatei stehen (auch als Prozent-/Vorzeichen-Umrechnung, auf die im Text genannte Stellenzahl gerundet).
Das belegt nur, dass der Text zur Datei passt (Prüftiefe C+). Es belegt nicht, dass die Datei richtig gerechnet wurde.
Nicht gefundene Zahlen werden einzeln aufgeführt und müssen von Hand angesehen werden.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

# Studie -> Ergebnisdateien (relativ zu "repo" = docs/research_lab/reports oder "ps5" = Kopie der PS5-Ergebnisse)
DATEIEN: dict[str, list[tuple[str, str]]] = {
    "S1": [("repo", "s1_cpi_volatility.json")],
    "S4": [("repo", "s4_count_2026-10-25T1620Z.json")],
    "S5": [("repo", "s5_count_2026-10-25T1836Z.json")],
    "S6": [("repo", "s6_train_2026-10-25T2338Z.json")],
    "S7": [("repo", "s7_train_2026-10-26T1049Z.json")],
    "S7b": [("repo", "s7b_train_2026-10-26T1305Z.json")],
    "R4": [("repo", "r4_2026-09-29T2219Z.json")],
    "S10": [("repo", "s10_count_2026-10-28T0105Z.json")],
    "S13": [("repo", "s13_run_2026-11-01T1844Z.json")],
    "S14": [("repo", "s14_run_2026-11-01T2308Z.json")],
    "S15": [("repo", "s15_run_2026-11-02T1815Z.json")],
    "S20": [("repo", "s20_evaluate_2026-11-10T2345Z.json")],
    "S21": [("repo", "s21_evaluate_2026-11-11T1438Z.json")],
    "S25": [("repo", "s25_run_2026-11-12T0926Z.json")],
    "S22": [("ps5", "s22/s22_evaluate_2026-11-11T1841Z.json")],
    "S24": [("ps5", "s24/s24_evaluate_2026-11-11T2200Z.json")],
    "S26": [("ps5", "s26/s26_evaluate_2026-11-12T0923Z.json")],
    "S27": [("ps5", "s27/s27_evaluate_2026-11-12T0934Z.json")],
    "S28": [("ps5", "s28/s28_evaluate_2026-11-12T1535Z.json")],
    "S30": [("ps5", "s30/s30_raster_train_2026-11-12.json"), ("ps5", "s30/s30_ausbruch_train_2026-11-12.json"),
            ("ps5", "s30/s30_ausbruch_v02_train_2026-11-12.json"), ("ps5", "s30/s30_train_2026-11-12.json")],
    "S31": [("ps5", "s31/count_training.json"), ("ps5", "of2/run_aa853e1/training.json"), ("ps5", "of2/run_aa853e1/random_training.json")],
    "S31b": [("ps5", "s31/countb_tf60.json"), ("ps5", "s31/countb_tf240.json")],
    "S32": [("ps5", "s32/validierung/s32_validierung_2026-11-14.json"), ("ps5", "s32/s32_train_2026-11-12.json")],
    "S33-Carry": [("ps5", "s33/carry_train_2026-11-12.json")],
    "S34": [("ps5", "s34/s34_train_2026-11-14.json")],
    "S35a": [("ps5", "s35a/s35a_train_2026-11-14.json")],
    "S36": [("ps5", "s36/train.json"), ("ps5", "s36/count3.json")],
    "S37": [("ps5", "s37/s37_train_2026-11-15.json")],
    "S38": [("ps5", "s38/s38_train_2026-11-15.json")],
}

_ZAHL = re.compile(r"(?<![\w.,])([+\-−]?)(\d{1,3}(?:[. ]\d{3})+|\d+)(?:,(\d+))?")


def zahlen_aus_text(text: str) -> list[dict]:
    """Zahlen aus deutschem Text: Dezimalzahlen mit Komma und ganze Zahlen ab 100 (Tausendertrennung mit Punkt oder Leerzeichen).
    Kleine ganze Zahlen (Zähler, Jahre bis 2100 ausgenommen) sind zu mehrdeutig und werden übergangen."""
    out = []
    for m in _ZAHL.finditer(text):
        vorz, ganz, nach = m.group(1), m.group(2), m.group(3)
        roh = m.group(0)
        g = int(re.sub(r"[. ]", "", ganz))
        if nach is None:
            if g < 100 or 1990 <= g <= 2100:
                continue
            wert, stellen = float(g), 0
        else:
            wert, stellen = float(f"{g}.{nach}"), len(nach)
        if vorz in ("-", "−"):
            wert = -wert
        out.append({"text": roh.strip(), "wert": wert, "stellen": stellen})
    return out


def werte_aus_json(obj) -> np.ndarray:
    """Alle Zahlenblätter einer JSON-Struktur."""
    vals: list[float] = []
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, bool):
            continue
        elif isinstance(x, (int, float)):
            if x == x and abs(x) != float("inf"):
                vals.append(float(x))
    return np.sort(np.array(vals))


def gefunden(z: dict, werte: np.ndarray) -> bool:
    """Steht die Zahl (auf ihre Stellenzahl gerundet) unter den Werten? Mit Prozent- und Vorzeichen-Umrechnung."""
    tol = 0.5 * 10 ** (-z["stellen"]) + 1e-9
    for skal in (1.0, 0.01, 100.0):
        for vz in (1.0, -1.0):
            ziel = z["wert"] * skal * vz
            t = tol * (skal if skal < 1 else 1.0) * (1.0 if skal <= 1 else 100.0)
            i = int(np.searchsorted(werte, ziel - t))
            if i < len(werte) and werte[i] <= ziel + t:
                return True
    return False


def abgleich(logbuch: Path, repo_berichte: Path, ps5: Path) -> dict:
    d = json.loads(logbuch.read_text(encoding="utf-8"))
    eintraege = {e["id"]: e for e in d["entries"]}
    out = {}
    for sid, dateien in DATEIEN.items():
        e = eintraege.get(sid)
        if e is None:
            out[sid] = {"status": "nicht im Logbuch"}
            continue
        gelesen, fehlt, alle = [], [], []
        for wurzel, rel in dateien:
            p = (repo_berichte if wurzel == "repo" else ps5) / rel
            if not p.exists():
                fehlt.append(rel)
                continue
            gelesen.append({"datei": f"{wurzel}:{rel}", "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
            alle.append(werte_aus_json(json.loads(p.read_text(encoding="utf-8"))))
        if not alle:
            out[sid] = {"status": "keine Ergebnisdatei erreichbar", "dateien_fehlen": fehlt}
            continue
        werte = np.sort(np.concatenate(alle))
        zahlen = zahlen_aus_text(e["result"])
        nicht = [z["text"] for z in zahlen if not gefunden(z, werte)]
        out[sid] = {"dateien": gelesen, "dateien_fehlen": fehlt, "zahlen_im_logbuch": len(zahlen), "davon_in_datei": len(zahlen) - len(nicht),
                    "nicht_gefunden": nicht}
    return out


def main(argv: list[str]) -> int:
    logbuch, repo_berichte, ps5, ziel = (Path(a) for a in argv[1:5])
    res = abgleich(logbuch, repo_berichte, ps5)
    ziel.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for sid, r in res.items():
        if "zahlen_im_logbuch" in r:
            print(f"{sid:10s} {r['davon_in_datei']:3d}/{r['zahlen_im_logbuch']:3d}  nicht gefunden: {r['nicht_gefunden']}")
        else:
            print(f"{sid:10s} {r['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
