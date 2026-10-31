"""Tables sort on a click on a heading (static/js/app.js, docs/UI.md): a <table class="sortable">, with the raw value in each worded cell's
data-sort. The Segments page links each name to its segment instead of a View button. Full app, throwaway DB."""
import re

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
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, day, secs in (('r1', '2026-03-01', 300), ('r2', '2026-05-01', 240)):
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData) "
                       "VALUES (?, ?, 'Ride', 'Ride', 1, ?, ?, 20000, 3600, 3600, '{}')", [aid, 'Ride ' + aid, day + 'T08:00:00', day + 'T08:00:00'])
            db.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, avgSpeedMps, isPR) VALUES (1, ?, ?, ?, ?, ?)",
                       [aid, day, secs, 1000 / secs, int(aid == 'r2')])
        db.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, distanceM, sport) VALUES (1, 'Hill <climb>', 51, -1, 51.01, -1, 1000, 'ride')")
        db.execute("INSERT INTO Bike (id, riderId, name, kind) VALUES (1, 1, 'Road bike', 'road')")
        db.execute("INSERT INTO Part (id, bikeId, kind, name, installedOn, replaceEveryM) VALUES (1, 1, 'chain', 'KMC X11', '2026-01-01', 3000000)")
        db.execute("INSERT INTO ServiceLog (bikeId, partId, date, action, odometerM) VALUES (1, 1, '2026-02-01', 'cleaned', 123456)")
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _sortable(html):
    return re.findall(r'<table class="[^"]*\bsortable\b[^"]*"[^>]*>.*?</table>', html, re.S)


def test_the_segment_name_is_the_link_and_the_columns_sort_on_raw_values(client):
    html = client.get('/segments').get_data(as_text=True)
    [table] = _sortable(html)
    assert '<a href="/segments/1">Hill &lt;climb&gt;</a>' in table           # the name opens the segment, escaped
    assert '>View<' not in table and 'onmouseover' not in table
    assert 'data-sort="Hill &lt;climb&gt;"' in table and 'data-sort="240"' in table and 'data-sort="1000.0"' in table


def test_the_leaderboard_sorts_and_keeps_its_ranks_by_time(client):
    html = client.get('/segments/1').get_data(as_text=True)
    [table] = _sortable(html)
    assert '<th aria-sort="ascending" data-col="rank">' in table              # the rows come fastest first
    assert re.search(r'data-i="0".*?data-sort="2026-05-01".*?data-sort="240".*?data-sort="4\.16', table, re.S)   # r2 first: 240 s, 4.17 m/s
    assert "a.dataset.i - b.dataset.i" in html                                # filtering numbers the ranks in time order, whatever the sort


def test_the_bike_page_tables_sort_with_their_edit_rows(client):
    html = client.get('/gear/bike/1').get_data(as_text=True)
    names = re.findall(r'<table class="[^"]*\bsortable\b[^"]*" data-sort-name="(\w+)"', html)
    assert names == ['parts', 'log']                                          # one URL parameter each
    assert 'data-follows hidden' in html                                      # a part's edit row moves with it
    assert 'data-sort="2026-01-01"' in html and 'data-sort="123456.0"' in html


@pytest.mark.parametrize('page, names', [
    ('/riders/1', ['prs']),
    ('/nutrition/week', ['sort']),
])
def test_other_pages_have_their_sortable_tables(client, page, names):
    html = client.get(page).get_data(as_text=True)
    found = [re.search(r'data-sort-name="(\w+)"', t.split('>', 1)[0]) for t in _sortable(html)]
    assert [m.group(1) if m else 'sort' for m in found] == names
