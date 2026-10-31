"""The copy for troubleshooting (services/troubleshooting_copy.py, Tasks page): the database without secrets, addresses, friends' data or
photos, and without GPS or streams when asked. Only the copy changes. Made in the background and offered when ready (services/downloads.py):
here the job runs straight away. Full app, throwaway database, no network."""
import io
import json
import os
import sqlite3
import zipfile

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import backup, credentials, downloads

SECRETS = ('sk-openai-copy-test', 'sk-ant-copy-test', 'ha-token-copy-test', 'mqtt-pw-copy-test', 'friend-token-copy-test')
ADDRESSES = ('me@example.com', 'ha.home.lan', 'ollama.home.lan', 'ntfy.example', 'broker.home.lan', 'sam.example')
LATLNG = [[51.501234, -0.141234], [51.502345, -0.142345]]


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _streams():
    return json.dumps({'time': [0, 1], 'latlng': LATLNG, 'heartrate': [120, 121], 'distance': [0.0, 5.0]})


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
        d.execute('UPDATE Settings SET openaiKey=?, claudeKey=?, haToken=?, mqttPassword=?, garminEmail=?, haUrl=?, ollamaUrl=?, ntfyUrl=?, '
                  "mqttHost=?, mqttUser='mosquitto-user', installId='install-id-x', heightCm=180, "
                  "garminLastError='GET http://ha.home.lan/api?token=abcdef123456 failed' WHERE id=1",
                  [*SECRETS[:4], ADDRESSES[0], 'http://' + ADDRESSES[1], 'http://' + ADDRESSES[2], 'https://' + ADDRESSES[3], ADDRESSES[4]])
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0)")
        d.execute("INSERT INTO Friend (id, name, url, token, riderId, riderName) VALUES (1, 'Sam Smith', ?, ?, 2, 'Sam')",
                  ['https://' + ADDRESSES[5], SECRETS[4]])
        for aid, rider, name in (('mine', 1, 'Morning ride'), ('theirs', 2, 'Sams secret loop')):
            d.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, startDate, distance, startLat, startLng, "
                      "summaryPolyline, streams, notes) VALUES (?, ?, 'Ride', 'Ride', ?, '2026-10-01T08:00:00', '2026-10-01T07:00:00Z', 5, "
                      "51.501234, -0.141234, 'encodedpolyline', ?, 'felt good')", [aid, name, rider, _streams()])
            d.execute("INSERT INTO ActivityPhoto (activityId, filename) VALUES (?, ?)", [aid, f'act_{aid}.jpg'])
            d.execute("INSERT INTO BestEffort (activityId, activityDate, distanceMi, elapsedSecs) VALUES (?, '2026-10-01', 1, 200)", [aid])
        d.execute("INSERT INTO WeightLog (riderId, logDate, weightKg) VALUES (1, '2026-10-01', 80), (2, '2026-10-01', 70)")
        d.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, friendId) VALUES (1, 'My hill', 51.5, -0.14, 51.51, -0.15, NULL), "
                  "(2, 'Sams hill', 52.5, -1.14, 52.51, -1.15, 1)")
        d.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs) VALUES (1, 'mine', '2026-10-01', 60), "
                  "(2, 'mine', '2026-10-01', 70)")
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Sam Smith', 'hash-of-sams-token')")
        row = {'id': 'parked', 'name': 'Morning ride (watch)', 'startLat': 51.501234, 'startLng': -0.141234, 'summaryPolyline': 'encodedpolyline',
               'streams': _streams()}
        d.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, source, reason, rowJson) VALUES ('parked', 'mine', 1, 'garmin', 'same', ?)",
                  [json.dumps(row)])
        listing = {'activityName': 'Morning ride', 'startLatitude': 51.501234, 'endLongitude': -0.141234, 'locationName': 'Westminster',
                   'ownerFullName': 'Tom Example', 'ownerDisplayName': 'tom_example', 'distance': 5000}
        d.execute("INSERT INTO GarminMissing (garminId, riderId, name, activity) VALUES ('g1', 1, 'Morning ride', ?)", [json.dumps(listing)])
        d.commit()
        database.close_db()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(downloads, '_spawn', lambda fn: fn())
    monkeypatch.setattr(downloads, '_jobs', {})
    return path, app_module.create_app()


def _client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _copy(app, tmp_path, **form):
    c = _client(app)
    r = c.post('/tasks/troubleshooting-copy', data=form)
    assert r.status_code == 302 and r.headers['Location'].endswith('/tasks#copy')
    assert c.get('/tasks/troubleshooting-copy/status').get_json()['state'] == 'ready'
    r = c.get('/tasks/troubleshooting-copy/download')
    assert r.status_code == 200 and 'headwind-troubleshooting-' in r.headers['Content-Disposition']
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ['README.txt', 'headwind.db']             # no photo, no avatar, no key
    out = str(tmp_path / 'copy.db')
    open(out, 'wb').write(z.read('headwind.db'))
    conn = sqlite3.connect(out)
    conn.row_factory = sqlite3.Row
    return out, conn, z.read('README.txt').decode()


def test_the_copy_leaves_out_secrets_addresses_and_friends(setup, tmp_path):
    path, app = setup
    out, c, readme = _copy(app, tmp_path)
    data = open(out, 'rb').read()
    for text in (*SECRETS, *ADDRESSES, 'mosquitto-user', 'install-id-x', 'Sam Smith', 'Sams secret loop', 'Sams hill', 'hash-of-sams-token',
                 'abcdef123456', 'Tom Example', 'tom_example'):
        assert text.encode() not in data, text
    assert [r['name'] for r in c.execute('SELECT name FROM Rider')] == ['Tom']
    assert [r['id'] for r in c.execute('SELECT id FROM Activity')] == ['mine']
    assert [r['activityId'] for r in c.execute('SELECT activityId FROM ActivityPhoto')] == ['mine']
    assert [r['activityId'] for r in c.execute('SELECT activityId FROM BestEffort')] == ['mine']
    assert [r['riderId'] for r in c.execute('SELECT riderId FROM WeightLog')] == [1]
    assert [r['name'] for r in c.execute('SELECT name FROM Segment')] == ['My hill']
    assert [r['segmentId'] for r in c.execute('SELECT segmentId FROM SegmentEffort')] == [1]
    assert dict(c.execute('SELECT name, url, token, riderName FROM Friend').fetchone()) == {'name': 'Friend 1', 'url': '', 'token': None,
                                                                                         'riderName': 'Friend 1'}
    s = c.execute('SELECT * FROM Settings').fetchone()
    assert s['heightCm'] == 180 and s['garminEmail'] is None and s['haUrl'] is None
    # what the person may want to share stays: their activity, its GPS and streams
    a = c.execute("SELECT * FROM Activity WHERE id='mine'").fetchone()
    assert a['name'] == 'Morning ride' and a['notes'] == 'felt good' and json.loads(a['streams'])['latlng'] == LATLNG
    assert c.execute('PRAGMA freelist_count').fetchone()[0] == 0           # nothing taken out is left in a free page
    assert 'Left in it' in readme and 'GPS tracks' in readme
    # a backup with no photos: it restores
    assert backup.validate(out) == 1
    # the live database is untouched
    live = sqlite3.connect(path)
    assert live.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 2
    assert live.execute('SELECT url FROM Friend').fetchone()[0] == 'https://' + ADDRESSES[5]


def test_leave_out_gps(setup, tmp_path):
    _, app = setup
    out, c, readme = _copy(app, tmp_path, no_gps='1')
    data = open(out, 'rb').read()
    for text in (b'51.501234', b'-0.141234', b'encodedpolyline', b'Westminster', b'latlng'):
        assert text not in data, text
    a = c.execute("SELECT * FROM Activity WHERE id='mine'").fetchone()
    assert a['startLat'] is None and json.loads(a['streams'])['heartrate'] == [120, 121]
    row = json.loads(c.execute('SELECT rowJson FROM ActivityDuplicate').fetchone()[0])
    assert isinstance(row['streams'], str) and json.loads(row['streams'])['heartrate'] == [120, 121]     # still a string, as parked
    assert 'startLat' not in row and row['name'] == 'Morning ride (watch)'
    assert c.execute('SELECT COUNT(*) FROM Segment').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM ActivityTrack').fetchone()[0] == 0
    assert json.loads(c.execute('SELECT activity FROM GarminMissing').fetchone()[0]) == {'activityName': 'Morning ride', 'distance': 5000}
    assert 'Also taken out: GPS' in readme


def test_leave_out_the_streams(setup, tmp_path):
    _, app = setup
    out, c, readme = _copy(app, tmp_path, no_streams='1')
    data = open(out, 'rb').read()
    assert b'heartrate' not in data and b'51.501234' not in data
    assert c.execute("SELECT streams FROM Activity WHERE id='mine'").fetchone()[0] is None
    assert json.loads(c.execute('SELECT rowJson FROM ActivityDuplicate').fetchone()[0])['streams'] is None
    assert 'streams' in readme


def test_the_tasks_page_says_what_is_left(setup):
    html = _client(setup[1]).get('/tasks').get_data(as_text=True)
    assert 'Make a copy for troubleshooting' in html and 'Still in it:' in html
    assert 'name="no_gps"' in html and 'name="no_streams"' in html


def test_it_is_made_in_the_background_and_offered_when_ready(setup, monkeypatch):
    path, app = setup
    waiting = []
    monkeypatch.setattr(downloads, '_spawn', waiting.append)          # started, not run yet
    c = _client(app)
    assert c.get('/tasks/troubleshooting-copy/status').get_json() == {'state': 'none'}
    c.post('/tasks/troubleshooting-copy')
    assert c.get('/tasks/troubleshooting-copy/status').get_json()['state'] == 'running'
    html = c.get('/tasks').get_data(as_text=True)
    assert 'Making the copy' in html and 'Make a copy for troubleshooting' not in html
    c.post('/tasks/troubleshooting-copy')                               # one at a time
    assert len(waiting) == 1
    assert c.get('/tasks/troubleshooting-copy/download').status_code == 302      # nothing to download yet
    waiting[0]()
    html = c.get('/tasks').get_data(as_text=True)
    assert 'Your copy is ready' in html and '/tasks/troubleshooting-copy/download' in html
    folder = os.path.join(os.path.dirname(path), downloads.FOLDER)
    made = os.listdir(folder)
    assert len(made) == 1 and made[0].startswith('troubleshooting-')   # beside the database, the work folder gone
    with app.app_context():
        run = database.get_db().execute("SELECT status, result FROM TaskLog WHERE task='download:troubleshooting'").fetchone()
    assert run['status'] == 'done' and 'MB' in run['result']
    # kept for a day, then gone
    monkeypatch.setattr(downloads, 'KEEP_SECS', -1)
    assert c.get('/tasks/troubleshooting-copy/status').get_json() == {'state': 'none'}
    assert os.listdir(folder) == []


def test_delete_it_now_and_a_restart_clears_what_is_left(setup, tmp_path, monkeypatch):
    path, app = setup
    c = _client(app)
    c.post('/tasks/troubleshooting-copy')
    folder = os.path.join(os.path.dirname(path), downloads.FOLDER)
    assert len(os.listdir(folder)) == 1
    c.post('/tasks/troubleshooting-copy/delete')
    assert os.listdir(folder) == [] and c.get('/tasks/troubleshooting-copy/status').get_json() == {'state': 'none'}
    c.post('/tasks/troubleshooting-copy')
    app_module.create_app()
    assert not os.path.exists(folder)


def test_a_failed_copy_says_why(setup, monkeypatch):
    _, app = setup
    from services import troubleshooting_copy
    def broken(*a, **kw):
        raise RuntimeError('disk full')
    monkeypatch.setattr(troubleshooting_copy, 'build', broken)
    c = _client(app)
    c.post('/tasks/troubleshooting-copy')
    assert c.get('/tasks/troubleshooting-copy/status').get_json()['error'] == 'disk full'
    assert 'The last copy failed: disk full' in c.get('/tasks').get_data(as_text=True)
