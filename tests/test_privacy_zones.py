"""Privacy zones (services/privacy_zones.py): nothing within a zone's radius of its point leaves Headwind, whichever way its circle was moved,
in a friend's feed, a live link, the Home Assistant tracks or the heatmap's HD export; the rider's own pages keep it all; a zone made or
changed sends the activities near it to friends again; the troubleshooting copy leaves the zones out. Throwaway databases."""
import json
import math
import random

import pytest
from flask import Flask

import database
from services import feed_tokens, privacy_zones
from services import streams as _streams

HOME = (51.5, -0.1)
TOKEN = 'feed-token-zones'


def metres(a, b):
    kx = 111_320.0 * math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 111_320.0, (a[1] - b[1]) * kx)


def north(n, lat0=HOME[0], lng=HOME[1]):
    """n positions heading north from (lat0, lng), about 111 m apart."""
    return [[round(lat0 + i * 0.001, 6), lng] for i in range(n)]


class Fixed:
    """A stand-in for random: uniform() gives these in turn (the bearing, then the shift)."""
    def __init__(self, *values):
        self.values = list(values)

    def uniform(self, a, b):
        return self.values.pop(0)


def zone(radius=400, bearing=0.0, shift=0.5, lat=HOME[0], lng=HOME[1]):
    return {'lat': lat, 'lng': lng, 'radiusM': radius, 'bearing': bearing, 'shift': shift}


# ── The geometry ──

@pytest.mark.parametrize('seed', range(20))
def test_everything_within_the_radius_is_hidden_whichever_way_the_circle_moved(seed):
    rng = random.Random(seed)
    z = zone(400, rng.uniform(0, 360), rng.uniform(*privacy_zones.SHIFT))
    h = privacy_zones.Hider([z])
    lat, lng, r = privacy_zones.circle(z)
    assert 400 * 1.2 - 1 <= r <= 400 * 1.5 + 1 and metres((lat, lng), HOME) > 50      # moved off the point, and larger
    for k in range(36):                                     # every way out from the point, just inside the radius
        b = math.radians(k * 10)
        p = (HOME[0] + 395 * math.cos(b) / 111_320.0, HOME[1] + 395 * math.sin(b) / (111_320.0 * math.cos(math.radians(HOME[0]))))
        assert h.inside(*p)
    assert not h.inside(HOME[0] + 0.01, HOME[1])            # 1.1 km away


def test_a_tracks_streams_lose_the_samples_taken_inside_and_stay_in_step():
    h = privacy_zones.Hider([zone(400, bearing=180, shift=0.5)])   # the circle is 200 m south, 600 m round: up to 400 m north is hidden
    ll = north(30)
    streams = {'latlng': {'data': ll}, 'time': {'data': list(range(30))}, 'heartrate': {'data': [100 + i for i in range(30)]},
               'cadence': {'data': [80, 81]}}               # out of step: left as it was
    cut = h.streams(streams)
    kept = cut['latlng']['data']
    assert kept and all(metres(p, HOME) >= 400 for p in kept) and not any(h.inside(*p) for p in kept)
    first = ll.index(kept[0])
    assert cut['time']['data'] == list(range(first, 30)) and cut['heartrate']['data'][0] == 100 + first
    assert cut['cadence']['data'] == [80, 81]
    assert h.streams({'latlng': {'data': north(5, lat0=HOME[0] + 0.02)}}) is None       # nothing inside: sent as it was
    assert h.streams({'time': {'data': [1, 2]}}) is None                                # no GPS


def test_a_start_inside_becomes_the_first_position_shown():
    h = privacy_zones.Hider([zone(400)])
    ll = north(20)
    lat, lng = h.start(*HOME, ll)
    assert (lat, lng) != HOME and not h.inside(lat, lng) and [lat, lng] in ll
    assert h.start(*HOME, []) == (None, None)
    assert h.start(52.0, 0.0, ll) == (52.0, 0.0)            # outside: as it is


def test_a_line_is_cut_at_a_zones_edge():
    h = privacy_zones.Hider([zone(400, shift=0.2)])                 # hidden: 480 m round a centre 80 m north
    edge = (HOME[0] + 80 / 111_320.0, HOME[1])
    through = [[HOME[0] - 0.02, HOME[1]], [HOME[0] + 0.02, HOME[1]]]  # no point inside, but the stretch passes through
    a, b = h.pieces(through)
    assert a[0] == through[0] and b[-1] == through[1]
    for end in (a[-1], b[0]):
        assert 480 <= metres(end, edge) < 480 + privacy_zones.STEP_M
    by = [[HOME[0] + 0.02, HOME[1] - 0.02], [HOME[0] + 0.02, HOME[1] + 0.02]]
    assert h.pieces(by) == [by]                                         # nowhere near: as it was
    (piece,) = h.pieces([list(HOME), [HOME[0] + 0.02, HOME[1]]])        # from the door, two points
    assert piece[-1] == [HOME[0] + 0.02, HOME[1]] and 480 <= metres(piece[0], edge) < 500
    assert all(not h.inside(*p) for p in piece)


def test_a_place_is_checked():
    db = _db()
    with pytest.raises(ValueError):
        privacy_zones.add(db, 1, 'Home', 'here', None)
    with pytest.raises(ValueError):
        privacy_zones.add(db, 1, 'Home', 0, 0)
    with pytest.raises(ValueError):
        privacy_zones.add(db, 1, 'Home', *HOME, radius=333)
    assert privacy_zones.parse_place(' 51.50722, -0.1275 ') == ('51.50722', '-0.1275')
    assert privacy_zones.parse_place('51.5 -0.1') == ('51.5', '-0.1')
    assert privacy_zones.parse_place('London') == (None, None)


# ── A friend's feed ──

def _db():
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE Activity (id TEXT PRIMARY KEY, riderId INTEGER, startLat REAL, startLng REAL, updatedAt TEXT)')
    db.execute('CREATE TABLE ActivityTrack (activityId TEXT PRIMARY KEY, minLat REAL, maxLat REAL, minLng REAL, maxLng REAL)')
    return db


@pytest.fixture
def feed(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy_zones.random, 'uniform', lambda a, b: b if b == 360 else a)     # shift 0.2: hidden up to 480 m from home
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.teardown_appcontext(database.close_db)
    from routes.friends import bp
    app.register_blueprint(bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Friend', ?)", [feed_tokens._hash(TOKEN)])
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rob', 1)")
        d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (1, 1)')
        for aid, lat0 in (('from_home', HOME[0]), ('far', HOME[0] + 0.1)):
            ll = north(30, lat0)
            d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, startLat, startLng, updatedAt) "
                      "VALUES (?, 'ride', 1, '2026-10-01T08:00:00', ?, ?, '2026-10-01 09:00:00')", [aid, *ll[0]])
            _streams.save(d, aid, json.dumps({'latlng': {'data': ll}, 'time': {'data': list(range(30))}}))
        # a loop 2 km round home: its box takes home in, its track never goes near
        loop = [[HOME[0] + 0.02 * math.cos(math.radians(k)), HOME[1] + 0.03 * math.sin(math.radians(k))] for k in range(0, 361, 5)]
        d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, startLat, startLng, updatedAt) "
                  "VALUES ('loop', 'ride', 1, '2026-10-01T10:00:00', ?, ?, '2026-10-01 11:00:00')", loop[0])
        _streams.save(d, 'loop', json.dumps({'latlng': {'data': loop}}))
        d.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, polyline) VALUES "
                  "('Up the hill', ?, ?, ?, ?, 1000, '[]'), ('Far climb', ?, ?, ?, ?, 1000, '[]')",
                  [*HOME, HOME[0] + 0.009, HOME[1], HOME[0] + 0.1, HOME[1], HOME[0] + 0.11, HOME[1]])
        d.commit()
    c = app.test_client()
    c.app_ = app
    return c


def _lines(client, kind, query=''):
    resp = client.get('/api/feed' + query, headers={'X-Feed-Token': TOKEN})
    return [o for o in map(json.loads, resp.get_data(as_text=True).splitlines()) if o['type'] == kind]


def _add_zone(client, radius=400):
    with client.app_.app_context():
        return privacy_zones.add(database.get_db(), 1, 'Home', *HOME, radius=radius)


def test_a_feed_without_zones_sends_the_whole_track(feed):
    rides = {r['id']: r for r in _lines(feed, 'ride')}
    assert json.loads(rides['from_home']['streams'])['latlng']['data'][0] == list(HOME)
    assert [s['name'] for s in _lines(feed, 'segment')] == ['Up the hill', 'Far climb']


def test_a_feed_leaves_out_what_is_inside_a_zone(feed):
    _add_zone(feed)
    rides = {r['id']: r for r in _lines(feed, 'ride')}
    s = json.loads(rides['from_home']['streams'])
    ll = s['latlng']['data']
    assert ll and all(metres(p, HOME) >= 400 for p in ll) and len(s['time']['data']) == len(ll)
    assert [rides['from_home']['startLat'], rides['from_home']['startLng']] == ll[0]
    assert len(json.loads(rides['far']['streams'])['latlng']['data']) == 30          # nowhere near: untouched
    assert [x['name'] for x in _lines(feed, 'segment')] == ['Far climb']             # one that starts at home would say where it is


def test_a_new_zone_sends_the_activities_near_it_again(feed):
    before = {r[0]: r[1] for r in _lines(feed, 'manifest', '?manifest=1')[0]['rides']}
    _add_zone(feed)
    after = {r[0]: r[1] for r in _lines(feed, 'manifest', '?manifest=1')[0]['rides']}
    assert after['from_home'] > before['from_home'] and after['far'] == before['far'] and after['loop'] == before['loop']
    with feed.app_.app_context():
        zid = privacy_zones.listing(database.get_db(), 1)[0]['id']
        privacy_zones.update(database.get_db(), 1, zid, name='House')                 # a new name moves nothing
        same = {r[0]: r[1] for r in _lines(feed, 'manifest', '?manifest=1')[0]['rides']}
        assert same == after
        privacy_zones.remove(database.get_db(), 1, zid)
    gone = {r[0]: r[1] for r in _lines(feed, 'manifest', '?manifest=1')[0]['rides']}
    assert gone['from_home'] > after['from_home']


def test_the_start_places_offered_leave_out_those_in_a_zone(feed):
    with feed.app_.app_context():
        d = database.get_db()
        for i in range(6):
            d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, startLat, startLng) VALUES (?, 'r', 1, '2026-10-02', ?, ?)",
                      [f'h{i}', HOME[0] + i * 1e-5, HOME[1]])
        d.commit()
        got = privacy_zones.suggestions(d, 1)
        assert len(got) == 1 and metres((got[0]['lat'], got[0]['lng']), HOME) < 10 and got[0]['count'] == 7
    _add_zone(feed)
    with feed.app_.app_context():
        assert privacy_zones.suggestions(database.get_db(), 1) == []


# ── The live link ──

from tests.test_live_share import phone, post, reading, start, token_of     # noqa: E402,F401  (the fixture and its helpers)


def test_a_live_link_hides_what_is_inside_a_zone(phone, monkeypatch):
    monkeypatch.setattr(privacy_zones.random, 'uniform', lambda a, b: b if b == 360 else a)
    far = (HOME[0] + 0.05, HOME[1])                                     # the ride started 5.5 km north and rides on through
    with phone.app_.app_context():
        privacy_zones.add(database.get_db(), 1, 'Work', HOME[0] + 0.06, HOME[1], radius=400)
    share = start(phone).get_json()
    for i in range(20):
        post(phone, reading(i, lat=far[0] + i * 0.001))
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    work = (HOME[0] + 0.06, HOME[1])
    assert d['points'] and all(metres(p, work) >= 400 for p in d['points'])
    assert any(metres(p, work) < 1000 for p in d['points'])             # and the rest of the ride is shown
    assert d['position'] is not None                                     # 19 * 111 m on: past the zone


# ── Home Assistant and the heatmap ──

class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def web(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'w.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr(privacy_zones.random, 'uniform', lambda a, b: b if b == 360 else a)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, hour in (('ride', 'Ride', 8), ('run', 'Run', 9)):
            ll = north(40)
            db.execute("INSERT INTO Activity (id, name, sportType, type, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, "
                       "startLat, startLng, rawData) VALUES (?, ?, ?, ?, 1, ?, ?, 4400, 1200, 1200, ?, ?, '{}')",
                       [aid, aid, sport, sport, f'2026-10-01T0{hour}:00:00Z', f'2026-10-01T0{hour}:00:00', *ll[0]])
            _streams.save(db, aid, json.dumps({'latlng': {'data': ll}, 'time': {'data': list(range(40))}}))
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.app_ = app
    return c


def test_home_assistant_gets_the_tracks_without_the_zone(web):
    from services import mqtt, run_stats
    with web.app_.app_context():
        before = mqtt._ride_route_payloads(1)['nutrition_ride_route']['pts']
        assert before[0] == list(HOME)
        privacy_zones.add(database.get_db(), 1, 'Home', *HOME)
        ride = mqtt._ride_route_payloads(1)['nutrition_ride_route']['pts']
        run = run_stats.payloads(1)['nutrition_run_route']['pts']
    for pts in (ride, run):
        assert pts and all(metres(p, HOME) >= 400 for p in pts)


def test_the_heatmaps_hd_export_is_cut_but_the_map_is_not(web):
    with web.app_.app_context():
        privacy_zones.add(database.get_db(), 1, 'Home', *HOME)
    hd = web.get('/heatmap/data?hd=1').get_json()
    assert hd['count'] == 2
    for line in hd['tracks']:
        assert all(metres(p, HOME) >= 400 for p in line)
    shown = web.get('/heatmap/data').get_json()
    assert any(metres(p, HOME) < 50 for line in shown['tracks'] for p in line)      # your own map keeps it all


def test_settings_adds_a_zone_from_a_pasted_place_and_removes_it(web):
    r = web.post('/settings/privacy-zones', data={'name': 'Home', 'place': '51.5, -0.1', 'radius': '600'})
    assert r.status_code == 302 and r.headers['Location'].endswith('#privacy')
    with web.app_.app_context():
        zs = privacy_zones.listing(database.get_db(), 1)
    assert [(z['name'], z['lat'], z['lng'], z['radius']) for z in zs] == [('Home', 51.5, -0.1, 600)]
    page = web.get('/settings/').get_data(as_text=True)
    assert 'id="privacyMap"' in page and 'privacy_zones.js' in page
    web.post(f"/settings/privacy-zones/{zs[0]['id']}", data={'name': 'House', 'radius': '800'})
    with web.app_.app_context():
        assert [(z['name'], z['radius']) for z in privacy_zones.listing(database.get_db(), 1)] == [('House', 800)]
    web.post('/settings/privacy-zones', data={'name': 'Nowhere', 'place': 'London', 'radius': '400'})
    assert web.post(f"/settings/privacy-zones/{zs[0]['id']}/delete").status_code == 302
    assert web.post(f"/settings/privacy-zones/{zs[0]['id']}/delete").status_code == 404
    with web.app_.app_context():
        assert privacy_zones.listing(database.get_db(), 1) == []


# ── The troubleshooting copy ──

def test_the_troubleshooting_copy_leaves_the_zones_out(web):
    from services import troubleshooting_copy
    with web.app_.app_context():
        db = database.get_db()
        privacy_zones.add(db, 1, 'Home', *HOME)
        troubleshooting_copy.strip(db)
        assert db.execute('SELECT COUNT(*) FROM PrivacyZone').fetchone()[0] == 0
        db.rollback()
