"""Saved routes (PlannedRoute): listed, renamed and given a sport on the Routes page (routes/saved_routes.py), drawn in the planner
(routes/route_builder.py). One that holds a followed line comes from a GPX file, an activity, a Strava export or a Garmin Connect course.

A route made by clicking the map is its waypoints ([{lat, lng}], joined by straight lines). One that follows a line has a track instead,
[[lat, lng, ele], ...] with ele None where the source had no height: hundreds or thousands of points, drawn as one line and exported with
its own heights. Editing one turns it into waypoints (as_waypoints), as a new route, so the line it came from stays.

Each route belongs to a rider and says where it came from (source: planner, gpx, activity, strava, garmin; sourceId the activity's id or the
Garmin course's). Saving the same rider's route again with the same points keeps the one already here, whatever either is called (save), so a
Strava export imported twice, a GPX file chosen twice or a route renamed since makes no copies."""
import json
import math

SOURCES = ('planner', 'gpx', 'activity', 'strava', 'garmin')
MAX_NAME = 100
SIMPLIFY_M = 5          # as_waypoints: how far the straight lines between waypoints may stray from the line they replace
_R = 6371008.8          # metres


def _m(lat1, lng1, lat2, lng2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return _R * 2 * math.asin(math.sqrt(min(1.0, a)))


def distance_m(points):
    """Metres along [[lat, lng, ...], ...] or [{lat, lng}, ...]."""
    pts = [(p['lat'], p['lng']) if isinstance(p, dict) else (p[0], p[1]) for p in points or ()]
    return sum(_m(*pts[i - 1], *pts[i]) for i in range(1, len(pts)))


def gain_m(track):
    """Metres climbed along a track, as gpxpy works it out for a GPX ride (services/parser.py); None when it has no heights."""
    from gpxpy.geo import calculate_uphill_downhill
    eles = [p[2] for p in track if len(p) > 2 and p[2] is not None]
    return round(calculate_uphill_downhill(eles)[0], 1) if len(eles) > 1 else None


def clean(points):
    """[[lat, lng, ele], ...] rounded (lat and lng to 6 places, about 10 cm; ele to 0.1 m), without points the same as the one before (a
    recording standing still) or out of range. points: [[lat, lng], ...] or [[lat, lng, ele], ...]."""
    out = []
    for p in points or ():
        try:
            lat, lng = round(float(p[0]), 6), round(float(p[1]), 6)
            ele = round(float(p[2]), 1) if len(p) > 2 and p[2] is not None else None
        except (TypeError, ValueError, IndexError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
            continue
        if out and out[-1][0] == lat and out[-1][1] == lng:
            continue
        out.append([lat, lng, ele])
    return out


def simplify(track, tol_m=SIMPLIFY_M):
    """Douglas-Peucker: the indexes of the points to keep so that no point left out is more than tol_m from the straight line between the kept
    points either side of it. Measured on a flat projection about the track's middle, near enough over a route's few tens of km."""
    n = len(track)
    if n < 3:
        return list(range(n))
    lat0 = math.radians(sum(p[0] for p in track) / n)
    k = math.pi / 180 * _R
    xy = [(p[1] * k * math.cos(lat0), p[0] * k) for p in track]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:                                        # not recursive: a track has thousands of points
        a, b = stack.pop()
        (ax, ay), (bx, by) = xy[a], xy[b]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        far, far_i = -1.0, None
        for i in range(a + 1, b):
            px, py = xy[i]
            t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
            d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d > far:
                far, far_i = d, i
        if far_i is not None and far > tol_m:
            keep[far_i] = True
            stack += [(a, far_i), (far_i, b)]
    return [i for i in range(n) if keep[i]]


def as_waypoints(track, tol_m=SIMPLIFY_M):
    """A track as planner waypoints [{lat, lng}], simplified (simplify)."""
    return [{'lat': track[i][0], 'lng': track[i][1]} for i in simplify(track, tol_m)]


def from_gpx(data, filename=''):
    """{name, sportType, track} from a GPX file's bytes, or None when it holds no points. The points of its tracks (<trk>), else of its routes
    (<rte>: what the planner's own export writes, so a route goes round trip). The name: <metadata><name>, else the first track's or route's,
    else the file's name. sportType from <trk><type> (Strava's routes say mountain_biking, cycling, running), else None. Raises on a file that
    isn't GPX at all."""
    import os
    from services.parser import _map_sport, read_gpx
    gpx, _ = read_gpx(data)
    pts = [[p.latitude, p.longitude, p.elevation] for t in gpx.tracks for s in t.segments for p in s.points]
    if not pts:
        pts = [[p.latitude, p.longitude, p.elevation] for r in gpx.routes for p in r.points]
    track = clean(pts)
    if len(track) < 2:
        return None
    first = (gpx.tracks or gpx.routes or [None])[0]
    name = (gpx.name or (first.name if first else None) or os.path.splitext(os.path.basename(filename or ''))[0] or 'Route').strip()
    kind = next((t.type for t in gpx.tracks if t.type), None)
    return {'name': name[:100], 'sportType': _map_sport(kind) if kind else None, 'track': track}


def save(db, rider_id, name, *, track=None, waypoints=None, source='planner', source_id=None, sport=None):
    """(id, True) for a new PlannedRoute, or (id, False) when the rider has one already with these points, under any name (it may have been
    renamed since). track: as clean() gives it; waypoints: [{lat, lng}]. Does not commit."""
    name = (name or 'Unnamed Route').strip()[:MAX_NAME] or 'Unnamed Route'
    track_json = json.dumps(track, separators=(',', ':')) if track else None
    wps_json = json.dumps(waypoints or [])
    if track_json:
        same = db.execute('SELECT id FROM PlannedRoute WHERE riderId IS ? AND track=?', [rider_id, track_json]).fetchone()
        if same:
            return same[0], False
    cur = db.execute('''INSERT INTO PlannedRoute (name, waypoints, track, source, sourceId, sportType, riderId, distance, elevationGain)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     [name, wps_json, track_json, source, source_id, sport, rider_id,
                      round(distance_m(track or waypoints or []), 1), gain_m(track) if track else None])
    return cur.lastrowid, True


def from_activity(db, activity_id, rider_id):
    """A route from an activity's own points (its streams, not the track summary cut to a few hundred) for rider_id: (id, created), or None
    when it has no GPS track. Does not commit."""
    from services import streams as _streams
    row = db.execute('SELECT name, sportType FROM Activity WHERE id=?', [activity_id]).fetchone()
    if not row:
        return None
    s = _streams.load(db, activity_id) or {}
    latlng = (s.get('latlng') or {}).get('data') or []
    alt = (s.get('altitude') or {}).get('data') or []
    track = clean([[p[0], p[1], alt[i] if i < len(alt) else None] for i, p in enumerate(latlng) if p and len(p) >= 2])
    if len(track) < 2:
        return None
    return save(db, rider_id, row['name'] or row['sportType'] or 'Route', track=track, source='activity', source_id=str(activity_id),
                sport=row['sportType'])


def import_strava(db, zf, names, rider_id):
    """The routes in a Strava export (routes.csv: Route Name, Route Filename -> routes/<n>.gpx) saved for the rider, source 'strava'. Matched on
    the points (save), as the file numbers change between exports and the route may have been renamed here. {routes_created, routes_existing, routes_unread}. Does not commit."""
    import csv
    import io
    import logging
    log = logging.getLogger(__name__)
    with zf.open('routes.csv') as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='replace')))
    created = existing = unread = 0
    for r in rows:
        path = (r.get('Route Filename') or '').strip()
        if path not in names:
            unread += 1
            continue
        try:
            got = from_gpx(zf.read(path), path)
        except Exception as e:
            log.warning('Strava import: route %s could not be read (%s)', path, e)
            got = None
        if not got:
            unread += 1
            continue
        _, new = save(db, rider_id, (r.get('Route Name') or '').strip() or got['name'], track=got['track'], source='strava',
                      sport=got['sportType'])
        created += new
        existing += not new
    return {'routes_created': created, 'routes_existing': existing, 'routes_unread': unread}


def rename(db, route_id, name):
    """The route's new name, trimmed, or None when it's blank or there's no such route. Does not commit."""
    name = (name or '').strip()[:MAX_NAME]
    if not name:
        return None
    return name if db.execute('UPDATE PlannedRoute SET name=? WHERE id=?', [name, route_id]).rowcount else None


def set_sport(db, route_id, sport):
    """Give the route a sport (one of services/sports.SPORTS), or none with '' or None. False for a sport not in the list or no such route.
    Does not commit."""
    from services import sports
    sport = sports.canonical(sport) or None
    if sport is not None and sport not in sports.SPORTS:
        return False
    return bool(db.execute('UPDATE PlannedRoute SET sportType=? WHERE id=?', [sport, route_id]).rowcount)


def _garmin_courses(raw):
    """The list of courses in what Garmin's /course-service/course/owner/<name> sends: a list, or (in case) an object holding one."""
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list) and all(isinstance(c, dict) for c in v):
                return v
    return []


def _garmin_sport(course):
    from services import sports
    t = course.get('activityType')
    key = t.get('typeKey') if isinstance(t, dict) else course.get('activityTypeKey')
    return sports.from_type(key) if key else None


def import_garmin(db, api, rider_id, progress=None):
    """The rider's Garmin Connect courses (garminconnect's get_courses, then each one's GPX) saved as routes, source 'garmin' with the course id
    in sourceId. A course brought in before is skipped without downloading it again, and one with the same points as a route here is kept once
    (save). A course deleted on Garmin stays here. progress(done, total): after each course.
    {created, existing, unread, total}. Commits after each course, so a run that fails part way keeps what it got."""
    import logging
    log = logging.getLogger(__name__)
    courses = _garmin_courses(api.get_courses())
    have = {r[0] for r in db.execute("SELECT sourceId FROM PlannedRoute WHERE riderId IS ? AND source='garmin'", [rider_id])}
    out = {'created': 0, 'existing': 0, 'unread': 0, 'total': len(courses)}
    for i, c in enumerate(courses):
        cid = c.get('courseId') or c.get('id')
        if cid is None:
            out['unread'] += 1
        elif str(cid) in have:
            out['existing'] += 1
        else:
            try:
                got = from_gpx(api.download_course(cid, 'gpx'), f'{cid}.gpx')
            except Exception as e:
                log.warning('Garmin courses: course %s could not be read (%s)', cid, e)
                got = None
            if not got:
                out['unread'] += 1
            else:
                _, new = save(db, rider_id, (c.get('courseName') or c.get('name') or '').strip() or got['name'], track=got['track'],
                              source='garmin', source_id=str(cid), sport=_garmin_sport(c) or got['sportType'])
                out['created' if new else 'existing'] += 1
                db.commit()
        if progress:
            progress(i + 1, len(courses))
    return out
