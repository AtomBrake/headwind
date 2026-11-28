"""The copy for troubleshooting with GPS left in (services/troubleshooting_copy._without_zones): the privacy zones are cut out of everything it
keeps (the streams and track summaries, start points, laps and rawData, the summary polyline, planned routes, segments, and the copies in
ActivityDuplicate, ImportChange and Garmin's listings), read before strip() deletes them. Throwaway database, no network."""
import json
import random
import sqlite3

import polyline
import pytest
from flask import Flask

import database
from services import planned_routes, privacy_zones, tracks, troubleshooting_copy
from services import streams as stream_store

HOME = (52.0, -1.0)            # made-up places
AWAY = (53.0, -2.0)
SEMI = 2 ** 31 / 180


def _track(start, n=200, step=0.0001):
    """n points heading north from start, about 11 m apart."""
    return [[round(start[0] + i * step, 6), start[1]] for i in range(n)]


def _streams(track):
    n = len(track)
    return {'latlng': {'data': track}, 'time': {'data': list(range(n))}, 'heartrate': {'data': [100 + i % 50 for i in range(n)]},
            'distance': {'data': [i * 11.1 for i in range(n)]}}


def _raw(track):
    return {'start_latlng': track[0], 'end_latlng': track[-1], 'map': {'summary_polyline': polyline.encode([tuple(p) for p in track[::10]])},
            'startLatitude': track[0][0], 'startLongitude': track[0][1], 'name': 'Morning ride',
            'records': [{'position_lat': int(p[0] * SEMI), 'position_long': int(p[1] * SEMI), 'heart_rate': 120} for p in track[:3]]}


@pytest.fixture
def db(tmp_path):
    """A database with a zone round HOME, an activity from it and one far away, and the other places a track is kept. Gives (path, the
    zones as a Hider)."""
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, start in (('home', HOME), ('away', AWAY)):
            t = _track(start)
            d.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, startDate, distance, startLat, startLng, "
                      "summaryPolyline, rawData, laps, updatedAt) VALUES (?, 'Ride', 'Ride', 'Ride', 1, '2026-10-01T08:00:00', "
                      "'2026-10-01T07:00:00Z', 2200, ?, ?, ?, ?, ?, '2026-10-02 09:00:00.000')",
                      [aid, t[0][0], t[0][1], polyline.encode([tuple(p) for p in t[::10]]), json.dumps(_raw(t)),
                       json.dumps([{'start_latlng': t[0], 'end_latlng': t[100], 'distance': 1100}, {'start_latlng': t[100], 'distance': 1100}])])
            stream_store.save(d, aid, _streams(t))
        tracks.fill(d)
        t = _track(HOME)
        row = {'id': 'parked', 'name': 'Ride (watch)', 'startLat': t[0][0], 'startLng': t[0][1],
               'summaryPolyline': polyline.encode([tuple(p) for p in t[::10]]), 'rawData': json.dumps(_raw(t))}
        d.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, source, reason, rowJson, streams) VALUES ('parked', 'home', 1, 'garmin', "
                  "'same', ?, ?)", [json.dumps(row), stream_store.pack(_streams(t))])
        d.execute("INSERT INTO ImportChange (activityId, riderId, activityName, diffs, act, streams) VALUES ('home', 1, 'Ride', ?, ?, ?)",
                  [json.dumps([{'label': 'Start', 'old': None, 'new': 'x'}]), json.dumps({'startLat': t[0][0], 'startLng': t[0][1], 'name': 'Ride'}),
                   stream_store.pack(_streams(t))])
        d.execute("INSERT INTO GarminMissing (garminId, riderId, name, activity) VALUES ('g1', 1, 'Ride', ?)",
                  [json.dumps({'activityName': 'Ride', 'startLatitude': t[0][0], 'startLongitude': t[0][1], 'distance': 2200})])
        planned_routes.save(d, 1, 'From home', track=planned_routes.clean(_track(HOME)), source='gpx')
        planned_routes.save(d, 1, 'Away', track=planned_routes.clean(_track(AWAY)), source='gpx')
        planned_routes.save(d, 1, 'Across', waypoints=[{'lat': HOME[0], 'lng': HOME[1] - 0.03}, {'lat': HOME[0], 'lng': HOME[1] + 0.03}])
        planned_routes.save(d, 1, 'Round the block', waypoints=[{'lat': HOME[0] + 0.0005, 'lng': HOME[1]}, {'lat': HOME[0], 'lng': HOME[1] + 0.0005}])
        d.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, polyline) VALUES "
                  "(1, 'Up from home', ?, ?, ?, ?, NULL), (2, 'Through home', ?, ?, ?, ?, NULL), (3, 'Far hill', ?, ?, ?, ?, NULL)",
                  [*HOME, HOME[0] + 0.02, HOME[1], HOME[0] - 0.02, HOME[1], HOME[0] + 0.02, HOME[1],
                   *AWAY, AWAY[0] + 0.01, AWAY[1]])
        d.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs) VALUES (1, 'home', '2026-10-01', 60), "
                  "(3, 'away', '2026-10-01', 70)")
        privacy_zones.add(d, 1, 'Home', HOME[0], HOME[1], 400, rng=random.Random(1))
        d.execute("UPDATE Activity SET updatedAt='2026-10-02 09:00:00.000'")       # as before the zone was made
        d.commit()
        zones = privacy_zones.hider(d, 1)
        database.close_db()
    return path, zones


def _strip(path, **kw):
    conn = sqlite3.connect(path)                    # as build() opens the copy: no row factory
    troubleshooting_copy.strip(conn, **kw)
    conn.commit()
    conn.row_factory = sqlite3.Row
    stream_store.register(conn)
    return conn


def _inside(zones, pts):
    return [p for p in pts if zones.inside(p[0], p[1])]


def test_the_zones_are_cut_out_of_the_streams_and_start_points(db):
    path, zones = db
    c = _strip(path)
    assert c.execute('SELECT COUNT(*) FROM PrivacyZone').fetchone()[0] == 0            # the zones themselves never go in
    s = stream_store.load(c, 'home')
    ll = s['latlng']['data']
    assert 100 < len(ll) < 200 and not _inside(zones, ll)
    assert len(s['time']['data']) == len(s['heartrate']['data']) == len(ll)              # still in step
    a = c.execute("SELECT * FROM Activity WHERE id='home'").fetchone()
    assert [a['startLat'], a['startLng']] == ll[0]                                      # the first position shown
    assert not _inside(zones, polyline.decode(a['summaryPolyline']))
    assert a['updatedAt'] == '2026-10-02 09:00:00.000'                                  # as it was
    # the track summary made from the old streams went; one far away is as it was
    assert not c.execute("SELECT 1 FROM ActivityTrack WHERE activityId='home'").fetchone()
    assert c.execute("SELECT 1 FROM ActivityTrack WHERE activityId='away'").fetchone()
    away = stream_store.load(c, 'away')
    assert away == _streams(_track(AWAY))


def test_the_zones_are_cut_out_of_laps_and_raw_data(db):
    path, zones = db
    c = _strip(path)
    a = c.execute("SELECT rawData, laps FROM Activity WHERE id='home'").fetchone()
    raw, laps = json.loads(a['rawData']), json.loads(a['laps'])
    assert raw['start_latlng'] == [] and raw['end_latlng'] == _track(HOME)[-1]
    assert 'startLatitude' not in raw and 'startLongitude' not in raw and raw['name'] == 'Morning ride'
    assert not _inside(zones, polyline.decode(raw['map']['summary_polyline']))
    assert all('position_lat' not in r and 'position_long' not in r and r['heart_rate'] == 120 for r in raw['records'])   # semicircles too
    assert laps[0]['start_latlng'] == [] and laps[0]['end_latlng'] == _track(HOME)[100] and laps[1]['start_latlng'] == _track(HOME)[100]
    away = json.loads(c.execute("SELECT rawData FROM Activity WHERE id='away'").fetchone()[0])
    assert away == _raw(_track(AWAY))


def test_the_zones_are_cut_out_of_the_other_copies(db):
    path, zones = db
    c = _strip(path)
    dup = c.execute('SELECT rowJson, streams FROM ActivityDuplicate').fetchone()
    row = json.loads(dup['rowJson'])
    assert 'startLat' not in row and 'startLng' not in row and row['name'] == 'Ride (watch)'
    assert not _inside(zones, polyline.decode(row['summaryPolyline']))
    assert json.loads(row['rawData'])['start_latlng'] == []                             # rawData kept as a string, cut inside it
    ll = json.loads(stream_store.unpack(dup['streams']))['latlng']['data']
    assert ll and not _inside(zones, ll)
    imp = c.execute('SELECT act, streams FROM ImportChange').fetchone()
    assert json.loads(imp['act']) == {'name': 'Ride'}
    ll = json.loads(stream_store.unpack(imp['streams']))['latlng']['data']
    assert ll and not _inside(zones, ll)
    assert json.loads(c.execute('SELECT activity FROM GarminMissing').fetchone()[0]) == {'activityName': 'Ride', 'distance': 2200}


def test_the_zones_are_cut_out_of_routes_and_segments(db):
    path, zones = db
    c = _strip(path)
    routes = {r['name']: r for r in c.execute('SELECT * FROM PlannedRoute')}
    assert 'Round the block' not in routes                                               # all of it inside: gone
    home = json.loads(routes['From home']['track'])
    assert 100 < len(home) < 200 and not _inside(zones, home) and len(home[0]) == 3     # heights kept
    assert json.loads(routes['Away']['track']) == planned_routes.clean(_track(AWAY))
    across = [[w['lat'], w['lng']] for w in json.loads(routes['Across']['waypoints'])]
    assert len(across) >= 4 and not _inside(zones, across)                              # cut at the zone's edge, either side
    assert [r['name'] for r in c.execute('SELECT name FROM Segment')] == ['Far hill']
    assert [r['segmentId'] for r in c.execute('SELECT segmentId FROM SegmentEffort')] == [3]


def test_without_zones_nothing_is_cut(db):
    path, _ = db
    conn = sqlite3.connect(path)
    conn.execute('DELETE FROM PrivacyZone')
    conn.commit()
    before = conn.execute("SELECT data FROM ActivityStream WHERE activityId='home'").fetchone()[0]
    conn.close()
    c = _strip(path)
    assert c.execute("SELECT data FROM ActivityStream WHERE activityId='home'").fetchone()[0] == before
    assert c.execute("SELECT startLat FROM Activity WHERE id='home'").fetchone()[0] == HOME[0]
    assert c.execute('SELECT COUNT(*) FROM PlannedRoute').fetchone()[0] == 4 and c.execute('SELECT COUNT(*) FROM Segment').fetchone()[0] == 3


def test_leaving_out_gps_still_takes_it_all(db):
    path, _ = db
    c = _strip(path, no_gps=True)
    assert c.execute('SELECT COUNT(*) FROM PlannedRoute').fetchone()[0] == 0
    assert 'latlng' not in stream_store.load(c, 'away')
    assert c.execute("SELECT startLat FROM Activity WHERE id='away'").fetchone()[0] is None


def test_the_readme_says_the_zones_are_cut():
    assert 'privacy zones cut out' in troubleshooting_copy.readme(False, False)
    assert 'privacy zones cut out' not in troubleshooting_copy.readme(True, False)
