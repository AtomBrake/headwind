"""Segments by sport: ride and on foot (services/sports.segment_family). An activity only meets segments of its own family. Pedal and e-bike rides
share the ride segments, and an e-bike, by sport or by bike, makes an effort an e-bike one (segment_class), with its own PRs, badges and leaderboard
filter. Walks, runs and hikes share foot segments. The start-up regroup and merge_bikes move an old install across once. Throwaway DB."""
import json

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import convert, credentials, gear, segments, sport_fix, workouts
from services.sports import ebike_sql, segment_class, segment_family


def line(secs, speed_mps, lat0=51.5, lng0=-0.12):
    """A straight northbound GPS track at a steady speed, one fix per second."""
    d_lat = speed_mps / 111_320.0
    ll = [[lat0 + i * d_lat, lng0] for i in range(secs + 1)]
    return json.dumps({'latlng': {'data': ll}, 'time': {'data': list(range(secs + 1))}})


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider(name,isDefault) VALUES ('Tom',1)")
        d.commit()
        yield d


def add(db, aid, sport, speed, secs=1200, day='2026-10-07', bike=None):
    """An activity on the shared track; rides go through the ride ingest, everything else through workouts.refresh_derived, as in the app."""
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,rawData,riderId,streams,bikeId) "
               "VALUES (?,?,?,?,?,?,?,?,?,'{}',1,?,?)", [aid, aid, sport, sport, f'{day}T10:00:00', f'{day}T10:00:00', secs * speed, secs, secs, line(secs, speed), bike])
    if sport in ('Walk', 'Run', 'Hike', 'Swim'):
        workouts.refresh_derived(db, aid)
    else:
        segments.scan_new_ride(db, aid)
    db.commit()


def add_seg(db, family, name='Seg'):
    """From 100 m to 1,000 m up the track, whatever speed covers it."""
    d = 1 / 111_320.0
    db.execute("INSERT INTO Segment (name,startLat,startLng,endLat,endLng,distanceM,sport) VALUES (?,?,?,?,?,900,?)",
               [name, 51.5 + 100 * d, -0.12, 51.5 + 1000 * d, -0.12, family])
    db.commit()
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def on(db, sid):
    return {r[0]: r[1] for r in db.execute('SELECT activityId, isPR FROM SegmentEffort WHERE segmentId=?', [sid])}


@pytest.mark.parametrize('sport, kind, cls', [
    ('Ride', None, 'bike'), (None, None, 'bike'), ('Mountain Bike Ride', None, 'bike'), ('Gravel Ride', 'road', 'bike'),
    ('EBikeRide', None, 'ebike'), ('E-Bike Ride', None, 'ebike'), ('E-Mountain Bike Ride', None, 'ebike'), ('EMountainBikeRide', None, 'ebike'),
    ('Ride', 'ebike', 'ebike'),                                     # whatever the sport says, an e-bike makes it an e-bike effort
    ('VirtualRide', None, None), ('Virtual Ride', None, None), ('VirtualRide', 'ebike', None),
    ('Walk', None, 'foot'), ('Run', None, 'foot'), ('Hike', None, 'foot'), ('Trail Run', None, 'foot'), ('TrailRun', None, 'foot'), ('VirtualRun', None, 'foot'),
    ('Swim', None, None), ('Paddle', None, None), ('Ski', None, None), ('Other', None, None),
])
def test_every_sport_has_one_class_or_none(sport, kind, cls):
    assert segment_class(sport, kind) == cls
    assert segment_family(sport) == {'bike': 'ride', 'ebike': 'ride'}.get(cls, cls)
    if cls in ('bike', 'ebike'):                                     # the SQL the leaderboards filter with says the same
        import sqlite3
        d = sqlite3.connect(':memory:')
        d.execute('CREATE TABLE t (sportType TEXT, kind TEXT)')
        d.execute('INSERT INTO t VALUES (?, ?)', [sport, kind])
        assert d.execute(f'SELECT {ebike_sql("sportType", "kind")} FROM t').fetchone()[0] == (cls == 'ebike')


def test_walks_runs_and_hikes_share_one_foot_leaderboard_and_rides_stay_off_it(db):
    foot, ride = add_seg(db, 'foot'), add_seg(db, 'ride')
    add(db, 'walk', 'Walk', 1.4)
    add(db, 'hike', 'Hike', 0.7, secs=2400)                          # a steep hike: slower than the old run limit (1.2 m/s)
    add(db, 'run', 'Run', 3.0)
    add(db, 'ride', 'Ride', 6.0)
    assert on(db, foot) == {'walk': 0, 'hike': 0, 'run': 1}           # one PR for the rider, whatever the sport
    assert on(db, ride) == {'ride': 1}
    segments.scan_all_activities(db)                                  # the full rescan agrees: no walk on a ride segment any more
    assert on(db, foot) == {'walk': 0, 'hike': 0, 'run': 1} and on(db, ride) == {'ride': 1}


def test_pedal_and_e_bike_rides_share_a_segment_with_a_pr_each(db):
    ride = add_seg(db, 'ride')
    add(db, 'slow', 'Ride', 5.0, day='2026-10-01')
    add(db, 'pedal', 'Ride', 6.0)
    add(db, 'strava_e', 'E-Bike Ride', 9.0)
    assert on(db, ride) == {'slow': 0, 'pedal': 1, 'strava_e': 1}     # the e-bike is fastest, and the pedal PR is still the pedal ride's


def test_indoor_rides_and_swims_get_no_segments(db):
    ride, foot = add_seg(db, 'ride'), add_seg(db, 'foot')
    add(db, 'zwift', 'VirtualRide', 9.0)
    add(db, 'swim', 'Swim', 1.0)
    assert on(db, ride) == {} and on(db, foot) == {}


def test_the_bike_moves_a_ride_between_pedal_and_e_bike_prs(db):
    ride = add_seg(db, 'ride')
    road = gear.create_bike(db, 1, 'Road', kind='road')
    ebike = gear.create_bike(db, 1, 'Turbo', kind='ebike')
    add(db, 'slow', 'Ride', 5.0, day='2026-10-01')
    add(db, 'fast', 'Ride', 8.0)
    assert on(db, ride) == {'slow': 0, 'fast': 1}

    gear.set_ride_bike(db, 'fast', ebike); db.commit()               # it was on the e-bike: the pedal PR goes back, and it holds the e-bike one
    assert on(db, ride) == {'slow': 1, 'fast': 1}

    gear.update_bike(db, ebike, kind='road'); db.commit()            # the bike was mislabelled after all
    assert on(db, ride) == {'slow': 0, 'fast': 1}

    gear.update_bike(db, ebike, kind='ebike'); db.commit()
    gear.delete_bike(db, ebike); db.commit()                          # its rides become unassigned, so pedal rides again
    assert on(db, ride) == {'slow': 0, 'fast': 1}

    gear.assign_rides(db, 1, gear.create_bike(db, 1, 'Commuter', kind='ebike'), dates=['2026-10-01']); db.commit()
    assert on(db, ride) == {'slow': 1, 'fast': 1}
    gear.set_ride_bike(db, 'fast', road); db.commit()                 # a pedal bike changes nothing
    assert on(db, ride) == {'slow': 1, 'fast': 1}


def test_a_new_ride_on_a_default_e_bike_gets_its_pr_even_if_it_was_scanned_first(db):
    ride = add_seg(db, 'ride')
    add(db, 'old', 'Ride', 5.0, day='2026-10-01')
    gear.set_default(db, 1, gear.create_bike(db, 1, 'Turbo', kind='ebike'))
    add(db, 'new', 'Ride', 8.0)                                       # scanned before it has its bike, as a file import does: it takes the pedal PR
    assert on(db, ride) == {'old': 0, 'new': 1}
    gear.on_ride_added(db, 'new'); db.commit()
    assert on(db, ride) == {'old': 1, 'new': 1}


def test_changing_the_type_between_ride_sports_moves_the_pr_or_the_segments(db):
    ride = add_seg(db, 'ride')
    add(db, 'p', 'Ride', 6.0, day='2026-10-01')
    add(db, 'r', 'Ride', 8.0)
    assert on(db, ride) == {'p': 0, 'r': 1}
    convert.change_sport(db, 'ride', 'r', 'EBikeRide'); db.commit()
    assert on(db, ride) == {'p': 1, 'r': 1}
    convert.change_sport(db, 'ride', 'r', 'VirtualRide'); db.commit()
    assert on(db, ride) == {'p': 1}
    convert.change_sport(db, 'ride', 'r', 'Ride'); db.commit()
    assert on(db, ride) == {'p': 0, 'r': 1}


def test_the_garmin_type_check_proposes_e_bike_for_garmin_rides(db):
    add(db, 'garmin_1', 'Ride', 8.0)
    add(db, 'garmin_2', 'Ride', 8.0)

    class Api:
        def get_activities(self, start, limit):
            return [{'activityId': 1, 'activityType': {'typeKey': 'e_bike_mountain'}, 'startTimeLocal': '2026-10-07 10:00:00'},
                    {'activityId': 2, 'activityType': {'typeKey': 'mountain_biking'}, 'startTimeLocal': '2026-10-07 10:00:00'}][start:start + limit]
    sport_fix.scan(db, Api(), 1)
    assert [(p['rideId'], p['newSport']) for p in sport_fix.pending(db, 1)] == [('garmin_1', 'EBikeRide'), ('garmin_2', 'MountainBikeRide')]
    ride = add_seg(db, 'ride')
    sport_fix.apply(db, 1, ['garmin_1'])
    assert db.execute("SELECT sportType FROM Activity WHERE id='garmin_1'").fetchone()[0] == 'EBikeRide'
    segments.scan_all_activities(db, segment_ids=[ride])
    assert on(db, ride) == {'garmin_1': 1, 'garmin_2': 1}             # same time, but one is an e-bike ride: a PR each


def test_regroup_moves_an_old_install_across_once(db):
    ride, run_seg = add_seg(db, 'ride'), add_seg(db, 'run')          # as 0.7.1 left them
    ebike = gear.create_bike(db, 1, 'Turbo', kind='ebike')
    add(db, 'pedal', 'Ride', 6.0)
    add(db, 'onebike', 'Ride', 9.0, bike=None)
    add(db, 'walk', 'Walk', 1.4)
    add(db, 'run', 'Run', 3.0)
    db.execute('UPDATE Activity SET bikeId=? WHERE id=?', [ebike, 'onebike'])
    for aid in ('walk', 'onebike'):                                   # what the old matcher put on the ride segment
        db.execute("INSERT OR REPLACE INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs) VALUES (?,?,'2026-10-07',?)", [ride, aid, 100])
    db.execute("UPDATE SegmentEffort SET isPR = (activityId = 'onebike') WHERE segmentId=?", [ride])          # one PR per segment, as 0.7.1 picked
    db.execute("INSERT OR REPLACE INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, isPR) VALUES (?,'run','2026-10-07',300,1)", [run_seg])
    db.execute("UPDATE Settings SET segmentFamiliesDone=0 WHERE id=1"); db.commit()

    res = segments.regroup(db)
    assert res['ran'] and res['removed'] == 1 and res['foot'] == 1 and res['prs_moved'] == 1
    assert db.execute('SELECT sport FROM Segment WHERE id=?', [run_seg]).fetchone()[0] == 'foot'
    assert on(db, ride) == {'pedal': 1, 'onebike': 1}                 # the walk goes; the pedal ride gets back the PR the e-bike held, which keeps its own
    assert on(db, run_seg) == {'run': 1, 'walk': 0}                   # the walk joins the foot leaderboard
    assert segments.regroup(db) == {'ran': False}


def test_merge_bikes_moves_0_7_3_e_bike_segments_into_the_ride_ones_once(db):
    ride, eride = add_seg(db, 'ride', 'Lane'), add_seg(db, 'eride', 'Hill')
    add(db, 'pedal', 'Ride', 6.0)
    add(db, 'e', 'EBikeRide', 9.0)
    db.execute("DELETE FROM SegmentEffort WHERE (segmentId=? AND activityId='e') OR (segmentId=? AND activityId='pedal')", [ride, eride])   # as 0.7.3 left it
    db.execute("UPDATE SegmentEffort SET isPR=1")
    db.execute("UPDATE Settings SET segmentBikesMergedDone=0 WHERE id=1"); db.commit()

    res = segments.merge_bikes(db)
    assert res == {'ran': True, 'merged': 1, 'found': 2, 'scanned': 2, 'prs_moved': 2}
    assert db.execute("SELECT COUNT(*) FROM Segment WHERE sport='ride'").fetchone()[0] == 2
    assert on(db, ride) == on(db, eride) == {'pedal': 1, 'e': 1}
    assert segments.merge_bikes(db) == {'ran': False}


def test_pedal_and_e_bike_rides_have_their_own_badges_on_the_same_segments(db):
    from routes.riders import _compute_badges
    ride, foot = add_seg(db, 'ride'), add_seg(db, 'foot')
    add(db, 'pedal', 'Ride', 6.0)
    add(db, 'e', 'E-Bike Ride', 12.0)                                 # 26.8 mph
    add(db, 'run', 'Run', 3.4)                                        # 7:53 /mi
    cats = {c['name']: {b['name']: b for b in c['badges']} for c in _compute_badges(1, {'rides': 2, 'dist': 0, 'elev': 0})}
    ride_b, e_b, foot_b = cats['Segments'], cats['E-Bike Segments'], cats['Segments on Foot']
    assert ride_b['First Effort']['progress'] == 1 and ride_b['King of the Road']['earned']       # the e-bike's faster time doesn't take it
    assert not ride_b['Segment Rocket']['earned']                    # the e-bike's 26.8 mph is not a pedal speed
    assert e_b['Plugged In']['ride_id'] == 'e' and e_b['Turbo Mode']['earned'] and not e_b['Boost']['earned']
    assert e_b['King of the E-Road']['earned'] and e_b['King of the E-Road']['desc'] == 'Hold every segment PR on an e-bike (1 segment)'
    assert foot_b['First Steps']['ride_id'] == 'run' and foot_b['King of the Trail']['earned']
    assert foot_b['Runner']['earned'] and not foot_b['Swift']['earned']
    assert foot_b['Runner']['desc'] == '8:00 /mi avg on a foot segment'


@pytest.fixture
def client(tmp_path, monkeypatch):
    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'c.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.mqtt.push_update', lambda *a, **k: None)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, name, sport, speed in (('walk', 'Morning walk', 'Walk', 1.4), ('pedal', 'Pedal Tuesday', 'Ride', 6.0),
                                        ('turbo', 'Turbo Thursday', 'EBikeRide', 9.0), ('zwift', 'Zwift', 'VirtualRide', 9.0)):
            d.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,rawData,riderId,streams) "
                      "VALUES (?,?,?,?,'2026-10-07T10:00:00','2026-10-07T10:00:00',?,1200,1200,'{}',1,?)", [aid, name, sport, sport, 1200 * speed, line(1200, speed)])
        d.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.app_ = app
    return c


def test_a_segment_takes_its_family_from_the_activity_it_was_made_on(client):
    d = 1 / 111_320.0
    form = {'name': 'Lane', 'startLat': 51.5 + 100 * d, 'startLng': -0.12, 'endLat': 51.5 + 1000 * d, 'endLng': -0.12, 'distanceM': 900}
    assert client.post('/segments/create', data=dict(form, activityId='walk', sport='ride')).status_code == 302      # the page's value is not trusted
    assert client.post('/segments/create', data=dict(form, activityId='zwift')).status_code == 400
    with client.app_.app_context():
        seg = database.get_db().execute('SELECT id, sport FROM Segment').fetchone()
        assert seg['sport'] == 'foot'
        assert [r[0] for r in database.get_db().execute('SELECT activityId FROM SegmentEffort WHERE segmentId=?', [seg['id']])] == ['walk']
    page = client.get('/segments?sport=foot').get_data(as_text=True)
    assert 'Lane' in page and 'On foot' in page and 'E-bike' not in page          # no pedal / e-bike filter on foot
    assert 'Lane' not in client.get('/segments').get_data(as_text=True)
    assert 'Lane' in client.get('/segments?sport=run').get_data(as_text=True)                                       # an old bookmark
    seg_page = client.get(f"/segments/{seg['id']}").get_data(as_text=True)
    assert 'Avg Pace' in seg_page and '/mi' in seg_page
    ride_page = client.get('/rides/zwift').get_data(as_text=True)
    assert 'Create Segment' not in ride_page and 'Segments are only for outdoor' in ride_page
    assert 'name="sport"      value="foot"' in client.get('/rides/walk').get_data(as_text=True)
    rider = client.get('/riders/1').get_data(as_text=True)
    assert 'E-Bike Segments' in rider and 'Segments on Foot' in rider and 'First Steps' in rider
    assert client.get('/segments?sport=eride').status_code == 200                                                    # a bookmark from 0.7.3


def test_the_ride_leaderboards_show_every_bike_or_one_kind(client):
    d = 1 / 111_320.0
    form = {'name': 'Climb', 'startLat': 51.5 + 100 * d, 'startLng': -0.12, 'endLat': 51.5 + 1000 * d, 'endLng': -0.12, 'distanceM': 900}
    assert client.post('/segments/create', data=dict(form, activityId='turbo')).status_code == 302                   # made on an e-bike: a ride segment
    with client.app_.app_context():
        seg = database.get_db().execute('SELECT id, sport FROM Segment').fetchone()
        assert seg['sport'] == 'ride'
        assert {r[0]: r[1] for r in database.get_db().execute('SELECT activityId, isPR FROM SegmentEffort')} == {'pedal': 1, 'turbo': 1}
    every = client.get(f"/segments/{seg['id']}").get_data(as_text=True)
    assert 'Pedal Tuesday' in every and 'Turbo Thursday' in every and 'title="E-bike"' in every
    assert 'All <span style="opacity:.7;">(2)</span>' in every and 'E-bike <span style="opacity:.7;">(1)</span>' in every
    pedal = client.get(f"/segments/{seg['id']}?only=bike").get_data(as_text=True)
    assert 'Pedal Tuesday' in pedal and 'Turbo Thursday' not in pedal
    e = client.get(f"/segments/{seg['id']}?only=ebike").get_data(as_text=True)
    assert 'Turbo Thursday' in e and 'Pedal Tuesday' not in e and '2:30' not in e                                  # the pedal ride's 2:30 is in no stat
    assert client.get(f"/segments/{seg['id']}?only=nonsense").get_data(as_text=True).count('Turbo Thursday') == every.count('Turbo Thursday')
    lst = client.get('/segments?only=ebike').get_data(as_text=True)
    assert 'Climb' in lst and '1:40' in lst and f"/segments/{seg['id']}?only=ebike" in lst                         # the e-bike's best, and the link keeps the filter
    assert '2:30' in client.get('/segments?only=bike').get_data(as_text=True)
    assert 'name="sport"      value="ride"' in client.get('/rides/turbo').get_data(as_text=True)
