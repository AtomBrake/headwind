"""The demo's builder (demo/): patterns hold only numbers, generated tracks read back as real recordings, lake routes stay on the water, and the
audit refuses a demo that holds a name, id, secret or place of the real database. No routing engine and no network: throwaway files only."""
import json
import os
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, 'demo')
sys.path.insert(0, DEMO)

import audit_demo_db  # noqa: E402
import extract_patterns  # noqa: E402
import generate_demo_db as gen  # noqa: E402


def _db(path, riders=('Alex',)):
    from flask import Flask
    import database
    app = Flask('t')
    app.config['DATABASE'] = str(path)
    with app.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        for i, name in enumerate(riders):
            db.execute('INSERT INTO Rider (name, isDefault) VALUES (?, ?)', [name, 1 if i == 0 else 0])
        db.commit()
        database.close_db()
    return str(path)


def _add(path, act_id, name, lat, lng, sport='Ride', rider=1, n=120, when='2025-06-01T09:00:00'):
    """An activity with a little track heading north-east from (lat, lng), one point a second."""
    from services import streams
    c = sqlite3.connect(path)
    streams.register(c)
    c.execute('INSERT INTO Activity (id, riderId, name, sportType, type, startDate, startDateLocal, distance, movingTime, elapsedTime, startLat, startLng, '
              'averageHeartrate, rawData) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              [act_id, rider, name, sport, sport, when, when, n * 6.0, n, n, lat, lng, 130, '{}'])
    ll = [[lat + i * 0.00004, lng + i * 0.00004] for i in range(n)]
    st = {'latlng': {'data': ll}, 'time': {'data': list(range(n))}, 'distance': {'data': [i * 6.0 for i in range(n)]},
          'altitude': {'data': [100 + i * 0.3 for i in range(n)]}, 'heartrate': {'data': [120 + i % 20 for i in range(n)]}}
    streams.save(c, act_id, st)
    c.commit()
    c.close()


# ---------------------------------------------------------------- patterns
def test_patterns_refuse_anything_but_numbers():
    extract_patterns.check({'sports': {'Ride': {'distance_km_q': [1.0, 2.5], 'by_grade': {'-4': {'speed': 5.1, 'n': 3}}, 'count_by_year': {'2024': 3}}}})
    for bad in ({'sports': {'Ride': {'note': 'Morning loop with Jo'}}}, {'sports': {'Ride': {'start': [53.3, -1.8], 'where': 'Edale'}}},
                {'sports': {'My Secret Sport': {}}}):
        with pytest.raises(SystemExit):
            extract_patterns.check(bad)


def test_patterns_hold_no_name_date_or_position(tmp_path):
    src = _db(tmp_path / 'real.db', riders=('Jordan Example',))
    for i in range(6):
        _add(src, f'9876543{i}', f'Ride to Grandma Example {i}', 51.123456, -2.654321, when=f'2025-06-0{i + 1}T07:30:00')
    out = tmp_path / 'patterns.json'
    subprocess.run([sys.executable, os.path.join(DEMO, 'extract_patterns.py'), '--source', src, '--out', str(out)], check=True, capture_output=True,
                   encoding='utf-8')
    text = out.read_text(encoding='utf-8')
    for leak in ('Jordan', 'Grandma', '9876543', '51.12', '2.65', '2025-06'):
        assert leak not in text, leak
    p = json.loads(text)['sports']['Ride']
    assert p['count_by_year'] == {'2025': 6} and p['weekday_weights'] and p['by_grade']


# ---------------------------------------------------------------- tracks
def _route(n=400, climb=True):
    """A straight route north, 10 m between points, with a 6% climb in its second half."""
    return [(53.30 + i * 10 / 111320, -1.80, 200 + (max(0, i - n // 2) * 0.6 if climb else 0)) for i in range(n)]


def _model(kind, speed=6.0, hr=130):
    sp = {'by_grade': {str(g): {'speed': speed * (1 - g / 15), 'hr': hr + g * 2, 'cadence': 80, 'watts': None, 'n': 50} for g in range(-10, 11, 2)},
          'avg_hr_q': [hr] * 19, 'day_speed_ratio_q': [1.0] * 19, 'day_hr_offset_q': [0.0] * 19, 'elapsed_over_moving_q': [1.05] * 19}
    return gen.Model(sp, gen.KINDS[kind])


def test_a_generated_ride_reads_back_as_a_recording():
    from services.parser import parse_gpx
    rng = random.Random(1)
    pts = gen.synth(_route(), 'road', _model('road'), datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc), rng, dict(kg=64, rest=52, max=186, form=1.0))
    times = [p[0] for p in pts]
    assert times == sorted(times) and (times[-1] - times[0]).total_seconds() > 300
    assert all(52 <= p[4] <= 186 for p in pts if p[4] is not None)
    act = parse_gpx(gen.gpx(pts, 'Test loop', 'Ride'))
    st = json.loads(act['streams'])
    assert act['sportType'] == 'Ride' and act['name'] == 'Test loop'
    assert 3800 < act['distance'] < 4200                              # the route's 4 km, give or take the GPS wobble
    assert st.get('heartrate') and st.get('cadence') and st.get('watts')
    assert max(st['watts']['data']) > 0


def test_running_has_no_power_and_paddling_no_climb():
    rng = random.Random(2)
    run = gen.synth(_route(200), 'run', _model('run', 3.0, 150), datetime(2026, 5, 2, 8, tzinfo=timezone.utc), rng, dict(kg=64, rest=52, max=186, form=1.0))
    assert all(p[6] is None for p in run)
    flat = [(54.6 + i * 25 / 111320, -3.14, 0.0) for i in range(80)]
    sup = gen.synth(flat, 'sup', gen.Model({}, gen.KINDS['sup']), datetime(2026, 7, 2, 10, tzinfo=timezone.utc), rng, dict(kg=64, rest=52, max=186, form=1.0))
    assert len({round(p[3]) for p in sup}) <= 8                     # a lake is flat: only the barometer's small offset
    secs = (sup[-1][0] - sup[0][0]).total_seconds()
    assert 1.0 < 2000 / secs < 2.2                                   # paddling pace, stops included


def test_a_lake_route_stays_on_the_water():
    ring = [(54.60, -3.20), (54.60, -3.10), (54.55, -3.10), (54.55, -3.20), (54.60, -3.20)]
    island = [(54.58, -3.16), (54.58, -3.14), (54.57, -3.14), (54.57, -3.16), (54.58, -3.16)]
    rings = [ring, island]
    r = gen.lake_route(rings, ('Launch', 54.555, -3.15), 6, random.Random(3))
    assert r
    water = r[1:-1]
    assert all(gen.inside(p, rings) for p in water)
    assert not gen.inside((54.575, -3.15), rings)                    # the island is land
    assert 4000 < gen.cumulative(r)[-1] < 8500


def test_rings_are_joined_from_split_ways():
    a, b, c = (0.0, 0.0), (0.0, 1.0), (1.0, 1.0)
    rings = gen.join_rings([[a, b], [c, b], [c, (1.0, 0.0), a]])
    assert len(rings) == 1 and rings[0][0] == rings[0][-1] and len(rings[0]) == 5


def test_the_biggest_climb_is_found():
    got = gen.best_climb(_route(600))
    assert got
    i0, i1, gain = got
    assert 150 <= gain <= 190 and i1 > i0 >= 250


# ---------------------------------------------------------------- the audit
def _audit(src, demo, *extra):
    return subprocess.run([sys.executable, os.path.join(DEMO, 'audit_demo_db.py'), '--source', src, '--demo', demo, *extra], capture_output=True,
                          encoding='utf-8')


@pytest.fixture
def real(tmp_path):
    src = _db(tmp_path / 'real.db', riders=('Jordan Example',))
    for i in range(6):                                               # a frequent start
        _add(src, f'1122334{i}', f'Ride to the Grandmother Inn {i}', 52.500000, -1.000000, when=f'2025-06-0{i + 1}T07:30:00')
    c = sqlite3.connect(src)
    c.execute("UPDATE Settings SET haUrl='http://ha.internal.example:8123', mqttHost='broker.internal.example' WHERE id=1")
    c.commit()
    c.close()
    return src


def test_the_audit_passes_a_clean_demo(tmp_path, real):
    demo = _db(tmp_path / 'demo.db')
    _add(demo, 'imp_a1', 'Morning Ride', 53.3647, -1.8167)
    r = _audit(real, demo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'audit passed' in r.stdout


@pytest.mark.parametrize('leak', ['name', 'rider', 'id', 'secret', 'place'])
def test_the_audit_refuses_a_leak(tmp_path, real, leak):
    demo = _db(tmp_path / 'demo.db')
    name = {'name': 'Ride to the Grandmother Inn 3', 'rider': 'Lunch with Jordan'}.get(leak, 'Morning Ride')
    act_id = '11223342' if leak == 'id' else 'imp_a1'
    lat, lng = (52.5005, -1.0005) if leak == 'place' else (53.3647, -1.8167)
    _add(demo, act_id, name, lat, lng)
    if leak == 'secret':
        c = sqlite3.connect(demo)
        c.execute("UPDATE Activity SET notes='see broker.internal.example' WHERE id='imp_a1'")
        c.commit()
        c.close()
    r = _audit(real, demo)
    assert r.returncode == 2, r.stdout
    assert 'AUDIT FAILED' in r.stdout
    assert '52.5' not in r.stdout and '-1.0' not in r.stdout          # never says where


def test_the_audit_lets_a_named_public_place_through(tmp_path, real):
    demo = _db(tmp_path / 'demo.db')
    from demo_areas import AREAS
    name, lat, lng, _ = AREAS['peak']['starts'][0]
    src = _db(tmp_path / 'real2.db', riders=('Jordan Example',))
    for i in range(6):
        _add(src, f'5566778{i}', 'Morning Ride', lat + 0.001, lng + 0.001, when=f'2025-06-0{i + 1}T07:30:00')
    _add(demo, 'imp_a1', 'Morning Ride', lat, lng)
    assert _audit(src, demo).returncode == 2
    assert _audit(src, demo, '--allow-near', name).returncode == 0


# ---------------------------------------------------------------- the map summaries
def test_the_builder_saves_every_activitys_map_summary(tmp_path):
    """pristine.db carries them, so even a Headwind whose reset doesn't make them (0.7.64) has the heatmap ready after a reset."""
    from datetime import date
    from flask import Flask
    import database
    from services import tracks
    path = _db(tmp_path / 'demo.db')
    _add(path, 'imp_a1', 'Morning Ride', 53.3647, -1.8167)
    _add(path, 'imp_a2', 'Evening Run', 53.3700, -1.8000, sport='Run')
    app = Flask('t')
    app.config['DATABASE'] = path
    with app.app_context():
        try:
            gen.finish(database.get_db(), built_on=date(2026, 11, 1))
        finally:
            database.close_db()
    c = sqlite3.connect(path)
    rows = c.execute('SELECT activityId, version, line, lineHd, cells FROM ActivityTrack ORDER BY activityId').fetchall()
    assert [r[0] for r in rows] == ['imp_a1', 'imp_a2']
    assert all(r[1] == tracks.VERSION and r[2] and r[3] and r[4] for r in rows)
    assert c.execute("SELECT value FROM DemoMeta WHERE key='built_on'").fetchone()[0] == '2026-11-01'
    c.close()


@pytest.mark.parametrize('where', ['line', 'lineHd', 'cells'])
def test_the_audit_checks_the_map_summaries_too(tmp_path, real, where):
    """The heatmap draws ActivityTrack, not the streams: a summary near a real place fails the audit even when the streams are clean."""
    demo = _db(tmp_path / 'demo.db')
    _add(demo, 'imp_a1', 'Morning Ride', 53.3647, -1.8167)
    c = sqlite3.connect(demo)
    c.execute("INSERT OR REPLACE INTO ActivityTrack (activityId, line, lineHd, cells, version) VALUES ('imp_a1', ?, ?, ?, 2)", [
        '[[52.5005,-1.0005],[52.501,-1.001]]' if where == 'line' else '[[53.3647,-1.8167],[53.37,-1.81]]',
        '[[52.5005,-1.0005],[52.501,-1.001]]' if where == 'lineHd' else '[[53.3647,-1.8167],[53.37,-1.81]]',
        '10500:-201' if where == 'cells' else '10672:-364'])
    c.commit()
    c.close()
    r = _audit(real, demo)
    assert r.returncode == 2, r.stdout
    assert 'AUDIT FAILED' in r.stdout and '52.5' not in r.stdout


def test_the_audit_passes_a_clean_demos_map_summaries(tmp_path, real):
    from services import streams, tracks
    demo = _db(tmp_path / 'demo.db')
    _add(demo, 'imp_a1', 'Morning Ride', 53.3647, -1.8167)
    c = sqlite3.connect(demo)
    streams.register(c)
    assert tracks.fill(c) == 1
    c.close()
    r = _audit(real, demo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_demo_has_a_segment_race_on_the_segments_both_rode(tmp_path):
    """make_race: the ride segments Alex and the friend both pedalled in the past four weeks, the most ridden first; one only Alex rode, or
    only on an e-bike, isn't in it."""
    from datetime import date
    from flask import Flask
    import database
    from build_fiction import make_race
    from services import challenges
    from tests.test_segment_race import add_ride, add_segment, up
    app = Flask('t')
    app.config['DATABASE'] = str(tmp_path / 'race.db')
    with app.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1), (2, 'Sam', 0)")
        fid = db.execute("INSERT INTO Friend (name, url, riderId) VALUES ('Sam', 'https://sam.example.org', 2)").lastrowid
        hills = [add_segment(db, f'Hill {i}', x=i * 3000) for i in range(5)]
        today = date(2026, 11, 20)
        for i, x in enumerate((0, 3000, 6000)):                                       # both of them, three times each
            for r, day in ((1, '2026-11-10'), (2, '2026-11-11'), (1 if i == 0 else 2, '2026-11-13')):
                add_ride(db, f'r{i}-{r}-{day}', day, up(6 + r, x=x), rider=r)
        add_ride(db, 'solo', '2026-11-10', up(6, x=9000), rider=1)                      # Alex alone
        add_ride(db, 'zoom', '2026-11-10', up(9, x=12000), sport='EBikeRide', rider=2)   # an e-bike: not in a bike race
        add_ride(db, 'zoom2', '2026-11-11', up(6, x=12000), rider=1)
        assert make_race(db, 1, fid, today) == 3
        c = next(c for c in challenges.challenges(db, 1, today=today) if c['metric'] == 'segments')
        assert c['start'] == '2026-10-24' and c['end'] == '2026-11-30' and c['name'] == 'Hill race'
        assert [s['id'] for s in c['race']['segments']] == hills[:3]
        assert all(len(s['board']) == 2 for s in c['race']['segments'])
        assert db.execute('SELECT COUNT(*) FROM ChallengeSegment WHERE leaderRiderId IS NOT NULL').fetchone()[0] == 3
        database.close_db()
