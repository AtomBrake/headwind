"""The segment race (services/segment_race.py, the 'segments' metric of services/challenges.py): started on one instance on its own or a friend's
segments, carried to friends in the 'challenge' line with the segments' shapes, each shape matched to a segment there (or added for the race),
and the standings worked out on each instance from the efforts it has. Two or three linked throwaway instances, the feed between them in memory."""
import io
import json
from datetime import date
from math import cos, radians

import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

import database
from routes import friends
from services import challenges, feed_tokens, privacy_zones, segment_race, segments
from services import streams as _streams

LAT0, LNG0 = 51.5, -0.12
M_LAT = 1 / 111_320.0
M_LNG = 1 / (111_320.0 * cos(radians(LAT0)))
TODAY = date(2026, 10, 20)


def at(x, y):
    """x metres east and y metres north of (LAT0, LNG0)."""
    return [LAT0 + y * M_LAT, LNG0 + x * M_LNG]


def walk(legs):
    """latlng / time / distance streams along [(x, y, speed), ...]: from each point to the next at that leg's speed (m/s), a fix a second."""
    pts, ts, ds, t, d = [], [], [], 0, 0.0
    for (x0, y0, v), (x1, y1, _) in zip(legs, legs[1:]):
        seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        n = max(1, int(seg / v))
        for i in range(n):
            f = i / n
            pts.append(at(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
            ts.append(t)
            ds.append(round(d + seg * f, 1))
            t += 1
        d += seg
    pts.append(at(legs[-1][0], legs[-1][1]))
    ts.append(t)
    ds.append(round(d, 1))
    return {'latlng': {'data': pts}, 'time': {'data': ts}, 'distance': {'data': ds}}


def up(speed=6.0, x=0):
    """Along the hill: from 0 to 1600 m north, at x metres east."""
    return walk([(x, 0, speed), (x, 1600, speed)])


def two_laps(first, second):
    """Up the hill, round by a road 300 m east and back down to the bottom, and up again."""
    return walk([(0, 0, first), (0, 1600, 8), (300, 1600, 8), (300, 0, 8), (0, 0, second), (0, 1600, second)])


def line_shape(x=0, bulge=0):
    """The hill's shape, 200 m to 1400 m north, every 50 m; bulge: the middle 400-1200 m runs that far east instead (a sibling)."""
    return [at(x + (bulge if 450 <= y <= 1150 else 0), y) for y in range(200, 1401, 50)]


def add_segment(db, name='Hill', family='ride', bulge=0, x=0):
    shape = line_shape(x, bulge)
    length = sum(segments._haversine(a[0], a[1], b[0], b[1]) for a, b in zip(shape, shape[1:]))
    sid = db.execute('INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, polyline, sport) '
                     'VALUES (?,?,?,?,?,?,40,?,?)', [name, *at(x, 200), *at(x, 1400), length, json.dumps(shape), family]).lastrowid
    segments.scan_all_activities(db, [sid])
    db.commit()
    return sid


def add_ride(db, aid, day, streams, sport='Ride', rider=1):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId) "
               "VALUES (?,?,?,?,?,?,1600,300,300,'{}',?)", [aid, aid, sport, sport, f'{day}T08:00:00', f'{day}T08:00:00', rider])
    _streams.save(db, aid, json.dumps(streams))
    segments.scan_new_ride(db, aid)
    db.commit()


# ── Linked instances ─────────────────────────────────────────────

def make_app(path, rider):
    app = Flask(__name__)
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    app.register_blueprint(friends.bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, ?, 1)", [rider])
        d.commit()
    return app


def link(a, b, a_name, b_name, fid):
    """b follows a: a gives b a feed token, and b adds a as friend fid."""
    tok = f'{a_name}-for-{b_name}'.lower()

    def give(d):
        t = d.execute('INSERT INTO FeedToken (name, tokenHash) VALUES (?, ?)', [b_name, feed_tokens._hash(tok)]).lastrowid
        d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (?, 1)', [t])
    on(a, give)
    on(b, lambda d: d.execute('INSERT INTO Friend (id, name, url, token) VALUES (?, ?, ?, ?)', [fid, a_name, f'https://{a_name.lower()}.example', tok]))


@pytest.fixture
def trio(tmp_path, monkeypatch):
    """Tom, Alex and Sam, each following the other two: on each instance the friends are ids 1 and 2, in the order Tom, Alex, Sam less
    themselves."""
    apps = {n: make_app(tmp_path / f'{n}.db', n) for n in ('Tom', 'Alex', 'Sam')}
    for me in apps:
        others = [n for n in apps if n != me]
        for fid, other in enumerate(others, 1):
            link(apps[other], apps[me], other, me, fid)
    clients = {f'{n.lower()}.example': a.test_client() for n, a in apps.items()}

    def peer(url, headers, timeout):
        host, path = url.split('://', 1)[1].split('/', 1)
        resp = clients[host].get('/' + path, headers=headers)
        assert resp.status_code == 200
        return io.BytesIO(resp.data)
    monkeypatch.setattr(friends, 'open_peer', peer)
    return apps


@pytest.fixture
def pair(trio):
    return trio['Tom'], trio['Alex']


def on(app, fn):
    with app.app_context():
        d = database.get_db()
        out = fn(d)
        d.commit()
        return out


def fid(app, name):
    return on(app, lambda d: d.execute('SELECT id FROM Friend WHERE name=?', [name]).fetchone()[0])


def sync(app, name):
    """app's instance syncs from friend `name`."""
    return on(app, lambda d: friends._do_ride_sync(fid(app, name)))


def start(app, seg_ids, seg_class='bike', tokens=None, **form):
    fields = {'metric': 'segments', 'segClass': seg_class, 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'name': 'October hills', **form}

    def go(d):
        ids = [t['id'] for t in challenges.invitable(d)] if tokens is None else tokens
        return challenges.start_challenge(d, 1, MultiDict(list(fields.items()) + [('tokens', str(i)) for i in ids]
                                                          + [('segments', str(s)) for s in seg_ids]))
    return on(app, go)


def race(app, today=TODAY):
    """The first race's boards here: ({position: [(rider, secs)]}, [(rider, points)])."""
    def go(d):
        c = next(c for c in challenges.challenges(d, 1, today=today) if c['metric'] == 'segments')
        return ({s['position']: [(r['name'], r['secs']) for r in s['board']] for s in c['race']['segments']},
                [(o['name'], o['points']) for o in c['race']['overall']])
    return on(app, go)


def rows(app, sql, args=()):
    return on(app, lambda d: [tuple(r) for r in d.execute(sql, args).fetchall()])


def cid(app):
    return on(app, lambda d: d.execute("SELECT id FROM Challenge WHERE metric='segments'").fetchone()[0])


def join(app):
    on(app, lambda d: challenges.set_joined(d, cid(app), True))


def secs(app, aid):
    """The fastest exact effort of an activity on any segment here."""
    return on(app, lambda d: d.execute('SELECT MIN(elapsedSecs) FROM SegmentEffort WHERE activityId=? AND approx=0', [aid]).fetchone()[0])


# ── Across instances ──────────────────────────────────────────────

def test_a_friends_effort_shows_once_their_activity_syncs(pair):
    tom, alex = pair
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 't1', '2026-10-05', up(6)))
    assert start(tom, [hill]) is None
    sync(alex, 'Tom')                                             # the invitation, and Tom's segment as a segment line
    assert rows(alex, 'SELECT friendId, challengeOnly FROM Segment') == [(1, 0)]
    join(alex)
    on(alex, lambda d: add_ride(d, 'a1', '2026-10-06', up(8)))
    t1, a1 = secs(tom, 't1'), secs(alex, 'a1')
    assert a1 < t1
    assert race(alex) == ({1: [('Alex', a1), ('Tom', t1)]}, [('Alex', 10), ('Tom', 8)])
    assert race(tom) == ({1: [('Tom', t1)]}, [('Tom', 10)])         # Alex's ride isn't here yet
    sync(tom, 'Alex')
    assert race(tom) == ({1: [('Alex', a1), ('Tom', t1)]}, [('Alex', 10), ('Tom', 8)])


def test_an_effort_outside_the_dates_doesnt_count(pair):
    tom, _ = pair
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 'before', '2026-09-30', up(9)))
    on(tom, lambda d: add_ride(d, 'after', '2026-11-01', up(9)))
    on(tom, lambda d: add_ride(d, 'in', '2026-10-31', up(5)))
    start(tom, [hill])
    assert race(tom, today=date(2026, 11, 5)) == ({1: [('Tom', secs(tom, 'in'))]}, [('Tom', 10)])
    assert race(tom, today=date(2026, 10, 30)) == ({1: []}, [('Tom', 0)])      # the last day hasn't come yet


def test_two_laps_in_one_ride_count_the_faster(pair):
    tom, _ = pair
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 'laps', '2026-10-05', two_laps(5, 8)))
    times = on(tom, lambda d: sorted(r[0] for r in d.execute('SELECT elapsedSecs FROM SegmentEffort')))
    assert len(times) == 2
    start(tom, [hill])
    assert race(tom) == ({1: [('Tom', times[0])]}, [('Tom', 10)])


def test_a_friend_without_the_segment_gets_it_from_the_challenge_and_is_matched(pair):
    tom, alex = pair
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareSegments=0'))     # Tom's segments don't go to Alex as segment lines
    hill = on(tom, add_segment)
    on(alex, lambda d: add_ride(d, 'a1', '2026-10-06', up(7)))                  # before the race came: no segment here to match
    on(tom, lambda d: add_ride(d, 't1', '2026-10-05', up(6)))
    start(tom, [hill])
    sync(alex, 'Tom')
    seg = on(alex, lambda d: dict(d.execute('SELECT * FROM Segment').fetchone()))
    assert (seg['friendId'], seg['challengeOnly'], seg['matchPending'], seg['sourceSegId']) == (1, 1, 0, hill)
    join(alex)
    assert race(alex)[0] == {1: [('Alex', secs(alex, 'a1')), ('Tom', secs(alex, 'f1_t1'))]}

    # Not sent on, not on the Segments page's list, and Tom sending it as a segment line later takes it over
    lines = [json.loads(x) for x in
             alex.test_client().get('/api/feed?manifest=1', headers={'X-Feed-Token': 'alex-for-sam'}).get_data(as_text=True).splitlines()]
    assert [x for x in lines if x['type'] == 'segment'] == []
    race_line = next(x for x in lines if x['type'] == 'challenge')
    assert race_line['segClass'] == 'bike' and [s['name'] for s in race_line['segments']] == ['Hill'] and 'id' not in race_line['segments'][0]
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareSegments=1'))
    sync(alex, 'Tom')
    assert rows(alex, 'SELECT id, friendId, challengeOnly FROM Segment') == [(seg['id'], 1, 0)]
    assert race(alex)[0] == {1: [('Alex', secs(alex, 'a1')), ('Tom', secs(alex, 'f1_t1'))]}


def test_a_challenge_only_segment_goes_with_its_race(pair):
    tom, alex = pair
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareSegments=0'))
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 't1', '2026-10-05', up(6)))
    start(tom, [hill])
    sync(alex, 'Tom')
    assert on(alex, lambda d: d.execute('SELECT COUNT(*) FROM SegmentEffort').fetchone()[0]) == 1
    on(tom, lambda d: challenges.delete_challenge(d, cid(tom)))
    sync(alex, 'Tom')                                            # the invitation goes, and the segment it brought
    assert on(alex, lambda d: (d.execute('SELECT COUNT(*) FROM Segment').fetchone()[0], d.execute('SELECT COUNT(*) FROM SegmentEffort').fetchone()[0],
                               d.execute('SELECT COUNT(*) FROM ChallengeSegment').fetchone()[0])) == (0, 0, 0)


def test_turning_a_race_down_drops_its_segments_and_joining_brings_them_back(pair):
    tom, alex = pair
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareSegments=0'))
    hill = on(tom, add_segment)
    start(tom, [hill])
    sync(alex, 'Tom')
    on(alex, lambda d: challenges.set_joined(d, cid(alex), False))
    assert on(alex, lambda d: d.execute('SELECT COUNT(*) FROM Segment').fetchone()[0]) == 0
    join(alex)
    assert rows(alex, 'SELECT challengeOnly FROM Segment') == [(1,)]


def test_leaving_takes_the_rider_off_the_board(pair):
    tom, alex = pair
    hill = on(tom, add_segment)
    start(tom, [hill])
    sync(alex, 'Tom')
    join(alex)
    on(alex, lambda d: add_ride(d, 'a1', '2026-10-06', up(8)))
    sync(tom, 'Alex')
    assert [r[0] for r in race(tom)[0][1]] == ['Alex']
    on(alex, lambda d: challenges.set_joined(d, cid(alex), False))
    sync(tom, 'Alex')
    assert race(tom) == ({1: []}, [('Tom', 0)])


def test_an_ebike_ride_doesnt_count_in_a_pedal_race(pair):
    tom, alex = pair
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 'pedal', '2026-10-05', up(6)))
    on(tom, lambda d: add_ride(d, 'zoom', '2026-10-06', up(9), sport='EBikeRide'))
    start(tom, [hill])
    assert race(tom)[0] == {1: [('Tom', secs(tom, 'pedal'))]}
    start(tom, [hill], seg_class='ebike', name='Battery hills')
    on(tom, lambda d: d.execute("DELETE FROM Challenge WHERE segClass='bike'"))
    assert race(tom)[0] == {1: [('Tom', secs(tom, 'zoom'))]}


def test_a_race_on_foot(pair):
    tom, alex = pair
    path = on(tom, lambda d: add_segment(d, 'Riverside', family='foot'))
    on(tom, lambda d: add_ride(d, 'run', '2026-10-05', up(3.5), sport='Run'))
    on(tom, lambda d: add_ride(d, 'ride', '2026-10-05', up(6)))                  # a ride along it: not a foot effort
    assert start(tom, [path], seg_class='bike') == 'A race on a bike needs ride segments.'
    assert start(tom, [path], seg_class='foot') is None
    sync(alex, 'Tom')
    join(alex)
    on(alex, lambda d: add_ride(d, 'walk', '2026-10-07', up(1.5), sport='Walk'))
    assert race(alex)[0] == {1: [('Tom', secs(alex, 'f1_run')), ('Alex', secs(alex, 'walk'))]}
    c = on(alex, lambda d: challenges.challenges(d, 1, today=TODAY)[0])
    assert c['icon'] == '🏃' and c['title'] == 'Fastest on 1 segment (on foot)' and c['sport'] == 'foot'


def test_in_a_race_of_three_the_third_gets_the_segments_from_a_joiners_line(trio):
    """Sam has the race from Tom; Sam then removes Tom, and the segment Tom's line brought goes with him. Alex's line still has the race and its
    segment's shape: Sam finds it again from that, as Alex's."""
    tom, alex, sam = trio['Tom'], trio['Alex'], trio['Sam']
    for app in trio.values():
        on(app, lambda d: d.execute('UPDATE FeedToken SET shareSegments=0'))
    hill = on(tom, add_segment)
    start(tom, [hill])
    for app in (alex, sam):
        sync(app, 'Tom')
        join(app)
    on(alex, lambda d: add_ride(d, 'a1', '2026-10-06', up(8)))
    sync(sam, 'Alex')
    assert [r[0] for r in race(sam)[0][1]] == ['Alex']
    sam_client = sam.test_client()
    assert sam_client.post(f'/friends/{fid(sam, "Tom")}/delete').status_code == 302
    seg = rows(sam, 'SELECT friendId, challengeOnly FROM Segment')
    assert seg == [(None, 1)]                                     # the race kept the shape: no friend to have it from yet
    assert race(sam)[0] == {1: []}                                # Alex's efforts were on the segment that went
    sync(sam, 'Alex')
    assert rows(sam, 'SELECT friendId, challengeOnly FROM Segment') == [(fid(sam, 'Alex'), 1)]
    assert [r[0] for r in race(sam)[0][1]] == ['Alex']


def test_a_third_rider_joining_late_gets_the_race_from_the_starter_and_sees_the_joiner(trio):
    tom, alex, sam = trio['Tom'], trio['Alex'], trio['Sam']
    hill = on(tom, add_segment)
    start(tom, [hill])
    sync(alex, 'Tom')
    join(alex)
    on(alex, lambda d: add_ride(d, 'a1', '2026-10-06', up(8)))
    sync(sam, 'Alex')                                             # Alex's line alone is no invitation
    assert on(sam, lambda d: d.execute('SELECT COUNT(*) FROM Challenge').fetchone()[0]) == 0
    sync(sam, 'Tom')
    sync(sam, 'Alex')
    join(sam)
    assert [r[0] for r in race(sam)[0][1]] == ['Alex']


def test_an_older_style_line_still_works(pair):
    """A total challenge from a friend whose line has no segClass or segments, as every line before the race had, is as it was; a race line
    with no segments, or segments of the wrong family, is ignored."""
    _, alex = pair
    old = {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'own': True,
           'name': 'Climbing', 'creator': 'Tom'}
    assert on(alex, lambda d: challenges.store_from_friend(d, 1, old, 1)) == 'abcdef0123'
    shape = {'name': 'Hill', 'startLat': at(0, 200)[0], 'startLng': at(0, 200)[1], 'endLat': at(0, 1400)[0], 'endLng': at(0, 1400)[1],
             'distanceM': 1200, 'polyline': json.dumps(line_shape()), 'family': 'ride'}
    bad = [{'segClass': 'bike'}, {'segClass': 'bike', 'segments': []}, {'segClass': 'rocket', 'segments': [shape]},
           {'segClass': 'foot', 'sport': 'foot', 'segments': [shape]}, {'segClass': 'bike', 'segments': [shape] * 6},
           {'segClass': 'bike', 'segments': [{**shape, 'startLat': 123}]}]
    race_line = {**old, 'uid': 'abcdef0124', 'metric': 'segments'}
    assert on(alex, lambda d: [challenges.store_from_friend(d, 1, {**race_line, **b}, 1) for b in bad]) == [None] * len(bad)
    assert on(alex, lambda d: challenges.store_from_friend(d, 1, {**race_line, 'segClass': 'bike', 'segments': [shape]}, 1)) == 'abcdef0124'
    assert on(alex, lambda d: [r[0] for r in d.execute('SELECT metric FROM Challenge ORDER BY id')]) == ['climb', 'segments']


# ── Picking segments ──────────────────────────────────────────────

def test_a_segment_in_a_privacy_zone_cant_be_picked(pair):
    tom, _ = pair
    hill = on(tom, add_segment)
    other = on(tom, lambda d: add_segment(d, 'Far', x=5000))
    on(tom, lambda d: privacy_zones.add(d, 1, 'Home', *at(0, 150), radius=200))
    assert [s['name'] for s in on(tom, lambda d: segment_race.pickable(d, 1))] == ['Far']
    assert 'privacy zones' in start(tom, [other, hill])
    assert start(tom, []) == 'Pick at least one segment.'
    assert start(tom, [other] * 1 + [hill + 100]) == 'One of those segments has gone. Pick again.'
    assert start(tom, [other]) is None


def test_a_sibling_isnt_mixed_up_with_it(pair):
    """Alex has a segment with the same ends as Tom's, the other way round a field 30 m east: Tom's shape isn't it."""
    tom, alex = pair
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareSegments=0'))
    hill = on(tom, add_segment)
    sibling = on(alex, lambda d: add_segment(d, 'Field edge', bulge=30))
    sent = segment_race.clean({**on(tom, lambda d: dict(d.execute('SELECT * FROM Segment').fetchone())), 'family': 'ride'})
    assert on(alex, lambda d: segment_race.find_local(d, sent)) is None
    same = on(alex, lambda d: add_segment(d, 'Hill too'))                     # the same line drawn again here: that one is it
    assert on(alex, lambda d: segment_race.find_local(d, sent)) == same
    on(alex, lambda d: d.execute('DELETE FROM Segment WHERE id=?', [same]))
    start(tom, [hill])
    sync(alex, 'Tom')
    assert on(alex, lambda d: d.execute('SELECT COUNT(*) FROM Segment WHERE challengeOnly=1').fetchone()[0]) == 1
    assert on(alex, lambda d: d.execute('SELECT segmentId FROM ChallengeSegment').fetchone()[0]) != sibling


def test_our_own_segment_is_preferred_to_a_friends(pair):
    tom, alex = pair
    hill = on(tom, add_segment)
    start(tom, [hill])
    on(alex, lambda d: add_segment(d, 'My hill'))
    sync(alex, 'Tom')                                             # Tom's comes too, as a segment line
    mine = on(alex, lambda d: d.execute('SELECT id FROM Segment WHERE friendId IS NULL').fetchone()[0])
    assert on(alex, lambda d: d.execute('SELECT segmentId FROM ChallengeSegment').fetchone()[0]) == mine


# ── Standings ─────────────────────────────────────────────────────

def test_points_ties_and_the_overall_order(pair):
    tom, _ = pair

    def go(d):
        ids = [add_segment(d, f'S{i}', x=i * 3000) for i in range(3)]
        for r, name in ((2, 'Alex'), (3, 'Sam')):
            d.execute('INSERT INTO Rider (id, name, isDefault) VALUES (?, ?, 0)', [r, name])
        c = {'id': 99, 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'segClass': 'bike'}
        for pos, sid in enumerate(ids, 1):
            d.execute('INSERT INTO ChallengeSegment (challengeId, position, segmentId, name, startLat, startLng, endLat, endLng, family) '
                      "VALUES (99, ?, ?, 'S', 0, 0, 0, 0, 'ride')", [pos, sid])

        def effort(sid, rider, day, secs, n):
            d.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, riderId, rawData) VALUES (?, ?, 'Ride', ?, ?, '{}')",
                      [f'e{n}', f'e{n}', f'{day}T08:00:00', rider])
            d.execute('INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, startSecs) VALUES (?,?,?,?,0)',
                      [sid, f'e{n}', day, secs])
        effort(ids[0], 1, '2026-10-02', 100, 1)
        effort(ids[0], 2, '2026-10-03', 100, 2)            # the same time, a day later: second
        effort(ids[1], 2, '2026-10-04', 90, 3)
        effort(ids[1], 1, '2026-10-04', 95, 4)
        effort(ids[2], 3, '2026-10-05', 50, 5)
        effort(ids[2], 1, '2026-10-05', 60, 6)
        effort(ids[2], 2, '2026-10-05', 70, 7)
        d.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, approx, startSecs) "
                  "VALUES (?, 'e6', '2026-10-05', 10, 1, 5)", [ids[2]])                 # a close match never counts
        people = [(1, 'Tom', None, True), (2, 'Alex', None, False), (3, 'Sam', None, False)]
        return segment_race.boards(d, c, people, TODAY)
    b = on(tom, go)
    assert [[r['name'] for r in s['board']] for s in b['segments']] == [['Tom', 'Alex'], ['Alex', 'Tom'], ['Sam', 'Tom', 'Alex']]
    # Tom 10+8+8 = 26, Alex 8+10+6 = 24, Sam 10
    assert [(o['name'], o['points'], o['wins']) for o in b['overall']] == [('Tom', 26, 1), ('Alex', 24, 1), ('Sam', 10, 1)]


def test_a_tie_on_points_goes_to_more_wins_then_less_time():
    rows = [{'name': 'A', 'points': 18, 'wins': 1, 'secs': 300, 'done': 2}, {'name': 'B', 'points': 18, 'wins': 0, 'secs': 100, 'done': 3}]
    key = lambda o: (-o['points'], -o['wins'], o['secs'] if o['done'] else float('inf'), o['name'])
    assert [o['name'] for o in sorted(rows, key=key)] == ['A', 'B']


def test_new_marks_since_the_rider_last_looked(pair):
    tom, alex = pair
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 't1', '2026-10-05', up(6)))
    start(tom, [hill])

    def look(d):
        c = d.execute('SELECT * FROM Challenge').fetchone()
        b = segment_race.boards(d, c, challenges.people(d, c), TODAY)
        n = segment_race.mark_new(d, c['id'], 1, b)
        segment_race.seen(d, c['id'], 1, b)
        return n
    assert on(tom, look) == 0                                     # the first look: nothing is new
    assert on(tom, look) == 0
    on(tom, lambda d: add_ride(d, 't2', '2026-10-06', up(9)))
    assert on(tom, look) == 1
    on(tom, lambda d: segments.rescan_activity(d, 't2'))         # matched again: createdAt is new, the time isn't
    assert on(tom, look) == 0


def test_a_new_leader_is_notified_once(pair, monkeypatch):
    tom, alex = pair
    sent = []
    from services import notify
    monkeypatch.setattr(notify, 'send_notification', lambda title, body, url=None: sent.append(title))
    hill = on(tom, add_segment)
    on(tom, lambda d: add_ride(d, 't1', '2026-10-05', up(6)))
    start(tom, [hill], startDate='2026-10-01', endDate=date.today().isoformat())
    sync(alex, 'Tom')
    join(alex)
    on(alex, lambda d: add_ride(d, 'a1', date.today().isoformat(), up(9)))
    sync(tom, 'Alex')
    assert sent == ['October hills: Alex took Hill']
    sync(tom, 'Alex')
    assert sent == ['October hills: Alex took Hill']
    on(tom, lambda d: (add_ride(d, 't2', date.today().isoformat(), up(12)),))
    from services import ingest
    on(tom, lambda d: ingest.after_ride_added(d, 't2'))
    assert sent[-1] == 'October hills: you took Hill' and len(sent) == 2


# ── Removing a friend ─────────────────────────────────────────────

def test_removing_a_friend_removes_the_efforts_on_their_segments(pair):
    """There's no ON DELETE CASCADE here (SQLite's foreign keys are off): the efforts on a removed friend's segments are deleted with them."""
    tom, alex = pair
    on(tom, add_segment)
    on(alex, lambda d: add_ride(d, 'a1', '2026-10-06', up(8)))
    sync(alex, 'Tom')
    assert on(alex, lambda d: d.execute('SELECT COUNT(*) FROM SegmentEffort').fetchone()[0]) == 1
    assert alex.test_client().post(f'/friends/{fid(alex, "Tom")}/delete').status_code == 302
    assert on(alex, lambda d: (d.execute('SELECT COUNT(*) FROM Segment').fetchone()[0], d.execute('SELECT COUNT(*) FROM SegmentEffort').fetchone()[0])) == (0, 0)


# ── The pages ─────────────────────────────────────────────────────

from tests.test_goals import client      # noqa: E402,F401  (fixture: the whole app, signed in, rider Tom)


def in_app(client, fn):
    with client.application.app_context():
        d = database.get_db()
        out = fn(d)
        d.commit()
        return out


def test_racing_a_segment_from_its_page(client):
    today = date.today().isoformat()
    hill = in_app(client, add_segment)
    in_app(client, lambda d: add_ride(d, 'r1', today, up(6)))
    page = client.get(f'/segments/{hill}').get_data(as_text=True)
    assert f'href="/challenges?segment={hill}#startChallenge"' in page and 'Race this segment' in page
    form = client.get(f'/challenges?segment={hill}').get_data(as_text=True)
    assert 'race-form' in form and f'name="segments" value="{hill}" data-change="racePick(this)" checked' in form
    assert '<option value="segments" selected>' in form

    r = client.post('/challenges', data={'metric': 'segments', 'segClass': 'bike', 'sport': 'all', 'segments': [str(hill)],
                                         'startDate': today, 'endDate': today})
    assert r.status_code == 302 and 'error' not in r.headers['Location']
    cards = client.get('/challenges').get_data(as_text=True)
    cid = in_app(client, lambda d: d.execute('SELECT id FROM Challenge').fetchone()[0])
    assert 'Race: Hill' in cards and 'Fastest on 1 segment (bike)' in cards and f'href="/challenges/{cid}"' in cards and '10 pts · 1 won' in cards

    page = client.get(f'/challenges/{cid}').get_data(as_text=True)
    assert 'id="raceMap"' in page and 'id="raceData"' in page and '/static/js/challenge_race.js' in page
    assert '>Hill</a>' in page and 'href="/activities/r1"' in page and 'since you last looked' not in page and '>New<' not in page
    in_app(client, lambda d: add_ride(d, 'r2', today, up(9)))
    page = client.get(f'/challenges/{cid}').get_data(as_text=True)
    assert '1 new since you last looked' in page and '>New<' in page and 'href="/activities/r2"' in page
    assert '>New<' not in client.get(f'/challenges/{cid}').get_data(as_text=True)

    assert f'the race <a href="/challenges/{cid}">Race: Hill</a>' in client.get(f'/segments/{hill}').get_data(as_text=True)
    assert client.get('/challenges/999').status_code == 404


def test_a_race_only_segment_isnt_on_the_segments_page(client):
    hill = in_app(client, add_segment)
    in_app(client, lambda d: d.execute("UPDATE Segment SET challengeOnly=1, name='Their hill' WHERE id=?", [hill]))
    assert 'Their hill' not in client.get('/segments').get_data(as_text=True)
    page = client.get(f'/segments/{hill}').get_data(as_text=True)
    assert 'Race this segment' not in page and 'Delete this segment' not in page


def test_a_bad_race_form_says_why(client):
    r = client.post('/challenges', data={'metric': 'segments', 'segClass': 'bike', 'startDate': '2026-10-01', 'endDate': '2026-10-31'},
                    follow_redirects=True)
    assert 'Pick at least one segment.' in r.get_data(as_text=True)
    hill = in_app(client, add_segment)
    in_app(client, lambda d: privacy_zones.add(d, 1, 'Home', *at(0, 1400), radius=200))
    r = client.post('/challenges', data={'metric': 'segments', 'segClass': 'bike', 'segments': [str(hill)], 'startDate': '2026-10-01',
                                         'endDate': '2026-10-31'}, follow_redirects=True)
    assert 'privacy zones' in r.get_data(as_text=True)
    assert 'can’t be raced' in client.get(f'/challenges?segment={hill}').get_data(as_text=True)
