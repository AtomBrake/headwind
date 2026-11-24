"""New rides analysed by the AI coach as they're imported (services/auto_analyse.py): only when the setting is on, only recent rides, and a failing
provider leaves the ride imported with a failed task. No network: the chat is faked, and the queued jobs are run in the test's own thread."""
import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

import database
from services import auto_analyse, jobs


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


class FakeChat:
    name = 'Fake'

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def __call__(self, messages, system=None, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError('rate limited')
        return '🚴 The ride — steady.\n\n🎯 Honest verdict — fine.'


def gpx(start, seconds=120, kind='cycling'):
    pts = ''.join(f'<trkpt lat="{51.5 + i * 0.00005:.7f}" lon="-0.1000000"><ele>10.0</ele>'
                  f'<time>{(start + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i in range(seconds))
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name>Morning Ride</name><type>{kind}</type><trkseg>{pts}</trkseg></trk></gpx>').encode()


NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as app_module
    import config
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    a = app_module.create_app()
    with a.app_context():
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
    return a


@pytest.fixture
def chat(monkeypatch):
    c = FakeChat()
    monkeypatch.setattr('services.ai.get_chat', lambda: c)
    return c


def _on(app, on=True):
    with app.app_context():
        d = database.get_db()
        d.execute('UPDATE Settings SET aiAutoAnalyse=? WHERE id=1', [1 if on else 0])
        d.commit()


def _import_file(app, data, tmp_path, name='ride.gpx'):
    from routes.import_rides import _process_single_file
    path = tmp_path / name
    path.write_bytes(data)
    with app.app_context():
        list(_process_single_file(str(path), name, 1))


def _import_zip(app, files):
    from routes.import_rides import _process_generic_zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for n, data in files.items():
            zf.writestr(n, data)
    with app.app_context(), zipfile.ZipFile(buf) as zf:
        list(_process_generic_zip(zf, zf.namelist(), 1))


def _rides(app):
    with app.app_context():
        return [dict(r) for r in database.get_db().execute('SELECT id, startDateLocal, aiKudos FROM Activity ORDER BY startDateLocal')]


def _tasks(app):
    with app.app_context():
        return [dict(r) for r in database.get_db().execute("SELECT status, error FROM TaskLog WHERE task='ai_analysis'")]


def test_a_new_upload_is_analysed_when_on(app, chat, tmp_path):
    _on(app)
    _import_file(app, gpx(NOW - timedelta(hours=2)), tmp_path)
    rid = _rides(app)[0]['id']
    with app.app_context():
        assert auto_analyse.is_pending(rid)
    jobs.run_queued(app)
    assert _rides(app)[0]['aiKudos'].startswith('🚴 The ride') and chat.calls == 1
    with app.app_context():
        assert not auto_analyse.is_pending(rid)
    assert _tasks(app) == [{'status': 'done', 'error': None}]
    with app.app_context():
        assert database.get_db().execute('SELECT COUNT(*) FROM ActivityMemory WHERE activityId=?', [rid]).fetchone()[0] == 1


def test_nothing_is_analysed_when_off(app, chat, tmp_path):
    _import_file(app, gpx(NOW - timedelta(hours=2)), tmp_path)
    jobs.run_queued(app)
    assert _rides(app)[0]['aiKudos'] is None and chat.calls == 0 and _tasks(app) == []


def test_a_zip_analyses_only_its_recent_rides(app, chat):
    _on(app)
    _import_zip(app, {'old1.gpx': gpx(datetime(2020, 5, 1, 8, tzinfo=timezone.utc)),
                      'old2.gpx': gpx(NOW - timedelta(days=auto_analyse.RECENT_DAYS + 2)),
                      'new.gpx': gpx(NOW - timedelta(hours=3))})
    jobs.run_queued(app)
    rides = _rides(app)
    assert [bool(r['aiKudos']) for r in rides] == [False, False, True] and chat.calls == 1


def _sports(app, raw):
    with app.app_context():
        d = database.get_db()
        d.execute('UPDATE Settings SET aiAutoSports=? WHERE id=1', [raw])
        d.commit()


def test_every_sport_is_analysed_by_default(app, chat, tmp_path):
    """A new install (no rider before step 14) analyses every sport: a run as well as a ride."""
    _on(app)
    _import_file(app, gpx(NOW - timedelta(hours=2), kind='running'), tmp_path)
    jobs.run_queued(app)
    assert _rides(app)[0]['aiKudos'] and chat.calls == 1


def _add_and_queue(app, act_id, sport):
    with app.app_context():
        d = database.get_db()
        start = (NOW - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')
        d.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime) VALUES (?, ?, ?, 1, ?, 5000, 1500)",
                  [act_id, f'Morning {sport}', sport, start])
        auto_analyse.queue_ride(d, act_id)
        d.commit()
    jobs.run_queued(app)
    with app.app_context():
        return database.get_db().execute('SELECT aiKudos FROM Activity WHERE id=?', [act_id]).fetchone()[0]


def test_only_the_sports_picked_are_analysed(app, chat):
    _on(app)
    _sports(app, '["group:ride"]')                      # an install from before the choice: rides only, as it was
    assert _add_and_queue(app, 'run1', 'Run') is None and chat.calls == 0
    assert _add_and_queue(app, 'ride1', 'GravelRide') and chat.calls == 1
    _sports(app, '["group:ride", "sport:Run"]')
    assert _add_and_queue(app, 'run2', 'Run') and chat.calls == 2
    assert _add_and_queue(app, 'walk1', 'Walk') is None and chat.calls == 2


def test_covers_groups_and_single_sports():
    assert auto_analyse.covers(None, 'Kitesurf')
    assert auto_analyse.covers(['group:ride'], 'Virtual Ride') and auto_analyse.covers(['group:ride'], None)
    assert auto_analyse.covers(['group:foot'], 'Hike') and not auto_analyse.covers(['group:foot'], 'Ride')
    assert auto_analyse.covers(['sport:Run'], 'Run') and not auto_analyse.covers(['sport:Run'], 'Walk')
    assert not auto_analyse.covers([], 'Ride')
    assert auto_analyse.chosen(None) is None and auto_analyse.chosen('["group:ride", "nonsense", 3]') == ['group:ride']


def test_an_empty_activity_is_not_analysed(app, chat):
    """An Apple Health workout with nothing recorded: no distance, no moving time, nothing to coach."""
    _on(app)
    with app.app_context():
        d = database.get_db()
        start = (NOW - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')
        d.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal) VALUES ('e1', 'Walk', 'Walk', 1, ?)", [start])
        auto_analyse.queue_ride(d, 'e1')
        assert not auto_analyse.is_pending('e1')


def test_the_ai_page_saves_the_sports(app, chat):
    c = _client(app)
    c.post('/ai/auto-analyse', data={'auto': '1', 'sport': ['group:ride', 'sport:Run', 'bogus']})
    with app.app_context():
        assert database.get_db().execute('SELECT aiAutoSports FROM Settings WHERE id=1').fetchone()[0] == '["group:ride", "sport:Run"]'
    c.post('/ai/auto-analyse', data={'auto': '1', 'every': '1', 'sport': 'group:ride'})
    with app.app_context():
        assert database.get_db().execute('SELECT aiAutoSports FROM Settings WHERE id=1').fetchone()[0] is None
    r = c.post('/ai/auto-analyse', data={'auto': '1'}, follow_redirects=True)      # on, with nothing picked: refused
    assert 'Pick at least one sport' in r.get_data(as_text=True)


def test_a_failing_provider_leaves_the_ride_and_records_a_failed_task(app, monkeypatch, tmp_path):
    c = FakeChat(fail=True)
    monkeypatch.setattr('services.ai.get_chat', lambda: c)
    _on(app)
    _import_file(app, gpx(NOW - timedelta(hours=2)), tmp_path)
    jobs.run_queued(app)
    rides = _rides(app)
    assert len(rides) == 1 and rides[0]['aiKudos'] is None and c.calls == 1      # tried once, not retried
    assert _tasks(app) == [{'status': 'failed', 'error': 'rate limited'}]
    with app.app_context():
        assert not auto_analyse.is_pending(rides[0]['id'])


def _client(app):
    from services import credentials
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _setting(app):
    with app.app_context():
        return database.get_db().execute('SELECT aiAutoAnalyse FROM Settings WHERE id=1').fetchone()[0]


def test_the_setting_needs_a_provider(app, monkeypatch):
    monkeypatch.setattr('services.ai.get_chat', lambda: None)
    c = _client(app)
    c.post('/ai/auto-analyse', data={'auto': '1'})
    assert _setting(app) == 0
    assert 'API key in Settings to analyse new activities automatically' in c.get('/ai').get_data(as_text=True)
    monkeypatch.setattr('services.ai.get_chat', lambda: FakeChat())
    c.post('/ai/auto-analyse', data={'auto': '1', 'every': '1'})
    assert _setting(app) == 1
    c.post('/ai/auto-analyse', data={})
    assert _setting(app) == 0


def test_the_ride_page_says_analysing_until_it_is_done(app, chat, tmp_path):
    _on(app)
    _import_file(app, gpx(NOW - timedelta(hours=2)), tmp_path)
    rid = _rides(app)[0]['id']
    c = _client(app)
    assert 'Analysing…' in c.get(f'/activities/{rid}').get_data(as_text=True)
    assert c.get(f'/activities/{rid}/kudos/status').get_json() == {'pending': True, 'kudos': None}
    jobs.run_queued(app)
    assert c.get(f'/activities/{rid}/kudos/status').get_json()['pending'] is False
    page = c.get(f'/activities/{rid}').get_data(as_text=True)
    assert 'Analysing…' not in page and 'Honest verdict' in page


def test_an_import_rolled_back_leaves_nothing_queued(app, chat):
    """Queued inside the import's transaction: no ride, no job, so nothing waits for a ride that never comes."""
    _on(app)
    with app.app_context():
        d = database.get_db()
        start = (NOW - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')
        d.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, movingTime) VALUES ('x1', 'Ride', 'Ride', 1, ?, 3600)", [start])
        auto_analyse.queue_ride(d, 'x1')
        assert auto_analyse.is_pending('x1')
        d.rollback()
        assert not auto_analyse.is_pending('x1')
    assert jobs.run_queued(app) == 0 and chat.calls == 0
