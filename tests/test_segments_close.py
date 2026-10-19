"""The forgiving 'close match' tier: rides that clearly follow a segment but are not perfectly on it."""
import json
import sqlite3
from math import cos, radians

from services import segments as S

LAT0, LNG0 = 50.0, 0.0
M_LAT = 1 / 111_195.0                               # degrees per metre northwards


def _line(length_m, offset_m=0.0, step=10.0, start_m=0.0):
    """Points along a straight north-going road, `offset_m` metres east of it."""
    off = offset_m / (111_195.0 * cos(radians(LAT0)))
    n = int(length_m / step) + 1
    return [[LAT0 + (start_m + i * step) * M_LAT, LNG0 + off] for i in range(n)]


def _ride(points, speed=6.0, step=10.0):
    return json.dumps({'latlng': {'data': points}, 'time': {'data': [int(i * step / speed) for i in range(len(points))]}})


def _seg(length=3000.0):
    poly = _line(length)
    return {'id': 1, 'sport': 'ride', 'distanceM': length, 'startLat': poly[0][0], 'startLng': poly[0][1],
            'endLat': poly[-1][0], 'endLng': poly[-1][1], 'polyline': json.dumps(poly)}


def test_exact_ride_is_still_exact():
    seg = _seg()
    assert S.match_segment(_ride(_line(3000)), seg) is not None


def test_stops_short_of_the_end_is_caught_as_close_not_exact():
    seg = _seg()
    ride = _ride(_line(3200, start_m=-500))          # starts before, finishes 300 m (10%) short
    assert S.match_segment(ride, seg) is None
    secs, cover = S.match_segment_close(ride, seg)
    assert 0.85 <= cover <= 0.95
    assert abs(secs - 3000 / 6.0) < 15              # same speed -> time scaled to the whole segment


def test_a_road_beside_it_is_not_it():
    """Until 0.7.7 a line 50 m to one side the whole way counted as a close match; on a real export that was a road beside a trail segment
    ("Avoiding the road"), at road speeds. Drift wanders either side of the line; a parallel road sits off it the whole way (CLOSE_MEDIAN_M)."""
    seg = _seg()
    ride = _ride(_line(3000, offset_m=50))           # 50 m east: too far for the exact start/end zones
    assert S.match_segment(ride, seg) is None
    assert S.match_segment_close(ride, seg) is None


def test_only_part_of_it_is_not_a_match():
    assert S.match_segment_close(_ride(_line(1800)), _seg()) is None        # 60 %


def test_riding_it_the_other_way_is_not_a_match():
    assert S.match_segment_close(_ride(_line(3000)[::-1]), _seg()) is None


def test_a_different_road_nearby_is_not_a_match():
    assert S.match_segment_close(_ride(_line(3000, offset_m=400)), _seg()) is None


def test_too_slow_is_not_a_match():
    assert S.match_segment_close(_ride(_line(2800), speed=0.8), _seg()) is None


def test_segment_without_a_shape_cannot_be_matched_loosely():
    seg = _seg(); seg['polyline'] = None
    assert S.match_segment_close(_ride(_line(3000)), seg) is None


def test_approximate_efforts_never_take_the_pr():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE SegmentEffort (id INTEGER PRIMARY KEY, segmentId INT, activityId TEXT, activityDate TEXT, elapsedSecs INT,
                                    avgSpeedMps REAL, isPR INT DEFAULT 0, approx INT DEFAULT 0);
        CREATE TABLE Segment (id INTEGER PRIMARY KEY, sport TEXT);
        CREATE TABLE Activity (id TEXT, riderId INT, sportType TEXT, bikeId INT);
        CREATE TABLE Bike (id INTEGER PRIMARY KEY, kind TEXT);
        CREATE VIEW SegActivity AS SELECT id, riderId, sportType, bikeId FROM Activity;
        INSERT INTO Segment VALUES (1, 'ride');
        INSERT INTO Activity VALUES ('a', 1, 'Ride', NULL), ('b', 1, 'Ride', NULL);
        INSERT INTO SegmentEffort (segmentId, activityId, elapsedSecs, approx) VALUES (1, 'a', 500, 0), (1, 'b', 400, 1);
    ''')
    S._refresh_prs(db, 1)
    assert [r['activityId'] for r in db.execute('SELECT activityId FROM SegmentEffort WHERE isPR=1')] == ['a']
