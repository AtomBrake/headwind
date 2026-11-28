"""Public demo mode: what is refused, rate limiting, the hit counter (bots excluded), the GIF, and the nightly reset. No network, throwaway files."""
import io
import os
import sqlite3

import pytest
from PIL import Image

from services import demo


def test_dangerous_writes_are_refused_by_default():
    for ep in ('settings.change_password', 'settings.backup_import', 'settings.index', 'friends.add', 'garmin.connect', 'import_rides.upload', 'setup.restore', 'phones.create',
               'segments.scan', 'activities.delete', 'riders.edit', 'api_v1.post_activity', 'mqtt.do_publish', 'homeassistant.save', 'sync.sync', 'kudos.kudos', 'nutrition.import_screenshot',
               'nutrition.estimate_meal_photo', 'nutrition.set_food_image', 'nutrition.upload_food_image', 'route_builder.export_current', 'totally.new.endpoint'):
        assert demo.decide('POST', ep), ep
    for method in ('PUT', 'PATCH', 'DELETE'):
        assert demo.decide(method, 'settings.change_password')


def test_the_harmless_fun_stuff_still_works():
    for ep in ('login.login_page', 'nutrition.log_food', 'nutrition.add_water', 'nutrition.log_weight', 'gear.api_assign', 'gear.bike_save', 'gear.part_add', 'dashboard.activities_new', 'activities.save_notes'):
        assert demo.decide('POST', ep) is None, ep
    assert demo.decide('GET', 'dashboard.dashboard') is None and demo.decide('GET', 'static') is None and demo.decide('GET', 'demo.counter') is None


def test_proxies_downloads_and_peer_endpoints_are_refused_even_for_get():
    for ep in ('settings.backup_export', 'settings.backup_download', 'heatmap.tile_proxy', 'friends.feed', 'friends.foods_feed', 'nutrition.image_search'):
        assert demo.decide('GET', ep), ep


def test_rate_limiter_blocks_a_burst_per_client_and_recovers():
    r = demo.RateLimiter(limit=5, window=60)
    assert [r.check('a', now=100.0 + i) for i in range(5)] == [0] * 5
    assert r.check('a', now=106.0) > 0                               # the 6th in the window waits
    assert r.check('b', now=106.0) == 0                              # other clients are unaffected
    assert r.check('a', now=100.0 + 61) == 0                         # and the window slides
    r2 = demo.RateLimiter(limit=10, window=60)
    assert r2.check('x', cost=4, now=1) == 0 and r2.check('x', cost=4, now=2) == 0 and r2.check('x', cost=4, now=3) > 0     # writes cost more


def test_rate_limiter_memory_is_bounded():
    r = demo.RateLimiter(limit=5, window=60, max_clients=100)
    for i in range(1000):
        r.check(f'ip{i}', now=float(i))
    assert len(r._hits) <= 300


def test_the_counter_counts_real_browsers_once_per_half_hour_and_ignores_bots():
    v = demo.Visitors(ttl=1800)
    chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
    assert v.is_new('1.2.3.4', chrome, now=1000) is True
    assert v.is_new('1.2.3.4', chrome, now=1500) is False             # refresh spam
    assert v.is_new('1.2.3.4', chrome, now=1000 + 1900) is True       # back after half an hour
    assert v.is_new('5.6.7.8', chrome, now=1000) is True              # someone else
    for bot in ('Googlebot/2.1', 'curl/8.0', 'python-requests/2.31', 'UptimeRobot/2.0', 'HeadlessChrome/120', '', None):
        assert v.is_new('9.9.9.9', bot, now=1) is False, bot


def test_counter_persists_and_starts_where_told(tmp_path, monkeypatch):
    p = str(tmp_path / 'c.db')
    monkeypatch.setenv('DEMO_COUNTER_START', '41')
    assert demo.counter_value(p) == 41
    assert demo.counter_hit(p) == 42 and demo.counter_hit(p) == 43 and demo.counter_value(p) == 43


def test_counter_gif_is_a_valid_gif_for_any_number():
    for n in (0, 7, 1337, 9999999, 12345678):
        im = Image.open(io.BytesIO(demo.counter_gif(n)))
        assert im.format == 'GIF' and im.size[0] > 100 and im.size[1] > 30
    assert demo.counter_gif(1) != demo.counter_gif(2) and demo.counter_gif(5) == demo.counter_gif(5)


def test_reset_restores_the_pristine_database_and_bike_pictures(tmp_path):
    pristine, live = str(tmp_path / 'pristine.db'), str(tmp_path / 'live.db')
    for path, rows in ((pristine, ['good']), (live, ['good', 'vandalised'])):
        c = sqlite3.connect(path); c.execute('CREATE TABLE t (v TEXT)'); c.executemany('INSERT INTO t VALUES (?)', [(r,) for r in rows]); c.commit(); c.close()
    src, dst = tmp_path / 'src_img', tmp_path / 'live_img'
    src.mkdir(); dst.mkdir(); (src / 'bike_1_aaaaaaaa.jpg').write_bytes(b'x'); (dst / 'junk.jpg').write_bytes(b'y')
    assert demo.reset_now(live, pristine, str(src), str(dst)) is True
    assert [r[0] for r in sqlite3.connect(live).execute('SELECT v FROM t')] == ['good']
    assert sorted(os.listdir(dst)) == ['bike_1_aaaaaaaa.jpg']
    assert demo.reset_now(live, str(tmp_path / 'missing.db')) is False


def test_reset_brings_an_older_clean_copy_up_to_this_version_and_leaves_nothing_behind(tmp_path):
    """A clean copy built by an older Headwind is migrated before it goes live, in a folder that's then removed (with the copy migrating keeps)."""
    import database
    pristine, live = str(tmp_path / 'pristine.db'), str(tmp_path / 'live.db')
    for path in (pristine, live):
        c = sqlite3.connect(path); c.execute('CREATE TABLE t (v TEXT)'); c.commit(); c.close()
    assert demo.reset_now(live, pristine) is True
    c = sqlite3.connect(live)
    assert c.execute('PRAGMA user_version').fetchone()[0] == len(database.STEPS)
    assert c.execute("SELECT 1 FROM sqlite_master WHERE name='Activity'").fetchone()
    c.close()
    assert sorted(f for f in os.listdir(tmp_path) if not f.startswith('live.db')) == ['pristine.db']
    c = sqlite3.connect(pristine)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 0      # the clean copy itself is never changed
    c.close()


def _with_tracks(tmp_path, stale=False):
    """_demo_db with a second activity that has a GPS track, and no map summaries (as the builder made them before 0.7.65), or with stale ones
    of an older tracks.VERSION."""
    from services import streams, tracks
    path = _demo_db(tmp_path)
    c = sqlite3.connect(path)
    streams.register(c)
    c.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,riderId,createdAt,updatedAt)"
              " VALUES ('a2','Run','Run','Run','2026-03-02T08:00:00','2026-03-02T08:00:00',3000,900,900,1,'n','n')")
    streams.save(c, 'a2', {'latlng': {'data': [[53.36 + i * 0.0002, -1.81 + i * 0.0001] for i in range(200)]}, 'time': {'data': list(range(200))}})
    c.execute('DELETE FROM ActivityTrack')
    if stale:
        c.executemany("INSERT INTO ActivityTrack (activityId, line, version) VALUES (?, '[[0,0],[1,1]]', ?)", [('a1', tracks.VERSION - 1), ('a2', tracks.VERSION - 1)])
    c.commit()
    c.close()
    return path


def _tracks(path):
    c = sqlite3.connect(path)
    try:
        return {r[0]: r[1:] for r in c.execute('SELECT activityId, version, line FROM ActivityTrack')}
    finally:
        c.close()


@pytest.mark.parametrize('stale', [False, True])
def test_reset_leaves_every_activity_with_its_map_summary(tmp_path, stale):
    """The heatmap's first visitor after a reset mustn't wait while every line is made: the reset makes them before the swap, whether the clean
    copy had none or had them from another tracks.VERSION."""
    from services import tracks
    pristine = _with_tracks(tmp_path, stale=stale)
    live = str(tmp_path / 'live.db')
    sqlite3.connect(live).close()
    assert demo.reset_now(live, pristine) is True
    got = _tracks(live)
    assert set(got) == {'a1', 'a2'}
    assert all(v == tracks.VERSION for v, _ in got.values())
    assert got['a1'][1] is None and got['a2'][1].startswith('[[53.36')         # no GPS: a row with no line, so it isn't read again
    assert set(_tracks(pristine)) == (({'a1', 'a2'}) if stale else set())       # the clean copy itself is never changed


def test_a_failed_map_summary_fill_does_not_stop_the_reset(tmp_path, monkeypatch, caplog):
    from services import tracks
    pristine = _with_tracks(tmp_path)
    live = str(tmp_path / 'live.db')
    sqlite3.connect(live).close()

    def broken(db, on_batch=None):
        raise RuntimeError('no streams today')
    monkeypatch.setattr(tracks, 'fill', broken)
    assert demo.reset_now(live, pristine) is True
    c = sqlite3.connect(live)
    assert sorted(r[0] for r in c.execute('SELECT id FROM Activity')) == ['a1', 'a2']      # swapped in all the same
    c.close()
    assert 'map summaries not made' in caplog.text


def test_first_start_makes_the_live_databases_map_summaries_before_waiting(tmp_path, monkeypatch):
    """The first start (the live database is a plain copy of the clean one) makes them straight away too, not 20 s on or in a visitor's request."""
    from services import tracks

    class Stop(BaseException):
        pass

    def sleep(s):
        raise Stop
    live = _with_tracks(tmp_path)
    monkeypatch.setattr(demo.time, 'sleep', sleep)
    monkeypatch.setenv('DEMO_PRISTINE_DB', str(tmp_path / 'missing.db'))
    with pytest.raises(Stop):
        demo.reset_loop(type('App', (), {'config': {'DATABASE': live}})())
    got = _tracks(live)
    assert set(got) == {'a1', 'a2'} and all(v == tracks.VERSION for v, _ in got.values())


def test_demo_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    assert demo.enabled() is False
    monkeypatch.setenv('HEADWIND_DEMO', '1')
    assert demo.enabled() is True


# ---------------------------------------------------------------- rebasing the dates
def _demo_db(tmp_path):
    import json
    from datetime import date
    from flask import Flask
    import database
    from services import gear
    app = Flask(__name__)
    path = str(tmp_path / 'demo.db')
    app.config['DATABASE'] = path
    with app.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT INTO Rider(name,isDefault) VALUES ('A',1)")
        db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,totalElevationGain,averageSpeed,maxSpeed,riderId,createdAt,updatedAt)"
                   " VALUES ('a1','Ride','Ride','Ride','2026-03-01T08:00:00','2026-03-01T09:00:00',30000,5400,5500,100,5,9,1,'n','n')")
        db.execute("INSERT INTO BestEffort (activityId, activityDate, distanceMi, elapsedSecs, avgSpeedMps) VALUES ('a1','2026-03-01',5,900,5)")
        for i in range(5):                                          # consecutive days in a UNIQUE column: the case that breaks a naive UPDATE
            d = date(2026, 3, 1).toordinal() + i
            db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (1, ?, 80, 'x')", [date.fromordinal(d).isoformat()])
            db.execute("INSERT INTO GarminDaily (date, restingHR, hrStream, bodyBatteryStream) VALUES (?, 55, ?, ?)", [date.fromordinal(d).isoformat(), json.dumps([[1000, 60], [2000, 61]]), json.dumps([[1000, 80]])])
        b = gear.create_bike(db, 1, 'B', bought_on='2025-01-06')
        gear.add_part(db, b, 'chain', installed_on='2026-02-02', replace_m=1000)
        db.execute('CREATE TABLE IF NOT EXISTS DemoMeta (key TEXT PRIMARY KEY, value TEXT)')
        db.execute("INSERT INTO DemoMeta VALUES ('built_on', '2026-03-10')")
        db.commit()
    return path


def test_rebase_moves_everything_by_whole_weeks_without_collisions(tmp_path):
    path = _demo_db(tmp_path)
    demo.rebase_dates(path, 14)
    c = sqlite3.connect(path)
    assert c.execute("SELECT startDate, startDateLocal FROM Activity").fetchone() == ('2026-03-15T08:00:00', '2026-03-15T09:00:00')
    assert c.execute("SELECT activityDate FROM BestEffort").fetchone()[0] == '2026-03-15'
    assert [r[0] for r in c.execute('SELECT logDate FROM WeightLog ORDER BY logDate')] == ['2026-03-15', '2026-03-16', '2026-03-17', '2026-03-18', '2026-03-19']
    assert c.execute('SELECT MIN(date), MAX(date), COUNT(*) FROM GarminDaily').fetchone() == ('2026-03-15', '2026-03-19', 5)
    assert c.execute('SELECT installedOn, retiredOn FROM Part').fetchone() == ('2026-02-16', None)             # NULL stays NULL
    assert c.execute('SELECT boughtOn FROM Bike').fetchone()[0] == '2025-01-20'
    import json
    assert json.loads(c.execute('SELECT hrStream FROM GarminDaily LIMIT 1').fetchone()[0]) == [[1000 + 14 * 86400000, 60], [2000 + 14 * 86400000, 61]]
    from datetime import date
    assert date.fromisoformat('2026-03-15').weekday() == date.fromisoformat('2026-03-01').weekday()           # weekdays are preserved
    with pytest.raises(ValueError):
        demo.rebase_dates(path, 10)


def test_rebase_if_needed_only_moves_when_a_week_has_passed_and_remembers_it(tmp_path):
    from datetime import date
    path = _demo_db(tmp_path)
    assert demo.rebase_if_needed(path, today=date(2026, 3, 16)) == 0                                            # 6 days: nothing
    assert demo.rebase_if_needed(path, today=date(2026, 3, 27)) == 14                                           # 17 days: two whole weeks
    c = sqlite3.connect(path)
    assert c.execute("SELECT value FROM DemoMeta WHERE key='built_on'").fetchone()[0] == '2026-03-24'
    assert demo.rebase_if_needed(path, today=date(2026, 3, 27)) == 0                                            # and not again
    assert c.execute("SELECT startDateLocal FROM Activity").fetchone()[0] == '2026-03-15T09:00:00'


# ---------------------------------------------------------------- every endpoint has a decision; the one-click way in
class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _make_app(tmp_path, monkeypatch, demo_on):
    from flask import Flask
    import app as app_module
    import config
    import database
    if demo_on:
        monkeypatch.setenv('HEADWIND_DEMO', '1')
    else:
        monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1)")
        db.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    _keep_socket(monkeypatch)                           # demo mode guards the socket for the whole process: give the other tests theirs back
    return app_module.create_app()


def _keep_socket(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, 'connect', socket.socket.connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', socket.socket.connect_ex)


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    return _make_app(tmp_path, monkeypatch, True)


def test_every_endpoint_has_a_demo_decision(demo_app):
    """A new page or API is shut in the demo until it's on one of the lists: this says which ones need a look, so the demo doesn't just show 'switched off'.
    Endpoints that only take writes are refused unless allowed, which is what they should be, so only those that answer GET need a decision."""
    known = demo.ALLOWED_WRITES | demo.DENIED_ENDPOINTS | demo.SAFE_READS | set(demo._STATIC) | {'demo.counter', 'demo.health'}
    reads = {r.endpoint for r in demo_app.url_map.iter_rules() if 'GET' in r.methods}
    endpoints = {r.endpoint for r in demo_app.url_map.iter_rules()}
    assert sorted(reads - known) == [], 'add these to SAFE_READS (after checking what they show), ALLOWED_WRITES or DENIED_ENDPOINTS in services/demo.py'
    assert sorted(known - endpoints - {'avatar_files'}) == [], 'these names in services/demo.py match no endpoint any more'
    assert not demo.SAFE_READS & demo.DENIED_ENDPOINTS and not demo.ALLOWED_WRITES & demo.DENIED_ENDPOINTS


def test_reads_are_refused_unless_checked_as_safe():
    assert demo.decide('GET', 'totally.new.page')
    for ep in ('tasks.index', 'tasks.logs_json', 'tasks.diagnostics', 'tasks.troubleshooting_copy_download', 'settings.version_check', 'api_v1.contacts_list',
               'live_share.page', 'live_share.data', 'setup.wizard', 'saved_routes.garmin_courses'):
        assert demo.decide('GET', ep), ep
    for ep in ('dashboard.dashboard', 'activities.detail', 'nutrition.search_food', 'heatmap.index', 'settings.index', 'saved_routes.route'):
        assert demo.decide('GET', ep) is None, ep


def test_one_click_enter_signs_in_without_a_password(demo_app):
    c = demo_app.test_client()
    page = c.get('/login').get_data(as_text=True)
    assert 'name="enter" value="demo"' in page and 'Enter the demo' in page
    r = c.post('/login', data={'enter': 'demo'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
    assert c.get('/tasks').status_code == 403            # signed in, and the server's logs stay shut
    with c.session_transaction() as s:
        assert s.get('logged_in') is True


def test_one_click_enter_does_nothing_outside_the_demo(tmp_path, monkeypatch):
    c = _make_app(tmp_path, monkeypatch, False).test_client()
    assert 'Enter the demo' not in c.get('/login').get_data(as_text=True)
    r = c.post('/login', data={'enter': 'demo'})
    assert r.status_code == 200 and 'Invalid username or password' in r.get_data(as_text=True)
    with c.session_transaction() as s:
        assert not s.get('logged_in')


# ---------------------------------------------------------------- nothing on the network around it
def test_private_addresses_are_recognised():
    for a in ('192.168.1.20', '10.0.0.5', '172.20.0.3', '169.254.1.1', '100.64.0.1', 'fd12::1', 'fe80::1', '::ffff:192.168.1.1'):
        assert demo._private(a), a
    for a in ('8.8.8.8', '1.1.1.1', '127.0.0.1', '::1', '2606:4700::1111', '172.32.0.1'):
        assert not demo._private(a), a


def test_demo_refuses_connections_to_the_home_network_but_not_to_itself(monkeypatch):
    import socket
    _keep_socket(monkeypatch)
    demo.block_private_networks()
    demo.block_private_networks()                       # twice is harmless
    for target in (('192.168.1.1', 1883), ('10.0.0.2', 8123)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(PermissionError):
                s.connect(target)
            with pytest.raises(PermissionError):
                s.connect_ex(target)
        finally:
            s.close()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    try:
        c = socket.create_connection(server.getsockname(), timeout=2)
        c.close()
    finally:
        server.close()


def test_demo_app_guards_the_socket(demo_app):
    import socket
    assert getattr(socket.socket.connect, '_demo_guard', False)


def test_the_demo_has_no_link_to_the_shut_tasks_page(demo_app):
    c = demo_app.test_client()
    c.post('/login', data={'enter': 'demo'})
    page = c.get('/dashboard').get_data(as_text=True)
    assert 'href="/tasks"' not in page and 'href="/settings/"' in page
