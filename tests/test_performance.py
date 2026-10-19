"""What made big histories fast, and that it changes no result: Activity's large columns kept last (database.heavy_last), track summaries for
the heatmap and the segment pre-filter (services/tracks.py, segments.seg_reach), and the badge cache (services/data_version.py). Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from routes import riders
from services import data_version, segments, tracks


def line(secs, speed_mps=6.0, lat0=51.5, lng0=-0.12, d_lng=0.0):
    """A straight northbound GPS track at a steady speed, one fix per second (d_lng per second drifts it east)."""
    d_lat = speed_mps / 111_320.0
    ll = [[lat0 + i * d_lat, lng0 + i * d_lng] for i in range(secs + 1)]
    return json.dumps({'latlng': {'data': ll}, 'time': {'data': list(range(secs + 1))}, 'heartrate': {'data': [120] * (secs + 1)}})


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    return app


@pytest.fixture
def db(app):
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


def add(db, aid, streams, sport='Ride', day='2026-10-07'):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId, "
               "streams, source, weatherTempC) VALUES (?,?,?,?,?,?,7200,1200,1200,'{}',1,?,'strava',12.5)",
               [aid, aid, sport, sport, f'{day}T10:00:00', f'{day}T10:00:00', streams])
    db.commit()


def test_heavy_columns_end_up_last_and_every_value_survives(db):
    names = [r[1] for r in db.execute('PRAGMA table_info(Activity)')]
    assert names[-len(database.HEAVY_COLUMNS['Activity']):] == database.HEAVY_COLUMNS['Activity']
    add(db, 'a1', line(100))
    db.execute('ALTER TABLE Activity ADD COLUMN later INTEGER')               # a later release adds a column: it lands after streams
    db.execute("UPDATE Activity SET later = 7")
    db.commit()
    before = dict(db.execute("SELECT * FROM Activity WHERE id='a1'").fetchone())
    assert database.heavy_last(db, 'Activity', database.HEAVY_COLUMNS['Activity']) == 1
    names = [r[1] for r in db.execute('PRAGMA table_info(Activity)')]
    assert names[-1] == 'streams' and 'later' in names
    assert dict(db.execute("SELECT * FROM Activity WHERE id='a1'").fetchone()) == before
    # the views over it, its indexes and its triggers are all back
    assert db.execute("SELECT COUNT(*) FROM Ride").fetchone()[0] == 1
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE tbl_name='Activity' AND type IN ('index', 'trigger')")}
    assert {'idx_activity_rider_date', 'idx_activity_bike', 'ActivityTrack_delete', 'DataVersion_Activity_update'} <= have
    assert database.heavy_last(db, 'Activity', database.HEAVY_COLUMNS['Activity']) is None   # nothing to do a second time


def test_a_rebuild_cut_short_carries_on_from_where_it_stopped(db, monkeypatch):
    for i in range(7):
        add(db, f'a{i}', line(50), day=f'2026-10-0{i + 1}')
    db.execute('ALTER TABLE Activity ADD COLUMN later INTEGER')
    db.commit()
    monkeypatch.setattr(database, '_HEAVY_BATCH', 3)
    real_commit, commits = db.commit, []

    class Stop(Exception):
        pass

    class Conn:                                         # the worker is killed after the second batch is committed
        def __getattr__(self, k):
            return getattr(db, k)

        def commit(self):
            real_commit()
            commits.append(1)
            if db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='Activity_new'").fetchone()[0] and \
                    db.execute('SELECT COUNT(*) FROM Activity_new').fetchone()[0] >= 6:
                raise Stop

    with pytest.raises(Stop):
        database.heavy_last(Conn(), 'Activity', database.HEAVY_COLUMNS['Activity'])
    assert db.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] + db.execute('SELECT COUNT(*) FROM Activity_new').fetchone()[0] == 7
    assert database.heavy_last(db, 'Activity', database.HEAVY_COLUMNS['Activity']) == 1     # the one row left
    assert sorted(r[0] for r in db.execute('SELECT id FROM Activity')) == [f'a{i}' for i in range(7)]
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='Activity_new'").fetchone()


def test_track_summaries_follow_the_streams(db):
    add(db, 'a1', line(600))
    assert tracks.fill(db) == 1 and tracks.fill(db) == 0
    t = db.execute("SELECT * FROM ActivityTrack WHERE activityId='a1'").fetchone()
    ll = json.loads(line(600))['latlng']['data']
    step = max(1, len(ll) // tracks.SAMPLE)
    assert json.loads(t['line']) == [[round(p[0], 4), round(p[1], 4)] for p in ll[::step]]     # what the heatmap drew from the streams
    assert t['minLat'] == ll[0][0] and t['maxLat'] == ll[-1][0]
    db.execute("UPDATE Activity SET name='renamed' WHERE id='a1'")                         # not the track: kept
    assert db.execute("SELECT 1 FROM ActivityTrack WHERE activityId='a1'").fetchone()
    db.execute("UPDATE Activity SET streams=? WHERE id='a1'", [line(100, lng0=2.0)])       # a new track: made again when next needed
    assert not db.execute("SELECT 1 FROM ActivityTrack WHERE activityId='a1'").fetchone()
    tracks.fill(db)
    assert db.execute("SELECT minLng FROM ActivityTrack WHERE activityId='a1'").fetchone()[0] == 2.0
    db.execute("DELETE FROM Activity WHERE id='a1'")
    assert not db.execute("SELECT 1 FROM ActivityTrack").fetchone()
    add(db, 'a2', json.dumps({'heartrate': {'data': [100, 110]}}))                          # no GPS: a row with no box, not read again
    tracks.fill(db)
    assert db.execute("SELECT minLat, line FROM ActivityTrack WHERE activityId='a2'").fetchone()[:] == (None, None)


def _seg(db, lat0, lng0, n=150, name='Seg'):
    d = 1 / 111_320.0
    poly = [[round(lat0 + i * 6 * d, 6), lng0] for i in range(n)]
    db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, polyline, sport) VALUES (?,?,?,?,?,?,?, 'ride')",
               [name, *poly[0], *poly[-1], (n - 1) * 6.0, json.dumps(poly)])
    db.commit()
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def test_the_prefilter_never_changes_what_matches(db, monkeypatch):
    add(db, 'on', line(1200))                                                    # rides the whole segment
    add(db, 'drift', line(1200, d_lng=0.0000004))                                # wanders off sideways toward the end: close match or none
    add(db, 'half', line(170))                                                   # stops half way along it: near the start only
    add(db, 'far', line(1200, lng0=-0.30))                                       # same road shape 12 km west
    add(db, 'cross', json.dumps({'latlng': {'data': [[51.5 + 300 * 6 / 111_320.0, -0.13 + i * 0.0001] for i in range(200)]},
                                 'time': {'data': list(range(200))}}))           # crosses the middle of it
    sid = _seg(db, 51.5 + 100 * 6 / 111_320.0, -0.12)
    segments.scan_all_activities(db, segment_ids=[sid])
    filtered = {r[0]: (r[1], r[2]) for r in db.execute('SELECT activityId, elapsedSecs, approx FROM SegmentEffort WHERE segmentId=?', [sid])}
    assert 'on' in filtered and not {'far', 'cross', 'half'} & set(filtered)
    monkeypatch.setattr(segments, 'can_reach', lambda *a: True)                  # the same scan without any pre-filter
    segments.scan_all_activities(db, segment_ids=[sid])
    every = {r[0]: (r[1], r[2]) for r in db.execute('SELECT activityId, elapsedSecs, approx FROM SegmentEffort WHERE segmentId=?', [sid])}
    assert filtered == every


def test_cells_cover_every_point_a_matcher_could_count():
    seg = {'startLat': 51.5, 'startLng': -0.12, 'endLat': 51.51, 'endLng': -0.12, 'polyline': None}
    box, head, tail = segments.seg_reach(seg)
    for dlat, dlng in ((0, 0), (0.0006, 0), (0, 0.001), (-0.0006, -0.001)):      # up to ~70 m away (CLOSE_TOL_M is 75) in each direction
        near = tracks.cells_of([[51.5 + dlat, -0.12 + dlng], [51.51 + dlat, -0.12 + dlng]])
        assert segments.can_reach(tracks.box_of([[51.5 + dlat, -0.12 + dlng], [51.51 + dlat, -0.12 + dlng]]), near, (box, head, tail))
    assert tracks.cells_of([[51.5, None]]) is None and tracks.box_of([[float('nan'), 0], [1, 1]]) is None   # never trusted when bad


def test_badges_are_kept_until_something_they_count_changes(db, app, monkeypatch):
    add(db, 'a1', line(100))
    counted = []
    real = riders._count_badges
    monkeypatch.setattr(riders, '_count_badges', lambda rid, totals: counted.append(1) or real(rid, totals))
    riders._BADGES.clear()
    totals = {'rides': 1, 'dist': 7200, 'elev': 0}
    first = riders._compute_badges(1, totals)
    assert riders._compute_badges(1, totals) == first and len(counted) == 1
    v = data_version.current(db)
    db.execute("UPDATE Activity SET distance = 9000 WHERE id='a1'")
    db.commit()
    assert data_version.current(db) > v            # two writes: database.Activity_touch moves updatedAt on too
    riders._compute_badges(1, totals)
    assert len(counted) == 2
    db.execute("INSERT INTO Bike (riderId, name) VALUES (1, 'Road')")           # a bike can make a ride an e-bike ride
    db.commit()
    riders._compute_badges(1, totals)
    assert len(counted) == 3
