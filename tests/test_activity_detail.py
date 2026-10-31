"""The activity page by sport (services/activity_detail.py, routes/rides.detail): splits and pace on foot, a pool swim's sets and SWOLF, a ski day's
runs, the device's laps from a FIT file, and what's hidden where it doesn't fit. Throwaway DB, no network."""
import json
from datetime import datetime, timedelta

import pytest

from services import activity_detail as ad, parser


def streams(speed_mps, secs, alt=None, every=1):
    t = list(range(0, secs + 1, every))
    s = {'time': {'data': t}, 'distance': {'data': [round(speed_mps * x, 2) for x in t]}}
    if alt:
        s['altitude'] = {'data': [alt(x) for x in t]}
    return s


def test_views():
    assert [ad.view(s) for s in ('Ride', 'E-Bike Ride', 'Run', 'Trail Run', 'Walk', 'Hike', 'Swim', 'Alpine Ski', 'Ski', 'Snowboard',
                                 'Nordic Ski', 'Stand Up Paddling', 'Windsurf', 'Kitesurf', 'Yoga')] == \
        ['ride', 'ride', 'foot', 'foot', 'foot', 'foot', 'swim', 'ski', 'ski', 'ski', 'other', 'water', 'water', 'water', 'other']


def test_splits_per_km_use_moving_time_and_keep_the_part_left_over():
    s = streams(3.0, 2000)                                     # 6 km at 3 m/s: 333 s a km
    t, d = s['time']['data'], s['distance']['data']
    t[1000:] = [x + 600 for x in t[1000:]]                     # a 10-minute stop (the device paused) after 3 km
    out = ad.splits(s, 'foot', 'metric')
    assert [x['n'] for x in out] == [1, 2, 3, 4, 5, 6]
    assert all(abs(x['secs'] - 333) <= 1 for x in out)         # the stop isn't in any split
    s = streams(3.0, 1700)                                     # 5.1 km: five whole km and 100 m
    out = ad.splits(s, 'foot', 'metric')
    assert len(out) == 6 and out[-1]['dist_m'] == pytest.approx(100, abs=1)
    assert len(ad.splits(streams(3.0, 1690), 'foot', 'metric')) == 5    # 70 m left over: under a tenth of a km, not shown


def test_swim_splits_are_per_100_m_and_imperial_foot_splits_per_mile():
    assert len(ad.splits(streams(1.0, 1000), 'swim')) == 10
    assert len(ad.splits(streams(3.0, 1100), 'foot', 'imperial')) == 2  # 3.3 km: two miles and a bit (a bit < a tenth of a mile)


def test_pace_series_is_seconds_per_unit_with_gaps_for_stops():
    s = streams(4.0, 600)
    s['distance']['data'][300:330] = [s['distance']['data'][300]] * 30       # standing still for 30 s
    p = ad.pace_series(s, 'foot', 'metric', points=600)
    assert p['values'][100] == 250 and None in p['values']                  # 4 m/s is 4:10 a km


def test_pool_sets_break_at_each_rest():
    lengths = [{'t': i * 30, 'secs': 30, 'active': True, 'strokes': 15, 'stroke': 'freestyle'} for i in range(4)]
    lengths += [{'t': 120, 'secs': 45, 'active': False}]
    lengths += [{'t': 165 + i * 40, 'secs': 40, 'active': True, 'strokes': 20, 'stroke': 'breaststroke'} for i in range(2)]
    p = ad.pool({'lengths': lengths, 'pool_m': 25.0, 'laps': []})
    assert (p['lengths'], p['dist_m'], p['rest_secs'], p['strokes']) == (6, 150.0, 45, 100)
    assert [(x['lengths'], x['stroke'], x['swolf'], x['rest_after']) for x in p['sets']] == [(4, 'Freestyle', 45, 45), (2, 'Breaststroke', 60, 0)]
    assert p['swolf'] == round((4 * 45 + 2 * 60) / 6)
    assert ad.pool({'laps': []}) is None


def test_ski_runs_come_from_the_descents():
    # up a lift for 10 min (+300 m), down for 5 min (-300 m), twice, with a little rise in the middle of the second run
    def alt(x):
        c = x % 900
        base = 1500 + (c / 600 * 300 if c < 600 else 300 - (c - 600) / 300 * 300)
        return base + (8 if 1650 < x < 1660 else 0)
    s = streams(5.0, 1799, alt)
    s['velocity_smooth'] = {'data': [5.0] * len(s['time']['data'])}
    out = ad.ski_runs(s)
    assert len(out['runs']) == 2 and all(abs(r['drop_m'] - 300) < 20 for r in out['runs'])
    assert out['lift_secs'] >= 1100 and out['top_mps'] == 5.0


def _fit_msgs():
    start = datetime(2020, 10, 29, 19, 1, 9)
    laps = [{'start_time': start, 'total_timer_time': 600.0, 'total_distance': 1675.0, 'avg_heart_rate': 120, 'swim_stroke': 'mixed'}]
    lengths = [{'start_time': start + timedelta(seconds=30 * i), 'total_timer_time': 30.0, 'total_strokes': 14, 'swim_stroke': 'freestyle',
                'length_type': 'active', 'avg_swimming_cadence': 22} for i in range(3)]
    lengths.append({'start_time': start + timedelta(seconds=90), 'total_timer_time': 20.0, 'length_type': 'idle'})
    return start, laps, lengths


def test_fit_laps_keep_a_pool_swims_lengths_and_drop_a_single_lap():
    start, laps, lengths = _fit_msgs()
    d = json.loads(parser.fit_laps(laps, lengths, {'pool_length': 25.0, 'pool_length_unit': 'metric'}, start))
    assert d['pool_m'] == 25.0 and len(d['lengths']) == 4 and d['lengths'][3] == {'t': 90, 'secs': 20.0, 'active': False}
    assert d['laps'] == []                                     # one lap says nothing the summary doesn't
    assert parser.fit_laps(laps, [], {}, start) is None
    two = laps + [dict(laps[0], start_time=start + timedelta(seconds=600))]
    assert len(json.loads(parser.fit_laps(two, [], {}, start))['laps']) == 2


def test_auto_laps_that_repeat_the_splits_are_not_shown_twice():
    km_laps = json.dumps({'laps': [{'t': 333 * i, 'secs': 333, 'dist': 1000.0} for i in range(5)] + [{'t': 1665, 'secs': 35, 'dist': 100.0}]})
    a = {'sportType': 'Run', 'laps': km_laps}
    assert ad.for_activity(a, streams(3.0, 1700), 'metric')['laps'] == []
    assert len(ad.for_activity(a, streams(3.0, 1700), 'imperial')['laps']) == 6          # per-km laps aren't the mile splits
    pressed = json.dumps({'laps': [{'t': 0, 'secs': 600, 'dist': 2000.0}, {'t': 600, 'secs': 300, 'dist': 1200.0}, {'t': 900, 'secs': 400, 'dist': 1500.0}]})
    assert len(ad.for_activity({'sportType': 'Run', 'laps': pressed}, streams(3.0, 1700), 'metric')['laps']) == 3


def test_a_crop_keeps_the_laps_inside_it_shifted_to_its_start():
    laps = json.dumps({'laps': [{'t': 0, 'secs': 100}, {'t': 100, 'secs': 100}, {'t': 200, 'secs': 100}, {'t': 300, 'secs': 50}]})
    d = json.loads(parser.crop_laps(laps, 100, 150))                    # the laps that start inside the window
    assert [x['t'] for x in d['laps']] == [0, 100]
    assert parser.crop_laps(laps, 290, 100) is None            # one lap left


def test_reimport_fills_in_laps_without_asking(tmp_path):
    from flask import Flask
    import database
    from services import reimport
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, movingTime, elapsedTime) VALUES ('s', 'Swim', 'Swim', '2020-10-29T19:01:09', 1675, 2550, 2550)")
        saved = db.execute("SELECT * FROM Activity WHERE id='s'").fetchone()
        start, laps, lengths = _fit_msgs()
        act = {'distance': 1675, 'movingTime': 2550, 'elapsedTime': 2550, 'startDateLocal': '2020-10-29T19:01:09',
               'laps': parser.fit_laps(laps, lengths, {'pool_length': 25.0}, start)}
        assert reimport.propose(db, saved, act, 'Strava export') is False      # the same swim: nothing to choose
        assert json.loads(db.execute("SELECT laps FROM Activity WHERE id='s'").fetchone()[0])['pool_m'] == 25.0


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as app_module
    import config
    import database
    from services import credentials

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'web.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    start, laps, lengths = _fit_msgs()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET units='metric' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        ins = ("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageCadence, "
               "streams, laps) VALUES (?,?,?,1,?,?,?,?,?,?,?,?)")
        db.execute(ins, ['run', 'Parkrun', 'Run', '2026-10-01T09:00:00', 5000, 1500, 1500, 30, 85, json.dumps(streams(5000 / 1500, 1500)), None])
        db.execute(ins, ['pool', 'Pool', 'Swim', '2026-10-02T09:00:00', 100, 140, 140, 0, 22, None, parser.fit_laps(laps, lengths, {'pool_length': 25.0}, start)])
        db.execute(ins, ['sup', 'Paddle', 'Stand Up Paddling', '2026-10-03T09:00:00', 8000, 3600, 3600, 120, None, json.dumps(streams(2.2, 3600)), None])
        db.execute(ins, ['yoga', 'Yoga', 'Yoga', '2026-10-04T09:00:00', 0, 3600, 3600, 0, None, None, None])
        db.execute(ins, ['ride', 'Ride', 'Ride', '2026-10-05T09:00:00', 30000, 3600, 3600, 300, 80, json.dumps(streams(30000 / 3600, 3600)), None])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_each_sport_gets_its_own_page(client):
    run = client.get('/rides/run').get_data(as_text=True)
    assert 'Avg Pace' in run and '5:00 /km' in run and 'id="splitsCard"' in run and 'id="paceChart"' in run and '170 spm' in run
    assert 'id="speedChart"' not in run and 'Avg Speed' not in run
    pool = client.get('/rides/pool').get_data(as_text=True)
    assert 'id="poolCard"' in pool and 'Avg SWOLF' in pool and '3 &times; 25 m pool' in pool and 'Stroke Rate' in pool
    assert 'Elevation Gain' not in pool
    sup = client.get('/rides/sup').get_data(as_text=True)
    assert 'Avg Speed' in sup and 'Elevation Gain' not in sup and 'id="speedChart"' in sup     # speed worked out from distance and time
    yoga = client.get('/rides/yoga').get_data(as_text=True)
    assert '>Distance<' not in yoga and 'Avg Speed' not in yoga and 'Elevation Gain' not in yoga
    ride = client.get('/rides/ride').get_data(as_text=True)
    assert 'Avg Speed' in ride and '80 rpm' in ride and 'id="splitsCard"' not in ride and 'id="kitCard"' not in ride
