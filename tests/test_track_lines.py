"""The heatmap's lines (services/tracks.simplify): the points needed to stay within a tolerance of the recorded track, so straight roads take few
points and bends keep theirs; spaced out evenly again (tracks.even) for anything that counts points; and rows made the old way (every nth point)
made again. Throwaway DB."""
import json
import random
from math import cos, radians

import pytest
from flask import Flask

import database
from services import tracks
from services import streams as _streams

LAT0, LNG0 = 51.5, -0.12
M_LAT = 1 / 111_320.0
M_LNG = 1 / (111_320.0 * cos(radians(LAT0)))


def walk(legs, step=5.0):
    """[[lat, lng], ...] along straight legs [(east m, north m), ...] from LAT0/LNG0, a point every `step` metres."""
    pts, x, y = [[LAT0, LNG0]], 0.0, 0.0
    for dx, dy in legs:
        n = max(1, int((dx * dx + dy * dy) ** 0.5 / step))
        pts += [[LAT0 + (y + dy * i / n) * M_LAT, LNG0 + (x + dx * i / n) * M_LNG] for i in range(1, n + 1)]
        x, y = x + dx, y + dy
    return pts


def metres(p, q):
    return (((p[0] - q[0]) / M_LAT) ** 2 + ((p[1] - q[1]) / M_LNG) ** 2) ** 0.5


def off_line(p, line):
    """Metres from p to the nearest segment of line."""
    best = float('inf')
    for a, b in zip(line, line[1:]):
        ax, ay, bx, by = a[1] / M_LNG, a[0] / M_LAT, b[1] / M_LNG, b[0] / M_LAT
        px, py = p[1] / M_LNG, p[0] / M_LAT
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0.0 if not ll else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
        best = min(best, ((ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2) ** 0.5)
    return best


def test_a_straight_road_is_its_two_ends():
    pts = walk([(0, 5000)])
    assert tracks.simplify(pts, 10) == [pts[0], pts[-1]]


def test_every_bend_is_kept():
    legs = [(0, 2000), (3000, 0), (0, 1000), (-500, -500)]
    corners = [walk(legs[:k])[-1] for k in range(len(legs) + 1)]
    out = tracks.simplify(walk(legs), 10)
    assert len(out) == len(corners) and all(metres(a, b) < 0.01 for a, b in zip(out, corners))


def test_an_out_and_back_keeps_its_turn():
    pts = walk([(0, 3000), (0, -3000)])                 # first and last points are the same: the turn is still far from the segment between them
    assert len(tracks.simplify(pts, 10)) == 3


def test_every_point_stays_within_the_tolerance():
    random.seed(4)
    legs = [(random.uniform(-40, 40), random.uniform(-40, 40)) for _ in range(400)]     # a wandering GPS track with noise
    pts = walk(legs, step=3)
    for tol in (5, 10, 20):
        out = tracks.simplify(pts, tol)
        assert out[0] == pts[0] and out[-1] == pts[-1] and len(out) < len(pts)
        assert max(off_line(p, out) for p in pts) <= tol + 0.01


def test_even_spreads_points_by_distance():
    line = tracks.simplify(walk([(0, 1000), (3000, 0)]), 10)      # 3 points: one short leg, one long one
    out = tracks.even(line, 41)
    assert len(out) == 41 and metres(out[0], line[0]) < 0.01 and metres(out[-1], line[-1]) < 0.01
    gaps = [metres(a, b) for a, b in zip(out, out[1:])]
    assert all(abs(g - 100) < 1 for g in gaps)          # 4 km in 40 steps
    assert tracks.even([[LAT0, LNG0], [LAT0, LNG0]], 5) == [[LAT0, LNG0]] * 5     # no distance at all


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


def test_lines_made_the_old_way_are_made_again(db):
    pts = walk([(0, 2000), (3000, 0)])
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId) "
               "VALUES ('a1', 'a1', 'Ride', 'Ride', '2026-11-01T10:00:00', '2026-11-01T10:00:00', 5000, 900, 900, '{}', 1)")
    _streams.save(db, 'a1', json.dumps({'latlng': {'data': pts}}))
    tracks.fill(db)
    line = json.loads(db.execute("SELECT line FROM ActivityTrack").fetchone()[0])
    assert len(line) == 3 and len(json.loads(db.execute("SELECT lineHd FROM ActivityTrack").fetchone()[0])) == 3
    db.execute("UPDATE ActivityTrack SET version = NULL, line = '[[0,0],[1,1]]'")       # as an older Headwind left it
    tracks.ensure_schema(db)
    assert db.execute('SELECT COUNT(*) FROM ActivityTrack').fetchone()[0] == 0
    assert tracks.fill(db) == 1 and json.loads(db.execute("SELECT line FROM ActivityTrack").fetchone()[0]) == line
