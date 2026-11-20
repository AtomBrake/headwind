"""Laps: an activity that rides a segment more than once has an effort for each time round, not only its fastest. Two passes on one ride, entries
into the start zone that are one pass, a lap only close to the line, the table rebuilt without UNIQUE(segmentId, activityId), and the one rematch
that finds the laps on an existing database. Throwaway DB, synthetic tracks."""
import json

import pytest

import database
from services import segments as S
from tests.test_segment_matching_fixes import add, at, db, seg_row  # noqa: F401  (db: the fixture)
from services import streams as _streams

POLY = [at(x, 0) for x in range(0, 1001, 50)]
SEG = seg_row(at(0, 0), at(1000, 0), 1000, POLY)


def legs(*parts):
    """Streams along metre waypoints, each part ([(x, y), ...], speed in m/s) carrying on from the last, one fix a second."""
    pts, ts, t, last = [], [], 0, None
    for waypoints, speed in parts:
        way = ([last] if last else []) + list(waypoints)
        for (x0, y0), (x1, y1) in zip(way, way[1:]):
            n = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / speed))
            for i in range(n):
                pts.append(at(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n))
                ts.append(t)
                t += 1
        last = way[-1]
    pts.append(at(*last))
    ts.append(t)
    return {'latlng': {'data': pts}, 'time': {'data': ts}}


BACK_UP = [(1100, 300), (-100, 300), (-100, 0)]                  # the fire road back to the top, 300 m away from the trail


def two_laps(first=5, second=8):
    return legs(([(-100, 0), (1100, 0)], first), (BACK_UP, 3), ([(1100, 0)], second))


def add_segment(db):
    db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, polyline, sport) "
               "VALUES ('Gentle Giant', ?, ?, ?, ?, 1000, 0, ?, 'ride')", [*at(0, 0), *at(1000, 0), json.dumps(POLY)])
    return db.execute('SELECT * FROM Segment').fetchone()


def test_each_lap_of_a_segment_is_an_effort():
    laps = S.match_segment_efforts(two_laps(), SEG)
    assert [round(f[0] / 10) * 10 for f in laps] == [200, 130]   # 1000 m at 5 m/s, then at 8 m/s
    assert laps[0][2] < laps[1][1]                                 # in ride order, one after the other
    assert S.match_segment(two_laps(), SEG) == laps[1][0]          # the fastest, as before


def test_rolling_into_the_start_twice_is_one_effort():
    st = legs(([(-100, 0), (10, 0), (-60, 0)], 2), ([(1100, 0)], 6))   # in to the marker, back out to wait, then off
    laps = S.match_segment_efforts(st, SEG)
    assert len(laps) == 1 and 160 < laps[0][0] < 180               # timed from the second entry: 1000 m at 6 m/s


def test_a_lap_only_close_to_the_line_is_an_approximate_effort_of_its_own():
    st = legs(([(-100, 0), (1100, 0)], 6), (BACK_UP, 3), ([(930, 0), (930, 300)], 6))   # the second time down, off the trail 70 m early
    exact = S.match_segment_efforts(st, SEG)
    assert len(exact) == 1
    close = S.match_segment_close_efforts(st, SEG, skip=[(f[1], f[2]) for f in exact])
    assert len(close) == 1 and close[0][2] > exact[0][2]           # the second lap, never the first one again
    assert S.match_segment_close_efforts(st, SEG, skip=[(0, len(st['latlng']['data']) - 1)]) == []


def test_a_rides_laps_are_kept_and_numbered_and_the_fastest_is_the_pr(db):
    seg = add_segment(db)
    add(db, 'r1', two_laps())
    act = db.execute(f"SELECT id, startDateLocal, {_streams.sql()}, sportType FROM Activity WHERE id='r1'").fetchone()
    for _ in range(2):                                             # matched again: its laps replace the old ones, none doubled
        assert S.scan_activity_against_segments(db, act, [seg]) == 1
    S._refresh_prs(db, seg['id'])
    rows = db.execute('SELECT * FROM SegmentEffort ORDER BY startSecs').fetchall()
    assert [r['isPR'] for r in rows] == [0, 1] and rows[0]['startSecs'] < rows[1]['startSecs']
    assert S.lap_numbers(rows) == {rows[0]['id']: 1, rows[1]['id']: 2}


def test_an_only_effort_is_not_a_lap():
    assert S.lap_numbers([{'id': 1, 'segmentId': 1, 'activityId': 'a', 'startSecs': 30},
                          {'id': 2, 'segmentId': 2, 'activityId': 'a', 'startSecs': 30}]) == {}


def test_the_table_from_before_laps_is_rebuilt_with_its_efforts(db):
    db.execute('DROP TABLE SegmentEffort')
    db.execute('''CREATE TABLE SegmentEffort (id INTEGER PRIMARY KEY AUTOINCREMENT, segmentId INTEGER NOT NULL REFERENCES Segment(id) ON DELETE CASCADE,
                  activityId TEXT NOT NULL, activityDate TEXT, elapsedSecs INTEGER NOT NULL, avgSpeedMps REAL, isPR INTEGER DEFAULT 0,
                  createdAt TEXT DEFAULT (datetime('now')), approx INTEGER DEFAULT 0, UNIQUE(segmentId, activityId))''')
    add_segment(db)
    db.execute("INSERT INTO SegmentEffort (id, segmentId, activityId, activityDate, elapsedSecs, isPR) VALUES (7, 1, 'r1', '2026-10-01', 130, 1)")
    db.commit()
    db.execute('PRAGMA user_version = 0')                                       # from before the steps (database.STEPS)
    database.migrate_db()
    assert [tuple(r) for r in db.execute('SELECT id, activityId, elapsedSecs, isPR, startSecs FROM SegmentEffort')] == [(7, 'r1', 130, 1, None)]
    db.execute("INSERT INTO SegmentEffort (segmentId, activityId, elapsedSecs, startSecs) VALUES (1, 'r1', 200, 0)")   # a second lap
    assert db.execute('SELECT MAX(id) FROM SegmentEffort').fetchone()[0] == 8
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE tbl_name='SegmentEffort'")}
    assert {'idx_effort_activity', 'DataVersion_SegmentEffort_insert'} <= names


def test_every_segment_is_matched_again_once_for_its_laps(db):
    add_segment(db)
    add(db, 'r1', two_laps())
    db.execute("INSERT INTO SegmentEffort (segmentId, activityId, activityDate, elapsedSecs, isPR) VALUES (1, 'r1', '2026-10-01', 125, 1)")   # its best
    db.execute('UPDATE Settings SET segmentLapsDone=0 WHERE id=1')
    assert S.rematch_laps(db) == {'ran': True, 'segments': 1, 'found': 0, 'laps': 1, 'prs_moved': 0}
    assert db.execute('SELECT COUNT(*) FROM SegmentEffort WHERE startSecs IS NOT NULL').fetchone()[0] == 2
    assert S.rematch_laps(db) == {'ran': False}


def test_the_route_rematch_finds_the_laps_too(db):
    add_segment(db)
    add(db, 'r1', two_laps())
    db.execute('UPDATE Settings SET segmentRouteDone=0, segmentLapsDone=0 WHERE id=1')
    res = S.rematch_routes(db)
    assert res['ran'] and res['found'] == 1 and res['laps'] == 1
    assert S.rematch_laps(db) == {'ran': False}
