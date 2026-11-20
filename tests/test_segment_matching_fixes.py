"""Impossible segment times (0.7.7): loop segments that collapsed to a few metres, short segments whose ends are close, the close matcher on short
segments and on a straighter line nearby, impossible speeds, a speed floor that drops on a climb and leaves out the stops, waits at a segment's
ends, another way between the same ends, GPS and time streams out of step, and Strava segments given the wrong family.
Throwaway DB, synthetic tracks."""
import json
from datetime import datetime, timedelta, timezone
from math import cos, radians, sin

import pytest
from flask import Flask

import database
from services import parser, reimport, segments as S
from services import streams as _streams

LAT0, LNG0 = 50.70, -3.50
M_LAT = 1 / 111_320.0
M_LNG = 1 / (111_320.0 * cos(radians(LAT0)))


def at(x, y):
    """A point x metres east and y metres north of (LAT0, LNG0)."""
    return [LAT0 + y * M_LAT, LNG0 + x * M_LNG]


def walk(waypoints, speed, step=1):
    """latlng / time / distance streams along metre waypoints [(x, y), ...] at a steady speed, one fix every `step` seconds."""
    pts, ts, ds = [], [], []
    t, d = 0, 0.0
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        n = max(1, int(seg / (speed * step)))
        for i in range(n):
            f = i / n
            pts.append(at(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
            ts.append(t)
            ds.append(round(d + seg * f, 1))
            t += step
        d += seg
    pts.append(at(*waypoints[-1]))
    ts.append(t)
    ds.append(round(d, 1))
    return {'latlng': {'data': pts}, 'time': {'data': ts}, 'distance': {'data': ds}}


def circle(r, n=72, turns=1, start_angle=-90):
    """Metre waypoints round a circle of radius r centred at (0, r), starting at (0, 0)."""
    return [(r * cos(radians(start_angle + 360 * turns * i / n)), r + r * sin(radians(start_angle + 360 * turns * i / n))) for i in range(n + 1)]


def seg_row(start, end, dist, poly=None, sport='ride'):
    return {'id': 1, 'startLat': start[0], 'startLng': start[1], 'endLat': end[0], 'endLng': end[1], 'distanceM': dist,
            'polyline': json.dumps(poly) if poly else None, 'sport': sport}


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


def add(db, aid, streams, sport='Ride', day='2026-10-01'):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId) "
               "VALUES (?, 'A', ?, ?, ?, ?, 1000, 600, 600, '{}', 1)", [aid, sport, sport, f'{day}T10:00:00', f'{day}T10:00:00'])
    _streams.save(db, aid, json.dumps(streams))
    db.commit()


# ── Loops ────────────────────────────────────────────────────────

def test_a_loop_segment_is_cut_as_the_whole_loop_not_a_stub():
    loop = circle(300)                                          # ~1.9 km round, starting and ending at (0, 0)
    st = walk([(-200, 0)] + loop + [(200, 0)], speed=6)         # ride in, round once, ride out
    shape = S.shape_from_streams(st, at(0, 0), at(3, 2))        # Strava's ends a few metres apart
    assert shape and 1800 < shape[1] < 2000


def test_a_loop_is_timed_round_the_whole_lap():
    loop = circle(300)
    st = walk([(-200, 0)] + loop + [(200, 0)], speed=6)
    poly, dist, _ = S.shape_from_streams(st, at(0, 0), at(3, 2))
    secs = S.match_segment(st, seg_row(at(0, 0), at(3, 2), dist, poly))
    assert secs and 250 < secs < 340                             # a lap (~1.9 km at 6-6.5 m/s), not a second or two


def test_a_short_segment_whose_ends_are_close_is_still_found():
    """Hammer Time: 63 m long with its ends 33 m apart, so the track is in the end zone the moment it leaves the start."""
    path = [(-100, 0), (0, 0), (20, 25), (33, 0), (130, 0)]    # out and back round a hairpin: ~63 m from (0, 0) to (33, 0)
    st = walk(path, speed=4)
    shape = S.shape_from_streams(st, at(0, 0), at(33, 0))
    assert shape and 55 < shape[1] < 75
    secs = S.match_segment(st, seg_row(at(0, 0), at(33, 0), shape[1], shape[0]))
    assert secs and 10 <= secs <= 18                             # ~63 m at about 4 m/s


def test_a_segment_made_on_one_spot_is_refused(db):
    from routes.segments import bp
    app = Flask(__name__)
    app.config['DATABASE'] = db.execute('PRAGMA database_list').fetchone()[2]
    app.register_blueprint(bp)
    c = app.test_client()
    form = {'name': 'Stub', 'startLat': LAT0, 'startLng': LNG0, 'endLat': LAT0, 'endLng': LNG0, 'distanceM': 4}
    assert c.post('/segments/create', data=form).status_code == 400


# ── The close matcher and impossible speeds ─────────────────────

def test_no_close_matching_on_a_short_segment():
    st = walk([(-300, 30), (300, 30)], speed=6)                 # 30 m off a 100 m segment the whole way
    poly = [at(x, 0) for x in range(0, 101, 10)]
    assert S.match_segment_close(st, seg_row(at(0, 0), at(100, 0), 100, poly)) is None


def test_a_straighter_line_nearby_is_not_the_twisty_segment():
    """Badgers Hole: a trail zig-zagging either side of a road, within CLOSE_TOL_M of it; the road is about 3/4 of its length."""
    zig = [(x, 50 if (x // 50) % 2 else -50) for x in range(0, 801, 50)]
    trail = walk(zig, speed=4)
    poly = trail['latlng']['data'][::3]
    seg = seg_row(poly[0], poly[-1], S._path_length_m(poly), poly)
    road = walk([(-300, 0), (1100, 0)], speed=12)
    assert S.match_segment_close(road, seg) is None
    assert S.match_segment_close(trail, seg) is not None or S.match_segment(trail, seg) is not None


def test_an_effort_faster_than_a_bike_can_go_is_a_gps_jump():
    st = walk([(-100, 0), (1100, 0)], speed=40)                 # 90 mph
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    assert S.match_segment(st, seg_row(at(0, 0), at(1000, 0), 1000, poly)) is None


def stopped(st, after_m, secs):
    """The streams with a stop of `secs` seconds once `after_m` metres have been covered."""
    ts = [t + (secs if d > after_m else 0) for t, d in zip(st['time']['data'], st['distance']['data'])]
    return {**st, 'time': {'data': ts}}


def climb(gain, **kw):
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    return {**seg_row(at(0, 0), at(1000, 0), 1000, poly, **kw), 'elevationGainM': gain}


def test_a_steep_climb_pushed_at_walking_pace_is_an_effort():
    """7 of 65 segments in a real export never matched, not even on the ride they were drawn on: climbs of 6-15% ridden at 0.7-2 m/s, under
    the 2 m/s floor for a bike. On a climb the floor is a rate upward (MIN_CLIMB_MPS) instead."""
    st = walk([(-100, 0), (1100, 0)], speed=1)                  # 10% at 1 m/s: 360 m an hour
    assert S.match_segment(st, climb(100)) is not None
    assert S.match_segment(st, climb(0)) is None                # the same pace on the flat is still too slow
    assert S.match_segment(st, climb(None)) is None             # a segment with no climb stored keeps the plain floor
    assert S.match_segment(walk([(-100, 0), (1100, 0)], speed=1.5), climb(40)) is not None    # 4% at 1.5 m/s: 216 m an hour


def test_a_stop_part_way_along_is_still_an_effort_timed_with_the_stop():
    """A segment made on a ride didn't match that ride: mountain-bike descents of 200 m to 1.2 km, ridden at 3 m/s with stops of 3 to 7 minutes
    half way down, came out under the 2 m/s floor over their elapsed time. The floor is taken against the moving time; the effort keeps its
    elapsed time, as on Strava."""
    st = stopped(walk([(-100, 0), (1100, 0)], speed=6), 600, 1800)          # 6 m/s with half an hour at the café
    elapsed = S.match_segment(st, climb(0))
    assert elapsed == pytest.approx(1000 / 6 + 1800, abs=3)
    assert S.match_segment_close(st, climb(0))[0] >= 1800


def test_a_wait_at_the_start_or_the_finish_is_not_in_the_time():
    """Stood at the top before dropping in, or at the bottom after: the nearest point to the marker can fall anywhere in the wait. A stop on the
    segment itself, past the start or short of the finish, stays in the time."""
    seg = climb(0)
    ride = walk([(-100, 0), (1100, 0)], speed=3)                # a fix every 3 m: ... -1, 2, 5 ... 995, 998 ...
    assert S.match_segment(ride, seg) == pytest.approx(333, abs=3)
    assert S.match_segment(stopped(ride, 100, 120), seg) == pytest.approx(330, abs=3)      # 2 m past the start marker
    assert S.match_segment(stopped(ride, 1096, 120), seg) == pytest.approx(330, abs=3)     # 5 m short of the finish
    assert S.match_segment(stopped(ride, 130, 120), seg) == pytest.approx(333 + 120, abs=3)    # 30 m along
    assert S.match_segment(stopped(ride, 1080, 120), seg) == pytest.approx(333 + 120, abs=3)   # 20 m short of the finish
    assert S.match_segment(stopped(ride, 100, 2), seg) == pytest.approx(335, abs=3)       # a slow sample rolling through isn't a wait


def test_every_segment_is_matched_again_once_with_the_stops_left_out(db):
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, polyline, sport) "
               "VALUES ('Down', ?, ?, ?, ?, 1000, 0, ?, 'ride')", [*at(0, 0), *at(1000, 0), json.dumps(poly)])
    add(db, 'r1', stopped(walk([(-100, 0), (1100, 0)], speed=3), 600, 300))     # 3 m/s with 5 minutes half way down: 1.6 m/s in all
    db.execute('UPDATE Settings SET segmentStopsDone=0 WHERE id=1')
    assert S.rematch_stops(db) == {'ran': True, 'segments': 1, 'found': 1, 'shorter': 0, 'prs_moved': 1}
    assert db.execute('SELECT elapsedSecs, approx, isPR FROM SegmentEffort').fetchone()[:] == (pytest.approx(633, abs=3), 0, 1)
    assert S.rematch_stops(db) == {'ran': False}


def test_a_detour_off_the_segment_is_still_too_slow():
    """Leaving the segment and coming back is moving time, so the floor still turns it away."""
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    seg = {**seg_row(at(0, 0), at(1000, 0), 1000, poly), 'elevationGainM': 0}
    out_and_back = [(-100, 0), (500, 0), (500, 2000), (500, 0), (1100, 0)]      # 4 km up a side road and back from half way along
    assert S.match_segment(walk(out_and_back, speed=6), seg) is None
    assert S.match_segment(walk([(-100, 0), (1100, 0)], speed=6), seg) is not None


# ── Following the segment's own line ────────────────────────────

def bulge(apart, start=300, end=700):
    """Waypoints along the x axis from -100 to 1100 m that leave it `apart` metres to the north between `start` and `end`, and come back."""
    return [(-100, 0), (start - 50, 0), (start + 50, apart), (end - 50, apart), (end + 50, 0), (1100, 0)]


def test_another_way_between_the_same_ends_is_not_the_segment():
    """A road round instead of a steep path: the checkpoints are within 60 m, and it's fast enough, but it isn't the segment."""
    seg = climb(0)
    assert S.match_segment(walk(bulge(55), speed=6), seg) is None
    assert S.match_segment_close(walk(bulge(55), speed=6), seg) is None
    assert S.match_segment(walk(bulge(30), speed=6), seg) is not None        # GPS drift, or the far side of a road
    round_a_tree = [(-100, 0), (480, 0), (490, 50), (510, 50), (520, 0), (1100, 0)]
    assert S.match_segment(walk(round_a_tree, speed=6), seg) is not None    # 50 m off, but for under OFF_ROUTE_RUN_M


def test_a_single_stray_gps_point_is_not_another_way():
    ride = walk([(-100, 0), (1100, 0)], speed=6)
    i = len(ride['latlng']['data']) // 2
    ride['latlng']['data'][i] = at(500, 90)
    assert S.match_segment(ride, climb(0)) is not None


def test_two_lines_with_the_same_ends_each_keep_their_own_efforts():
    """Two lines down one hill that split and join again 30 m apart: close enough for GPS drift on either, so the pass goes to the line it
    runs nearer. Drawn twice on one line, both segments keep it."""
    a = {**seg_row(at(0, 0), at(1000, 0), 1000, [at(x, y) for x, y in [(0, 0), *bulge(30)[1:-1], (1000, 0)]]), 'id': 1}
    b = {**seg_row(at(0, 0), at(1000, 0), 1000, [at(x, 0) for x in range(0, 1001, 50)]), 'id': 2}
    on_a, on_b = walk(bulge(30), speed=6), walk([(-100, 0), (1100, 0)], speed=6)
    assert S.siblings_of(a, [a, b]) == (b['polyline'],)
    assert S.match_segment(on_a, a, S.siblings_of(a, [a, b])) is not None
    assert S.match_segment(on_a, b, S.siblings_of(b, [a, b])) is None
    assert S.match_segment(on_b, b, S.siblings_of(b, [a, b])) is not None
    assert S.match_segment(on_b, a, S.siblings_of(a, [a, b])) is None
    twice = {**b, 'id': 3}
    assert S.match_segment(on_b, b, S.siblings_of(b, [b, twice])) is not None
    assert S.match_segment(on_b, twice, S.siblings_of(twice, [b, twice])) is not None


def test_every_segment_is_matched_again_once_on_its_own_line(db):
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, polyline, sport) "
               "VALUES ('Path', ?, ?, ?, ?, 1000, 0, ?, 'ride')", [*at(0, 0), *at(1000, 0), json.dumps(poly)])
    add(db, 'r1', walk([(-100, 0), (1100, 0)], speed=6))
    add(db, 'r2', walk(bulge(55), speed=6), day='2026-10-02')
    db.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs) VALUES (1, 'r2', '2026-10-02', 190)")   # an old match
    db.execute('UPDATE Settings SET segmentRouteDone=0, segmentStopsDone=0 WHERE id=1')
    res = S.rematch_routes(db)
    assert res['ran'] and res['stops'] and res['removed'] == 1 and res['found'] == 1
    assert [r[0] for r in db.execute('SELECT activityId FROM SegmentEffort')] == ['r1']
    assert S.rematch_routes(db) == {'ran': False} and S.rematch_stops(db) == {'ran': False}


def test_a_broken_altimeter_does_not_take_the_floor_away():
    assert S.min_speed(climb(5000)) == pytest.approx(S.MIN_CLIMB_MPS / S.MAX_GRADE)
    st = walk([(-100, 0), (1100, 0)], speed=0.2)                # under the floor of the steepest climb taken (MAX_GRADE)
    assert S.match_segment(st, climb(5000)) is None


def test_the_close_matcher_takes_the_same_floor():
    st = walk([(-100, 0), (920, 0)], speed=1)                   # pushes up 10% at 1 m/s and stops 80 m short of the top
    assert S.match_segment(st, climb(100)) is None
    assert S.match_segment_close(st, climb(100)) is not None
    assert S.match_segment_close(st, climb(0)) is None


def test_steep_segments_are_matched_again_once(db):
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    for name, gain in (('Up', 100), ('Flat', 0)):
        db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, polyline, sport) "
                   "VALUES (?, ?, ?, ?, ?, 1000, ?, ?, 'ride')", [name, *at(0, 0), *at(1000, 0), gain, json.dumps(poly)])
    add(db, 'r1', walk([(-100, 0), (1100, 0)], speed=1))
    db.execute('UPDATE Settings SET segmentClimbFloorDone=0 WHERE id=1')
    res = S.rematch_climbs(db)
    assert res == {'ran': True, 'segments': 1, 'found': 1}
    assert [r[0] for r in db.execute('SELECT s.name FROM SegmentEffort e JOIN Segment s ON s.id=e.segmentId')] == ['Up']
    assert S.rematch_climbs(db) == {'ran': False}


def test_on_foot_the_floor_only_drops_on_a_steep_climb():
    assert S.min_speed(climb(0, sport='foot')) == S.MIN_SPEED_MPS['foot']
    assert S.min_speed(climb(100, sport='foot')) == S.MIN_SPEED_MPS['foot']   # 10%: 0.56 m/s up it is above the 0.5 m/s floor
    assert S.min_speed(climb(200, sport='foot')) < S.MIN_SPEED_MPS['foot']    # 20%: a scramble up at 0.3 m/s counts


# ── GPS and time in step ─────────────────────────────────────────

def test_records_without_a_fix_are_left_out_of_every_stream():
    t0 = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    pts = []
    for i in range(20):
        has_fix = not (5 <= i < 12)                             # a tunnel: no position for 7 records
        pts.append({'time': t0 + timedelta(seconds=i), 'latlng': at(i * 5, 0) if has_fix else None, 'heartrate': 120 + i})
    streams, kept = parser.aligned_streams(pts, t0)
    assert len(streams['latlng']['data']) == len(streams['time']['data']) == len(streams['heartrate']['data']) == 13
    assert streams['time']['data'][5] == 12                     # the point after the tunnel keeps its own time


def test_realign_drops_records_from_before_the_first_fix_only_when_certain():
    good = walk([(0, 0), (500, 0)], speed=5)
    early = {'latlng': good['latlng'], 'time': {'data': [-3, -2, -1] + good['time']['data']},
             'distance': {'data': [0.0, 0.0, 0.0] + good['distance']['data']}}
    fixed = S.realign(early)
    assert fixed and fixed['time']['data'] == good['time']['data']
    moving = {**early, 'distance': {'data': [0.0, 5.0, 10.0] + good['distance']['data']}}    # moving already: the gap could be anywhere
    assert S.realign(moving) is None


def test_a_track_far_out_of_step_is_not_timed():
    st = walk([(-100, 0), (1100, 0)], speed=6)
    st['time']['data'] = st['time']['data'] + list(range(st['time']['data'][-1] + 1, st['time']['data'][-1] + 40))
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    assert S.match_segment(st, seg_row(at(0, 0), at(1000, 0), 1000, poly)) is None


def test_importing_the_file_again_puts_its_streams_right(db):
    good = walk([(-100, 0), (1100, 0)], speed=6)
    bad = {**good, 'time': {'data': good['time']['data'] + list(range(5000, 5040))}}
    add(db, 'r1', bad)
    saved = db.execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='r1'").fetchone()
    reimport.ensure_schema(db)
    reimport.propose(db, saved, {'id': 'r1', 'streams': json.dumps(good)}, 'test')
    st = json.loads(_streams.load_json(db, 'r1'))
    assert len(st['time']['data']) == len(st['latlng']['data'])
    assert db.execute('SELECT COUNT(*) FROM ImportChange').fetchone()[0] == 0     # a repair, not a choice


# ── Strava segment families ──────────────────────────────────────

def test_a_strava_segment_takes_the_family_most_activities_along_it_have(db):
    st = walk([(-100, 0), (1100, 0)], speed=3)
    add(db, 'run1', st, 'Run', '2026-09-01')
    add(db, 'run2', st, 'Run', '2026-09-02')
    add(db, 'ride1', walk([(-100, 0), (1100, 0)], speed=7), 'Ride', '2026-09-03')     # the newest
    out = S.import_strava(db, [{'Segment Name': 'Lane', 'Activity ID': 'not-here', 'Starting Latitude': at(0, 0)[0], 'Starting Longitude': at(0, 0)[1],
                                'Ending Latitude': at(1000, 0)[0], 'Ending Longitude': at(1000, 0)[1]}])
    assert len(out['created']) == 1
    assert db.execute('SELECT sport FROM Segment').fetchone()[0] == 'foot'


def test_a_ride_segment_at_the_same_ends_does_not_stop_a_foot_one(db):
    add(db, 'run1', walk([(-100, 0), (1100, 0)], speed=3), 'Run')
    db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, sport) VALUES ('Road', ?, ?, ?, ?, 1000, 'ride')",
               [*at(0, 0), *at(1000, 0)])
    out = S.import_strava(db, [{'Segment Name': 'Lane', 'Activity ID': 'run1', 'Starting Latitude': at(0, 0)[0], 'Starting Longitude': at(0, 0)[1],
                                'Ending Latitude': at(1000, 0)[0], 'Ending Longitude': at(1000, 0)[1]}])
    assert len(out['created']) == 1 and out['existing'] == 0


def test_a_segments_sport_can_be_changed_and_it_is_matched_again(db, tmp_path):
    from routes.segments import bp
    add(db, 'run1', walk([(-100, 0), (1100, 0)], speed=3), 'Run')
    poly = [at(x, 0) for x in range(0, 1001, 50)]
    db.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, distanceM, polyline, sport) VALUES (5, 'Lane', ?, ?, ?, ?, 1000, ?, 'ride')",
               [*at(0, 0), *at(1000, 0), json.dumps(poly)])
    db.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, distanceM, sport, friendId) VALUES (6, 'Theirs', 0, 0, 1, 1, 10, 'ride', 1)")
    db.commit()
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.register_blueprint(bp)
    c = app.test_client()
    assert c.post('/segments/5/sport', data={'sport': 'foot'}).status_code == 302
    assert db.execute('SELECT sport FROM Segment WHERE id=5').fetchone()[0] == 'foot'
    assert db.execute('SELECT activityId FROM SegmentEffort WHERE segmentId=5').fetchone()[0] == 'run1'
    assert c.post('/segments/6/sport', data={'sport': 'foot'}).status_code == 400      # a friend's segment keeps its family


# ── The start-up repair ──────────────────────────────────────────

def test_the_repair_cuts_a_collapsed_loop_again_and_matches_everything_again(db):
    st = walk([(-200, 0)] + circle(300) + [(200, 0)], speed=6)
    add(db, 'src', st)
    db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, polyline, sourceActivityId, sport) "
               "VALUES ('Loop', ?, ?, ?, ?, 6, ?, 'src', 'ride')", [*at(0, 0), *at(3, 2), json.dumps([at(0, 0), at(3, 2)])])
    db.execute('INSERT INTO SegmentEffort (segmentId, activityId, elapsedSecs, approx) VALUES (1, ?, 1, 0)', ['src'])
    db.execute('UPDATE Settings SET segmentMatchFixDone=0')
    db.commit()
    res = S.repair_matching(db)
    assert res['ran'] and res['loops'] == 1
    assert db.execute('SELECT distanceM FROM Segment').fetchone()[0] > 1800
    assert db.execute('SELECT elapsedSecs FROM SegmentEffort').fetchone()[0] > 250
    assert S.repair_matching(db) == {'ran': False}


def test_a_road_running_beside_the_segment_is_not_it():
    """Avoiding the road: a road bike on the road 18 m away, the whole length of the segment, is not on the trail; drift either side is."""
    poly = [at(x, 0) for x in range(0, 801, 20)]
    seg = seg_row(at(0, 0), at(800, 0), 800, poly)
    road = walk([(-300, 18), (1100, 18)], speed=14)
    assert S.match_segment_close(road, seg) is None
    drift = walk([(-300, 0)] + [(x, 8 if (x // 100) % 2 else -8) for x in range(0, 801, 100)] + [(1100, 0)], speed=6)
    drift['latlng']['data'] = [[p[0], p[1]] for p in drift['latlng']['data']]
    assert S.match_segment_close(drift, seg) is not None or S.match_segment(drift, seg) is not None


# ── Moving time from a broken lap timer ──────────────────────────

TCX = """<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
<Activities><Activity Sport="Biking"><Id>2014-05-30T00:38:02Z</Id><Lap StartTime="2014-05-30T00:38:02Z">
<TotalTimeSeconds>9.89</TotalTimeSeconds><DistanceMeters>{dist}</DistanceMeters><Track>{points}</Track></Lap></Activity></Activities>
</TrainingCenterDatabase>"""


def test_a_lap_timer_of_seconds_is_not_the_moving_time():
    """Makara Peak, 'Garmin fail!': the lap says 9.89 s for 11 km; the trackpoints cover the ride."""
    t0 = datetime(2014, 5, 30, 0, 38, 2, tzinfo=timezone.utc)
    pts = ''.join(f'<Trackpoint><Time>{(t0 + timedelta(seconds=10 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")}</Time>'
                  f'<Position><LatitudeDegrees>{at(0, 30 * i)[0]}</LatitudeDegrees><LongitudeDegrees>{LNG0}</LongitudeDegrees></Position>'
                  f'<DistanceMeters>{30 * i}</DistanceMeters></Trackpoint>' for i in range(361))     # 10.8 km in an hour
    a = parser.parse_tcx(TCX.format(dist=10800, points=pts).encode())
    assert 3500 <= a['movingTime'] <= 3600
    assert 2.9 < a['averageSpeed'] < 3.1


def test_stored_moving_times_of_seconds_are_put_right(db):
    from services import moving_time
    add(db, 'flat', walk([(0, 0), (3000, 0)], speed=3))
    db.execute("UPDATE Activity SET distance=3000, movingTime=9, averageSpeed=333 WHERE id='flat'")
    add(db, 'fine', walk([(0, 0), (3000, 0)], speed=3))
    db.execute("UPDATE Activity SET distance=3000, movingTime=1000, averageSpeed=3 WHERE id='fine'")
    db.execute('UPDATE Settings SET movingTimeFixDone=0')
    db.commit()
    res = moving_time.repair(db)
    assert [f[0] for f in res['fixed']] == ['flat']
    row = db.execute("SELECT movingTime, averageSpeed FROM Activity WHERE id='flat'").fetchone()
    assert 950 <= row['movingTime'] <= 1010 and 2.9 < row['averageSpeed'] < 3.2
    assert db.execute("SELECT movingTime FROM Activity WHERE id='fine'").fetchone()[0] == 1000
