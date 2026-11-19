"""The activity lists' more filters (services/activity_filters.py): what an activity has, indoors or out, where it came from, the order, and paging
through a flat list. All in the URL, kept on the page's links and dropped by Clear. Full app, throwaway DB."""
import re

import pytest

import app as app_module
import config
import database
from services import activity_filters, credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


ACTS = (   # id, sport, day, km, climb m, secs, watts, hr, cadence, startLat, source, originId
    ('garmin_1', 'Ride', '2026-10-01', 40, 600, 5400, 180, 140, 85, 50.7, None, None),
    ('12345', 'Run', '2026-10-02', 10, 80, 3000, None, 150, None, 50.7, None, None),
    ('imp_zw', 'VirtualRide', '2026-10-03', 30, 200, 3600, 200, None, 90, None, None, None),
    ('wk_walk', 'Walk', '2026-10-04', 5, 20, 3600, None, None, None, 50.7, 'ios', None),
    ('man_x', 'Ride', '2026-10-05', 20, 0, 3000, None, None, None, None, 'manual', None),
    ('wk_conv', 'Other', '2026-10-06', 0, 0, 1800, None, 120, None, None, 'converted', 'garmin_9'),
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, day, km, climb, secs, watts, hr, cad, lat, src, origin in ACTS:
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, totalElevationGain, movingTime, averageSpeed, "
                       "averageWatts, averageHeartrate, averageCadence, startLat, source, originId) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       [aid, aid, sport, f'{day}T08:00:00', km * 1000, climb, secs, km * 1000 / secs, watts, hr, cad, lat, src, origin])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _ids(client, query):
    html = client.get('/activities?' + query).get_data(as_text=True)
    return re.findall(r'<a href="/rides/(\w+)">', html)


@pytest.mark.parametrize('query, ids', [
    ('power=1', {'garmin_1', 'imp_zw'}),
    ('power=0', {'12345', 'wk_walk', 'man_x', 'wk_conv'}),
    ('hr=1&gps=1', {'garmin_1', '12345'}),
    ('cadence=1', {'garmin_1', 'imp_zw'}),
    ('gps=0', {'imp_zw', 'man_x', 'wk_conv'}),
    ('place=indoor', {'imp_zw'}),
    ('place=outdoor&power=1', {'garmin_1'}),
    ('source=garmin', {'garmin_1', 'wk_conv'}),               # a Garmin ride changed into a workout long ago, by its originId
    ('source=strava', {'12345'}),
    ('source=file', {'imp_zw'}),
    ('source=phone', {'wk_walk'}),
    ('source=manual', {'man_x'}),
    ('power=nonsense&source=elsewhere', {a[0] for a in ACTS}),  # anything else is no filter
])
def test_each_filter(client, query, ids):
    assert set(_ids(client, query)) == ids


@pytest.mark.parametrize('sort, first', [('distance', ['garmin_1', 'imp_zw', 'man_x']), ('climb', ['garmin_1', 'imp_zw', '12345']),
                                         ('time', ['garmin_1', 'wk_walk', 'imp_zw']), ('oldest', ['garmin_1', '12345', 'imp_zw']),
                                         ('speed', ['imp_zw', 'garmin_1', 'man_x'])])
def test_the_list_in_another_order_is_flat(client, sort, first):
    html = client.get(f'/activities?sort={sort}').get_data(as_text=True)
    assert 'tree-year' not in html and '6 results' in html
    assert re.findall(r'<a href="/rides/(\w+)">', html)[:3] == first
    assert 'action="/rides/bulk-sport"' not in html                 # nothing narrowed: no "change the type of all 6"


def test_paging_through_a_flat_list_keeps_the_filters(client, monkeypatch):
    monkeypatch.setattr(activity_filters, 'PAGE', 2)
    html = client.get('/activities?sort=distance&hr=1').get_data(as_text=True)
    assert '3 results · page 1 of 2' in html and re.findall(r'<a href="/rides/(\w+)">', html) == ['garmin_1', '12345']
    nxt = re.search(r'href="([^"]+)">Next ›', html).group(1).replace('&amp;', '&')
    assert 'hr=1' in nxt and 'sort=distance' in nxt and 'page=2' in nxt
    page2 = client.get(nxt).get_data(as_text=True)
    assert re.findall(r'<a href="/rides/(\w+)">', page2) == ['wk_conv'] and '‹ Previous' in page2
    assert set(re.search(r'name="ids" value="([^"]+)"', page2).group(1).split(',')) == {'garmin_1', '12345', 'wk_conv'}   # every page's, not this one's


def test_links_keep_the_filters_and_clear_drops_them(client):
    html = client.get('/activities?power=1&source=garmin&sort=climb').get_data(as_text=True)
    assert 'More filters · 2 on' in html and '<details class="more-filters" open>' in html
    assert re.search(r'href="/activities\?group=ride&amp;power=1&amp;source=garmin&amp;sort=climb"', html)     # the "Only rides" shortcut
    clear = re.search(r'href="([^"]*)" class="btn btn-secondary btn-sm">&times; Clear', html).group(1)
    assert 'power' not in clear and 'sort' not in clear
    plain = client.get('/activities').get_data(as_text=True)
    assert '<details class="more-filters">' in plain and 'tree-year' in plain


def test_the_dashboard_list_and_totals_follow_them(client):
    html = client.get('/dashboard?power=1').get_data(as_text=True)
    assert set(re.findall(r'<a href="/rides/(\w+)">', html)) == {'garmin_1', 'imp_zw'}
    assert re.search(r'>2h 30m</div>\s*<div class="m-label">Total Time', html)      # 1:30 + 1:00 with power, not every activity's time
