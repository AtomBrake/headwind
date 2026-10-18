"""With metric chosen in Settings, no page shows miles, mph or feet, and the numbers are converted, not just relabelled. Full app, throwaway DB."""
import json
import re
from datetime import date, timedelta

import pytest

import app as app_module
import config
import database
from services import credentials, units

PAGES = ['/dashboard', '/rides/r1', '/rides/r2', '/data', '/riders/1', '/segments', '/segments/1', '/workouts', '/ai', '/planner/', '/roughness',
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
                       "calories, streams, weatherTempC, weatherWindKph, weatherCode, weatherWindRel) VALUES (?, 'Morning ride', 'Ride', 1, ?, 19900, 2843, 3000, 7.0, 12.0, 300, 600, ?, 12, 20, 3, 'headwind')",
                       [aid, (today - timedelta(days=days_ago)).isoformat() + 'T08:00:00', streams])
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
        act = database.get_db().execute("SELECT * FROM Activity WHERE id='r1'").fetchone()
        ai.generate_analysis(act)
    prompt = '\n'.join(m['content'] for m in sent['messages'])
    assert '19.9 km' in prompt and '25.2 km/h' in prompt and '300 m' in prompt      # this ride
    assert '20.0 km' in prompt and '25.3 km/h' in prompt                             # the stored ride memory (12.4 mi, 15.7 mph), converted
    hits = sorted({prompt[max(0, m.start() - 40):m.end() + 10] for m in IMPERIAL.finditer(prompt)})
    assert not hits, hits


def test_numbers_are_converted_not_just_relabelled(client):
    html = client.get('/rides/r1').get_data(as_text=True)
    assert '19.9 km' in html and '25.2 km/h' in html and '300 m' in html and '2:23 /km' in html
    html = client.get('/dashboard').get_data(as_text=True)
    assert 'window.UNITS = {"dist": "km"' in html or '"dist": "km"' in html
    week = json.loads(re.search(r'const weeklyData\s+=\s+(.*);', html).group(1))
    assert week[-1]['dist_m'] in (19900, 39800, 0)                  # metres go to the page, which converts with UNITS


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
