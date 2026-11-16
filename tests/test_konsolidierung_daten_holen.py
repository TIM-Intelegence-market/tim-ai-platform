"""Tests von ``daten_holen`` (Beschaffung nach Manifest mit SHA-256-Prüfung). Die Gegenstelle ist ein lokaler Ordner (``file://``-Adressen);
ein Abruf von data.binance.vision gehört nicht in die Testsuite."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.research_lab.konsolidierung import daten_holen as dh


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def quelle(tmp_path: Path) -> tuple[Path, dict]:
    """Gegenstelle mit vier Dateien (davon eine im Holdout, eine aus der 1m-Serie) und das passende Manifest."""
    q = tmp_path / "quelle"
    inhalt = {
        "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip": b"zip-btc-2019-11",
        "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-12.zip": b"zip-btc-2019-12",
        "futures_um/klines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip": b"zip-1m",
        "futures_um/klines/BTCUSDT/4h/BTCUSDT-4h-2025-01.zip": b"zip-holdout",
    }
    manifest = {}
    for rel, b in inhalt.items():
        p = q / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
        (q / (rel + ".CHECKSUM")).write_text(f"{_sha(b)}  {Path(rel).name}\n", encoding="ascii")
        manifest[rel] = {"url": p.as_uri(), "sha256": _sha(b)}
    return q, manifest


def test_auswahl_laesst_serien_aus_und_verweigert_den_holdout(quelle) -> None:
    _, m = quelle
    ok, verweigert = dh.auswahl(m)
    assert ok == ["spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip", "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-12.zip"]
    assert verweigert == ["futures_um/klines/BTCUSDT/4h/BTCUSDT-4h-2025-01.zip"]
    ok_alle, _ = dh.auswahl(m, ohne=())
    assert "futures_um/klines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip" in ok_alle           # nichts ausgelassen: die 1m-Serie ist dabei
    assert dh.auswahl(m, nur=("2019-12",))[0] == ["spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-12.zip"]
    assert dh.monat_von("x/BTCUSDT-4h-2024-12.zip") == "2024-12" and dh.monat_von("x/manifest.json") is None


def test_holdout_monat_wird_auch_bei_leerem_filter_nie_geladen(quelle, tmp_path: Path) -> None:
    _, m = quelle
    ziel = tmp_path / "ziel"
    erg = dh.hole(m, ziel, ohne=(), nur=())
    assert erg["wegen_holdout_verweigert"] == ["futures_um/klines/BTCUSDT/4h/BTCUSDT-4h-2025-01.zip"]
    assert not (ziel / "futures_um/klines/BTCUSDT/4h/BTCUSDT-4h-2025-01.zip").exists()
    assert erg["geladen"] == 3 and erg["abweichend"] == [] and erg["fehler"] == []


def test_laden_prueft_sha256_und_ueberspringt_vorhandene_dateien(quelle, tmp_path: Path) -> None:
    _, m = quelle
    ziel = tmp_path / "ziel"
    erg = dh.hole(m, ziel, checksum_datei=True)
    assert (erg["ausgewaehlt"], erg["geladen"], erg["vorhanden"]) == (2, 2, 0) and erg["abweichend"] == [] and erg["fehler"] == []
    assert (ziel / "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip").read_bytes() == b"zip-btc-2019-11"
    assert not list(ziel.rglob("*.part"))
    zweiter = dh.hole(m, ziel)
    assert (zweiter["geladen"], zweiter["vorhanden"]) == (0, 2)           # idempotent


def test_abweichende_pruefsumme_wird_verworfen_und_gemeldet(quelle, tmp_path: Path) -> None:
    _, m = quelle
    m["spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-12.zip"]["sha256"] = _sha(b"etwas anderes")
    ziel = tmp_path / "ziel"
    erg = dh.hole(m, ziel)
    assert erg["geladen"] == 1
    assert [a["pfad"] for a in erg["abweichend"]] == ["spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-12.zip"]
    assert not (ziel / "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-12.zip").exists()      # nicht behalten, was nicht passt
    assert dh.main(["daten_holen", str(_schreibe(tmp_path, m)), str(ziel)]) == 1       # Rückgabewert 1 bei Abweichung


def test_vorhandene_abweichende_datei_wird_nicht_ueberschrieben(quelle, tmp_path: Path) -> None:
    _, m = quelle
    ziel = tmp_path / "ziel"
    rel = "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip"
    (ziel / rel).parent.mkdir(parents=True)
    (ziel / rel).write_bytes(b"lokal veraendert")
    erg = dh.hole(m, ziel)
    assert (ziel / rel).read_bytes() == b"lokal veraendert"
    assert [a["pfad"] for a in erg["abweichend"]] == [rel] and erg["geladen"] == 1


def test_checksum_datei_der_gegenstelle_muss_passen(quelle, tmp_path: Path) -> None:
    q, m = quelle
    rel = "spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip"
    (q / (rel + ".CHECKSUM")).write_text(f"{_sha(b'falsch')}  BTCUSDT-4h-2019-11.zip\n", encoding="ascii")
    ziel = tmp_path / "ziel"
    erg = dh.hole(m, ziel, checksum_datei=True)
    assert [a["pfad"] for a in erg["abweichend"]] == [rel] and not (ziel / rel).exists()
    assert erg["geladen"] == 1


def test_nicht_erreichbare_adresse_ist_ein_fehler_kein_absturz(quelle, tmp_path: Path, monkeypatch) -> None:
    _, m = quelle
    monkeypatch.setattr(dh.time, "sleep", lambda s: None)
    m["spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip"]["url"] = (tmp_path / "gibt-es-nicht.zip").as_uri()
    erg = dh.hole(m, tmp_path / "ziel")
    assert [f["pfad"] for f in erg["fehler"]] == ["spot/klines/BTCUSDT/4h/BTCUSDT-4h-2019-11.zip"] and erg["geladen"] == 1


def test_manifest_ohne_url_oder_sha256_wird_abgelehnt(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"a/b-2019-01.zip": {"url": "file:///x"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        dh.lies_manifest(p)


def test_echte_manifeste_im_repo_haben_das_erwartete_format() -> None:
    eingaben = Path(__file__).resolve().parents[1] / "docs" / "research_lab" / "konsolidierung" / "eingaben"
    for name, anzahl, ohne_holdout in (("manifest_binance_archiv_2020_2024.json", 1093, True), ("manifest_t15.json", 58, True)):
        m = dh.lies_manifest(eingaben / name)
        assert len(m) == anzahl, name
        assert all(v["url"].startswith("https://data.binance.vision/data/") and len(v["sha256"]) == 64 for v in m.values()), name
        assert dh.auswahl(m)[1] == []                      # kein Eintrag ab 2025-01
    ok, _ = dh.auswahl(dh.lies_manifest(eingaben / "manifest_binance_archiv_2020_2024.json"))
    assert len(ok) == 861                                  # die 861 benötigten Dateien (ohne 1m und 15m), wie im Datenaudit


def _schreibe(tmp_path: Path, m: dict) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def test_eingaben_im_repo_stimmen_mit_den_festgehaltenen_pruefsummen() -> None:
    """Die Kopien der Laborlisten und der Bitunix-Rohdateien im Repo sind unverändert (SHA-256 gegen die Listen unter ``eingaben/``)."""
    eingaben = Path(__file__).resolve().parents[1] / "docs" / "research_lab" / "konsolidierung" / "eingaben"
    geprueft = 0
    for liste, ordner in (("SHA256_laborlisten.txt", "laborlisten"), ("SHA256_bitunix.txt", "bitunix")):
        for zeile in (eingaben / liste).read_text(encoding="utf-8").splitlines():
            summe, name = zeile.split(maxsplit=1)
            datei = eingaben / ordner / name.strip()
            if not datei.exists():
                assert name.strip() == "lab_klines_funding.tar", name      # das Archiv des Labors (18 MB) liegt nicht im Repo, die Daten kommen aus daten_holen
                continue
            assert dh.sha256_datei(datei) == summe, name
            geprueft += 1
    assert geprueft == 4 + 8
