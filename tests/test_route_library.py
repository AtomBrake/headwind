"""A saved route's own page (routes/saved_routes.route) and what it shows (services/route_library.py): the activities that followed it, either way
round, of the route's family; the segments along it, in order and the same way round; and the Routes page's overview map. Full app, throwaway
DB, made-up tracks near LAT0/LNG0."""
import json

import pytest

import app as app_module
import config
import database
from services import credentials, planned_routes, route_library
from tests.test_matched_routes import COMMUTE, DETOUR, M_LAT, M_LNG, add, track


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def shifted(legs, start=(0, 0)):
    return [[p[0] + start[1] * M_LAT, p[1] + start[0] * M_LNG] for p in track(legs)]


def add_segment(db, name, legs, start=(0, 0), sport='ride'):
    pts = shifted(legs, start)
    dist = sum((dx * dx + dy * dy) ** 0.5 for dx, dy in legs)
    return db.execute('INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, polyline, sport) VALUES (?,?,?,?,?,?,?,?)',
                      [name, *pts[0], *pts[-1], dist, json.dumps(pts), sport]).lastrowid


def add_route(db, legs, sport=None, start=(0, 0), name='Commute'):
    rid, _ = planned_routes.save(db, 1, name, track=planned_routes.clean(shifted(legs, start)), source='gpx', sport=sport)
    return rid


HOME = [(0, -1000), (-3000, 0), (0, -2000)]             # COMMUTE backwards, from where it ends
OUT_BACK = [(0, 2000), (0, -2000)]                      # 2 km north and back


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0)")
        for i, secs in enumerate([1500, 1400, 1450, 1350]):
            add(db, f'c{i}', COMMUTE, f'2026-10-0{i + 1}', secs, wobble=8 * (i % 2))
        add(db, 'home', HOME, '2026-10-05', 1500, start=(3000, 3000))     # the same roads the other way round
        add(db, 'detour', DETOUR, '2026-10-06', 1700)                      # same ends, another road
        add(db, 'run', COMMUTE, '2026-10-07', 2400, sport='Run')
        add(db, 'ebike', COMMUTE, '2026-10-08', 1000, sport='EBikeRide')
        add(db, 'zwift', COMMUTE, '2026-10-09', 1000, sport='VirtualRide')
        add(db, 'sam', COMMUTE, '2026-10-09', 1300, rider=2)
        add(db, 'long', [(0, -1500)] + COMMUTE + [(1500, 0)], '2026-10-11', 2200, start=(0, 1500))   # there and on, taking it all in
        add(db, 'half', [(0, 2000), (1500, 0)], '2026-10-12', 700)                                   # only part of it
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


# ---------- the activities that followed a route ----------

def test_a_ride_route_finds_this_riders_rides_on_it_either_way_round(app):
    with app.app_context():
        db = database.get_db()
        got = route_library.find(db, add_route(db, COMMUTE, 'Ride'))
    assert [(a['id'], a['reversed'], a['part']) for a in got] == [
        ('long', False, True), ('ebike', False, False), ('home', True, False), ('c3', False, False), ('c2', False, False), ('c1', False, False),
        ('c0', False, False)]                   # newest first; no run, Zwift, detour, Sam, or the one that did half of it


def test_a_run_route_finds_runs_and_a_route_with_no_sport_anything_outdoors(app):
    with app.app_context():
        db = database.get_db()
        assert [a['id'] for a in route_library.find(db, add_route(db, COMMUTE, 'Run'))] == ['run']
        assert {a['id'] for a in route_library.find(db, add_route(db, COMMUTE, None, start=(0, 1), name='Any'))} == \
            {'c0', 'c1', 'c2', 'c3', 'home', 'run', 'ebike', 'long'}
        assert route_library.find(db, 999) == []


def test_the_summary_is_for_the_routes_sport_and_counts_everything(app):
    with app.app_context():
        db = database.get_db()
        rid = add_route(db, COMMUTE, None)
        m = route_library.summary(db, rid)
    assert m['total'] == 8 and m['group'] == 'ride' and m['done'] == 6      # the run is listed, but its time isn't a ride's ...
    assert m['parts'] == 1                                                  # ... nor is the longer ride's, which did more than the route
    assert m['best']['id'] == 'ebike' and m['last']['id'] == 'long' and m['first'].startswith('2026-10-01')
    assert [p['id'] for p in m['series']] == ['c0', 'c1', 'c2', 'c3', 'home', 'ebike']
    assert m['median'] == 1425


def test_a_route_only_ever_taken_in_on_the_way_has_no_times(app):
    with app.app_context():
        db = database.get_db()
        m = route_library.summary(db, add_route(db, [(0, 1000), (3000, 0)], 'Ride', start=(0, 1000)))     # the middle of the commute
    assert m['done'] == 0 and m['best'] is None and m['median'] is None and m['series'] == []
    assert m['parts'] == m['total'] and {a['id'] for a in m['activities']} >= {'c0', 'long'}


def test_a_route_nobody_has_done_has_no_summary(app):
    with app.app_context():
        db = database.get_db()
        assert route_library.summary(db, add_route(db, DETOUR, 'Ride', start=(0, 5000))) is None


# ---------- the segments along a route ----------

def test_the_segments_along_a_route_in_order_the_same_way_round_and_of_its_family(app):
    with app.app_context():
        db = database.get_db()
        east = add_segment(db, 'East road', [(2000, 0)], start=(500, 2000))
        add_segment(db, 'East road backwards', [(-2000, 0)], start=(2500, 2000))
        north = add_segment(db, 'First climb', [(0, 1500)], start=(0, 200))
        add_segment(db, 'Detour road', [(2000, 0)], start=(500, 3500))
        add_segment(db, 'Park run', [(2000, 0)], start=(500, 2000), sport='foot')
        add_segment(db, 'Off the end', [(0, 1500)], start=(3000, 2500))           # starts on the route, finishes beyond it
        for aid, secs in (('c0', 300), ('c1', 280), ('sam', 200)):
            db.execute('INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, isPR) VALUES (?,?,?,?,?)',
                       [east, aid, '2026-10-01', secs, int(secs == 280)])
        ride, anything = add_route(db, COMMUTE, 'Ride'), add_route(db, COMMUTE, None, start=(0, 1), name='Any')
        segs = route_library.segments_on(db, ride)
        assert [s['id'] for s in segs] == [north, east]
        assert 150 < segs[0]['at'] < 250 and 2450 < segs[1]['at'] < 2550
        assert (segs[1]['efforts'], segs[1]['bestSecs']) == (2, 280)            # Sam's isn't counted
        assert segs[0]['efforts'] == 0 and segs[0]['bestSecs'] is None
        assert len(segs[1]['shape']) >= 2
        assert [s['name'] for s in route_library.segments_on(db, anything)] == ['First climb', 'East road', 'Park run']


def test_an_out_and_back_takes_in_a_segment_each_way(app):
    with app.app_context():
        db = database.get_db()
        up = add_segment(db, 'Up', [(0, 1000)], start=(0, 500))
        down = add_segment(db, 'Down', [(0, -1000)], start=(0, 1500))
        segs = route_library.segments_on(db, add_route(db, OUT_BACK, 'Run'))
        assert segs == []                                                          # ride segments, a run route
        db.execute("UPDATE Segment SET sport='foot'")
        segs = route_library.segments_on(db, add_route(db, OUT_BACK, 'Run', name='Run out and back', start=(0, 1)))
        assert [s['id'] for s in segs] == [up, down] and 2400 < segs[1]['at'] < 2600


# ---------- the overview map ----------

def test_the_overview_line_is_simplified_and_kept(app):
    with app.app_context():
        db = database.get_db()
        rid = add_route(db, COMMUTE)
        line = route_library.map_lines(db)[rid]
        assert 4 <= len(line) < 10 < 600                                           # three straight legs: their corners
        assert route_library.map_lines(db)[rid] is line


# ---------- the pages ----------

def test_the_old_address_of_a_route_opens_its_own_page(client, app):
    with app.app_context():
        db = database.get_db()
        rid = add_route(db, COMMUTE, 'Ride')
        db.commit()
    r = client.get(f'/routes/?route={rid}')
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/routes/{rid}')
    page = client.get(f'/routes/{rid}').get_data(as_text=True)
    assert 'Commute' in page and 'id="routeMap"' in page and 'href="/routes/"' in page
    assert client.get('/routes/999').status_code == 404
    assert client.get('/routes/999/activities').status_code == 404
    assert client.get('/routes/999/segments').status_code == 404


def test_the_route_page_lists_the_activities_and_segments(client, app):
    with app.app_context():
        db = database.get_db()
        add_segment(db, 'East road', [(2000, 0)], start=(500, 2000))
        rid, empty = add_route(db, COMMUTE, 'Ride'), add_route(db, DETOUR, 'Ride', start=(0, 5000), name='Nowhere')
        db.commit()
    card = client.get(f'/routes/{rid}/activities').get_data(as_text=True)
    assert 'Done before' in card and 'href="/activities/c0"' in card and 'the other way round' in card and 'as part of a longer one' in card
    assert 'href="/activities/run"' not in card
    assert 'No activity of yours' in client.get(f'/routes/{empty}/activities').get_data(as_text=True)
    segs = client.get(f'/routes/{rid}/segments').get_data(as_text=True)
    assert 'East road' in segs and 'data-shapes=' in segs
    assert client.get(f'/routes/{empty}/segments').get_data(as_text=True) == ''


def test_the_routes_page_has_the_filters_and_the_lines(client, app):
    with app.app_context():
        db = database.get_db()
        rid = add_route(db, COMMUTE, 'Ride')
        add_route(db, OUT_BACK, None, name='Out and back')
        db.commit()
    page = client.get('/routes/').get_data(as_text=True)
    assert 'id="routeFilters"' in page and f'href="/routes/{rid}"' in page
    assert '<option value="Ride">Ride</option>' in page and '<option value="-">Not set</option>' in page
    lines = client.get('/routes/lines').get_json()['lines']
    assert set(lines) == {str(rid), str(rid + 1)}
