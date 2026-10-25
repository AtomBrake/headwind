"""Matched routes (services/matched.py): the same start, finish and roads, the same way, the same kind of activity, whatever the names say; the
activity page's "Same route" card and the AI coach's context. Full app, throwaway DB."""
import json
from math import cos, radians

import pytest

import app as app_module
import config
import database
from services import credentials, matched

LAT0, LNG0 = 50.72, -3.53
M_LAT = 1 / 111_320.0
M_LNG = 1 / (111_320.0 * cos(radians(LAT0)))


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def track(legs, step=10, wobble=0.0):
    """[[lat, lng], ...] along straight legs [(east m, north m), ...] from LAT0/LNG0, a point every `step` metres; `wobble` metres east on every
    other point (GPS noise)."""
    pts, x, y = [[LAT0, LNG0]], 0.0, 0.0
    for dx, dy in legs:
        n = max(1, int((dx * dx + dy * dy) ** 0.5 / step))
        for i in range(1, n + 1):
            px, py = x + dx * i / n + (wobble if len(pts) % 2 else 0), y + dy * i / n
            pts.append([LAT0 + py * M_LAT, LNG0 + px * M_LNG])
        x, y = x + dx, y + dy
    return pts


COMMUTE = [(0, 2000), (3000, 0), (0, 1000)]                 # 6 km: north, east, north
DETOUR = [(0, 2000), (0, 1500), (3000, 0), (0, -500)]       # same start and finish, a road 1.5 km further north
HOME = [(0, -1000), (-3000, 0), (0, -2000)]                 # the commute back (starts where COMMUTE ends)


def add(db, aid, legs, day, secs, sport='Ride', rider=1, start=(0, 0), wobble=0.0):
    pts = track(legs, wobble=wobble)
    if start != (0, 0):
        pts = [[p[0] + start[1] * M_LAT, p[1] + start[0] * M_LNG] for p in pts]
    dist = sum(((dx * dx + dy * dy) ** 0.5) for dx, dy in legs)
    db.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, movingTime, averageSpeed, riderId, startLat, startLng, streams) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?)", [aid, aid, sport, f'{day}T08:00:00', dist, secs, dist / secs, rider, pts[0][0], pts[0][1],
                                                    json.dumps({'latlng': {'data': pts}})])


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0)")
        for i, secs in enumerate([1500, 1400, 1450, 1350]):               # four commutes on the way in, 1 to 4 October
            add(db, f'c{i}', COMMUTE, f'2026-10-0{i + 1}', secs, wobble=8 * (i % 2))
        add(db, 'today', COMMUTE, '2026-10-10', 1380)
        add(db, 'home', HOME, '2026-10-05', 1500, start=(3000, 3000))     # the way back: not the same route
        add(db, 'detour', DETOUR, '2026-10-06', 1700)                      # same ends, another road
        add(db, 'run', COMMUTE, '2026-10-07', 2400, sport='Run')           # on foot
        add(db, 'ebike', COMMUTE, '2026-10-08', 1000, sport='EBikeRide')   # an e-bike's times aren't a pedal bike's
        add(db, 'sam', COMMUTE, '2026-10-09', 1300, rider=2)               # someone else
        db.commit()
    return a


def test_same_route_needs_the_same_ends_roads_and_direction():
    a = track(COMMUTE)
    assert matched.same_route(a, track(COMMUTE, wobble=20))
    assert not matched.same_route(a, list(reversed(a)))
    assert not matched.same_route(a, track(DETOUR))


def test_only_this_riders_rides_of_the_same_kind_on_the_same_route(app):
    with app.app_context():
        db = database.get_db()
        assert [r['id'] for r in matched.find(db, 'today')] == ['c0', 'c1', 'c2', 'c3']
        assert matched.find(db, 'run') == []
        assert matched.find(db, 'ebike') == []
        assert matched.find(db, 'home') == []


def test_compare_ranks_this_one_against_the_ones_before(app):
    with app.app_context():
        m = matched.compare(database.get_db(), 'today')
    assert m['total'] == 5 and m['rank'] == 2                       # 1350 (c3) is quicker than today's 1380
    assert [r['id'] for r in m['recent']] == ['c3', 'c2', 'c1', 'c0']
    assert m['median'] == 1425 and m['delta'] == 1380 - 1425 and m['wins'] == 3
    assert m['best']['id'] == 'c3'
    assert [p['current'] for p in m['series']] == [False] * 4 + [True]


def test_an_older_ride_is_compared_with_only_the_ones_before_it(app):
    with app.app_context():
        m = matched.compare(database.get_db(), 'c0')
    assert m['recent'] == [] and m['median'] is None and m['total'] == 5


def test_a_track_summary_is_made_when_missing(app):
    with app.app_context():
        db = database.get_db()
        db.execute('DELETE FROM ActivityTrack')
        db.commit()
        assert len(matched.find(db, 'today')) == 4


def _client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_the_card_shows_the_comparison_and_is_empty_without_one(app):
    c = _client(app)
    html = c.get('/rides/today/matched').get_data(as_text=True)
    assert 'Same route' in html and '2nd' in html and 'quickest of 5' in html
    assert 'href="/rides/c3"' in html
    assert c.get('/rides/home/matched').get_data(as_text=True).strip() == ''
    assert c.get('/rides/nope/matched').status_code == 404
    page = c.get('/rides/today').get_data(as_text=True)
    assert '/rides/today/matched' in page


def test_the_coach_hears_about_the_same_route(app):
    from services.context import _build_route_context
    with app.app_context():
        text = _build_route_context('today')
    assert 'Same route' in text and '2nd quickest of 5' in text and 'median 23:45' in text
