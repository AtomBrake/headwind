"""With metric chosen in Settings, no page shows miles, mph or feet, and the numbers are converted, not just relabelled. Full app, throwaway DB."""
import json
import re
from datetime import date, timedelta

import pytest

import app as app_module
import config
import database
from services import credentials, units
from services import streams as _streams
from tests.page_data import page_data

PAGES = ['/dashboard', '/rides/r1', '/rides/r2', '/data', '/riders/1', '/segments', '/segments/1', '/ai', '/planner/', '/roughness',
         '/dashboard?min_dist=10&max_dist=100']
IMPERIAL = re.compile(r'\bmph\b|\d\s?mi\b|\bmi\b(?=[<)\'",])|\d\s?ft\b|\bft\b(?=[<)\'",])|/mi\b|\bmiles\b|\(ft\)')


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    today = date.today()
    streams = json.dumps({'latlng': {'data': [[51.5 + i * 1e-4, -2.6] for i in range(200)]}, 'distance': {'data': [i * 100.0 for i in range(200)]},
                          'altitude': {'data': [50 + (i % 20) for i in range(200)]}, 'velocity_smooth': {'data': [7.0] * 200}, 'time': {'data': list(range(0, 4000, 20))},
                          'heartrate': {'data': [140] * 200}})
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET units='metric' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, days_ago in (('r1', 1), ('r2', 9)):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, averageSpeed, maxSpeed, totalElevationGain, "
                       "calories, weatherTempC, weatherWindKph, weatherCode, weatherWindRel) VALUES (?, 'Morning ride', 'Ride', 1, ?, 19900, 2843, 3000, 7.0, 12.0, 300, 600, 12, 20, 3, 'headwind')",
                       [aid, (today - timedelta(days=days_ago)).isoformat() + 'T08:00:00'])
            _streams.save(db, aid, streams)
        db.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, sourceActivityId) VALUES (1, 'Hill', 51.5, -2.6, 51.51, -2.6, 1200, 60, 'r1')")
        db.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, avgSpeedMps, isPR) VALUES (1, 'r1', ?, 200, 6.0, 1)", [today.isoformat()])
        db.execute("INSERT INTO BestEffort (activityId, activityDate, distanceMi, elapsedSecs, avgSpeedMps) VALUES ('r1', ?, 5, 1200, 6.7)", [today.isoformat()])
        db.execute("INSERT INTO RideMemory (rideId, rideDate, rideName, distanceMi, movingTime, elevationFt, avgSpeedMph) VALUES ('r2', ?, 'Morning ride', 12.4, 2843, 984, 15.7)",
                   [today.isoformat()])
        db.execute("INSERT INTO Activity (id, riderId, sportType, startDateLocal, distance, movingTime, totalElevationGain, source) VALUES ('wk_1', 1, 'Run', ?, 5000, 1500, 40, 'android')",
                   [today.isoformat() + 'T07:00:00'])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _what_a_reader_sees(html):
    """The page's text, plus the quoted strings inside its scripts (chart labels, tooltips), without code comments, class names or the add-workout
    form's own miles / km choice."""
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    quoted = []
    for js in scripts:
        js = re.sub(r'//[^\n]*', '', js)
        quoted += re.findall(r"'([^'\n]*)'|`([^`]*)`", js)
    text = re.sub(r'<script[^>]*>.*?</script>|<style[^>]*>.*?</style>', ' ', html, flags=re.S)
    text = re.sub(r'<option value="mi"[^<]*</option>', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text + '\n' + '\n'.join(a or b for a, b in quoted)


@pytest.mark.parametrize('url', PAGES)
def test_no_imperial_units_on_any_page_when_metric_is_chosen(client, url):
    r = client.get(url)
    assert r.status_code == 200, url
    seen = _what_a_reader_sees(r.get_data(as_text=True))
    hits = sorted({seen[max(0, m.start() - 40):m.end() + 10] for m in IMPERIAL.finditer(seen)})
    assert not hits, f'{url} still shows imperial units: {hits}'


def test_the_ai_coach_is_given_metric_numbers_not_asked_to_convert(client, monkeypatch):
    from services import ai
    sent = {}

    def fake_chat(messages, system=None, **kw):
        sent['messages'] = [{'content': system}] + messages
        return 'ok'
    monkeypatch.setattr(ai, 'get_chat', lambda: fake_chat)
    with client.application.app_context():
        act = database.get_db().execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='r1'").fetchone()
        ai.generate_analysis(act)
    prompt = '\n'.join(m['content'] for m in sent['messages'])
    assert '19.9 km' in prompt and '25.2 km/h' in prompt and '300 m' in prompt      # this ride
    assert '20.0 km' in prompt and '25.3 km/h' in prompt                             # the stored ride memory (12.4 mi, 15.7 mph), converted
    hits = sorted({prompt[max(0, m.start() - 40):m.end() + 10] for m in IMPERIAL.finditer(prompt)})
    assert not hits, hits


def test_numbers_are_converted_not_just_relabelled(client):
    html = client.get('/rides/r1').get_data(as_text=True)
    assert '19.9 km' in html and '25.2 km/h' in html and '300 m' in html
    assert '5:00 /km' in client.get('/rides/wk_1').get_data(as_text=True)      # a run's page shows pace, a ride's speed
    html = client.get('/dashboard').get_data(as_text=True)
    assert page_data(html, 'unitsData')['dist'] == 'km'
    week = page_data(html, 'dashboardData')['weekly']
    assert week[-1]['by'].get('ride', {}).get('dist_m', 0) in (19900, 39800, 0)     # metres go to the page, which converts with UNITS


def test_distance_filter_is_in_the_riders_unit(client):
    html = client.get('/dashboard?min_dist=19&max_dist=21').get_data(as_text=True)
    assert '2 results' in html                                    # 19.9 km is inside 19-21 km (it would not be inside 19-21 miles)
    html = client.get('/dashboard?min_mi=12&max_mi=13').get_data(as_text=True)
    assert '2 results' in html                                    # an old link in miles still works


def test_imperial_is_unchanged(client):
    with client.application.app_context():
        db = database.get_db(); db.execute("UPDATE Settings SET units='imperial' WHERE id=1"); db.commit()
    html = client.get('/rides/r1').get_data(as_text=True)
    assert '12.4 mi' in html and '15.7 mph' in html and '984 ft' in html


def test_units_module():
    assert units.fmt_dist(1609.344, 'imperial') == '1.0 mi' and units.fmt_dist(1500, 'metric') == '1.5 km'
    assert units.fmt_speed(10, 'metric') == '36.0 km/h' and units.fmt_elev(100, 'imperial') == '328 ft'
    assert units.fmt_pace(1000 / 300, 'metric') == '5:00 /km' and units.to_metres('2', 'metric') == 2000


def _set(client, **cols):
    with client.application.app_context():
        db = database.get_db()
        for k, v in cols.items():
            db.execute(f'UPDATE Settings SET {k}=? WHERE id=1', [v])
        db.commit()


def test_weather_wind_follows_the_units_and_temperature_its_own_choice(client):
    html = client.get('/rides/r1').get_data(as_text=True)
    assert '12°C' in html and '20 km/h' in html                                 # stored as 12 °C and 20 km/h
    _set(client, units='imperial')
    html = client.get('/rides/r1').get_data(as_text=True)
    assert '12°C' in html and '12 mph' in html and 'kph' not in html            # miles and mph, still °C: the default
    assert client.post('/settings/', data={'tempUnit': 'F', 'units': 'imperial'}).status_code == 302
    html = client.get('/rides/r1').get_data(as_text=True)
    assert '54°F' in html and '°C' not in _what_a_reader_sees(html)
    assert 'Speed vs Temperature (mph / °F)' in client.get('/data').get_data(as_text=True)
    client.post('/settings/', data={'tempUnit': 'K', 'units': 'imperial'})        # nonsense keeps what's saved
    assert '54°F' in client.get('/rides/r1').get_data(as_text=True)


def test_weather_text_and_badge_wording():
    t = 'Light rain, 9°C, wind 12kph (gusts 30kph)'
    assert units.weather_text(t, 'metric', 'C') == 'Light rain, 9°C, wind 12 km/h (gusts 30 km/h)'
    assert units.weather_text(t, 'imperial', 'F') == 'Light rain, 48°F, wind 7 mph (gusts 19 mph)'
    assert units.weather_text('Ride when temp ≤ −5°C', 'imperial', 'C') == 'Ride when temp ≤ −5°C'
    assert units.weather_text('Ride when temp ≤ −5°C', 'imperial', 'F') == 'Ride when temp ≤ 23°F'
    assert units.weather_text('Ride when temp ≤ −20°C', 'metric', 'F') == 'Ride when temp ≤ −4°F'
    assert units.weather_text('Ride into a 30+ kph headwind', 'imperial') == 'Ride into a 19+ mph headwind'
    assert units.fmt_temp(None) == '—' and units.weather_text(None) is None


def test_a_metric_riders_badges_count_against_the_round_figures_they_show(client):
    assert [units.round_metric(v) for v in (8.05, 40.2, 48.3, 120.7, 152.4, 804.7, 1609.3, 16093, 40234)] == [8, 40, 50, 120, 150, 800, 1600, 16000, 40000]
    assert units.localise('25 miles in one ride', 'metric') == '40 km in one ride' and units.localise('Ride with 500ft+ elevation', 'metric') == 'Ride with 150m+ elevation'
    assert units.limit_dist(25, 'metric') == 40000 and units.limit_dist(25, 'imperial') == 25 * units.MI
    assert units.limit_elev(500, 'metric') == 150 and round(units.limit_speed(30, 'metric') * 3.6, 6) == 48
    from routes import riders
    with client.application.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, averageSpeed, maxSpeed, totalElevationGain) "
                   "VALUES ('long', 'Long one', 'Ride', 1, '2026-01-02T08:00:00', 40100, 5400, 7.4, 13.4, 151)", [])   # 40.1 km: short of 25 miles
        db.commit()

    def earned(system):
        _set(client, units=system)
        with client.application.test_request_context('/riders/1'):
            cats = riders._count_badges(1, {'rides': 3, 'dist': 79900, 'elev': 751})
        return {b['desc'] for c in cats for b in c['badges'] if b['earned']}
    metric = earned('metric')
    assert '40 km in one ride' in metric and 'Ride with 150m+ elevation' in metric and '48 km/h top speed' in metric
    imperial = earned('imperial')
    assert '25 miles in one ride' not in imperial and '30 mph top speed' not in imperial         # 40.1 km and 29.97 mph: short in miles
