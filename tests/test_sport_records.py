"""Every sport in the stats: run and swim best times (services/sport_records), the Data page's best times and records by sport, badges per sport
(routes/riders._sport_badges) and the Home Assistant sensors for every sport (services/mqtt). Full app, throwaway DB."""
import json
from datetime import date, timedelta

import pytest

import app as app_module
import config
import database
from services import credentials, sport_records


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def track(secs, speed):
    """A steady effort, one point a second: distance and time streams."""
    return json.dumps({'time': {'data': list(range(secs + 1))}, 'distance': {'data': [i * speed for i in range(secs + 1)]}})


MONDAY = date.today() - timedelta(days=date.today().weekday())


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, secs, speed, hour in (
                ('r1', 'Ride', 3600, 8.0, 7),              # 28.8 km
                ('run1', 'Run', 1800, 3.0, 9),            # 5.4 km at 3 m/s: 5 km in 1667 s (27:47)
                ('trail1', 'Trail Run', 1200, 3.5, 10),   # 4.2 km: no 5 km
                ('walk1', 'Walk', 3600, 1.4, 12),
                ('swim1', 'Swim', 1500, 1.0, 18),         # 1.5 km at 1 m/s: 400 m in 400 s
                ('sup1', 'Stand Up Paddling', 2400, 1.5, 15),
                ('ski1', 'Alpine Ski', 600, 15.0, 11)):   # 9 km of very fast "riding" if anyone counted it as a ride
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, movingTime, totalElevationGain, calories, streams) "
                       "VALUES (?, ?, 1, ?, ?, ?, ?, 10, 100, ?)", [aid, aid, sport, f'{MONDAY.isoformat()}T{hour:02d}:00:00', secs * speed, secs, track(secs, speed)])
        from services.best_efforts import save_best_efforts
        for aid in ('r1', 'ski1'):                 # the import saves them for anything with a track
            row = db.execute('SELECT startDateLocal, streams FROM Activity WHERE id=?', [aid]).fetchone()
            save_best_efforts(db, aid, row[0], row[1])
        db.commit()
        a.config['AV'] = credentials.auth_version()
    yield a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = app.config['AV']
    return c


def test_kinds_and_best_times():
    assert [sport_records.kind(s) for s in ('Run', 'Trail Run', 'VirtualRun', 'Walk', 'Swim', 'Open Water Swim', 'Ride', None)] == \
        ['run', 'run', 'run', None, 'swim', 'swim', None, None]
    got = dict(sport_records.compute(track(1500, 1.0), 'swim'))
    assert got[400.0] == 400 and got[1500.0] == 1500 and 1609.344 not in got


def test_ensure_works_out_each_run_and_swim_once_and_again_after_a_change_of_sport(app):
    with app.app_context():
        db = database.get_db()
        assert sport_records.ensure(db) == 3                                       # run, trail run, swim
        assert sport_records.ensure(db) == 0
        assert sport_records.bests(db, 1, 'run')[5000.0]['activityId'] == 'run1'
        assert db.execute("SELECT distanceM FROM SportEffort WHERE activityId='trail1' AND distanceM=5000").fetchone() is None
        db.execute("UPDATE Activity SET sportType='Swim' WHERE id='trail1'"); db.commit()
        assert sport_records.ensure(db) == 1                                       # its run rows don't count as a swim's
        assert db.execute("SELECT kind FROM SportEffort WHERE activityId='trail1'").fetchone()[0] == 'swim'
        assert 'trail1' not in {r['activityId'] for r in sport_records.efforts(db, 1, 'run')}
        assert 'trail1' not in {r['activityId'] for r in sport_records.efforts(db, 1, 'swim')}       # 3.5 m/s is faster than anyone swims


def test_data_page_best_times_per_sport_and_records_by_sport(client):
    html = client.get('/data').get_data(as_text=True)
    assert 'id="records-ride"' in html and 'id="records-run"' in html and 'id="records-swim"' in html
    assert 'Swim best times' in html and '3.8 km' in html and 'Half marathon' in html
    data = json.loads(html.split('const data = ', 1)[1].split(';\n', 1)[0])
    ride = next(a for a in data if a['key'] == 'ride')
    assert all(r['rideId'] == 'r1' for yr in ride['by_year'].values() for r in yr.values())      # the ski run is not a ride's best 5 miles
    run = next(a for a in data if a['key'] == 'run')
    assert run['by_year'][str(MONDAY.year)]['5000']['time'] == '27:47'
    swim = next(a for a in data if a['key'] == 'swim')
    assert swim['by_year'][str(MONDAY.year)]['400']['rate'] == '1:40 /100 m'
    recs = json.loads(html.split('const byPeriod = ', 1)[1].split(';\n', 1)[0])
    sports_ = [r['sport'] for r in recs['all']]
    assert sports_[0] == 'Ride' and 'Stand Up Paddling' in sports_ and 'Alpine Ski' in sports_
    swim_rec = next(r for r in recs['all'] if r['sport'] == 'Swim')
    assert swim_rec['dist']['v'] == '1,500 m' and swim_rec['fast']['v'] == '1:40 /100 m'

    html = client.get('/data?skip=Swim').get_data(as_text=True)
    assert 'id="records-swim"' not in html and 'id="records-run"' in html


def test_rider_page_best_efforts_per_sport(client):
    html = client.get('/riders/1').get_data(as_text=True)
    assert '>Runs</td>' in html and '>Swims</td>' in html and '5 km' in html and '/rides/swim1' in html
    assert '/rides/ski1' not in html.split('Best Efforts', 1)[1].split('Trophy Case', 1)[0]


def test_badges_per_sport(app):
    with app.test_request_context():
        from routes.riders import _compute_badges
        cats = {c['name']: {b['name']: b for b in c['badges']} for c in _compute_badges(1, {'rides': 1, 'dist': 28800, 'elev': 10})}
    assert {'Running', 'Walking & Hiking', 'Swimming', 'Other Sports', 'All Sports'} <= set(cats)
    assert cats['Running']['First Run']['earned'] and cats['Running']['First Run']['ride_id'] == 'run1'
    assert cats['Running']['5K Finisher']['earned'] and cats['Running']['5K Under 30']['earned'] and not cats['Running']['5K Under 25']['earned']
    assert cats['Swimming']['Olympic Distance']['earned'] and cats['Swimming']['Smooth Stroke']['earned'] and cats['Swimming']['Quick Stroke']['earned'] and not cats['Swimming']['Iron Distance']['earned']
    assert cats['Other Sports']['First Stand Up Paddling']['earned'] and not cats['Other Sports']['Stand Up Paddling Regular']['earned']
    assert cats['All Sports']['Triathlete']['earned'] and cats['All Sports']['Brick']['earned'] and cats['All Sports']['Explorer']['earned']
    assert cats['Ride Count']['First Pedal']['desc'] == '1 ride'


def test_a_rider_who_only_rides_gets_no_other_sport_badges(app):
    with app.test_request_context():
        db = database.get_db()
        db.execute("DELETE FROM Activity WHERE id <> 'r1'"); db.commit()
        from routes.riders import _compute_badges
        names = {c['name'] for c in _compute_badges(1, {'rides': 1, 'dist': 28800, 'elev': 10})}
    assert not names & {'Running', 'Walking & Hiking', 'Swimming', 'Other Sports', 'All Sports'}


def test_home_assistant_sensors_for_every_sport(app):
    from services import mqtt
    with app.test_request_context():
        vals = mqtt._state_values(mqtt._gather_stats())
        weekly = json.loads(mqtt._history_payloads()['nutrition_training_weekly'])
    assert vals['total_rides'] == '1' and vals['total_activities'] == '7'
    assert vals['week_activities'] == '7' and vals['week_swim_distance_m'] == '1500'
    assert vals['week_foot_distance_mi'] == str(round((5400 + 4200 + 5040) / 1609.344, 1))
    assert vals['last_activity_sport'] == 'Swim' and vals['last_ride_sport'] == 'Ride'
    assert weekly['n'][-1] == 7 and [g['key'] for g in weekly['groups']][:3] == ['ride', 'foot', 'swim']
    assert next(g for g in weekly['groups'] if g['key'] == 'swim')['m'][-1] == 1500
    assert 'week_training_hours' in {u for u, *_ in mqtt.SENSORS} and 'nutrition_training_weekly' in mqtt.HISTORY_UIDS


def test_no_climbing_record_on_the_water():
    from services import sports
    assert sports.has_climbing('Ride') and sports.has_climbing('Hike') and sports.has_climbing('Alpine Ski')
    assert not any(sports.has_climbing(s) for s in ('Swim', 'Kitesurf', 'Stand Up Paddling', 'Sail', 'Kayaking', 'Rowing'))


# ── Bad recordings: impossible stretches, stops counted as moving, Strava's own figures ──

def _ride_with_a_faulty_sensor():
    """A 2,000 s ride at 8 m/s along a straight line; for 300 s in the middle the speed sensor says 37 m/s while the GPS still shows 8."""
    lat0, d_lat = 50.6, 8.0 / 111_320.0
    ll = [[lat0 + i * d_lat, -3.5] for i in range(2001)]
    d, acc = [0.0], 0.0
    for i in range(1, 2001):
        acc += 37.0 if 800 <= i < 1100 else 8.0
        d.append(acc)
    return {'latlng': {'data': ll}, 'time': {'data': list(range(2001))}, 'distance': {'data': d}}


def test_best_times_leave_out_a_speed_sensor_fault_and_gps_jumps():
    from services.best_efforts import CEILING_MPS, compute_best_efforts, effort_series
    efforts = compute_best_efforts(json.dumps(_ride_with_a_faulty_sensor()))
    five = next(e for e in efforts if e['distanceMi'] == 5)
    assert abs(five['avgSpeedMps'] - 8.0) < 0.1                                     # not 37 m/s: the GPS is believed
    jump = {'time': {'data': [0, 1, 2, 3]}, 'distance': {'data': [0, 8, 1008, 1016]}}  # no GPS: a 1 km jump in one second counts for nothing
    d, _ = effort_series(jump, CEILING_MPS['ride'])
    assert d[-1] == 16


def test_moving_time_comes_from_the_track_when_the_device_counted_its_stops():
    from services.parser import pick_moving_time
    assert pick_moving_time(7200, 7150) == 7200          # auto-pause on: the device's
    assert pick_moving_time(9511, 7488) == 7488          # auto-pause off: every stop counted
    assert pick_moving_time(9, 2700) == 2700             # a flat battery's lap timer
    assert pick_moving_time(0, 0, 600) == 600            # nothing to go on: the elapsed time
    assert pick_moving_time(3000, 1200, sport='Swim') == 3000       # a slow swim looks stopped on the track: the watch's


def test_start_up_repairs_put_right_what_is_saved(app):
    from services import best_efforts, moving_time
    with app.app_context():
        db = database.get_db()
        streams = _ride_with_a_faulty_sensor()
        stops = {'time': {'data': list(range(0, 2001)) + list(range(5000, 7001))},   # 2,000 s moving, a 50 minute stop, 2,000 s more
                 'distance': {'data': [i * 8.0 for i in range(2001)] + [16000 + i * 8.0 for i in range(2001)]}}
        db.execute("UPDATE Activity SET streams=?, movingTime=7000 WHERE id='r1'", [json.dumps(stops)])
        db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, movingTime, streams) "
                   "VALUES ('bad', 'Morning Paddle', 1, 'Ride', '2021-05-16T10:45:00', 26000, 2000, ?)", [json.dumps(streams)])
        db.execute("INSERT INTO BestEffort (activityId, activityDate, distanceMi, elapsedSecs, avgSpeedMps) VALUES ('bad', '2021-05-16', 5, 215, 37.4)")
        db.execute('UPDATE Settings SET movingTimePausedDone=0, bestEffortsCleanDone=0')
        db.commit()
        res = moving_time.repair_paused(db)
        assert [f[0] for f in res['fixed']] == ['r1'] and db.execute("SELECT movingTime FROM Activity WHERE id='r1'").fetchone()[0] == 4000
        res = best_efforts.rescan_clean(db)
        five = next(c for c in res['changed'] if c[0] == 5)
        assert res['ran'] and five[1] == 215 and five[2] > 900                             # the rider's 5-mile record: 3:35 before, a real one now
        assert db.execute("SELECT MIN(elapsedSecs) FROM BestEffort WHERE activityId='bad' AND distanceMi=5").fetchone()[0] > 900
        assert db.execute('SELECT COUNT(*) FROM SportEffort').fetchone()[0] == 0          # runs and swims are worked out again on the next read
        assert best_efforts.rescan_clean(db) == {'ran': False} and moving_time.repair_paused(db) == {'ran': False}
