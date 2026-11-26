"""Tests für die lesende INFRA-09-Vorab-Prüfung."""

import json
import os

from src.archive_readiness import preflight as p

# Messung vom 26.11.2026 13:50 (lesend, tim-core-01): Größe und frei für Nicht-root.
SIZE = 391_999_193_088
AVAIL = 324_995_493_888


def _m(**kw):
    base = dict(parent_size=SIZE, parent_avail=AVAIL, parent_mounted=True, img_dir_exists=False,
                mount_exists=False, restore_need=p.LAST_RESTORE_NEED_BYTES)
    base.update(kw)
    return p.Measurement(**base)


def test_todays_measurement_passes_with_32_gib():
    r = p.evaluate(_m())
    assert r.urteil == "PASS", r.checks
    assert r.zahlen["anteil_waehrend_restore"] > 0.15


def test_100_gib_fails_the_reserve():
    r = p.evaluate(_m(), image_bytes=100 * p.GIB)
    assert r.urteil == "FAIL"
    assert any(c["name"] == "free_during_restore" and c["status"] == "FAIL" for c in r.checks)


def test_existing_target_fails():
    assert p.evaluate(_m(img_dir_exists=True)).urteil == "FAIL"
    assert p.evaluate(_m(mount_exists=True)).urteil == "FAIL"


def test_unmounted_parent_fails():
    assert p.evaluate(_m(parent_mounted=False)).urteil == "FAIL"


def test_missing_values_are_inconclusive_never_pass():
    for kw in ({"parent_size": None}, {"parent_avail": None}, {"parent_mounted": None},
               {"img_dir_exists": None}, {"restore_need": None}, {"restore_need": 0}):
        assert p.evaluate(_m(**kw)).urteil == "INCONCLUSIVE", kw


def test_implausible_sizes_are_inconclusive():
    assert p.evaluate(_m(parent_avail=SIZE + 1)).urteil == "INCONCLUSIVE"
    assert p.evaluate(_m(parent_size=0, parent_avail=0)).urteil == "INCONCLUSIVE"
    assert p.evaluate(_m(parent_size=True)).urteil == "INCONCLUSIVE"
    assert p.evaluate(_m(parent_avail=-1)).urteil == "INCONCLUSIVE"


def test_fail_wins_over_inconclusive():
    assert p.evaluate(_m(img_dir_exists=True, restore_need=None)).urteil == "FAIL"


def test_restore_growth_can_flip_to_fail():
    # Wächst die DB stark (Restore-Bedarf +12 %), reicht der Puffer nicht mehr.
    assert p.evaluate(_m(restore_need=int(p.LAST_RESTORE_NEED_BYTES * 1.12))).urteil == "FAIL"


def test_measure_is_read_only(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    before = sorted(os.listdir(tmp_path))
    m = p.measure(str(parent), str(parent / "img"), str(tmp_path / "mnt"))
    assert sorted(os.listdir(tmp_path)) == before
    assert list(parent.iterdir()) == []
    assert m.img_dir_exists is False and m.mount_exists is False
    assert m.parent_size and m.parent_size > 0


def test_measure_sees_symlink_as_existing(tmp_path):
    (tmp_path / "mnt").symlink_to(tmp_path / "nowhere")
    m = p.measure(str(tmp_path), str(tmp_path / "img"), str(tmp_path / "mnt"))
    assert m.mount_exists is True


def test_cli_output_and_exit_code(tmp_path, capsys):
    code = p.main(["--parent", str(tmp_path), "--img-dir", str(tmp_path / "i"), "--mount", str(tmp_path / "m")])
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "tim-archiv-preflight/1"
    assert out["trading_authorized"] == "NO"
    # tmp_path ist kein Einhängepunkt (meist) und meist zu klein: nie PASS-Code ohne PASS-Urteil.
    assert code == {"PASS": 0, "FAIL": 1}.get(out["urteil"], 2)
