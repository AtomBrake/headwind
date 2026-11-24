"""Goals of any set of sports, beyond the Goals page (services/goals.py): Home Assistant's weekly activity sensor and its "looking stagnant" status
count the sports of the rider's weekly goal of a number of activities, and say there's none when they have none; the Nutrition page's typical
week of exercise covers the sports picked, with a value offered from their calories; the phone API's profile still sends rideGoalWeek, worked out
from the goal. Throwaway DBs."""
import json
from datetime import timedelta

import pytest

import database
from services import goals, insights, tz


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as app_module
    import config
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(config.Config, 'APP_URL', 'https://h.example')     # the outside address phones pair with
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
    return a


@pytest.fixture
def web(app):
    from services import credentials
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def add(app, aid, sport, days_ago, dist=5000, secs=1800, kcal=None):
    day = (tz.today() - timedelta(days=days_ago)).isoformat()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, movingTime, calories, riderId, rawData) "
                  "VALUES (?,?,?,?,?,?,?,1,'{}')", [aid, aid, sport, f'{day}T08:00:00', dist, secs, kcal])
        d.commit()


def weekly(app):
    from services import mqtt
    with app.test_request_context():
        return json.loads(mqtt._history_payloads(1)['nutrition_activity_weekly'])


def test_the_weekly_sensor_says_there_is_no_goal_and_counts_every_sport(app):
    add(app, 'ride', 'Ride', 0)
    add(app, 'run', 'Run', 0)
    w = weekly(app)
    assert w['ride_goal'] is None and w['goal_nouns'] == 'activities'          # no default of 2 rides
    assert w['rides'][-1] == 2 and w['trend'] == 'h'                            # a ride's and a run's miles don't add up


def test_the_weekly_sensor_counts_the_sports_of_the_weekly_goal(app):
    with app.app_context():
        assert goals.add_goal(database.get_db(), 1, 'count', 'week', ['group:ride', 'sport:Run'], '3') is None
    add(app, 'ride', 'Ride', 0)
    add(app, 'run', 'Run', 0)
    add(app, 'walk', 'Walk', 0)
    add(app, 'swim', 'Swim', 0)
    w = weekly(app)
    assert w['ride_goal'] == 3 and w['goal_nouns'] == 'rides or runs' and w['rides'][-1] == 2
    assert w['h'][-1] == 1.0 and w['trend'] == 'h'


def test_a_weekly_goal_of_rides_alone_keeps_the_trend_in_miles(app):
    with app.app_context():
        goals.add_goal(database.get_db(), 1, 'count', 'week', 'ride', '2')
    add(app, 'ride', 'Ride', 0, dist=16093.44)
    add(app, 'run', 'Run', 0)
    w = weekly(app)
    assert w['trend'] == 'mi' and w['mi'][-1] == 10.0 and w['rides'][-1] == 1


def test_activity_status_follows_the_trend_it_is_given():
    flat, rising = [5] * 10, [1, 1, 1, 1, 1, 9, 9, 9, 9, 0]
    assert insights.activity_status({'mi': flat, 'h': rising, 'trend': 'h'}) == 'ok'
    assert insights.activity_status({'mi': flat, 'h': rising, 'trend': 'mi'}) == 'stagnant'
    assert insights.activity_status({'mi': flat, 'h': rising}) == 'stagnant'                # a payload from before: miles


def test_the_allowance_covers_the_sports_picked_and_offers_their_calories(app, web):
    for i in range(8):                                                          # 8 weeks: a ride and a run each
        add(app, f'ride{i}', 'Ride', 1 + 7 * i, kcal=1000, secs=0)
        add(app, f'run{i}', 'Run', 2 + 7 * i, kcal=400, secs=0)
    add(app, 'old', 'Ride', 60, kcal=9000, secs=0)                              # before the 8 weeks
    add(app, 'today', 'Ride', 0, kcal=9000, secs=0)                             # today: the week isn't over
    d = web.get('/nutrition/api/goal-plan').get_json()
    assert 'ride_goal_week' not in d['profile']
    assert d['exercise']['sports'] is None and d['exercise']['suggest'] == 1400 and d['exercise']['nouns'] == 'every sport'
    r = web.post('/nutrition/api/goal-profile', json={'exercise_sports': ['group:ride'], 'ride_kcal_week': 1000})
    d = r.get_json()
    assert r.status_code == 200 and d['exercise']['sports'] == ['group:ride'] and d['exercise']['suggest'] == 1000
    assert d['profile']['ride_kcal_week'] == 1000 and d['exercise']['nouns'] == 'rides'
    assert web.post('/nutrition/api/goal-profile', json={'exercise_sports': []}).status_code == 400
    assert web.post('/nutrition/api/goal-profile', json={'step_goal': 9000}).get_json()['exercise']['sports'] == ['group:ride']   # left alone
    d = web.post('/nutrition/api/goal-profile', json={'exercise_sports': None}).get_json()
    assert d['exercise']['sports'] is None
    html = web.get('/nutrition/').get_data(as_text=True)
    assert 'Typical exercise (kcal / week)' in html and 'sgRideGoal' not in html


def test_the_phone_api_works_out_ride_goal_week_from_the_goal(app, web):
    token = web.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://h.example'}).get_json()['token']
    phone = app.test_client()
    h = {'Authorization': 'Bearer ' + token}
    p = phone.get('/api/v1/sync/nutrition', headers=h).get_json()['profile']
    assert p['rideGoalWeek'] is None and p['exerciseSports'] is None and 'rideKcalWeek' in p
    with app.app_context():
        goals.add_goal(database.get_db(), 1, 'count', 'week', ['group:ride', 'sport:Run'], '4')
    assert phone.get('/api/v1/sync/nutrition', headers=h).get_json()['profile']['rideGoalWeek'] == 4
