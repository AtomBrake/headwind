"""Activities on the same route as this one: "this commute vs your last 20". Same rider, same kind of activity, starting and finishing in the same
places and following the same roads in the same direction, whatever their names say. Worked out from the track summaries (services/tracks.py), so
no activity's streams are read except to make a missing summary.

A route match is:
  - the same kind: a pedal ride with pedal rides, an e-bike ride with e-bike rides, an indoor ride with indoor rides (a Zwift route), an indoor run
    with indoor runs, and anything else with the same sport (a run with runs, never with walks);
  - a distance within DIST_TOL of this one's, and a bounding box whose every edge is within BOX_M of this one's (cheap, in SQL);
  - a start and a finish within END_M of this one's, so the ride home is not the ride to work;
  - and SHARE of each track's sampled points within NEAR_M of the other's line, so a detour or a different road between the same two places is
    not the same route.
"""
import json
import statistics
from math import cos, radians

from services import sports, tracks

DIST_TOL = 0.12
BOX_M = 400
END_M = 300
NEAR_M = 150
SHARE = 0.8
RECENT = 20         # "your last 20"
_M_PER_DEG = 111_320.0


def _xy(points, lat0):
    k = cos(radians(lat0))
    return [(p[1] * _M_PER_DEG * k, p[0] * _M_PER_DEG) for p in points]


def _gap(p, a, b):
    """Metres from point p to the segment a-b (all (x, y) in metres)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if not ll else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    ex, ey = a[0] + t * dx - p[0], a[1] + t * dy - p[1]
    return (ex * ex + ey * ey) ** 0.5


def _follows(pts, line):
    """Do SHARE of pts lie within NEAR_M of the line through `line`? Stops as soon as too many are off it."""
    allowed = len(pts) * (1 - SHARE)
    off = 0
    segs = list(zip(line, line[1:])) or [(line[0], line[0])]
    for p in pts:
        if all(_gap(p, a, b) > NEAR_M for a, b in segs):
            off += 1
            if off > allowed:
                return False
    return True


def same_route(line_a, line_b):
    """Are two sampled tracks ([[lat, lng], ...], services/tracks) the same route, ridden the same way?"""
    if not line_a or not line_b or len(line_a) < 2 or len(line_b) < 2:
        return False
    a, b = _xy(line_a, line_a[0][0]), _xy(line_b, line_a[0][0])
    d = lambda p, q: ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
    if d(a[0], b[0]) > END_M or d(a[-1], b[-1]) > END_M:
        return False
    return _follows(a, b) and _follows(b, a)


def _kind_sql(db, act):
    """(SQL, params) keeping the activities of the same kind as `act` (see the module's docstring). Columns are a.* and b.* (the bike)."""
    sport = act['sportType']
    if sports.is_ride(sport):
        if sports.is_virtual(sport):
            return sports.virtual_sql('a.sportType'), []
        cls = sports.class_of(db, act['id']) or 'bike'
        return f"{sports.RIDE_SQL.replace('sportType', 'a.sportType')} AND NOT {sports.virtual_sql('a.sportType')} AND " \
               f"{sports.class_sql(cls, 'a.sportType', 'b.kind')}", []
    if sports.is_virtual(sport):                         # a Zwift run: Strava's "Virtual Run" and Garmin's VirtualRun alike, never a Zwift ride
        return f"{sports.virtual_sql('a.sportType')} AND NOT {sports.RIDE_SQL.replace('sportType', 'a.sportType')}", []
    return 'a.sportType IS ?', [sport]


def _line(db, act_id):
    row = db.execute('SELECT line, minLat, maxLat, minLng, maxLng FROM ActivityTrack WHERE activityId=?', [act_id]).fetchone()
    if row is None:
        streams = db.execute('SELECT streams FROM Activity WHERE id=?', [act_id]).fetchone()
        if not streams:
            return None, None
        tracks.store(db, act_id, streams[0])
        db.commit()
        row = db.execute('SELECT line, minLat, maxLat, minLng, maxLng FROM ActivityTrack WHERE activityId=?', [act_id]).fetchone()
    if not row or not row[0]:
        return None, None
    return json.loads(row[0]), tuple(row[1:])


def find(db, act_id):
    """Every other activity on the same route as this one, oldest first, as dicts of the Activity row's figures. [] for one with no track (an indoor
    ride without a game route, a pool swim, a manual entry)."""
    act = db.execute('SELECT * FROM Activity WHERE id=?', [act_id]).fetchone()
    if not act or not act['distance']:
        return []
    line, box = _line(db, act_id)
    if not line:
        return []
    kind, kparams = _kind_sql(db, act)
    lo, hi = act['distance'] * (1 - DIST_TOL), act['distance'] * (1 + DIST_TOL)
    try:
        db.execute('SELECT 1 FROM Bike LIMIT 0')
        bike_join = 'LEFT JOIN Bike b ON b.id = a.bikeId'
    except Exception:                                     # a bare test database
        bike_join = 'LEFT JOIN (SELECT NULL AS id, NULL AS kind) b ON 0'

    # Activities of this kind and length that came in since the summaries were last made have none yet: make theirs first
    missing = db.execute(f'''SELECT a.id, a.streams FROM Activity a {bike_join} LEFT JOIN ActivityTrack t ON t.activityId = a.id
                             WHERE t.activityId IS NULL AND a.riderId IS ? AND a.distance BETWEEN ? AND ? AND {kind}''',
                         [act['riderId'], lo, hi, *kparams]).fetchall()
    for aid, streams in missing:
        tracks.store(db, aid, streams)
    if missing:
        db.commit()

    d_lat = BOX_M / _M_PER_DEG
    d_lng = BOX_M / (_M_PER_DEG * max(0.01, cos(radians(box[1]))))
    rows = db.execute(f'''
        SELECT a.id, a.name, a.sportType, a.startDateLocal, a.distance, a.movingTime, a.elapsedTime, a.totalElevationGain,
               a.averageSpeed, a.averageHeartrate, a.averageWatts, a.weatherWindRel, a.weatherWindKph, a.weatherTempC, a.commute, t.line
        FROM Activity a {bike_join} JOIN ActivityTrack t ON t.activityId = a.id
        WHERE a.riderId IS ? AND a.id != ? AND a.distance BETWEEN ? AND ? AND a.movingTime > 0 AND {kind}
          AND abs(t.minLat - ?) <= ? AND abs(t.maxLat - ?) <= ? AND abs(t.minLng - ?) <= ? AND abs(t.maxLng - ?) <= ?
        ORDER BY a.startDateLocal
    ''', [act['riderId'], act_id, lo, hi, *kparams, box[0], d_lat, box[1], d_lat, box[2], d_lng, box[3], d_lng]).fetchall()
    out = []
    for r in rows:
        try:
            other = json.loads(r['line'])
        except (TypeError, ValueError):
            continue
        if same_route(line, other):
            d = dict(r)
            d.pop('line')
            out.append(d)
    return out


def _speed(r):
    return r['averageSpeed'] or (r['distance'] / r['movingTime'] if r['movingTime'] else None)


def compare(db, act_id):
    """This activity against the others on its route: None when it has no route or nobody else has ridden it. Otherwise
    {this, total (with this one), rank (1 the quickest moving time, of total), best (the quickest other), recent (the RECENT before this one, newest
    first), median (their median moving time), delta (this one's moving time minus that median: below 0 is quicker), wins (of those recent, how
    many this one beats), first (the date of the first time), series [{id, d, secs, mps, name, current}] oldest first, for the chart}."""
    others = find(db, act_id)
    if not others:
        return None
    a = db.execute('SELECT id, name, sportType, startDateLocal, distance, movingTime, averageSpeed, commute FROM Activity WHERE id=?',
                   [act_id]).fetchone()
    this = dict(a)
    every = sorted(others + [this], key=lambda r: str(r['startDateLocal']))
    before = [r for r in others if str(r['startDateLocal']) < str(this['startDateLocal'])]
    recent = list(reversed(before[-RECENT:]))
    median = statistics.median([r['movingTime'] for r in recent]) if recent else None
    by_time = sorted(every, key=lambda r: r['movingTime'])
    return {
        'this': this,
        'total': len(every),
        'rank': next(i for i, r in enumerate(by_time, 1) if r['id'] == this['id']),
        'best': min(others, key=lambda r: r['movingTime']),
        'recent': recent,
        'median': median,
        'delta': this['movingTime'] - median if median is not None else None,
        'wins': sum(1 for r in recent if this['movingTime'] < r['movingTime']),
        'first': every[0]['startDateLocal'],
        'others': list(reversed(others)),
        'series': [{'id': r['id'], 'd': str(r['startDateLocal'])[:10], 'secs': r['movingTime'], 'mps': _speed(r), 'name': r['name'],
                    'current': r['id'] == this['id']} for r in every],
    }
