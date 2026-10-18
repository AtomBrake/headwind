"""The dashboard: its numbers drop as soon as a ride is deleted, and nearly everything on it links to what is behind it. Full app, throwaway DB."""
import json
import re
from datetime import date, timedelta

import pytest

import app as app_module
import config
import database
from services import credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    app = app_module.create_app()
    today = date.today()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, days_ago, dist in (('good', 1, 30000), ('huge', 2, 30_000_000), ('old', 400, 45_000_000)):
            db.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, distance, movingTime, averageSpeed, totalElevationGain) "
                       "VALUES (?, ?, 1, ?, ?, 3600, ?, 100)", [aid, aid, (today - timedelta(days=days_ago)).isoformat() + 'T08:00:00', dist, dist / 3600])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _page(client):
    html = client.get('/dashboard').get_data(as_text=True)
    weekly = json.loads(re.search(r'const weeklyData\s+=\s+(.*);', html).group(1))
    speed = json.loads(re.search(r'const yearSpeedData = (.*);', html).group(1))
    return html, weekly, speed


def test_deleting_a_ride_updates_every_dashboard_number_at_once(client, monkeypatch):
    pushed = []
    monkeypatch.setattr('services.mqtt.push_update', lambda *a, **kw: pushed.append(1))
    html, weekly, _ = _page(client)
    assert max(w['dist_m'] for w in weekly) > 18000 * 1609 and 'huge' in html

    assert client.post('/rides/huge/delete').status_code == 302
    html, weekly, speed = _page(client)
    assert max(w['dist_m'] for w in weekly) < 20 * 1609 and 'huge' not in html
    assert all(r['id'] != 'huge' for r in speed)
    assert pushed, 'the Home Assistant sensors are re-published after a web delete'

    client.post('/rides/old/delete')                    # a year old: in the lifetime totals, never in the 12-week bars
    html, _, _ = _page(client)
    assert '28,0' not in html and '18.6 mi' in html     # the total is only the one good ride now


def test_bars_link_to_their_week_and_speed_points_to_their_ride(client):
    _, weekly, speed = _page(client)
    monday = date.today() - timedelta(days=date.today().weekday())
    assert weekly[-1]['from'] == monday.isoformat() and weekly[-1]['to'] == (monday + timedelta(days=6)).isoformat()
    assert {r['id'] for r in speed} >= {'good', 'huge'}


def test_week_link_lists_exactly_that_week(client):
    _, weekly, _ = _page(client)
    w = weekly[-1]                                      # this week
    html = client.get(f"/dashboard?from={w['from']}&to={w['to']}").get_data(as_text=True)
    listed = set(re.findall(r'<a href="/rides/([^"]+)" class="dash-link"\s', html))
    monday = date.fromisoformat(w['from'])
    assert listed == {aid for aid, days_ago in (('good', 1), ('huge', 2)) if date.today() - timedelta(days=days_ago) >= monday}


def test_tiles_rows_and_history_are_real_links(client):
    html, _, _ = _page(client)
    assert 'class="metric-tile dash-link" href="#ride-history"' in html
    assert 'href="/data#climbing"' in html and 'href="/data#distance"' in html and 'href="/data#calories"' in html
    assert 'onclick="location.href=' not in html                          # every row is an <a>, so new-tab and keyboard work
    year = date.today().year
    assert f'from={year}-01-01&amp;to={year}-12-31#ride-history' in html     # the year heading's List link


def test_a_second_riders_links_keep_the_rider(client):
    with client.application.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
        db.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, distance, movingTime, averageSpeed) "
                   "VALUES ('sam1', 'sam1', 2, ?, 10000, 1800, 5.5)", [date.today().isoformat() + 'T07:00:00'])
        db.commit()
    html = client.get('/dashboard?rider=2').get_data(as_text=True)
    assert 'href="/data?rider=2#distance"' in html and 'const riderQuery    = "rider=2"' in html
    assert '/dashboard?rider=2&amp;from=' in html


def test_blips_go_in_one_click_and_the_rest_stay_flagged(client):
    from services import sanity
    with client.application.app_context():
        db = database.get_db()
        for aid, dist, top in (('blip1', 45, 3), ('blip2', 130, 3), ('spiky', 30000, 61)):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, averageSpeed, maxSpeed) "
                       "VALUES (?, 'Cycling', 'Ride', 1, '2023-08-04T10:00:00', ?, 600, 2, ?)", [aid, dist, top])
            sanity.flag(db, aid)
        db.commit()
    html, _, _ = _page(client)
    assert 'Delete all 2 blips (under 160 m)' in html
    assert client.post('/rides/flagged/delete-blips').status_code == 302
    with client.application.app_context():
        left = {f['id'] for f in sanity.flagged(database.get_db(), 1)}
    assert left == {'spiky'}


def test_activity_type_review_page_lists_pending_changes(client):
    with client.application.app_context():
        db = database.get_db()
        db.execute("INSERT INTO SportFix (rideId, riderId, name, startDateLocal, distance, oldSport, newSport, typeKey) "
                   "VALUES ('good', 1, 'Pool Swimming', '2021-07-19T08:00:00', 140, 'Ride', 'Swim', 'lap_swimming')")
        db.commit()
    html = client.get('/garmin/sports').get_data(as_text=True)
    assert 'Pool Swimming' in html and 'Garmin says lap swimming' in html and 'name="ride" value="good"' in html
    assert client.post('/garmin/sports/apply', data={'ride': 'good'}).status_code == 302
    with client.application.app_context():
        db = database.get_db()
        assert db.execute("SELECT sport FROM Workout WHERE sport='Swim'").fetchone()
        assert not db.execute("SELECT 1 FROM Activity WHERE id='good'").fetchone()
