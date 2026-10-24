"""Backup creation and health inspection must select the same platform default."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import tim_db_backup as backup
from scripts import tim_server_health as health


@pytest.mark.parametrize('command', ['backup', 'health'])
@pytest.mark.parametrize('platform_name,explicit', [
    ('darwin', False), ('linux', False), ('darwin', True), ('linux', True),
])
def test_backup_and_health_cli_directory_selection(command, platform_name, explicit, tmp_path, monkeypatch):
    home = tmp_path / 'Owner Home'
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(sys, 'platform', platform_name)
    selected = []
    custom = tmp_path / 'operator-selected'
    expected = custom if explicit else (
        home / 'Library/Application Support/TIM/backups/live' if platform_name == 'darwin'
        else Path('/var/backups/tim'))
    if command == 'health':
        def collect(directory, disk):
            selected.append(directory)
            return {'status': 'GREEN'}

        monkeypatch.setattr(health, 'collect', collect)
        monkeypatch.setattr(health, 'REPORT_PATH', tmp_path / 'health.json')
        assert health.main(['--backup-dir', str(custom)] if explicit else []) == 0
    else:
        # No secret provider, database or PostgreSQL tool is contacted in this CLI test.
        monkeypatch.setitem(sys.modules, 'config.settings', SimpleNamespace(
            settings=SimpleNamespace(database_url='postgresql://test@127.0.0.1/test')))

        def create(directory, keep_days, parts, **kwargs):
            selected.append(directory)
            return {'status': 'PASS', 'trading_actions': 0}

        monkeypatch.setattr(backup, 'backup', create)
        monkeypatch.setattr(backup, 'BACKUP_REPORT_PATH', tmp_path / 'backup.json')
        args = ['backup'] + (['--dir', str(custom)] if explicit else [])
        assert backup.main(args) == 0
    assert selected == [expected]
