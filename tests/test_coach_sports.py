"""The AI coach for every sport (services/coach_sports.py, services/ai.py, services/context.py): a run is coached as a run, in pace, against the
rider's other runs; a strength session has no distance to talk about; the other sports around an activity are its other training, never its history.
The chat is faked, so the prompt is read instead of sent. Full app, throwaway DB."""
import json
import re
from datetime import date, timedelta

import pytest

import app as app_module
import config
import database
from services import ai, coach_sports, credentials
from services import streams as _streams

TODAY = date.today()


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _day(days_ago, hour=8):
    return (TODAY - timedelta(days=days_ago)).isoformat() + f'T{hour:02d}:00:00'


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute("UPDATE Settings SET units='metric' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Sam', 1)")
        add = ("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, averageSpeed, totalElevationGain, "
               "averageHeartrate, averageCadence) VALUES (?,?,?,1,?,?,?,?,?,?,?)")
        db.execute(add, ['run_now', 'Lunch run', 'Run', _day(0, 12), 10000, 3000, 3.333, 80, 150, 84])
        db.execute(add, ['run_before', 'Tempo run', 'Run', _day(5), 10000, 2900, 3.448, 70, 158, 86])
        db.execute(add, ['ride_before', 'Long ride', 'Ride', _day(2), 80000, 10800, 7.4, 900, 135, 85])
        db.execute(add, ['gym', 'Leg day', 'Strength', _day(1), None, 2700, None, None, 120, None])
        db.execute(add, ['gym_before', 'Upper body', 'Strength', _day(8), None, 2400, None, None, 115, None])
        db.execute(add, ['run_later', 'Next week run', 'Run', _day(-7), 10000, 2800, 3.571, 70, 150, 86])
        for aid, name, d, dist_mi, spd in (('run_before', 'Tempo run', 5, 6.2, 7.71), ('ride_before', 'Long ride', 2, 49.7, 16.55),
                                           ('run_later', 'Next week run', -7, 6.2, 7.99)):
            db.execute("INSERT INTO ActivityMemory (activityId, activityDate, activityName, distanceMi, movingTime, elevationFt, avgSpeedMph, avgHR) "
                       "VALUES (?,?,?,?,?,?,?,?)", [aid, _day(d)[:10], name, dist_mi, 2900, 230, spd, 150])
        db.execute("INSERT INTO ActivityMemory (activityId, activityDate, activityName, distanceMi, movingTime, elevationFt, avgSpeedMph, avgHR, calories) "
                   "VALUES ('gym_before', ?, 'Upper body', 0, 2400, 0, 0, 115, 300)", [_day(8)[:10]])
        db.commit()
    return a


def _prompt(app, act_id, monkeypatch, personality=None):
    sent = {}

    def fake_chat(messages, system=None, **kw):
        sent['system'], sent['user'] = system, messages[0]['content']
        return 'ok'
    monkeypatch.setattr(ai, 'get_chat', lambda: fake_chat)
    with app.app_context():
        act = database.get_db().execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [act_id]).fetchone()
        ai.generate_analysis(act, personality_key=personality)
    return sent['system'], sent['user']


def test_profiles():
    run, swim, gym, ride, kite = (coach_sports.profile(s) for s in ('Run', 'Swim', 'Strength', 'GravelRide', 'Kitesurf'))
    assert (run.noun, run.athlete, run.rate, run.cadence) == ('run', 'runner', 'pace', ('steps/min', 2))
    assert (swim.rate, swim.climbing, swim.cadence[0]) == ('swim', False, 'strokes/min')
    assert not gym.distance and gym.noun == 'strength session' and gym.nouns == 'strength sessions'
    assert (ride.family, ride.rate, ride.athlete) == ('ride', 'speed', 'cyclist') and coach_sports.profile(None).family == 'ride'
    assert not kite.climbing and kite.distance
    assert coach_sports.profile('TrailRun').family == coach_sports.profile('VirtualRun').family == 'run'


def test_every_personality_fills_in_for_every_sport():
    from services.sports import SPORTS
    for sport in SPORTS:
        p = coach_sports.profile(sport)
        words = {'rider_name': 'Sam', 'sport': p.sport_word, 'session': p.noun, 'athlete': p.athlete}
        for key, persona in ai.PERSONALITIES.items():
            text = persona['framing'].format(**words) + (persona['tone_override'] or '').format(**words)
            assert '{' not in text, (sport, key)
            if sport not in ('Ride', 'VirtualRide', 'EBikeRide', 'MountainBikeRide', 'GravelRide'):
                assert 'cycl' not in text.lower(), (sport, key)


def test_a_run_is_coached_as_a_run_against_runs(app, monkeypatch):
    system, user = _prompt(app, 'run_now', monkeypatch)
    assert 'running coach' in system and 'This is a run' in system
    assert 'Avg pace   : 5:00 /km' in user and 'Avg cadence: 168 steps/min' in user
    assert '🏃 The run' in user and '🚴 The ride' not in user
    history = user[user.index('HISTORY & CONTEXT'):]
    assert 'Tempo run' in history.split('Other training')[0]                    # the earlier run is its history
    assert 'Next week run' not in history                                         # nothing after it
    other = history[history.index('Other training'):]
    assert 'Long ride' in other and 'Leg day' in other                            # the ride and the gym are other training
    assert 'Long ride' not in history.split('Other training')[0]                  # never its history
    assert not re.search(r'\bmph\b|\d mi\b|/mi\b', user)                        # metric chosen


def test_a_ride_sees_the_runs_and_gym_around_it_as_other_training(app, monkeypatch):
    system, user = _prompt(app, 'ride_before', monkeypatch)
    assert 'cycling coach' in system and 'Avg speed' in user and '🚴 The ride' in user
    other = user[user.index('Other training'):]
    assert 'Tempo run' in other and 'Upper body' in other


def test_a_strength_session_has_no_distance_or_pace(app, monkeypatch):
    system, user = _prompt(app, 'gym', monkeypatch, personality='yoda')
    assert 'strength coach' in system and 'never invent them' in system
    current = user[:user.index('HISTORY & CONTEXT')]
    assert 'Distance' not in current and 'pace' not in current.lower() and 'Moving time: 45 min' in current
    assert 'Upper body' in user and '40 min' in user                             # its history, by time
    assert '⛰️ Climbing' not in user and '🏋️ The strength session' in user


def test_a_run_s_best_times_are_in_the_prompt(app, monkeypatch):
    streams = json.dumps({'distance': {'data': [i * 10.0 for i in range(601)]}, 'time': {'data': [i * 3 for i in range(601)]}})
    with app.app_context():
        db = database.get_db()
        _streams.save(db, 'run_now', streams)
        db.commit()
    _, user = _prompt(app, 'run_now', monkeypatch)
    assert 'Best times set on this run:' in user and 'Best 5 km: 25:00 (first recorded effort' in user


def test_the_activity_page_offers_the_coach_for_a_run(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    page = c.get('/activities/run_now').get_data(as_text=True)
    assert 'AI Coaching Analysis' in page and ('Analyse Activity' in page or 'Analyse with history' in page)
    assert c.get('/ai').status_code == 200
    assert c.get('/ai/count?force=1&sport=sport:Run').get_json() == {'count': 3}
    assert c.get('/ai/count?force=1&sport=group:ride').get_json() == {'count': 1}
    assert c.get('/ai/count?force=1').get_json() == {'count': 6}
