"""The live tracking link (services/live_share.py, routes/live_share.py, POST /api/v1/live/share): the page shows the track and the figures,
stops working once stopped or expired, looks the same for a token that never existed, shows nothing of another rider or another recording,
keeps each rider's track apart, and survives a restart mid-ride."""
import json
import time

import pytest

import database
from services import live, live_share


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _make_app(tmp_path, monkeypatch, address='https://h.example'):
    import app as app_module
    import config
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(config.Config, 'APP_URL', address)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    monkeypatch.setattr(live, '_connection', lambda: None)        # no MQTT broker
    return app_module.create_app()


@pytest.fixture
def phone(tmp_path, monkeypatch):
    from services import credentials
    app = _make_app(tmp_path, monkeypatch)
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom Baker', 1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam Smith', 0)")
        d.commit()
        av = credentials.auth_version()
    web = app.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    token = web.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://h.example'}).get_json()['token']
    c = app.test_client()
    c.app_, c.H = app, {'Authorization': 'Bearer ' + token}
    return c


HOME = (51.5, -0.1)


def reading(i, recording='rec-1', state='riding', **kw):
    """The i-th reading of a ride heading north from HOME, about 111 m apart."""
    d = {'state': state, 'recording': recording, 'lat': HOME[0] + i * 0.001, 'lng': HOME[1], 'speed_mps': 6.0, 'distance_m': i * 111.0,
         'elapsed_s': i * 20, 'sport': 'Ride', 'battery_pct': 80}
    d.update(kw)
    return d


def start(phone, recording='rec-1', **body):
    return phone.post('/api/v1/live/share', json={'recording': recording, 'sport': 'Ride', **body}, headers=phone.H)


def token_of(url):
    return url.rsplit('/', 1)[1]


def post(phone, r):
    assert phone.post('/api/v1/live', json=r, headers=phone.H).status_code == 200


def test_a_link_shows_the_track_and_figures_to_anyone(phone):
    post(phone, reading(0))
    r = start(phone)
    assert r.status_code == 201
    share = r.get_json()
    assert share['url'].startswith('https://h.example/live/hwl_') and share['created'] is True
    for i in range(1, 8):
        post(phone, reading(i))
    anyone = phone.app_.test_client()                # nobody signed in
    page = anyone.get('/live/' + token_of(share['url']))
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store' and 'noindex' in page.headers['X-Robots-Tag']
    html = page.get_data(as_text=True)
    assert 'Anyone with this link can see this page' in html and 'Tom' in html and 'Baker' not in html
    d = anyone.get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['status'] == 'live' and d['name'] == 'Tom' and d['sport'] == 'Ride'
    assert d['distance'] == '0.5 mi' and d['time'] == '2:20' and d['battery'] == 80
    assert d['position'] == [round(HOME[0] + 0.007, 6), HOME[1]]
    # the points within HIDE_START_M of where it began (0, 111 and 222 m) are never sent
    assert [p[0] for p in d['points']] == [pytest.approx(HOME[0] + i * 0.001) for i in range(3, 8)]
    again = anyone.get('/live/' + token_of(share['url']) + '/data?since=' + str(d['last'])).get_json()
    assert again['points'] == []


def test_the_position_is_hidden_near_the_start(phone):
    share = start(phone).get_json()
    post(phone, reading(0))
    post(phone, reading(1))
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['position'] is None and d['hidden'] is True and d['points'] == []


def test_asking_again_gives_the_running_share(phone):
    first = start(phone).get_json()
    second = start(phone)
    assert second.status_code == 200 and second.get_json()['url'] == first['url'] and second.get_json()['created'] is False
    assert start(phone, 'rec-2').get_json()['url'] != first['url']       # another recording, another link


def test_a_stopped_link_ends_at_once_and_looks_like_one_that_never_was(phone):
    share = start(phone).get_json()
    for i in range(6):
        post(phone, reading(i))
    url = '/live/' + token_of(share['url'])
    anyone = phone.app_.test_client()
    assert anyone.get(url).status_code == 200
    assert phone.delete('/api/v1/live/share', json={'recording': 'rec-1'}, headers=phone.H).get_json() == {'stopped': 1}
    stopped, never = anyone.get(url), anyone.get('/live/hwl_' + 'x' * 32)
    assert stopped.status_code == never.status_code == 404
    assert stopped.get_data() == never.get_data() and b'This link has ended' in never.get_data()
    assert anyone.get(url + '/data').status_code == 404
    with phone.app_.app_context():
        assert database.get_db().execute('SELECT COUNT(*) FROM LivePoint').fetchone()[0] == 0


def test_a_finished_recording_keeps_its_link_for_an_hour_then_it_expires(phone):
    share = start(phone).get_json()
    for i in range(6):
        post(phone, reading(i))
    post(phone, reading(6, state='idle'))
    url = '/live/' + token_of(share['url'])
    anyone = phone.app_.test_client()
    d = anyone.get(url + '/data').get_json()
    assert d['status'] == 'finished' and d['endedAt']
    with phone.app_.app_context():
        db = database.get_db()
        row = db.execute('SELECT * FROM LiveShare').fetchone()
        assert row['expiresAt'] == pytest.approx(row['endedAt'] + live_share.AFTER_END_S)
        later = row['expiresAt'] + 1
        assert live_share.lookup(db, token_of(share['url']), now=later) is None
        assert live_share.sweep(db, now=later) > 0
        assert db.execute('SELECT COUNT(*) FROM LivePoint').fetchone()[0] == 0
        assert db.execute('SELECT reading, sealedToken FROM LiveShare').fetchone()[:] == (None, None)
    post(phone, reading(7, recording='rec-2'))           # the next recording doesn't bring an ended share back
    with phone.app_.app_context():
        db = database.get_db()
        db.execute('UPDATE LiveShare SET expiresAt=?', [time.time() - 1])
        db.commit()
    assert anyone.get(url).status_code == 404


def test_a_share_shows_only_its_own_recording(phone):
    """A later recording, with no share, never shows on the earlier one's page; nor a reading sent before the share began."""
    post(phone, reading(5, recording='rec-0', lat=40.0, lng=-3.0))      # an earlier activity, somewhere else
    share = start(phone).get_json()
    for i in range(5):
        post(phone, reading(i))
    post(phone, reading(4, state='idle'))
    post(phone, reading(9, recording='rec-2', lat=48.0, lng=2.0, sport='Run'))
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    lats = [p[0] for p in d['points']] + ([d['position'][0]] if d['position'] else [])
    assert all(51.4 < lat < 51.6 for lat in lats) and d['sport'] == 'Ride' and d['status'] == 'finished'


def test_two_riders_recording_at_once_keep_their_own_tracks(phone):
    with phone.app_.app_context():
        db = database.get_db()
        a, ta, _ = live_share.start(db, 1, 'rec-a')
        b, tb, _ = live_share.start(db, 2, 'rec-a')          # the same recording id from two phones
        for i in range(6):
            live.update(reading(i, recording='rec-a'), rider_id=1)
            live.update(reading(i, recording='rec-a', lat=-33.9 - i * 0.001, lng=151.2), rider_id=2)
        va = live_share.view(db, live_share.lookup(db, ta))
        vb = live_share.view(db, live_share.lookup(db, tb))
    assert va['name'] == 'Tom' and vb['name'] == 'Sam'
    assert all(p[0] > 0 for p in va['points']) and all(p[0] < 0 for p in vb['points'])
    assert va['points'] and vb['points']


def test_the_track_survives_a_restart(phone, tmp_path, monkeypatch):
    share = start(phone).get_json()
    for i in range(6):
        post(phone, reading(i))
    before = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    again = _make_app(tmp_path, monkeypatch)              # the same database, a new process
    after = again.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert after['points'] == before['points'] and len(after['points']) == 3 and after['distance'] == before['distance']


def test_a_share_started_mid_recording_takes_the_track_so_far(phone):
    t0 = time.time() - 600
    track = [[HOME[0] + i * 0.0005, HOME[1], t0 + i * 15] for i in range(20)]
    share = start(phone, track=track).get_json()
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert len(d['points']) == 20 - 6             # within 300 m of the start: hidden (0 to 277 m)


@pytest.mark.parametrize('address, says', [
    ('', 'no outside address'),
    ('http://localhost:5000', 'only works at home'),
    ('https://192.168.1.20', 'only works at home'),
    ('https://headwind.local', 'only works at home'),
    ('http://h.example', 'not https'),
])
def test_no_link_without_an_address_others_can_open(tmp_path, monkeypatch, address, says):
    app = _make_app(tmp_path, monkeypatch, address)
    with app.test_request_context():
        base, why = live_share.link_base()
    assert base is None and says in why and 'Settings → Outside address' in why


def test_the_api_refuses_without_an_address(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, 'http://192.168.1.20:5000')
    from services import device_auth
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        token = device_auth.create('iPhone')[0]
    r = app.test_client().post('/api/v1/live/share', json={'recording': 'r'}, headers={'Authorization': 'Bearer ' + token})
    assert r.status_code == 409 and r.get_json()['settings_url'] == '/settings#address'
    with app.app_context():
        assert database.get_db().execute('SELECT COUNT(*) FROM LiveShare').fetchone()[0] == 0


def test_home_assistant_still_gets_its_readings(phone):
    """The reading kept for Home Assistant is the same as before, with the figures for the link beside it."""
    post(phone, reading(3))
    with phone.app_.app_context():
        c = json.loads(database.get_db().execute('SELECT reading FROM LiveReading WHERE riderId=1').fetchone()[0])
    assert c['distance_mi'] == pytest.approx(0.21, abs=0.01) and c['speed_mph'] == pytest.approx(13.4, abs=0.1)
    assert c['recording'] == 'rec-1' and c['distance_m'] == 333.0
    assert live.states_for(c)['live_ride_status'] == 'riding'


def test_the_page_says_when_the_signal_went(phone):
    share = start(phone).get_json()
    with phone.app_.app_context():
        db = database.get_db()
        row = live_share.lookup(db, token_of(share['url']))
        assert live_share.view(db, row)['status'] == 'waiting'
    for i in range(5):
        post(phone, reading(i))
    with phone.app_.app_context():
        db = database.get_db()
        row = live_share.lookup(db, token_of(share['url']))
        assert live_share.view(db, row)['status'] == 'live'
        quiet = live_share.view(db, row, now=row['readingAt'] + live_share.NO_SIGNAL_S + 1)
        assert quiet['status'] == 'nosignal' and quiet['rateNow'] is None and quiet['rateAvg']


def test_one_address_asking_too_often_is_slowed(phone, monkeypatch):
    from routes import live_share as page
    from services.demo import RateLimiter
    monkeypatch.setattr(page, '_limiter', RateLimiter(limit=3, window=60))
    anyone = phone.app_.test_client()
    codes = [anyone.get('/live/hwl_unknown/data').status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]
    assert anyone.get('/live/hwl_unknown').status_code == 429
