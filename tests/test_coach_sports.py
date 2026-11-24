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
        db.commit()
    return a


def _add(app, *rows):
    """More activities: (id, name, sport, rider, day, distance, moving time, speed, climb, power)."""
    with app.app_context():
        db = database.get_db()
        for r in rows:
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, averageSpeed, totalElevationGain, "
                       "averageWatts) VALUES (?,?,?,?,?,?,?,?,?,?)", list(r))
        db.commit()


def _history(user):
    """The prompt's history of the same kind of activity: up to the other training."""
    h = user[user.index('HISTORY & CONTEXT'):]
    return h.split('Other training')[0]


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
    # Each kind of ride or run is its own history: their speeds don't compare
    kinds = {s: coach_sports.profile(s) for s in ('Ride', None, 'MountainBikeRide', 'Mountain Bike Ride', 'VirtualRide', 'EBikeRide', 'Trail Run')}
    assert kinds['Ride'].kind == kinds[None].kind == 'ride' and kinds['MountainBikeRide'].kind == kinds['Mountain Bike Ride'].kind
    assert [kinds[s].kind_nouns for s in ('Ride', 'MountainBikeRide', 'VirtualRide', 'EBikeRide', 'Trail Run')] == \
        ['rides', 'mountain bike rides', 'indoor rides', 'e-bike rides', 'trail runs']
    assert kinds['VirtualRide'].kind_count(1) == '1 indoor ride' and gym.kind_count(2) == '2 strength sessions'


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


def test_a_run_s_history_is_every_earlier_run_analysed_or_not(app, monkeypatch):
    with app.app_context():
        assert database.get_db().execute('SELECT COUNT(*) FROM ActivityMemory').fetchone()[0] == 0     # nothing has been analysed
    _add(app, ('run_old', 'Easy run', 'Run', 1, _day(20), 8000, 2880, 2.778, 120, None))
    _, user = _prompt(app, 'run_now', monkeypatch)
    history = _history(user)
    assert 'No previous runs' not in user
    assert 'Run history (last 2 runs):' in history
    assert 'Tempo run' in history and 'Easy run' in history
    assert '10.0 km' in history and '4:50 /km' in history and '8.0 km' in history  # metres and m/s, in the rider's units
    assert 'Comparable runs' in history and '30-day summary (2 runs)' in history


def test_a_later_run_never_appears(app, monkeypatch):
    _, user = _prompt(app, 'run_now', monkeypatch)
    assert 'Next week run' not in user
    assert _day(-7)[:10] not in user


def test_another_rider_s_activities_never_appear(app, monkeypatch):
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name) VALUES (2, 'Alex')")
        db.commit()
    _add(app, ('alex_run', 'Alex parkrun', 'Run', 2, _day(3), 5000, 1300, 3.846, 30, None),
              ('alex_ride', 'Alex commute', 'Ride', 2, _day(1), 12000, 2400, 5.0, 60, None))
    _, user = _prompt(app, 'run_now', monkeypatch)
    assert 'Alex' not in user
    assert 'last 1 run' in _history(user)


def test_an_activity_with_nothing_recorded_is_left_out(app, monkeypatch):
    _add(app, ('run_empty', 'Apple Health run', 'Run', 1, _day(3), 0, 0, 0, 0, None),
              ('gym_empty', 'Apple Health strength', 'Strength', 1, _day(4), None, None, None, None, None))
    _, run = _prompt(app, 'run_now', monkeypatch)
    _, gym = _prompt(app, 'gym', monkeypatch)
    assert 'Apple Health' not in run and 'Apple Health' not in gym
    assert 'Upper body' in _history(gym)                                         # the strength session with a time still counts


def test_a_ride_without_power_named_ride_activity_counts(app, monkeypatch):
    _add(app, ('ride_plain', 'Ride Activity', 'Ride', 1, _day(9), 78000, 10500, 7.43, 850, None))
    _, user = _prompt(app, 'ride_before', monkeypatch)
    history = _history(user)
    assert 'Ride Activity' in history and 'Comparable rides' in history


def test_a_mountain_bike_ride_is_compared_with_mountain_bike_rides_only(app, monkeypatch):
    """Zwift's speeds are a game's and a mountain bike's are off-road: neither is a road ride's history, nor it theirs."""
    _add(app, ('mtb_before', 'Trail centre', 'Mountain Bike Ride', 1, _day(6), 30000, 7500, 4.0, 700, 190),     # Strava's spelling
              ('mtb_now', 'Woods loop', 'MountainBikeRide', 1, _day(1), 32000, 8000, 4.0, 750, 200),
              ('zwift', 'Watopia', 'VirtualRide', 1, _day(3), 32000, 3300, 9.7, 300, 230))
    system, user = _prompt(app, 'mtb_now', monkeypatch)
    history = _history(user)
    assert 'Trail centre' in history and 'Mountain bike ride history (last 1 mountain bike ride):' in history
    assert 'Watopia' not in history and 'Long ride' not in history
    other = user[user.index('Other training'):]
    assert 'Indoor ride — Watopia' in other and 'Ride — Long ride' in other      # still the training load
    assert "other mountain bike rides, not with other sports" in system and 'Zwift' in system
    _, road = _prompt(app, 'ride_before', monkeypatch)
    assert 'Watopia' not in _history(road) and 'Trail centre' not in _history(road)
    assert 'No previous rides recorded' in road and 'Other kinds are under other training' in road


def test_a_trail_run_is_compared_with_trail_runs_only(app, monkeypatch):
    _add(app, ('trail', 'Fell race', 'Trail Run', 1, _day(3), 10000, 4200, 2.38, 600, None))
    _, run = _prompt(app, 'run_now', monkeypatch)
    assert 'Fell race' not in _history(run) and 'Fell race' in run[run.index('Other training'):]
    _, trail = _prompt(app, 'trail', monkeypatch)
    assert 'No previous trail runs recorded' in trail and 'Tempo run' not in _history(trail)


def test_a_ride_s_best_times_are_held_against_its_own_kind(app, monkeypatch):
    """A road ride's best 10 km isn't beaten by Zwift's, nor measured against it."""
    _add(app, ('zwift', 'Watopia', 'VirtualRide', 1, _day(9), 32000, 3300, 9.7, 300, 230),
              ('road_old', 'Club run', 'Ride', 1, _day(20), 40000, 5400, 7.4, 400, None))
    with app.app_context():
        db = database.get_db()
        add = 'INSERT INTO BestEffortKm (activityId, activityDate, distanceKm, elapsedSecs, avgSpeedMps) VALUES (?,?,?,?,?)'
        db.execute(add, ['zwift', _day(9)[:10], 10, 1030, 9.7])
        db.execute(add, ['road_old', _day(20)[:10], 10, 1300, 7.7])
        db.execute(add, ['ride_before', _day(2)[:10], 10, 1250, 8.0])
        db.commit()
    _, user = _prompt(app, 'ride_before', monkeypatch)
    assert 'Fastest 10 km: 20:50' in user and 'beat previous best of 21:40' in user and '17:10' not in user


def test_a_ride_slower_than_its_best_is_not_called_a_best(app, monkeypatch):
    """It used to read "beat previous best of 18:20 by -2:30" for every bracket, beaten or not; and a best set after it isn't one it beat."""
    _add(app, ('road_old', 'Club run', 'Ride', 1, _day(20), 40000, 5400, 7.4, 400, None),
              ('road_new', 'Chaingang', 'Ride', 1, _day(-3), 40000, 4800, 8.3, 400, None))
    with app.app_context():
        db = database.get_db()
        add = 'INSERT INTO BestEffortKm (activityId, activityDate, distanceKm, elapsedSecs, avgSpeedMps) VALUES (?,?,?,?,?)'
        db.execute(add, ['road_old', _day(20)[:10], 10, 1100, 9.1])
        db.execute(add, ['road_old', _day(20)[:10], 20, 2700, 7.4])
        db.execute(add, ['road_new', _day(-3)[:10], 20, 2000, 10.0])
        db.execute(add, ['ride_before', _day(2)[:10], 10, 1250, 8.0])
        db.execute(add, ['ride_before', _day(2)[:10], 20, 2600, 7.7])
        db.commit()
    _, user = _prompt(app, 'ride_before', monkeypatch)
    assert 'Fastest 10 km' not in user and 'Quickest stretches against personal bests: 10 km 20:50 (best 18:20' in user
    assert 'Fastest 20 km: 43:20' in user and 'beat previous best of 45:00' in user and '33:20' not in user


def test_analyse_with_history_means_earlier_activities_of_the_kind(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    assert 'comparing this run with your earlier runs' in c.get('/activities/run_now').get_data(as_text=True)
    first_gym = c.get('/activities/gym_before').get_data(as_text=True)              # nothing before it, though there's a later one
    assert 'Analyse with history' not in first_gym and 'Analyse Activity' in first_gym
    assert 'Analyse with history' in c.get('/activities/gym').get_data(as_text=True)


# ── Progress by month (Settings.coachProgressFrom) and the coach's earlier verdicts ──

def _setting(app, value):
    with app.app_context():
        db = database.get_db()
        db.execute('UPDATE Settings SET coachProgressFrom=? WHERE id=1', [value])
        db.commit()


def _months_of_runs(app):
    """A run in each of the 3 months before run_now's, slower the further back."""
    _add(app, *[(f'run_m{m}', f'Month {m} run', 'Run', 1, _day(31 * m), 10000, 3000 + 120 * m, 10000 / (3000 + 120 * m), 50, None)
                for m in (1, 2, 3)])


def test_progress_setting_reads_every_choice():
    from services.context import progress_setting
    assert progress_setting(None) == ('6m', None) and progress_setting('junk') == ('6m', None)
    assert progress_setting('12m') == ('12m', None) and progress_setting('off') == ('off', None)
    assert progress_setting('2026-09-27') == ('since', '2026-09-27')


def test_progress_by_month_covers_the_last_6_months_by_default(app, monkeypatch):
    _months_of_runs(app)
    _, user = _prompt(app, 'run_now', monkeypatch)
    assert 'Progress by month, runs (the last 6 months' in user and 'Comeback' not in user
    assert '⚠️ partial month' in user                                            # the activity's own month


def test_progress_since_a_comeback_starts_on_its_date(app, monkeypatch):
    _months_of_runs(app)
    since = (TODAY - timedelta(days=70)).isoformat()
    _setting(app, since)
    _, user = _prompt(app, 'run_now', monkeypatch)
    progress = user[user.index('Comeback progress by month, runs (since the comeback on'):].split('\n\n')[0]
    assert (TODAY - timedelta(days=93)).strftime('%Y-%m') not in progress           # the run before the comeback is left out
    assert (TODAY - timedelta(days=62)).strftime('%Y-%m') in progress


def test_progress_can_be_turned_off(app, monkeypatch):
    _months_of_runs(app)
    _setting(app, 'off')
    _, user = _prompt(app, 'run_now', monkeypatch)
    assert 'Progress by month' not in user and 'Comeback progress' not in user


def test_an_older_activity_s_progress_ends_on_its_own_month(app, monkeypatch):
    _months_of_runs(app)
    _, user = _prompt(app, 'run_m1', monkeypatch)                                  # analysed today, a month after it
    progress = user[user.index('Progress by month'):].split('\n\n')[0]
    months = re.findall(r'^  (\d{4}-\d{2})', progress, re.M)
    assert len(months) >= 2 and max(months) <= (TODAY - timedelta(days=31)).strftime('%Y-%m')     # nothing after it, not even run_now's month


def test_the_30_day_trend_reads_oldest_to_newest(app, monkeypatch):
    _add(app, *[(f'run_t{i}', f'Build {i}', 'Run', 1, _day(25 - 5 * i), 5000 + 2000 * i, 1800 + 700 * i, 2.9, 20, None) for i in range(4)])
    _, user = _prompt(app, 'run_now', monkeypatch)
    summary = user[user.index('30-day summary'):].split('\n\n')[0]
    assert 'Distance : ' in summary and summary.split('Distance : ')[1].split('\n')[0].endswith('trending up')   # 5, 7, 9, 11, 10 km


VERDICT_NOTE = """🏃 **The run**
Steady from the gun.

🎯 **Honest verdict**
A good day: the pacing held and the heart rate didn't drift. Hard to say more from one run.

The last kilometre was the quickest."""


def test_the_coach_sees_its_verdicts_on_earlier_runs_only(app, monkeypatch):
    with app.app_context():
        db = database.get_db()
        db.execute('UPDATE Activity SET aiKudos=? WHERE id=?', [VERDICT_NOTE, 'run_before'])
        db.execute('UPDATE Activity SET aiKudos=? WHERE id=?', ['🎯 **Honest verdict**\nThe future run.', 'run_later'])
        db.execute('UPDATE Activity SET aiKudos=? WHERE id=?', ['🎯 **Honest verdict**\nThe ride.', 'ride_before'])
        db.execute('UPDATE Activity SET aiKudos=? WHERE id=?', ['🎯 **Honest verdict**\nThis very run, last time.', 'run_now'])
        db.commit()
    system, user = _prompt(app, 'run_now', monkeypatch)
    notes = user[user.index('Your verdicts on the last 1 run you analysed'):].split('\n\n')[0]
    assert 'Tempo run: A good day: the pacing held and the heart rate didn\'t drift. Hard to say more from one run.' in notes
    assert 'future run' not in user and 'The ride.' not in user and 'This very run' not in user
    assert 'YOUR EARLIER VERDICTS' in system


def test_a_verdict_is_one_plain_line():
    from services.context import _verdict
    assert _verdict(VERDICT_NOTE) == "A good day: the pacing held and the heart rate didn't drift. Hard to say more from one run."
    assert _verdict('🎯 **Verdict**\n\nOn its own paragraph.\n\nClosing line.') == 'On its own paragraph.'
    assert _verdict('No headers at all.\nSecond line.') == 'No headers at all. Second line.'
    long = 'A first sentence that runs on ' + 'and on ' * 30 + 'to here. ' + 'word ' * 100
    assert _verdict(long).endswith('to here.') and len(_verdict(long)) <= 300
    assert _verdict('word ' * 100).endswith('word…')
    assert _verdict('') == ''


def test_the_ai_page_saves_the_progress_choice(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av

    def saved():
        with app.app_context():
            return database.get_db().execute('SELECT coachProgressFrom FROM Settings WHERE id=1').fetchone()[0]
    page = c.get('/ai').get_data(as_text=True)
    assert '<option value="6m" selected>' in page and 'id="progressFrom"' in page
    c.post('/ai/goals', data={'goals': 'Back from an ankle injury', 'progress': 'since', 'progress_from': '2026-09-27'})
    assert saved() == '2026-09-27'
    page = c.get('/ai').get_data(as_text=True)
    assert '<option value="since" selected>' in page and 'value="2026-09-27"' in page
    c.post('/ai/goals', data={'goals': 'x', 'progress': 'since', 'progress_from': ''})        # no date: kept as it was
    assert saved() == '2026-09-27'
    c.post('/ai/goals', data={'goals': 'x', 'progress': 'off'})
    assert saved() == 'off'
    c.post('/ai/goals', data={'goals': 'x', 'progress': '1y'})                                # not a choice: kept
    assert saved() == 'off'
