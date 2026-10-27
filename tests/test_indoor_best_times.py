"""Indoor rides and runs (Zwift, a turbo, a treadmill: services/sports.is_virtual) keep best times of their own, never an outdoor one's: the Data
page, the profile, the run badges and the AI's "beat your previous best" each count them apart. A run on a treadmill or in Zwift is a VirtualRun
whichever way it arrives (Garmin, a FIT or GPX file, a start in one of Zwift's made-up worlds), with no segments; and one saved as an outdoor run
before is put right at start-up (services/sport_fix.fix_misfiled). Full app, throwaway DB."""
import json
import re
from datetime import datetime, timezone

import pytest

import app as app_module
import config
import database
from services import credentials, sport_records, sports, zwift


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def track(secs, speed):
    """A steady effort, one point a second: distance and time streams."""
    return json.dumps({'time': {'data': list(range(secs + 1))}, 'distance': {'data': [i * speed for i in range(secs + 1)]}})


ACTS = (('run_out', 'Run', 1800, 3.0),            # 5 km in 1667 s (27:47)
        ('run_zw', 'Virtual Run', 1800, 4.0),     # Strava's Zwift run: 5 km in 1250 s, quicker than any run outside
        ('tread', 'VirtualRun', 1800, 3.5),       # a treadmill run from Garmin: 5 km in 1429 s
        ('ride_out', 'Ride', 3600, 8.0),          # 5 miles in 1006 s
        ('ride_zw', 'VirtualRide', 3600, 11.0))   # 5 miles in 732 s


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET timeZone='Europe/London' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for i, (aid, sport, secs, speed) in enumerate(ACTS):
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, movingTime, totalElevationGain, streams) "
                       "VALUES (?, ?, 1, ?, ?, ?, ?, 10, ?)", [aid, aid, sport, f'2026-10-0{i + 1}T08:00:00', secs * speed, secs, track(secs, speed)])
        from services.best_efforts import save_best_efforts
        for aid in ('ride_out', 'ride_zw'):
            row = db.execute('SELECT startDateLocal, streams FROM Activity WHERE id=?', [aid]).fetchone()
            save_best_efforts(db, aid, row[0], row[1])
        sport_records.ensure(db)
        a.config['AV'] = credentials.auth_version()
    yield a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = app.config['AV']
    return c


@pytest.mark.parametrize('key, sub, sport', [
    ('virtual_run', None, 'VirtualRun'), ('treadmill_running', None, 'VirtualRun'), ('indoor_running', None, 'VirtualRun'),   # Garmin's types
    ('running', 'treadmill', 'VirtualRun'), ('running', 'virtual_activity', 'VirtualRun'), ('running', 'indoor_running', 'VirtualRun'),   # FIT's
    ('VirtualRun', None, 'VirtualRun'), ('Virtual Run', None, 'VirtualRun'),                                     # a GPX's, Strava's
    ('running', None, 'Run'), ('trail_running', 'trail', 'Run'),
    ('cycling', 'virtual_activity', 'VirtualRide'), ('indoor_rowing', None, 'Row'),
])
def test_indoor_runs_are_told_apart_on_the_way_in(key, sub, sport):
    assert sports.from_type(key, sub) == sport


def test_indoor_runs_have_no_segments_and_read_as_indoor_runs():
    assert sports.segment_family('VirtualRun') is None and sports.segment_family('Virtual Run') is None
    assert sports.segment_family('Run') == 'foot'
    assert sports.stat_group('VirtualRun') == 'foot'                    # still adds to the distance on foot
    assert sports.label('VirtualRun') == sports.label('Virtual Run') == 'Indoor run' and sports.label('Virtual Ride') == 'Indoor ride'
    assert 'VirtualRun' in sports.SPORTS


def test_run_best_times_count_outdoors_and_indoors_apart(app):
    with app.app_context():
        db = database.get_db()
        assert sport_records.bests(db, 1, 'run')[5000.0]['activityId'] == 'run_out'
        assert sport_records.bests(db, 1, 'run', indoor=True)[5000.0]['activityId'] == 'run_zw'
        assert {r['activityId'] for r in sport_records.efforts(db, 1, 'run')} == {'run_out'}
        assert {r['activityId'] for r in sport_records.efforts(db, 1, 'run', indoor=True)} == {'run_zw', 'tread'}


def _tables(html):
    return {a['key']: a for a in json.loads(re.search(r'const data = (.*);', html).group(1))}


def test_data_page_has_indoor_tables_of_their_own(client):
    html = client.get('/data').get_data(as_text=True)
    t = _tables(html)
    assert set(t) == {'ride', 'vride', 'run', 'vrun'}
    assert t['ride']['by_year']['2026']['5']['rideId'] == 'ride_out' and t['vride']['by_year']['2026']['5']['rideId'] == 'ride_zw'
    assert t['run']['by_year']['2026']['5000']['rideId'] == 'run_out' and t['vrun']['by_year']['2026']['5000']['rideId'] == 'run_zw'
    assert 'Indoor ride best times' in html and 'Indoor run best times' in html


def test_data_page_without_indoor_activities_has_no_indoor_tables(app, client):
    with app.app_context():
        db = database.get_db()
        db.execute(f"DELETE FROM Activity WHERE {sports.virtual_sql()}")
        db.commit()
    assert set(_tables(client.get('/data').get_data(as_text=True))) == {'ride', 'run'}


def test_a_rider_who_only_rides_zwift_gets_no_empty_outdoor_table(app, client):
    with app.app_context():
        db = database.get_db()
        db.execute("DELETE FROM Activity WHERE id <> 'ride_zw'")
        db.commit()
    assert set(_tables(client.get('/data').get_data(as_text=True))) == {'vride'}


def test_profile_lists_indoor_best_times_under_their_own_headings(client):
    html = client.get('/riders/1').get_data(as_text=True)
    best = html[html.index('Best Efforts'):]
    i_ride, i_run = best.index('Indoor rides'), best.index('Indoor runs')
    assert best.index('/rides/ride_out') < i_ride < best.index('/rides/ride_zw')
    assert best.index('/rides/run_out') < i_run < best.index('/rides/run_zw')


def test_run_badges_count_runs_outside_only(app):
    with app.app_context():
        from routes.riders import _compute_badges
        cats = {c['name']: {b['name']: b for b in c['badges']} for c in _compute_badges(1, {'rides': 2, 'dist': 60000, 'elev': 20})}
    run = cats['Running']
    assert run['5K Under 30']['ride_id'] == 'run_out'
    assert not run['5K Under 25']['earned']                              # the Zwift run's 20:50 doesn't earn it
    assert run['First Run']['progress'] == 3                             # but every run counts as a run


def test_indoor_activities_count_for_activity_and_time_badges_but_not_the_roads(app):
    """Counts, hours and days of training take indoor rides and runs; distance, climbing, speed and weather don't."""
    with app.app_context():
        db = database.get_db()
        for aid, sport, dist, secs, gain in (('zw_long', 'VirtualRide', 170000, 18000, 2500),      # 105 miles and 8,200 ft up Alpe du Zwift
                                             ('zw_10k', 'VirtualRun', 12000, 3600, 0)):
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, movingTime, averageSpeed, maxSpeed, "
                       "totalElevationGain, weatherTempC) VALUES (?, ?, 1, ?, '2026-09-01T08:00:00', ?, ?, ?, 25, ?, -8)",
                       [aid, aid, sport, dist, secs, dist / secs, gain])
        db.execute('UPDATE Activity SET averageSpeed = distance / movingTime WHERE averageSpeed IS NULL')
        db.commit()
        from routes.riders import _compute_badges
        cats = {c['name']: {b['name']: b for b in c['badges']} for c in _compute_badges(1, {'rides': 3, 'dist': 0, 'elev': 0})}
    assert cats['Ride Count']['First Pedal']['ride_id'] == 'zw_long'      # the first ride, wherever it was
    assert not cats['Distance']['Road Tripper']['earned']                 # 105 indoor miles are no road trip
    assert not cats['Epic Rides']['Century Club']['earned']
    assert not cats['Climbing']['Hills Exist']['earned'] and cats['Elevation']['Summit Seeker']['progress'] == 0
    assert cats['Speed']['Respectable']['ride_id'] == 'ride_out' and not cats['Speed']['Flying']['earned']    # the Zwift ride's 24.6 mph
    assert not cats['Speed']['Missile']['earned']                         # Zwift's 56 mph descent
    assert not cats['Weather']['Deep Freeze']['earned']
    run = cats['Running']
    assert run['First Run']['ride_id'] == 'zw_10k' and run['First Run']['progress'] == 4
    assert not run['10K Finisher']['earned'] and run['5K Finisher']['ride_id'] == 'run_out'
    assert cats['All Sports']['Hundred Hours']['progress'] == 10          # 9.5 hours, indoors and out


def test_ai_holds_an_indoor_ride_against_indoor_rides_only(app):
    with app.app_context():
        from services.context import _build_achievement_context
        assert 'first recorded effort' in _build_achievement_context('ride_zw', '2026-10-05')
        assert 'beat previous best' not in _build_achievement_context('ride_out', '2026-10-04')


def test_indoor_run_calories_and_shoes(app):
    from services import kit
    from services.workouts import estimate_calories
    assert estimate_calories('VirtualRun', 5000, 1500, 0, 70) == estimate_calories('Run', 5000, 1500, 0, 70) > 0
    with app.app_context():
        db = database.get_db()
        road = kit.create(db, 1, 'Pegasus', sports_=['Run'])
        assert kit.default_for(db, 1, 'VirtualRun') == road                 # no treadmill shoes: the running ones
        assert kit.default_for(db, 1, 'Virtual Run') == road
        gym = kit.create(db, 1, 'Gym shoes', sports_=['VirtualRun'])
        assert kit.default_for(db, 1, 'VirtualRun') == gym and kit.default_for(db, 1, 'Run') == road


WATOPIA = (-11.70, 166.95)


@pytest.mark.parametrize('sport, lat, lng, want', [
    ('Run', *WATOPIA, 'VirtualRun'), ('Trail Run', *WATOPIA, 'VirtualRun'), ('Ride', *WATOPIA, 'VirtualRide'), (None, *WATOPIA, 'VirtualRide'),
    ('Walk', *WATOPIA, 'Walk'), ('Virtual Run', *WATOPIA, 'Virtual Run'),
    ('Run', -10.80, 165.82, 'VirtualRun'),                                  # Makuri Islands
    ('Run', 51.50, -0.12, 'Run'),                                           # London, the real one or Zwift's: can't tell, so as it says
    ('Run', None, None, 'Run'),
])
def test_a_run_or_ride_in_a_made_up_world_is_zwifts(sport, lat, lng, want):
    assert zwift.indoor_sport(sport, lat, lng) == want


def _gpx(kind, lat, lng):
    pts = ''.join(f'<trkpt lat="{lat + i * 0.0001}" lon="{lng}"><time>2026-10-17T17:{i // 60:02d}:{i % 60:02d}Z</time></trkpt>' for i in range(0, 600, 5))
    return (f'<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>t</name><type>{kind}</type>'
            f'<trkseg>{pts}</trkseg></trk></gpx>').encode()


def test_a_gpx_run_from_watopia_arrives_as_a_zwift_run():
    from services.parser import parse_activity_file
    assert parse_activity_file('a.gpx', _gpx('running', *WATOPIA))['sportType'] == 'VirtualRun'
    assert parse_activity_file('a.gpx', _gpx('VirtualRun', 51.5, -0.12))['sportType'] == 'VirtualRun'
    assert parse_activity_file('a.gpx', _gpx('running', 51.5, -0.12))['sportType'] == 'Run'


def test_runs_and_rides_saved_from_watopia_as_outdoor_ones_are_put_right(app):
    from services import tz
    from services.sport_fix import fix_misfiled
    utc = datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc)
    with app.app_context():
        db = database.get_db()
        there = tz.local_at(utc, *WATOPIA, 'Run')                            # the Solomon Islands' clock: the next morning
        assert there.startswith('2026-10-18')
        for aid, sport, local in (('zrun', 'Run', there), ('zride', 'Ride', there), ('garmin_9', 'Run', '2026-10-17T18:00:00')):
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, type, startDate, startDateLocal, startLat, startLng, distance, movingTime, "
                       "weatherSummary, weatherTempC, streams) VALUES (?, ?, 1, ?, ?, '2026-10-17T17:00:00', ?, ?, ?, 6000, 1800, 'Overcast, 26°C', 26, ?)",
                       [aid, aid, sport, sport, local, *WATOPIA, track(1800, 3.3)])
        sport_records.ensure(db)
        seg = db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, sport) VALUES ('Lap', -11.7, 166.95, -11.69, 166.95, 900, 'foot')").lastrowid
        for aid, secs in (('zrun', 300), ('run_zw', 250), ('run_out', 400)):
            db.execute('INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs) VALUES (?, ?, ?, ?)', [seg, aid, '2026-10-18', secs])
        db.commit()

        res = fix_misfiled(db)
        db.commit()
        got = {r['id']: r for r in db.execute("SELECT * FROM Activity WHERE id IN ('zrun', 'zride', 'garmin_9')")}
        assert sorted(m[0] for m in res['moved']) == ['garmin_9', 'zride', 'zrun']
        assert (got['zrun']['sportType'], got['zride']['sportType'], got['garmin_9']['sportType']) == ('VirtualRun', 'VirtualRide', 'VirtualRun')
        assert got['zrun']['startDateLocal'] == '2026-10-17T18:00:00'      # back on the home clock (London, BST)
        assert got['garmin_9']['startDateLocal'] == '2026-10-17T18:00:00'  # the device's own clock was right all along: left alone
        assert db.execute("SELECT DISTINCT activityDate FROM SportEffort WHERE activityId='zrun'").fetchone()[0] == '2026-10-17'
        assert {r[0] for r in db.execute('SELECT activityId FROM SegmentEffort')} == {'run_out'}        # Zwift's laps aren't the segment's
        assert db.execute('SELECT isPR FROM SegmentEffort WHERE activityId=?', ['run_out']).fetchone()[0] == 1
        assert res['efforts'] == 2
        assert fix_misfiled(db) == {'moved': [], 'efforts': 0}             # nothing left to do: cheap on every start


def test_startup_takes_the_weather_off_what_it_put_right(tmp_path, monkeypatch):
    db_path = str(tmp_path / 's.db')
    monkeypatch.setattr(config.Config, 'DATABASE', db_path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, startLat, startLng, distance, movingTime, weatherSummary, weatherTempC) "
                   "VALUES ('zrun', 'Watopia', 1, 'Run', '2026-10-18T04:00:00', ?, ?, 6000, 1800, 'Overcast, 26°C', 26)", list(WATOPIA))
        db.commit()
        database.migrate_db()
        r = db.execute("SELECT sportType, weatherSummary, weatherTempC FROM Activity WHERE id='zrun'").fetchone()
        assert tuple(r) == ('VirtualRun', None, None)
        assert db.execute("SELECT 1 FROM TaskLog WHERE task='startup:zwift_misfiled'").fetchone()
