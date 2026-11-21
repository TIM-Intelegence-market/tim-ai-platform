import hashlib
import json
from datetime import date

import pytest

from src.research_lab.ps4 import datenpruefer, nachrechner


def test_vergleich_gleich_und_abweichung(tmp_path):
    ref = {"studie": "S37", "phase": "train", "bis": "2023-12-31", "zeit": "a", "configs": {"x": {"n": 5, "net": 0.1}}}
    neu = json.loads(json.dumps(ref)) | {"zeit": "b"}
    (tmp_path / "r.json").write_text(json.dumps(ref))
    (tmp_path / "n.json").write_text(json.dumps(neu))
    assert nachrechner.vergleich_dateien(tmp_path / "r.json", tmp_path / "n.json")["reproduzierbar"] is True
    neu["configs"]["x"]["net"] = 0.1000001
    (tmp_path / "n.json").write_text(json.dumps(neu))
    res = nachrechner.vergleich_dateien(tmp_path / "r.json", tmp_path / "n.json")
    assert res["reproduzierbar"] is False and res["abweichungen"][0]["pfad"] == "$.configs.x.net"


@pytest.mark.parametrize("ref", [{"phase": "valid"}, {"phase": "train", "bis": "2024-12-31"}])
def test_referenz_ausserhalb_training_abgelehnt(ref):
    with pytest.raises(nachrechner.Abgelehnt):
        nachrechner.pruefe_referenz(ref)


def test_befehl_mit_holdout_abgelehnt():
    with pytest.raises(nachrechner.Abgelehnt):
        nachrechner.pruefe_befehl(["python", "s.py", "--phase", "valid", "--out", "{OUT}"])


def test_lauf_reproduziert(tmp_path):
    ref = {"phase": "train", "bis": "2023-12-31", "wert": 1.5}
    (tmp_path / "r.json").write_text(json.dumps(ref))
    script = tmp_path / "s.py"
    script.write_text("import json,sys\nopen(sys.argv[1],'w').write(json.dumps({'phase':'train','bis':'2023-12-31','wert':1.5}))\n")
    import sys
    res = nachrechner.lauf(tmp_path / "r.json", [sys.executable, str(script), "{OUT}"], tmp_path / "b.json")
    assert res["reproduzierbar"] is True and (tmp_path / "b.json").exists()


def _checksum_fetcher(table):
    def fetch(url):
        return table[url]
    return fetch


def test_datenpruefer_klines(tmp_path):
    payload = b"zip-inhalt"
    digest = hashlib.sha256(payload).hexdigest()
    name = "BTCUSDT-1h-2024-01.zip"
    lp = f"futures_um/klines/BTCUSDT/1h/{name}"
    (tmp_path / lp).parent.mkdir(parents=True)
    (tmp_path / lp).write_bytes(payload)
    url = "https://data.binance.vision/x/" + name
    (tmp_path / "manifest.json").write_text(json.dumps({
        lp: {"sha256": digest, "url": url},
        "a/BTCUSDT-1h-2025-01.zip": {"sha256": "00", "url": url},
    }))
    ok = datenpruefer.pruefe_klines(tmp_path, _checksum_fetcher({url + ".CHECKSUM": f"{digest}  {name}".encode()}))
    assert ok["geprueft_ok"] == 1 and ok["uebersprungen_holdout"] == 1 and not ok["befunde"]
    bad = datenpruefer.pruefe_klines(tmp_path, _checksum_fetcher({url + ".CHECKSUM": f"{'a' * 64}  {name}".encode()}))
    assert bad["befunde"][0]["art"] == "weicht_von_binance_ab"


def test_datenpruefer_aggtrades_luecke(tmp_path):
    (tmp_path / "agg").mkdir()
    manifest, table = {}, {}
    for tag in (date(2024, 3, 1), date(2024, 3, 3)):
        csv = b"x" + tag.isoformat().encode()
        (tmp_path / "agg" / f"BTCUSDT-{tag.isoformat()}.csv").write_bytes(csv)
        name = f"BTCUSDT-aggTrades-{tag.isoformat()}.zip"
        url = "https://data.binance.vision/a/" + name
        arch = "b" * 64
        manifest[tag.isoformat()] = {"agg_sha256": hashlib.sha256(csv).hexdigest(), "archive_sha256": arch, "url": url}
        table[url + ".CHECKSUM"] = f"{arch}  {name}".encode()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    res = datenpruefer.pruefe_aggtrades(tmp_path, _checksum_fetcher(table))
    assert res["geprueft_ok"] == 2 and res["luecken_tage"] == ["2024-03-02"]
