"""Private, bounded installer snapshots; game files and saves are never touched."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
import urllib.error
from contextlib import closing


SERVICE_FILES = (
    'systemd/system/arma-server.service',
    'systemd/system/arma-server.service.d/panel-control.conf',
    'systemd/system/arma-panel.service.d/legacy-game.conf',
    'systemd/system/arma-server@.service',
    'sudoers.d/arma-panel-control', 'sudoers.d/arma-panel-instances',
    'arma-panel/instance-control.py',
)


def settings_for(panel):
    settings = {}
    for line in (Path(panel) / 'config.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            settings[key.strip()] = value.strip().strip('"').strip("'")
    return settings


def verify_database(conn):
    if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('Database integrity check failed; keep the original database')


def ready(panel, timeout=30):
    port = int(settings_for(panel).get('PANEL_PORT', '8888'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid panel port')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(f'http://127.0.0.1:{port}/login', timeout=min(2, max(.1, deadline-time.monotonic()))) as response:
                if response.status == 200 and b'id="login-form"' in response.read(256 * 1024):
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(min(.5, max(0, deadline-time.monotonic())))
    raise RuntimeError('Panel sign-in page did not become ready before the deadline')


def backup(panel, source, config_root='/etc', backup_root='/var/backups/arma-panel'):
    panel, source, config_root = Path(panel).resolve(), Path(source).resolve(), Path(config_root).resolve()
    root = Path(backup_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    snapshot = Path(tempfile.mkdtemp(prefix='update-', dir=root))
    # Include files that the new installer may create, so rollback removes them.
    names = {p.name for folder in (panel, source) for p in folder.glob('*.py')}
    names.update(p.name for folder in (panel, source) for p in folder.glob('*.html'))
    names.update(('config.env', '.panel-secret', 'LICENSE', 'ATTRIBUTION.md'))
    for folder in (panel, source):
        for name in ('static','docs'):
            assets=folder/name
            if assets.is_symlink():
                raise ValueError(f'Update recovery requires a regular directory: {assets}')
            for asset in assets.rglob('*'):
                if asset.is_symlink():
                    raise ValueError(f'Update recovery requires regular assets: {asset}')
                if asset.is_file():
                    names.add(asset.relative_to(folder).as_posix())
    targets = [panel / name for name in sorted(names)] + [config_root / name for name in SERVICE_FILES]
    records = []
    for index, target in enumerate(targets):
        if target.is_symlink():
            raise ValueError(f'Update recovery requires regular files: {target}')
        record = {'path': str(target), 'saved': None}
        if target.exists():
            record['saved'] = str(index)
            shutil.copy2(target, snapshot / str(index))
            stat = target.stat()
            record.update(uid=stat.st_uid, gid=stat.st_gid)
        records.append(record)
    (snapshot / 'manifest.json').write_text(json.dumps(records))
    # Keep an independent consistent database backup for manual disaster recovery.
    # Do not rewind accounts/audit records automatically during code rollback.
    settings = settings_for(panel)
    database = Path(settings.get('PANEL_DATA_FILE', str(panel / '.panel-data.sqlite3')))
    if not database.is_absolute():
        database = panel / database
    if database.exists():
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(str(snapshot / 'panel-data.sqlite3'))) as saved:
            original.backup(saved)
            verify_database(saved)
    (snapshot / 'database.json').write_text(json.dumps({'path': str(database), 'present': database.exists(), 'integrity': 'ok' if database.exists() else 'not present'}))
    return str(snapshot)


def restore_database(snapshot, target):
    """Explicit offline recovery; retain a consistent copy of the replaced database."""
    snapshot, target = Path(snapshot).resolve(), Path(target)
    if target.is_symlink() or not target.is_file():
        raise ValueError('Choose the existing regular panel database file')
    source = snapshot / 'panel-data.sqlite3'
    if not source.is_file() or source.is_symlink() or source.resolve() == target.resolve():
        raise ValueError('Choose a snapshot containing a separate saved database')
    previous = snapshot / f'before-database-restore-{time.time_ns()}.sqlite3'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as saved:
        verify_database(saved)
        with closing(sqlite3.connect(str(target))) as live:
            with closing(sqlite3.connect(str(previous))) as retained:
                live.backup(retained)
                verify_database(retained)
            saved.backup(live)
            verify_database(live)
    return str(previous)


def restore(snapshot):
    snapshot = Path(snapshot)
    for record in json.loads((snapshot / 'manifest.json').read_text()):
        target = Path(record['path'])
        if record['saved'] is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot / record['saved'], target)
            if hasattr(os, 'chown'):
                os.chown(target, record['uid'], record['gid'])


if __name__ == '__main__':
    if sys.argv[1] == 'backup':
        print(backup(*sys.argv[2:]))
    elif sys.argv[1] == 'restore':
        restore(sys.argv[2])
    elif sys.argv[1] == 'ready':
        ready(sys.argv[2])
    elif sys.argv[1] == 'restore-database':
        print(restore_database(sys.argv[2], sys.argv[3]))
    else:
        sys.exit('Expected backup, restore, ready or restore-database')
