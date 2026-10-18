"""The sport filter on the dashboard and the Data page: every sport by default, the rider leaves some out, and distances only add up within a stat group
(rides, on foot, swims, each other sport alone). Speed for rides, pace on foot, per 100 m for swims. Full app, throwaway DB."""
import json
import re
from datetime import date, timedelta

import pytest

import app as app_module
import config
import database
from services import credentials, sports, units


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    app = app_module.create_app()
    day = date.today() - timedelta(days=date.today().weekday())         # this week's Monday: everything lands in this week's bar and this year
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, dist, secs, elev, cals, hour in (
                ('r1', 'Ride', 40000, 5400, 300, 900, 7),        # 40 km in 1:30
                ('run1', 'Run', 10000, 3000, 50, 700, 9),        # 10 km in 50:00, 5:00 /km
                ('walk1', 'Walk', 5000, 3600, 20, 250, 12),      # 5 km in an hour
                ('swim1', 'Swim', 2000, 2400, 0, 500, 18)):      # 2 km in 40:00, 2:00 /100 m
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, movingTime, totalElevationGain, calories) "
                       "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)", [aid, aid, sport, f'{day.isoformat()}T{hour:02d}:00:00', dist, secs, elev, cals])
        db.execute("UPDATE Activity SET averageSpeed = distance * 1.0 / movingTime WHERE id='r1'")     # workouts are often saved without one
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _json(html, name):
    return json.loads(re.search(rf'const {name}\s*=\s*(.*?);[ \t]*(?://[^\n]*)?\n', html).group(1))


def test_stat_groups_and_how_speed_reads():
    assert [sports.stat_group(s) for s in ('Ride', 'VirtualRide', 'EBikeRide', None, 'Run', 'Trail Run', 'Walk', 'Hike', 'Swim', 'Paddle')] == \
        ['ride', 'ride', 'ride', 'ride', 'foot', 'foot', 'foot', 'foot', 'swim', 'Paddle']
    assert [sports.rate_style(s) for s in ('Ride', 'Run', 'Walk', 'Swim', 'Paddle')] == ['speed', 'pace', 'pace', 'swim', 'speed']
    assert units.fmt_swim_pace(2000 / 2400) == '2:00 /100 m' and units.fmt_swim_pace(0) == '—'
    assert units.fmt_rate(10000 / 3000, 'pace', 'metric') == '5:00 /km' and units.fmt_rate(None, 'speed') == '—'


def test_every_sport_shows_time_and_each_groups_own_distance_never_one_sum(client):
    html = client.get('/dashboard').get_data(as_text=True)
    assert 'Total Time' in html and 'Total Distance' not in html
    assert '24.9 mi' in html and '9.3 mi' in html and '1.2 mi' in html            # 40 km of rides, 15 km on foot, 2 km of swims, each on its own
    assert '35.0 mi' not in html                                                  # never the 57 km of all of them added up
    assert '>4h 0m<' in html                                                      # 1:30 + 50:00 + 1:00 + 40:00 = 4 hours of training
    week = _json(html, 'weeklyData')[-1]
    assert week['dist_m'] is None and week['secs'] == 14400
    assert {g: v['dist_m'] for g, v in week['by'].items()} == {'ride': 40000, 'foot': 15000, 'swim': 2000}
    assert [g['key'] for g in _json(html, 'chartGroups')] == ['ride', 'foot', 'swim']
    assert _json(html, 'yearSpeedData') == [] and _json(html, 'rateStyle') is None   # no speed line mixing ride speeds with walking paces
    assert 'data-metric="distance"' not in html and 'data-metric="time"' in html


def test_leaving_out_rides_and_swims_gives_distance_and_pace_on_foot(client):
    html = client.get('/dashboard?skip=Ride&skip=Swim').get_data(as_text=True)
    assert 'Total Distance' in html and '9.3 mi' in html                          # the run and the walk do add up
    assert '/rides/run1' in html and '/rides/r1' not in html and '/rides/swim1' not in html
    assert _json(html, 'rateStyle') == 'pace' and '>Pace</button>' in html
    assert {r['id'] for r in _json(html, 'yearSpeedData')} == {'run1', 'walk1'}   # a workout without a stored speed gets distance over time
    assert '8:03 /mi' in html and 'Avg Pace' in html                              # 5:00 /km is 8:03 /mi
    assert 'skip=Ride&amp;skip=Swim' in html                                      # the list, week and Data links keep the filter
    assert re.search(r'data-sport value="Ride"\s+onchange', html)                 # the left-out sports are unticked


def test_only_shortcuts_and_old_one_sport_links(client):
    html = client.get('/dashboard').get_data(as_text=True)
    hrefs = re.findall(r'<a class="sport-only[^"]*" href="([^"]+)"', html)
    assert len(hrefs) == 3 and any('skip=Run' in h and 'skip=Walk' in h and 'skip=Ride' not in h for h in hrefs)    # "only rides"
    html = client.get('/dashboard?sport=swim').get_data(as_text=True)              # an old link: one sport, by part of its name
    assert '/rides/swim1' in html and '/rides/r1' not in html and '2:00 /100 m' in html and 'Pace /100 m' in html


def test_data_page_follows_the_filter(client):
    html = client.get('/data').get_data(as_text=True)
    assert 'Monthly Time (hours)' in html and 'Duration Distribution' in html and 'id="speedChart"' not in html
    assert 'id="records"' in html and 'rides only' in html                         # the ride records stay, saying they count rides
    assert _json(html, 'DIST_MODE') is False

    html = client.get('/data?skip=Ride&skip=Swim').get_data(as_text=True)
    assert 'Monthly Distance (mi)' in html and 'Avg Pace Per Activity (/mi' in html and 'id="records"' not in html
    assert json.dumps('0–2 mi') in html                                            # buckets that fit walks and runs, not 0–5 mi rides
    assert 'Weather &amp; Performance' not in html

    html = client.get('/data?sport=Swim').get_data(as_text=True)
    assert 'Avg Pace Per Activity (/100 m' in html and json.dumps('500 m–1 km') in html

    html = client.get('/data?skip=Run&skip=Walk&skip=Swim').get_data(as_text=True)
    assert 'Avg Speed Per Activity (mph)' in html and 'rides only' not in html


def test_the_phone_weekly_bars_stay_rides_only(client):
    with client.application.app_context():
        from routes.dashboard import _weekly_data
        assert _weekly_data(1)[-1]['dist_m'] == 40000
