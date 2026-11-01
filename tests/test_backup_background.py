"""Make backup on Settings (routes/settings.backup_export): the zip is made in the background (services/backup.build through
services/downloads.py), the card and the pill at the top of every page say how far it's got, then offer the download by a name the job
made. Full app, throwaway database, no network."""
import io
import os
import sqlite3
import zipfile
from datetime import datetime

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import backup, credentials, downloads, notify

JPEG = b'\xff\xd8\xff\xe0' + b'photo' * 2000


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setenv('AVATAR_DIR', str(tmp_path / 'avatars'))
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, startDate, distance) "
                  "VALUES ('a1', 'Morning ride', 'Ride', 'Ride', 1, '2026-10-01T08:00:00', '2026-10-01T07:00:00Z', 5000)")
        d.commit()
        database.close_db()
    os.makedirs(tmp_path / 'rideimg')
    for name in ('act_0123456789ab.jpg', 'act_0123456789ab_t.jpg', 'act_ba9876543210.jpg'):
        (tmp_path / 'rideimg' / name).write_bytes(JPEG)
    os.makedirs(tmp_path / 'avatars')
    (tmp_path / 'avatars' / 'rider_1.png').write_bytes(b'\x89PNG' + b'x' * 100)
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(downloads, '_jobs', {})
    monkeypatch.setattr(downloads, '_expire_later', lambda kind, path: None)
    waiting = []
    monkeypatch.setattr(downloads, '_spawn', waiting.append)      # the job waits until the test runs it
    return path, app_module.create_app(), waiting


def _client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _pill(c):
    return {i['id']: i for i in c.get('/tasks/background').get_json()['items']}


def _made(path):
    return sorted(os.listdir(downloads.folder(path)))


def test_the_button_returns_at_once_and_the_zip_restores(setup, tmp_path):
    path, app, waiting = setup
    c = _client(app)
    r = c.post('/settings/backup/export')
    assert r.status_code == 302 and r.headers['Location'].endswith('/settings#backup')
    assert len(waiting) == 1                                     # nothing made yet: the request only started it
    assert c.get('/settings/backup/status').get_json()['state'] == 'running'
    assert 'Making the backup' in c.get('/settings/').get_data(as_text=True)
    assert _pill(c)['download:backup']['state'] == 'running'
    waiting.pop()()
    s = c.get('/settings/backup/status').get_json()
    name = f'headwind-backup-{datetime.now():%Y-%m-%d}.zip'
    assert s['state'] == 'ready' and s['url'] == f'/settings/backup/download/{name}'
    assert 'Your backup is ready' in c.get('/settings/').get_data(as_text=True)
    pill = _pill(c)['download:backup']
    assert pill['state'] == 'done' and pill['text'].startswith('✓ Backup ready (') and pill['url'] == s['url']
    assert _made(path) == [n for n in _made(path) if n.startswith('backup-') and n.endswith('.zip')]    # beside the database, no work folder left

    r = c.get(s['url'])
    assert r.status_code == 200 and name in r.headers['Content-Disposition']
    assert 'download:backup' not in _pill(c)                     # fetched: the notice has done its job, the file stays a day
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ['avatars/rider_1.png', 'headwind.db', 'rideimg/act_0123456789ab.jpg', 'rideimg/act_0123456789ab_t.jpg',
                                    'rideimg/act_ba9876543210.jpg']
    kinds = {i.filename: i.compress_type for i in z.infolist()}
    assert kinds['rideimg/act_0123456789ab.jpg'] == zipfile.ZIP_STORED and kinds['headwind.db'] == zipfile.ZIP_DEFLATED
    out = tmp_path / 'restored.db'
    out.write_bytes(z.read('headwind.db'))
    assert backup.validate(str(out)) == 1
    assert sqlite3.connect(out).execute('SELECT name FROM Activity').fetchall() == [('Morning ride',)]

    c.post('/settings/backup/delete')
    assert _made(path) == [] and c.get('/settings/backup/status').get_json()['state'] == 'none'
    assert 'The last one, <span data-backup-when=' in c.get('/settings/').get_data(as_text=True)      # and how big it was


def test_a_second_press_while_one_runs_starts_nothing(setup):
    path, app, waiting = setup
    c = _client(app)
    c.post('/settings/backup/export')
    c.post('/settings/backup/export', data={'secrets': '1'})
    assert len(waiting) == 1
    with c.session_transaction() as s:
        assert any('already being made' in m for _, m in s.get('_flashes', []))
    waiting.pop()()
    assert c.get('/settings/backup/status').get_json()['state'] == 'ready'


def test_the_download_refuses_a_name_it_didnt_make(setup):
    path, app, waiting = setup
    c = _client(app)
    assert c.get('/settings/backup/download/headwind-backup-2026-01-01.zip').status_code == 302      # nothing made: back to the card
    c.post('/settings/backup/export')
    waiting.pop()()
    assert c.get('/settings/backup/download/headwind-backup-2026-01-01.zip').status_code == 404
    assert c.get('/settings/backup/download/..%2Ft.db').status_code == 404
    assert c.get('/settings/backup/download/' + _made(path)[0]).status_code == 404          # the file's own name on disk isn't one


def test_a_failed_run_shows_on_the_tasks_page_and_leaves_no_half_written_zip(setup, monkeypatch):
    path, app, waiting = setup
    real = backup._files

    def files(*a):
        it = real(*a)
        yield next(it)
        raise OSError('No space left on device')
    monkeypatch.setattr(backup, '_files', files)
    c = _client(app)
    c.post('/settings/backup/export')
    waiting.pop()()
    s = c.get('/settings/backup/status').get_json()
    assert s['state'] == 'failed' and 'No space left' in s['error']
    assert _made(path) == []                                     # neither a zip nor the folder it was being made in
    html = c.get('/tasks').get_data(as_text=True)
    assert 'No space left on device' in html and 'Backup' in html
    assert 'The last backup failed' in c.get('/settings/').get_data(as_text=True)
    assert _pill(c)['download:backup']['state'] == 'failed'
    c.post('/tasks/background/dismiss', data={'id': 'download:backup'})
    assert 'download:backup' not in _pill(c)


def test_the_secrets_key_goes_only_inside_the_zip_and_with_it(setup):
    path, app, waiting = setup
    c = _client(app)
    c.post('/settings/backup/export', data={'secrets': '1'})
    waiting.pop()()
    s = c.get('/settings/backup/status').get_json()
    assert 'with-secrets' in s['url']
    z = zipfile.ZipFile(io.BytesIO(c.get(s['url']).data))
    assert z.read('.secrets_key') == open(os.path.join(os.path.dirname(path), '.secrets_key'), 'rb').read()
    assert len(_made(path)) == 1                                 # the zip, and no copy of the key beside it
    c.post('/settings/backup/delete')
    assert _made(path) == []


def test_earlier_backups_stay_out_of_the_next_one(setup, tmp_path):
    path, app, waiting = setup
    c = _client(app)
    c.post('/settings/backup/export')
    waiting.pop()()
    (tmp_path / 'rideimg' / 'headwind-backup.zip').write_bytes(b'PK old one')       # one copied into a photo folder by hand
    c.post('/settings/backup/export')
    waiting.pop()()
    assert len(_made(path)) == 1                                 # the one before is deleted when the next is made
    names = zipfile.ZipFile(io.BytesIO(c.get(c.get('/settings/backup/status').get_json()['url']).data)).namelist()
    assert not [n for n in names if n.endswith('.zip') or downloads.FOLDER in n]


def test_ready_says_so_through_ntfy_and_the_file_goes_after_a_day(setup, monkeypatch):
    path, app, waiting = setup
    sent = []
    monkeypatch.setattr(notify, 'send_notification', lambda *a: sent.append(a))
    app.config['APP_URL'] = 'https://headwind.example/'
    c = _client(app)
    c.post('/settings/backup/export')
    waiting.pop()()
    title, body, click = sent[0]
    assert title == 'Backup ready' and 'kept for a day' in body and click == 'https://headwind.example/settings#backup'
    downloads._expire('backup', downloads._jobs['backup']['path'])
    assert _made(path) == [] and c.get('/settings/backup/status').get_json()['state'] == 'none'


def test_start_up_clears_what_a_run_before_the_restart_left(setup):
    path, app, waiting = setup
    left = os.path.join(downloads.folder(path), 'backup-20260101-000000.zip')
    open(left, 'wb').write(b'PK')
    app_module.create_app()
    assert not os.path.exists(left)
