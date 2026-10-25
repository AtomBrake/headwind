"""The Weight page: in the Health nav, and its weigh-ins table gets each reading's source, trend and change. Full app, throwaway DB."""
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
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")
        for days_ago, kg, source, detail in ((40, 90.0, 'backfill', None), (10, 89.0, 'garmin', None), (5, 88.5, 'homeassistant', None),
                                             (3, 88.6, 'garmin', 'MANUAL'), (1, 88.8, 'manual', None)):
            db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source, sourceDetail) VALUES (1, ?, ?, ?, ?)",
                       [(today - timedelta(days=days_ago)).isoformat(), kg, source, detail])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_weight_is_in_the_health_nav_and_highlighted_on_its_own_page(client):
    html = client.get('/nutrition/weight').get_data(as_text=True)
    assert '<a href="/nutrition/weight"\n         class="nav-item active">' in html
    assert '<a href="/nutrition/"\n         class="nav-item ">' in html      # Nutrition no longer lights up too
    assert 'id="wgLogBody"' in html


def test_graph_points_carry_source_trend_and_change_since_the_previous_weigh_in(client):
    data = client.get('/nutrition/api/weight/graph?period=M').get_json()
    raw = data['raw']
    assert [p['source'] for p in raw] == ['garmin', 'homeassistant', 'garmin', 'manual']    # the 40-day-old one is outside the month
    assert [p['scale'] for p in raw] == [True, True, False, False]     # a Garmin weigh-in is a scale's unless Garmin says MANUAL
    assert raw[0]['changeKg'] == pytest.approx(-1.0)     # against the backfilled reading before the window, not None
    assert raw[1]['changeKg'] == pytest.approx(-0.5)
    assert raw[3]['changeKg'] == pytest.approx(0.2)
    assert all(p['trendKg'] is not None for p in raw)


def test_day_view_marks_garmin_scale_weigh_ins_as_scale(client):
    day = lambda n: client.get(f'/nutrition/api/day/{(date.today() - timedelta(days=n)).isoformat()}').get_json()['weight']
    assert day(10)['scale'] and day(5)['scale']
    assert not day(3)['scale'] and not day(1)['scale'] and not day(2)['scale']   # typed into Garmin, typed here, no weigh-in

    first = client.get('/nutrition/api/weight/graph?period=ALL').get_json()['raw'][0]
    assert first['source'] == 'backfill' and first['changeKg'] is None and first['trendKg'] == pytest.approx(90.0)


def test_milestone_lines_are_every_stone_or_every_5_kg_in_metric(client):
    # the oldest reading (90 kg) is the heaviest and no diet start is set, so lines run down from 90 kg
    stlb = client.get('/nutrition/api/weight/graph?period=M').get_json()['milestones']
    assert stlb == []                                       # lowest is 88.5 kg: not a stone down yet
    client.post('/nutrition/api/weight', json={'date': (date.today() - timedelta(days=2)).isoformat(), 'unit': 'kg', 'kg': 83.0})
    stlb = client.get('/nutrition/api/weight/graph?period=M').get_json()['milestones']
    assert [m['label'] for m in stlb] == ['-1st']
    assert stlb[0]['kg'] == pytest.approx(90 - 6.35, abs=0.01)

    client.post('/nutrition/api/weight/settings', json={'unit': 'kg'})
    kg = client.get('/nutrition/api/weight/graph?period=M').get_json()['milestones']
    assert kg == [{'kg': 85.0, 'label': '-5kg'}]
