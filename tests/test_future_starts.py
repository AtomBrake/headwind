"""Activities dated in the future (a device whose clock was reset): flagged at start-up, and given their real date from the activity page. Full
app, throwaway DB."""
import pytest

import app as app_module
import config
import database
from services import credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, day in (('imp_avinox', '2106-02-08T23:46:37'), ('imp_twin', '2025-04-21T14:30:00'), ('ok', '2025-04-20T12:05:24')):
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, "
                       "averageSpeed, startLat, startLng, rawData) VALUES (?, ?, 'Ride', 'Ride', 1, ?, ?, 27377, 7000, 7705, 3.9, 51.5, -0.12, '{}')",
                       [aid, aid, day, day])
        db.commit()
    return a


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_start_up_flags_what_was_saved_before_the_check(app):
    with app.app_context():
        database.migrate_db()                           # the next start
        db = database.get_db()
        flags = dict(db.execute('SELECT id, flagReason FROM Activity').fetchall())
        assert 'the device\'s clock was wrong' in flags['imp_avinox'] and flags['ok'] is None
        note = db.execute("SELECT result FROM TaskLog WHERE task='startup:future_starts'").fetchone()[0]
        assert note.startswith('1 activity starts after today') and 'the real date' in note and '(8 Feb 2106)' in note


def test_the_page_asks_for_the_real_date_and_takes_it(app, client):
    with app.app_context():
        database.migrate_db()
    html = client.get('/rides/imp_avinox').get_data(as_text=True)
    assert 'When did it really start?' in html and "It's right, keep it" not in html
    assert client.post('/rides/imp_avinox/start', data={'start': '2107-01-01T10:00'}).status_code == 400
    r = client.post('/rides/imp_avinox/start', data={'start': '2025-04-21T14:30'})
    assert r.status_code == 200 and r.get_json()['id'] in ('imp_avinox', 'imp_twin')    # on the right day it meets its copy
    with app.app_context():
        db = database.get_db()
        assert db.execute("SELECT COUNT(*) FROM Activity WHERE flagReason IS NOT NULL").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ActivityDuplicate WHERE status='parked' AND id IN ('imp_avinox', 'imp_twin')").fetchone()[0] == 1
