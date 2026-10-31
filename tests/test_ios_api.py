"""The phone API the iPhone and Watch apps use beyond recording rides: every sport in the Overview, sessions with no track (strength, a pool swim),
Apple Health's daily figures, photos, and the Watch's own token."""
from datetime import date, timedelta
from io import BytesIO

import pytest

import database
from services import sports, tz


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def phone(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
        d.commit()
        av = credentials.auth_version()
    web = app.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    token = web.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://h.example'}).get_json()['token']
    c = app.test_client()
    c.app_, c.web, c.H = app, web, {'Authorization': 'Bearer ' + token}
    return c


def db(phone):
    return database.get_db()


def add(phone, aid, sport, day, dist=0, secs=1800, kcal=100, rider=1):
    with phone.app_.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Activity (id, riderId, type, sportType, name, startDate, startDateLocal, distance, movingTime, elapsedTime, "
                  "totalElevationGain, calories, rawData) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'{}')",
                  [aid, rider, sport, sport, aid, f'{day}T08:00:00Z', f'{day}T08:00:00', dist, secs, secs, 10, kcal])
        d.commit()


# ── Strength, HIIT and Yoga ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('key, sport', [
    ('strength_training', 'Strength'), ('Weight Training', 'Strength'), ('Crossfit', 'Strength'), ('TraditionalStrengthTraining', 'Strength'),
    ('FunctionalStrengthTraining', 'Strength'), ('CoreTraining', 'Strength'), ('hiit', 'HIIT'), ('HighIntensityIntervalTraining', 'HIIT'),
    ('yoga', 'Yoga'), ('Yoga', 'Yoga'), ('pilates', 'Other'), ('MindAndBody', 'Other'),
    ('indoor_rowing', 'Row'), ('running', 'Run'), ('lap_swimming', 'Swim'),          # unchanged
])
def test_strength_hiit_and_yoga_are_sports(key, sport):
    assert sports.from_type(key) == sport


def test_they_stay_out_of_the_ride_and_on_foot_totals():
    for s in ('Strength', 'HIIT', 'Yoga'):
        assert not sports.is_ride(s) and sports.stat_group(s) == s and sports.segment_family(s) is None
        assert s in sports.SPORTS and sports.icon(s) != '🏅'


# ── Sessions with no track ─────────────────────────────────────────────────────────────

def test_a_strength_session_needs_no_distance_and_gets_met_calories(phone):
    with phone.app_.app_context():
        database.get_db().execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (1, ?, 80, 'manual')", [tz.today().isoformat()])
        database.get_db().commit()
    r = phone.post('/api/v1/activities', headers=phone.H, json={
        'sport': 'Strength', 'start': '2026-10-20T18:30:00+01:00', 'duration_s': 3600, 'client_id': 'abc', 'source': 'ios', 'avg_hr': 112})
    assert r.status_code == 201, r.get_json()
    with phone.app_.app_context():
        a = database.get_db().execute('SELECT sportType, distance, calories, source, averageHeartrate, startDateLocal FROM Activity WHERE id=?',
                                      [r.get_json()['id']]).fetchone()
    assert (a['sportType'], a['distance'], a['source'], a['averageHeartrate']) == ('Strength', 0, 'ios', 112)
    assert a['calories'] == 280                       # 3.5 MET x 80 kg x 1 h
    assert a['startDateLocal'] == '2026-10-20T18:30:00'    # +01:00 is London's summer time
    again = phone.post('/api/v1/activities', headers=phone.H, json={
        'sport': 'Strength', 'start': '2026-10-20T18:30:00+01:00', 'duration_s': 3600, 'client_id': 'abc', 'source': 'ios'})
    assert again.status_code == 200 and again.get_json()['status'] == 'exists'


def test_a_pool_swim_keeps_the_watchs_calories(phone):
    r = phone.post('/api/v1/activities', headers=phone.H, json={
        'sport': 'Swim', 'start': '2026-10-21T07:00:00Z', 'duration_s': 1800, 'distance_m': 1500, 'calories': 321, 'source': 'ios'})
    assert r.status_code == 201
    with phone.app_.app_context():
        a = database.get_db().execute('SELECT distance, calories, caloriesRaw FROM Activity WHERE id=?', [r.get_json()['id']]).fetchone()
    assert (a['distance'], a['calories'], a['caloriesRaw']) == (1500, 321, None)


def test_a_session_still_refuses_what_it_cant_be(phone):
    bad = phone.post('/api/v1/activities', headers=phone.H, json={'sport': 'Darts', 'start': '2026-10-21T07:00:00Z', 'duration_s': 1800})
    assert bad.status_code == 400
    short = phone.post('/api/v1/activities', headers=phone.H, json={'sport': 'Yoga', 'start': '2026-10-21T07:00:00Z', 'duration_s': 10})
    assert short.status_code == 400


# ── Every sport in the Overview ────────────────────────────────────────────────────────

def test_overview_totals_each_sport_group_on_its_own(phone):
    today = tz.today()
    add(phone, 'r1', 'Ride', today.isoformat(), dist=20000)
    add(phone, 'r2', 'EBikeRide', today.isoformat(), dist=10000)
    add(phone, 'w1', 'Run', today.isoformat(), dist=5000)
    add(phone, 'w2', 'Swim', today.isoformat(), dist=1500)
    add(phone, 'w3', 'Strength', today.isoformat(), secs=2700)
    add(phone, 'old', 'Run', (today - timedelta(days=400)).isoformat(), dist=10000)
    add(phone, 'sam', 'Run', today.isoformat(), dist=99999, rider=2)
    o = phone.get('/api/v1/overview', headers=phone.H).get_json()
    groups = {g['key']: g for g in o['groups']}
    assert [g['key'] for g in o['groups']] == ['ride', 'foot', 'swim', 'Strength']
    assert groups['ride']['totals']['week'] == {'count': 2, 'distance_m': 30000, 'moving_s': 3600, 'elev_m': 20, 'calories': 200}
    assert groups['foot']['totals']['week']['distance_m'] == 5000 and groups['foot']['totals']['all']['distance_m'] == 15000
    assert groups['swim']['totals']['week']['distance_m'] == 1500         # never added to the runs
    assert groups['Strength']['style'] == 'time' and not groups['Strength']['has_distance']
    assert groups['foot']['style'] == 'pace' and groups['swim']['style'] == 'swim'
    assert o['week']['distance_m'] == 30000                                # the old ride totals are still there for older apps
    current = o['weekly_all'][-1]
    assert current['current'] and current['by']['foot']['distance_m'] == 5000 and current['by']['Strength']['moving_s'] == 2700


def test_lists_label_each_sport_and_filter_by_group(phone):
    today = tz.today().isoformat()
    add(phone, 'r1', 'VirtualRide', today, dist=20000)
    add(phone, 'w1', 'Run', today, dist=5000)
    add(phone, 'w2', 'Hike', today, dist=8000)
    items = phone.get('/api/v1/rides?group=foot', headers=phone.H).get_json()['items']
    assert sorted(i['id'] for i in items) == ['w1', 'w2'] and {i['group'] for i in items} == {'foot'}
    ride = phone.get('/api/v1/rides?group=ride', headers=phone.H).get_json()['items']
    assert [(i['id'], i['label']) for i in ride] == [('r1', 'Indoor ride')]
    assert phone.get('/api/v1/rides?group=nothing', headers=phone.H).get_json() == {'total': 0, 'offset': 0, 'items': []}
    assert phone.get('/api/v1/workouts?days=lots', headers=phone.H).status_code == 400


# ── Apple Health ───────────────────────────────────────────────────────────────────────

def post_health(phone, days):
    return phone.post('/api/v1/health/days', headers=phone.H, json={'days': days})


def test_apple_health_days_are_stored_once_and_replaced(phone):
    d = tz.today().isoformat()
    r = post_health(phone, [{'date': d, 'metric': 'steps', 'value': 9000}, {'date': d, 'metric': 'resting_hr', 'value': 52},
                            {'date': d, 'metric': 'hrv_sdnn', 'value': 48.4}, {'date': d, 'metric': 'sleep_hours', 'value': 7.25},
                            {'date': d, 'metric': 'steps', 'value': 1e9}, {'date': 'yesterday', 'metric': 'steps', 'value': 1},
                            {'date': d, 'metric': 'blood_type', 'value': 1}, {'date': d, 'metric': 'steps', 'value': True}])
    assert r.status_code == 200
    assert r.get_json()['saved'] == 4 and r.get_json()['skipped'] == 4
    post_health(phone, [{'date': d, 'metric': 'steps', 'value': 9500}])          # sent again later in the day
    assert phone.get('/api/v1/today', headers=phone.H).get_json()['steps']['today'] == 9500
    rec = phone.get('/api/v1/overview', headers=phone.H).get_json()['recovery']
    assert (rec['restingHR'], rec['hrv'], rec['hrv_kind'], rec['sleepHours'], rec['source']) == (52, 48, 'sdnn', 7.25, 'apple_health')
    assert rec['bodyBattery'] is None and rec['hrvBalanced'] is None
    summary = phone.get('/api/v1/health', headers=phone.H).get_json()['metrics']
    assert summary['steps'] == {'last': d, 'days': 1} and summary['weight_kg'] is None


def test_garmin_wins_for_a_day_it_has(phone):
    d = tz.today().isoformat()
    with phone.app_.app_context():
        database.get_db().execute('INSERT INTO GarminDaily (date, restingHR, hrv, hrvBalanced, steps) VALUES (?, 48, 70, 1, 4000)', [d])
        database.get_db().commit()
    post_health(phone, [{'date': d, 'metric': 'resting_hr', 'value': 55}, {'date': d, 'metric': 'hrv_sdnn', 'value': 30},
                        {'date': d, 'metric': 'sleep_hours', 'value': 6.5}, {'date': d, 'metric': 'steps', 'value': 6000}])
    rec = phone.get('/api/v1/overview', headers=phone.H).get_json()['recovery']
    assert (rec['restingHR'], rec['hrv'], rec['hrv_kind'], rec['hrvBalanced']) == (48, 70, 'rmssd', 1)
    assert rec['sleepHours'] == 6.5 and rec['steps'] == 6000 and rec['source'] == 'apple_health+garmin'   # Garmin had no sleep that night


def test_apple_health_never_overwrites_another_sources_weigh_in_or_body_fat(phone):
    d, d2 = tz.today().isoformat(), (tz.today() - timedelta(days=1)).isoformat()
    with phone.app_.app_context():
        x = database.get_db()
        x.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (1, ?, 81.0, 'manual')", [d])
        x.execute("INSERT INTO BodyMetric (riderId, logDate, metric, value, unit, source) VALUES (1, ?, 'body_fat', 20, '%', 'homeassistant')", [d])
        x.commit()
    post_health(phone, [{'date': d, 'metric': 'weight_kg', 'value': 79.0}, {'date': d2, 'metric': 'weight_kg', 'value': 79.5},
                        {'date': d, 'metric': 'body_fat', 'value': 25}])
    post_health(phone, [{'date': d2, 'metric': 'weight_kg', 'value': 79.4}])     # a re-sent day replaces Apple's own
    with phone.app_.app_context():
        x = database.get_db()
        w = {r['logDate']: (r['weightKg'], r['source']) for r in x.execute('SELECT logDate, weightKg, source FROM WeightLog WHERE riderId=1')}
        fat = x.execute("SELECT value, source FROM BodyMetric WHERE metric='body_fat'").fetchone()
    assert w == {d: (81.0, 'manual'), d2: (79.4, 'apple_health')}
    assert tuple(fat) == (20, 'homeassistant')


def test_apple_health_calories_make_the_days_burn(phone):
    from services import health
    d = tz.today().isoformat()
    post_health(phone, [{'date': d, 'metric': 'active_kcal', 'value': 600}])
    with phone.app_.app_context():
        assert health.device_burn(1, d) is None                                  # active alone is far short of a day
    post_health(phone, [{'date': d, 'metric': 'basal_kcal', 'value': 1700}])
    with phone.app_.app_context():
        assert health.device_burn(1, d) == (2300, 'Apple Health total')
    day = phone.web.get(f'/nutrition/api/day/{d}').get_json()
    assert (day['burned'], day['burn_source']) == (2300, 'Apple Health total')


def test_apple_health_feeds_the_ai_recovery_context(phone):
    from services import context
    d = tz.today().isoformat()
    post_health(phone, [{'date': d, 'metric': 'hrv_sdnn', 'value': 41}, {'date': d, 'metric': 'resting_hr', 'value': 50}])
    with phone.app_.app_context():
        block = context._build_garmin_context(d, 1)
    assert block.startswith('Apple Health recovery data') and 'SDNN' in block and 'resting HR 50bpm' in block


def test_forgetting_apple_health(phone):
    d = tz.today().isoformat()
    post_health(phone, [{'date': d, 'metric': 'steps', 'value': 9000}, {'date': d, 'metric': 'weight_kg', 'value': 80}])
    assert phone.delete('/api/v1/health', headers=phone.H).get_json() == {'deleted': 2}
    assert phone.get('/api/v1/overview', headers=phone.H).get_json()['recovery'] is None


def test_a_bad_health_batch_is_refused(phone):
    assert phone.post('/api/v1/health/days', headers=phone.H, json={'days': 'lots'}).status_code == 400
    assert post_health(phone, [{'date': tz.today().isoformat(), 'metric': 'steps', 'value': 1}] * 5001).status_code == 400


# ── The Watch's own token ──────────────────────────────────────────────────────────────

def test_the_watch_gets_a_token_of_its_own_that_goes_with_the_phones(phone):
    r = phone.post('/api/v1/devices/watch', headers=phone.H)
    assert r.status_code == 201 and r.get_json()['name'] == 'iPhone · Apple Watch'
    watch = {'Authorization': 'Bearer ' + r.get_json()['token']}
    assert phone.get('/api/v1/ping', headers=watch).status_code == 200
    assert phone.post('/api/v1/devices/watch', headers=watch).status_code == 403          # a Watch can't make more
    assert phone.web.post('/api/v1/devices/watch').status_code == 403                    # nor can a web login
    second = phone.post('/api/v1/devices/watch', headers=phone.H).get_json()['token']
    assert phone.get('/api/v1/ping', headers=watch).status_code == 401                   # the first Watch token stopped
    watch2 = {'Authorization': 'Bearer ' + second}
    with phone.app_.app_context():
        phone_id = database.get_db().execute("SELECT id FROM DeviceToken WHERE name='iPhone'").fetchone()[0]
    phone.web.post(f'/phones/{phone_id}/revoke')
    assert phone.get('/api/v1/ping', headers=watch2).status_code == 401                  # revoking the phone revokes its Watch


# ── Photos ─────────────────────────────────────────────────────────────────────────────

def jpeg():
    from PIL import Image
    out = BytesIO()
    Image.new('RGB', (2400, 1800), (200, 30, 30)).save(out, 'JPEG')
    return out.getvalue()


def test_photos_from_the_app(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    add(phone, 'sams', 'Ride', tz.today().isoformat(), dist=20000, rider=2)
    up = lambda rid, data, **f: phone.post(f'/api/v1/rides/ride/{rid}/photos', headers=phone.H, content_type='multipart/form-data',
                                           data={'file': (BytesIO(data), 'IMG_1.jpg'), **f})
    r = up('r1', jpeg(), caption='Top of the climb', client_id='p1')
    assert r.status_code == 201
    photos = r.get_json()['photos']
    assert len(photos) == 1 and photos[0]['caption'] == 'Top of the climb'
    assert len(up('r1', jpeg(), client_id='p1').get_json()['photos']) == 1                 # a retry isn't added twice
    assert up('r1', b'not a picture').status_code == 422
    assert up('sams', jpeg()).status_code == 404                                         # not this rider's
    detail = phone.get('/api/v1/rides/ride/r1', headers=phone.H).get_json()
    assert detail['photos'] == photos
    f = phone.get(photos[0]['url'], headers=phone.H)
    assert f.status_code == 200 and f.mimetype == 'image/jpeg'
    assert phone.get(photos[0]['thumb_url'], headers=phone.H).status_code == 200
    assert phone.get('/api/v1/photos/../app.db', headers=phone.H).status_code == 404
    gone = phone.delete(f"/api/v1/rides/ride/r1/photos/{photos[0]['id']}", headers=phone.H)
    assert gone.status_code == 200 and gone.get_json()['photos'] == []
