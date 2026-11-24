"""Feature switches (services/features.py): a feature turned off in Settings → Features leaves the sidebar and the dashboard, its pages show the
"turned off in Settings" note and its API a JSON error, its background work stops, and its data is kept for when it's turned on again. Health is
over Nutrition, Steps, Weight and Recovery without changing them. Full app, throwaway DB."""
import json

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, device_auth, features, jobs


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
        db.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    return app_module.create_app()


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def run(app, fn):
    with app.app_context():
        db = database.get_db()
        out = fn(db)
        db.commit()
        return out


GOAL_SPORT = 'ride'


def switch(client, *off, default=False):
    """Settings → Features with every box ticked but these."""
    data = {'on': [n for n in features.NAMES if n not in off]}
    if default:
        data['default'] = '1'
    r = client.post('/settings/features', data=data)
    assert r.status_code == 302 and r.headers['Location'].endswith('/settings#features')


def stored(app, rider_id=1):
    return run(app, lambda db: features.stored(rider_id, db))


def is_on(app, name, rider_id=1):
    return run(app, lambda db: features.on(name, rider_id))


# ── The table of endpoints ──────────────────────────────────────────────

def test_every_endpoint_and_blueprint_named_is_real(app):
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    blueprints = set(app.blueprints)
    assert set(features.ENDPOINTS) <= endpoints, set(features.ENDPOINTS) - endpoints
    assert set(features.EXEMPT) <= endpoints
    assert set(features.BLUEPRINTS) <= blueprints, set(features.BLUEPRINTS) - blueprints
    for need in list(features.ENDPOINTS.values()) + list(features.BLUEPRINTS.values()):
        for name in (need if isinstance(need, tuple) else (need,)):
            assert name in features.BY_KEY


def test_an_unknown_name_is_an_error_not_quietly_on(app):
    with app.test_request_context('/'):
        with pytest.raises(KeyError):
            features.on('nutritoin')


def test_outside_a_request_the_rider_must_be_given(app):
    with app.app_context():
        with pytest.raises(ValueError):
            features.on('nutrition')
        assert features.on('nutrition', 1)


# ── Where they're kept ──────────────────────────────────────────────────

def test_step_13_makes_rider_settings_and_the_default(app):
    def cols(db, t):
        return {r[1] for r in db.execute(f'PRAGMA table_info({t})')}
    assert {'riderId', 'featuresOff'} <= run(app, lambda db: cols(db, 'RiderSettings'))
    assert 'featuresOff' in run(app, lambda db: cols(db, 'Settings'))


def test_each_rider_has_their_own_and_a_new_one_takes_the_default(app, client):
    switch(client, 'heatmap')
    assert stored(app, 1) == {'heatmap'}
    assert stored(app, 2) == frozenset()                # Sam has no row: the instance default, everything on
    switch(client, 'heatmap', 'coach', default=True)
    assert stored(app, 1) == {'heatmap', 'coach'}
    assert stored(app, 2) == {'heatmap', 'coach'}       # still no row of their own: a new or untouched rider follows the default
    run(app, lambda db: features.save(db, 2, set()))
    switch(client, default=True)                       # everything on again, for Tom and as the default
    assert stored(app, 2) == frozenset() and stored(app, 1) == frozenset()


def test_a_deleted_riders_switches_go_with_them(app, client):
    run(app, lambda db: features.save(db, 2, {'goals'}))
    with app.test_request_context('/'):
        db = database.get_db()
        features.forget_rider(db, 2)
        db.commit()
        assert db.execute('SELECT COUNT(*) FROM RiderSettings WHERE riderId=2').fetchone()[0] == 0


# ── Health over its four ────────────────────────────────────────────────

def test_health_overrides_its_four_without_changing_them(app, client):
    switch(client, 'steps')                            # Steps off on its own first
    assert not is_on(app, 'steps') and is_on(app, 'nutrition')
    switch(client, 'health', 'steps')                  # then Health off: the four boxes are sent as they were
    assert stored(app) == {'health', 'steps'}          # Nutrition, Weight and Recovery are still set on
    for name in ('nutrition', 'steps', 'weight', 'recovery'):
        assert not is_on(app, name)
    page = client.get('/settings/').get_data(as_text=True)
    assert 'id="featureParts-health"' in page and 'feature-parts is-dimmed' in page
    switch(client, 'steps')                            # Health back on: the same choices as before
    assert is_on(app, 'nutrition') and is_on(app, 'weight') and is_on(app, 'recovery') and not is_on(app, 'steps')


def test_gear_is_over_gear_maintenance(app, client):
    switch(client, 'gear')
    assert not is_on(app, 'maintenance') and stored(app) == {'gear'}
    switch(client)
    assert is_on(app, 'maintenance')


# ── The sidebar, the dashboard and the pages ────────────────────────────

SIDEBAR = {'nutrition': 'href="/nutrition/"', 'steps': 'href="/nutrition/steps"', 'weight': 'href="/nutrition/weight"',
           'recovery': 'href="/recovery"', 'goals': 'href="/goals"', 'segments': 'href="/segments"', 'routes': 'href="/routes/"',
           'gear': 'href="/gear/"', 'heatmap': 'href="/heatmap"', 'coach': 'href="/ai"'}


def test_a_switched_off_feature_leaves_the_sidebar(client):
    page = client.get('/dashboard').get_data(as_text=True)
    for link in SIDEBAR.values():
        assert link in page, link
    assert '>Health</div>' in page
    switch(client, *SIDEBAR)
    page = client.get('/dashboard').get_data(as_text=True)
    for link in SIDEBAR.values():
        assert link not in page, link
    assert '>Health</div>' not in page                 # nothing left under it
    switch(client, 'nutrition', 'steps')               # Weight on: the heading is back for it
    page = client.get('/dashboard').get_data(as_text=True)
    assert '>Health</div>' in page and SIDEBAR['weight'] in page and SIDEBAR['nutrition'] not in page


def test_the_health_heading_goes_with_health(client):
    switch(client, 'health')
    page = client.get('/dashboard').get_data(as_text=True)
    assert '>Health</div>' not in page and SIDEBAR['recovery'] not in page


@pytest.mark.parametrize('name, url', [('nutrition', '/nutrition/'), ('steps', '/nutrition/steps'), ('weight', '/nutrition/weight'),
                                       ('weight', '/nutrition/weight/backfill'), ('recovery', '/recovery'), ('goals', '/goals'),
                                       ('segments', '/segments'), ('routes', '/routes/'), ('heatmap', '/heatmap'), ('coach', '/ai'),
                                       ('friends', '/friends'), ('gear', '/gear/'), ('roughness', '/roughness'), ('planner', '/planner/')])
def test_its_pages_show_the_note_not_a_404(client, name, url):
    assert client.get(url).status_code == 200
    switch(client, name)
    r = client.get(url)
    page = r.get_data(as_text=True)
    assert r.status_code == 403 and 'is turned off in Settings' in page and f'data-feature="{name}"' in page
    assert 'href="/settings/#features"' in page
    switch(client)
    assert client.get(url).status_code == 200


def test_a_part_of_health_says_health_is_off(client):
    switch(client, 'health')
    page = client.get('/nutrition/steps').get_data(as_text=True)
    assert "It's part of Health, which is off" in page


def test_its_api_answers_with_a_clear_json_error(client):
    switch(client, 'nutrition')
    r = client.get('/nutrition/api/day/2026-11-20')
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Nutrition is turned off in Settings.', 'feature_off': 'nutrition', 'settings_url': '/settings#features'}
    r = client.post('/nutrition/api/water', json={'ml': 250})
    assert r.status_code == 403 and r.get_json()['feature_off'] == 'nutrition'


def test_the_nutrition_page_still_logs_weight_with_weight_off(client):
    switch(client, 'weight')
    assert client.get('/nutrition/api/weight/settings').status_code == 200      # the Nutrition page's weigh-ins
    assert client.get('/nutrition/api/weight/graph').status_code == 403         # the Weight page's own
    switch(client, 'weight', 'nutrition')
    assert client.get('/nutrition/api/weight/settings').status_code == 403


def test_recovery_today_leaves_the_dashboard_and_comes_back(app, client):
    run(app, lambda db: db.execute("INSERT INTO GarminDaily (date, restingHR, bodyBattery, sleepHours) VALUES ('2026-11-20', 48, 80, 7.5)"))
    assert 'Recovery Today' in client.get('/dashboard').get_data(as_text=True)
    switch(client, 'recovery')
    assert 'Recovery Today' not in client.get('/dashboard').get_data(as_text=True)
    assert run(app, lambda db: db.execute('SELECT COUNT(*) FROM GarminDaily').fetchone()[0]) == 1      # kept
    switch(client)
    assert 'Recovery Today' in client.get('/dashboard').get_data(as_text=True)


def test_the_goals_card_and_friends_button_leave_the_dashboard(app, client):
    from services import goals
    assert run(app, lambda db: goals.add_goal(db, 1, 'count', 'year', GOAL_SPORT, '50')) is None
    page = client.get('/dashboard').get_data(as_text=True)
    assert 'href="/friends"' in page and 'card-title">Goals<' in page
    switch(client, 'friends', 'goals')
    page = client.get('/dashboard').get_data(as_text=True)
    assert 'href="/friends"' not in page and 'card-title">Goals<' not in page


def test_the_gear_due_list_leaves_with_maintenance_but_the_bikes_stay(app, client):
    from services import gear
    bike = run(app, lambda db: gear.create_bike(db, 1, 'Roadie'))
    assert 'id="partCatalog"' in client.get(f'/gear/bike/{bike}').get_data(as_text=True)
    switch(client, 'maintenance')
    r = client.get('/gear/')
    assert r.status_code == 200 and 'Roadie' in r.get_data(as_text=True)       # Gear itself is still on, the bike too
    assert 'Needs attention' not in r.get_data(as_text=True)
    page = client.get(f'/gear/bike/{bike}').get_data(as_text=True)
    assert 'Roadie' in page and 'id="partCatalog"' not in page                 # no parts or service log
    assert client.post(f'/gear/bike/{bike}/part', data={'name': 'Chain'}).status_code == 403


def test_kit_keeps_its_replace_at_when_saved_with_maintenance_off(app, client):
    from services import kit
    kid = run(app, lambda db: kit.create(db, 1, 'Trainers', 'shoes', None, None, None, 0, 800000, None))
    switch(client, 'maintenance')
    assert 'name="replace"' not in client.get(f'/gear/kit/{kid}/edit').get_data(as_text=True)
    r = client.post('/gear/kit/save', data={'id': kid, 'name': 'Old trainers', 'kind': 'shoes'})
    assert r.status_code == 302
    row = run(app, lambda db: kit.get(db, kid))
    assert row['name'] == 'Old trainers' and row['replaceAtM'] == 800000


def test_the_edit_form_turns_an_items_warnings_off_and_keeps_them_with_maintenance_off(app, client):
    from services import gear, kit
    kid = run(app, lambda db: kit.create(db, 1, 'Beach shoes', 'shoes', None, None, None, 0, 100000, None))
    bike = run(app, lambda db: gear.create_bike(db, 1, 'Turbo'))
    assert 'name="warnings" value="1" checked' in client.get(f'/gear/kit/{kid}/edit').get_data(as_text=True)
    client.post('/gear/kit/save', data={'id': kid, 'name': 'Beach shoes', 'kind': 'shoes', 'replace': '100', 'warnings_shown': '1'})
    client.post('/gear/bike/save', data={'id': bike, 'name': 'Turbo', 'kind': 'road', 'warnings_shown': '1'})
    r = client.post('/gear/bike/save', data={'name': 'Spare', 'kind': 'road', 'warnings_shown': '1'})     # a new one, unticked from the start
    spare = int(r.headers['Location'].rstrip('/').split('/')[-1])
    assert run(app, lambda db: [kit.get(db, kid)['noWarnings'], gear.get_bike(db, bike)['noWarnings'], gear.get_bike(db, spare)['noWarnings']]) == [1, 1, 1]
    assert 'No warnings' in client.get(f'/gear/kit/{kid}').get_data(as_text=True)
    assert 'name="warnings" value="1" >' in client.get(f'/gear/bike/{bike}/edit').get_data(as_text=True)
    client.post('/gear/bike/save', data={'id': bike, 'name': 'Turbo', 'kind': 'road', 'warnings_shown': '1', 'warnings': '1'})
    assert run(app, lambda db: gear.get_bike(db, bike)['noWarnings']) == 0
    switch(client, 'maintenance')
    assert 'name="warnings"' not in client.get(f'/gear/kit/{kid}/edit').get_data(as_text=True)
    client.post('/gear/kit/save', data={'id': kid, 'name': 'Beach shoes', 'kind': 'shoes'})        # no box: what was set stays
    assert run(app, lambda db: kit.get(db, kid)['noWarnings']) == 1
    assert 'No warnings' not in client.get(f'/gear/kit/{kid}').get_data(as_text=True)


# ── The phone's API ─────────────────────────────────────────────────────

@pytest.fixture
def phone(app):
    with app.app_context():
        token = device_auth.create('Test phone')[0]
    return {'Authorization': f'Bearer {token}'}


def test_ping_lists_what_is_off(client, phone):
    assert client.get('/api/v1/ping', headers=phone).get_json()['features_off'] == []
    switch(client, 'health', 'friends')
    got = client.get('/api/v1/ping', headers=phone).get_json()['features_off']
    assert got == ['friends', 'health', 'nutrition', 'recovery', 'steps', 'weight']      # the four come with Health


def test_the_apps_endpoints_refuse_and_the_mixed_ones_leave_it_out(client, phone):
    switch(client, 'nutrition', 'recovery', 'segments', 'friends', 'live')
    for method, url in (('get', '/api/v1/sync/nutrition'), ('get', '/nutrition/api/recent'), ('get', '/api/v1/friends'),
                        ('get', '/api/v1/contacts'), ('post', '/api/v1/live/share')):
        r = getattr(client, method)(url, headers=phone, json={})
        assert r.status_code == 403 and r.get_json()['feature_off'], url
    today = client.get('/api/v1/today', headers=phone).get_json()
    assert today['entries'] == [] and today['steps'] is not None              # no food diary; Steps is still on
    assert client.get('/api/v1/overview', headers=phone).get_json()['recovery'] is None
    assert client.get('/api/v1/perform', headers=phone).get_json()['segments'] == []


# ── Background work ─────────────────────────────────────────────────────

def test_the_garmin_health_sync_reads_only_what_is_on(app, client, monkeypatch):
    from services import garmin
    read, weighed = [], []
    monkeypatch.setattr(garmin, '_fetch_day', lambda call, api, d: read.append(d) or {})
    monkeypatch.setattr(garmin, '_save_day', lambda db, d, m: None)
    monkeypatch.setattr(garmin, '_sync_weigh_ins', lambda api, db, rid, a, b: weighed.append(rid) or (0, 0))

    def sync():
        read.clear(); weighed.clear()
        return run(app, lambda db: garmin.sync_garmin(1, days=3, api=object()))
    assert sync() == 3 and len(read) == 3 and weighed == [1]
    switch(client, 'recovery')                          # Steps and Nutrition still need the daily figures
    assert sync() == 3 and len(read) == 3
    switch(client, 'recovery', 'steps', 'nutrition')    # nothing needs them; Weight still wants the weigh-ins
    assert sync() == 0 and read == [] and weighed == [1]
    switch(client, 'health')
    assert sync() == 0 and read == [] and weighed == []
    switch(client)
    assert sync() == 3 and weighed == [1]


def test_part_alerts_stop_with_maintenance_off(app, client, monkeypatch):
    from services import gear
    sent = []
    monkeypatch.setattr(gear, '_notify', lambda alerts: sent.append(alerts))
    switch(client, 'maintenance')
    quiet = run(app, lambda db: features.riders_without('maintenance', db))
    assert quiet == {1}                                 # Tom's switch; Sam has no row, so the default (on)
    assert run(app, lambda db: gear.evaluate_alerts(db, rider_id=1)) == []
    assert sent == []


def test_the_coach_doesnt_analyse_new_rides_with_it_off(app, client):
    from services import auto_analyse
    run(app, lambda db: db.execute("UPDATE Settings SET aiAutoAnalyse=1 WHERE id=1"))
    run(app, lambda db: db.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, movingTime, riderId, rawData) "
                                   "VALUES ('r1', 'Ride', 'Ride', datetime('now', 'localtime'), 10000, 1800, 1, '{}')"))
    assert run(app, lambda db: auto_analyse._wanted(db, 'r1'))
    switch(client, 'coach')
    assert not run(app, lambda db: auto_analyse._wanted(db, 'r1'))


def test_the_coach_leaves_out_recovery_and_steps_when_off(app, client, monkeypatch):
    from services import context, health
    real = health.recovery_days
    monkeypatch.setattr(health, 'recovery_days', lambda rid, until, days=3: [{**r, 'steps': 9876} for r in real(rid, until, days)])
    run(app, lambda db: db.execute("INSERT INTO GarminDaily (date, restingHR, steps) VALUES (date('now', 'localtime'), 48, 9876)"))
    run(app, lambda db: db.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, movingTime, riderId, rawData) "
                                   "VALUES ('r2', 'Ride', 'Ride', datetime('now', 'localtime'), 10000, 1800, 1, '{}')"))

    def ctx():
        with app.app_context():
            a = database.get_db().execute('SELECT * FROM Activity WHERE id=?', ['r2']).fetchone()
            return context.build_context(a)
    assert 'resting HR 48' in ctx() and 'steps 9,876' in ctx()
    switch(client, 'steps')
    assert 'resting HR 48' in ctx() and 'steps 9,876' not in ctx()
    switch(client, 'recovery')
    assert 'resting HR 48' not in ctx()


def test_calorie_goals_count_rides_only_with_steps_off(app, client):
    from services import goal_model
    run(app, lambda db: db.execute("UPDATE Settings SET stepGoal=12000 WHERE id=1"))
    with_steps = run(app, lambda db: goal_model.profile(1))
    assert with_steps['steps_counted'] and with_steps['activity'] > goal_model.SEDENTARY
    switch(client, 'steps')
    without = run(app, lambda db: goal_model.profile(1))
    assert not without['steps_counted'] and without['activity'] == goal_model.SEDENTARY
    assert run(app, lambda db: goal_model.profile())['activity'] == with_steps['activity']    # no rider: as before there were switches


def test_home_assistant_entities_are_taken_down_and_come_back(app, client, monkeypatch):
    from services import mqtt
    sent = []
    monkeypatch.setattr(mqtt, 'broker', lambda: ('broker', 1883, None, None))
    monkeypatch.setattr(mqtt, '_broker_send', lambda msgs, *conn: sent.extend(msgs))
    monkeypatch.setattr(mqtt, '_last_state', {})
    monkeypatch.setattr(mqtt, '_taken_down', set())
    monkeypatch.setattr(mqtt, '_fail_count', 0)
    monkeypatch.setattr(mqtt, '_next_retry', 0.0)
    cfg = 'homeassistant/sensor/bike_tracker_garmin_hrv/config'

    def push():
        sent.clear()
        with app.app_context():
            mqtt.push_update()
        return {m['topic']: m['payload'] for m in sent}
    first = push()
    assert first[cfg] and json.loads(first[cfg])['name'] == 'Recovery HRV'
    sent.clear()
    switch(client, 'recovery')                          # saving the switches queues the update for the worker
    jobs.run_queued(app)
    gone = {m['topic']: m['payload'] for m in sent}
    assert 'homeassistant/sensor/bike_tracker_garmin_steps/config' not in gone     # Steps is still on
    assert gone[cfg] == '' and gone['homeassistant/sensor/bike_tracker_garmin_hrv/state'] == ''
    assert mqtt._taken_down >= {'garmin_hrv', 'nutrition_recovery_history'}
    assert 'garmin_steps' not in mqtt._taken_down       # Steps is still on
    assert push().get(cfg) is None                      # taken down once, not again on every push
    sent.clear()
    switch(client)                                      # on again: published afresh as the switches are saved
    jobs.run_queued(app)
    got = {m['topic']: m['payload'] for m in sent}
    assert got.get(cfg) and json.loads(got[cfg])['name'] == 'Recovery HRV'
