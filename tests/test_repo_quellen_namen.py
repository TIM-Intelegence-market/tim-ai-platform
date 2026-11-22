"""Privacy guard: no name of the signal group, its people or its channels may come back into the repository.

The names themselves must not stand here either, so the guard only knows their SHA-256 digests
(lower case, words joined without separators). Real names live in a local file outside the
repository, see ``src/knowledge/signalgruppe_channels.py``.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "4c91e4dfa45664b969fc99e8e270941373070a5249f56d922876e1b9d5ada1f6",
    "ae15cd3265e97a36caaf240a319b33b4ee190d13fc0a87f775761fd001c37765",
    "e3d05cf7731b9d87fba37b33579821ff3f028c4ecb97427e570927012309b334",
    "4da2c7a3d5502f01098d2b0b1be1d99fcbedb1a7d14675fb0f49118ab2ac98f4",
    "93655726a2b64c1f74b1149bd5558e450a84adcf8564f1c563b6dcd2c628e6d5",
    "feee40935d92e2541651886580a3a6068f07637b7e5927f1657390972332aa80",
    "2c01a6718a66e46a8fb94c11592a71537e19c5d3512831e86ee8ee56b4184538",
    "406016819fb71dc81aa8e4489302cd805821f192461ba5231a9c10ba33635264",
    "b53f9cfd612781d2800b3d2074fcd315b746de20467eb7cad395e63f45b183c4",
    "36e9abd186784419a7fdd94e300f7798a76a6d7310cbc889ccc08c9e1ef739cc",
    "50993d4d71dc3c4b41db16aec403847ac9df8bed6f7f88a9d3a56a9b12fad6dc",
    "8b76c95129f1f36929c1ffa56724c81c1a8af7bbda1e6cf87fbcc4e63e6cbe65",
}
# The code-graph snapshot is pinned by hash as a security baseline (docs/integrations/secure_mcp_baseline.md) and must not be
# edited by hand; it still holds the old names until the graph is regenerated together with a new baseline.
PINNED = ("graphify-out/",)
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hits(text: str) -> set[str]:
    words = [word.lower() for word in _WORD.findall(text)]
    candidates = set(words) | {a + b for a, b in zip(words, words[1:])}
    return {candidate for candidate in candidates if _digest(candidate) in FORBIDDEN}


def test_guard_recognises_a_forbidden_name_in_any_spelling() -> None:
    probe = "zz" + "probe"
    FORBIDDEN.add(_digest(probe))
    try:
        assert _hits("x Zz-Probe y") and _hits("ZZPROBE") and _hits("zzProbe") and not _hits("zz and probe")
    finally:
        FORBIDDEN.discard(_digest(probe))


def test_no_source_names_in_tracked_files() -> None:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    found: dict[str, int] = {}
    for name in filter(None, files):
        if name.startswith(PINNED):
            continue
        path = ROOT / name
        try:
            text = name + "\n" + path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or missing in a sparse checkout
        if _hits(text):
            found[name] = len(_hits(text))
    assert not found, f"Namen der Signalgruppe in {len(found)} Dateien: {sorted(found)[:10]}"
