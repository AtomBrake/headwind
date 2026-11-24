"""The Routes page's overview and each route's own page (routes/saved_routes.py): every saved route (PlannedRoute) as a light line for the map,
the activities that followed a route, and the segments along it (segments_on).

A route's activities are found as the activity page's "Same route" card finds an activity's (services/matched.py): the same start, finish and
roads, and a distance within matched.DIST_TOL of the route's, from the track summaries (services/tracks.py), so no streams are read except to make
a missing summary. Unlike that card, a route may be followed either way round: one done backwards is kept and marked reversed (a loop done the
other way round is simply the same route, as its start and finish are the same place). A longer activity that took in the whole route on the
way (a ride out to its start and home again) is kept too, marked part: COVER of the route within COVER_M of its line. Only the route's rider's
activities count, of the same family as the route's sport (any ride for a ride, walks, runs and hikes alike on foot, the sport itself
otherwise); a route with no sport takes any activity done outdoors."""
import json
import statistics
from math import cos, radians

from services import matched, planned_routes, sports, tracks
from services import streams as _streams

COVER = 0.95           # a longer activity took in the route when this share of it ...
COVER_M = 100           # ... is within this of the activity's line
COVER_POINTS = 100      # points along the route checked
MAKE_AT_MOST = 200       # find: track summaries made while the page waits, at most
MAP_TOL_M = 15          # how far the overview's line may stray from the route: few points on long straight roads
RECENT = matched.RECENT
_lines = {}             # route id -> (the track's text length, its overview line): a route's points don't change once saved


def _points(row):
    """[[lat, lng], ...] of a PlannedRoute row: its track, else its waypoints joined by straight lines."""
    try:
        if row['track']:
            return [[p[0], p[1]] for p in json.loads(row['track'])]
        return [[w['lat'], w['lng']] for w in json.loads(row['waypoints'] or '[]')]
    except (TypeError, ValueError, KeyError, IndexError):
        return []


def map_line(row):
    """A route's line for the overview map, simplified to MAP_TOL_M and rounded to 5 places (about a metre). [] when it has fewer than two points.
    row: id, track and waypoints of a PlannedRoute. Kept in memory between requests."""
    key = len(row['track'] or row['waypoints'] or '')
    hit = _lines.get(row['id'])
    if hit and hit[0] == key:
        return hit[1]
    pts = _points(row)
    line = [[round(p[0], 5), round(p[1], 5)] for p in tracks.simplify(pts, MAP_TOL_M)] if len(pts) >= 2 else []
    _lines[row['id']] = (key, line)
    return line


def map_lines(db):
    """{id: line} for every saved route, for the overview map."""
    rows = db.execute('SELECT id, track, waypoints FROM PlannedRoute').fetchall()
    return {r['id']: map_line(r) for r in rows}


def _family(sport):
    """What a sport matches against: 'virtual', 'ride', 'foot', or the sport itself. None for no sport (anything outdoors)."""
    if not sport:
        return None
    if sports.is_virtual(sport):
        return 'virtual'
    return sports.segment_family(sport) or sport


def _fits(family, sport):
    if family is None:
        return not sports.is_virtual(sport)
    return _family(sport or 'Ride') == family             # an activity with no sport is a ride (sports.is_ride)


def find(db, route_id, rider_id=None):
    """The activities that followed the route, newest first, as dicts of the Activity row's figures plus reversed (done the other way round)
    and part (took it in as part of a longer one).
    rider_id: whose activities, when the route has no rider of its own. [] for no such route, or one with fewer than two points."""
    route = db.execute('SELECT id, riderId, sportType, distance, track, waypoints FROM PlannedRoute WHERE id=?', [route_id]).fetchone()
    if not route:
        return []
    pts = _points(route)
    if len(pts) < 2:
        return []
    line = tracks.simplify(pts, tracks.SIMPLIFY_M)
    dist = route['distance'] or planned_routes.distance_m(pts)
    if not dist:
        return []
    rider = route['riderId'] if route['riderId'] is not None else rider_id
    family = _family(route['sportType'])
    lo, hi = dist * (1 - matched.DIST_TOL), dist * (1 + matched.DIST_TOL)

    # Activities at least this long that came in since the summaries were last made have none yet: make theirs first (the newest MAKE_AT_MOST:
    # the start-up fill, app._track_summaries, makes the rest)
    missing = db.execute(f'''SELECT a.id, a.sportType, {_streams.sql('a')} FROM Activity a LEFT JOIN ActivityTrack t ON t.activityId = a.id
                             WHERE t.activityId IS NULL AND a.riderId IS ? AND a.distance >= ? ORDER BY a.startDateLocal DESC LIMIT ?''',
                         [rider, lo, MAKE_AT_MOST]).fetchall()
    made = 0
    for aid, sport, streams in missing:
        if _fits(family, sport):
            tracks.store(db, aid, streams)
            made += 1
    if made:
        db.commit()

    lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
    d_lat = matched.BOX_M / matched._M_PER_DEG
    d_lng = matched.BOX_M / (matched._M_PER_DEG * max(0.01, cos(radians(max(lats)))))
    # The box test doesn't care which way round: a route done backwards has the same box
    rows = db.execute('''
        SELECT a.id, a.name, a.sportType, a.startDateLocal, a.distance, a.movingTime, a.elapsedTime, a.totalElevationGain, a.averageSpeed,
               a.averageHeartrate, a.averageWatts, a.weatherWindRel, a.commute, t.line
        FROM Activity a JOIN ActivityTrack t ON t.activityId = a.id
        WHERE a.riderId IS ? AND a.distance BETWEEN ? AND ? AND a.movingTime > 0
          AND abs(t.minLat - ?) <= ? AND abs(t.maxLat - ?) <= ? AND abs(t.minLng - ?) <= ? AND abs(t.maxLng - ?) <= ?
        ORDER BY a.startDateLocal DESC''',
                      [rider, lo, hi, min(lats), d_lat, max(lats), d_lat, min(lngs), d_lng, max(lngs), d_lng]).fetchall()
    out = []
    for r in rows:
        if not _fits(family, r['sportType']):
            continue
        try:
            other = json.loads(r['line'])
        except (TypeError, ValueError):
            continue
        if matched.same_route(line, other):
            back = False
        elif matched.same_route(line, other[::-1]):
            back = True
        else:
            continue
        d = dict(r)
        d.pop('line')
        d.update(reversed=back, part=False)
        out.append(d)

    # Longer ones whose box takes in the route's, that went along all of it
    seen = {d['id'] for d in out}
    d_lat = COVER_M / matched._M_PER_DEG
    d_lng = COVER_M / (matched._M_PER_DEG * max(0.01, cos(radians(max(lats)))))
    rows = db.execute('''
        SELECT a.id, a.name, a.sportType, a.startDateLocal, a.distance, a.movingTime, a.elapsedTime, a.totalElevationGain, a.averageSpeed,
               a.averageHeartrate, a.averageWatts, a.weatherWindRel, a.commute, t.line
        FROM Activity a JOIN ActivityTrack t ON t.activityId = a.id
        WHERE a.riderId IS ? AND a.distance > ? AND a.movingTime > 0
          AND t.minLat <= ? AND t.maxLat >= ? AND t.minLng <= ? AND t.maxLng >= ?''',
                      [rider, lo, min(lats) + d_lat, max(lats) - d_lat, min(lngs) + d_lng, max(lngs) - d_lng]).fetchall()
    if rows:
        lat0 = pts[0][0]
        route_xy = matched._xy(tracks.even(line, COVER_POINTS), lat0)
        allowed = len(route_xy) * (1 - COVER)
        for r in rows:
            if r['id'] in seen or not _fits(family, r['sportType']):
                continue
            try:
                other = matched._xy(json.loads(r['line']), lat0)
            except (TypeError, ValueError):
                continue
            segs = list(zip(other, other[1:]))
            off = 0
            for p in route_xy:
                if all(matched._gap(p, a, b) > COVER_M for a, b in segs):
                    off += 1
                    if off > allowed:
                        break
            if off <= allowed:
                d = dict(r)
                d.pop('line')
                d.update(reversed=False, part=True)
                out.append(d)
    out.sort(key=lambda d: str(d['startDateLocal']), reverse=True)
    return out


def _speed(r):
    return r['averageSpeed'] or (r['distance'] / r['movingTime'] if r['movingTime'] else None)


def summary(db, route_id, rider_id=None):
    """The route's activities and what they add up to, for its page: None when none followed it. Otherwise {activities (newest first, all of
    them), total, parts (how many took it in as part of a longer one), group (the stat group the figures are for: the route's sport's, else
    the one done most), label, done (how many of that group did just the route), best (their quickest by moving time), median (the moving
    time in the middle of their last RECENT), recent (how many that is), last (the newest of all), first (the date of the oldest), series
    [{id, d, secs, mps, name, reversed}] of them oldest first, for the chart}. The figures are for one stat group, because a run's time says
    nothing about a ride's, and only for activities that did the route alone, as a longer one's time is mostly elsewhere; best, median and
    series are None and [] when there are none of those."""
    acts = find(db, route_id, rider_id)
    if not acts:
        return None
    sport = db.execute('SELECT sportType FROM PlannedRoute WHERE id=?', [route_id]).fetchone()[0]
    whole = [a for a in acts if not a['part']]
    groups = [sports.stat_group(a['sportType']) for a in (whole or acts)]
    group = sports.stat_group(sport) if sport and sports.stat_group(sport) in groups else max(set(groups), key=groups.count)
    mine = [a for a in whole if sports.stat_group(a['sportType']) == group]
    recent = mine[:RECENT]
    return {
        'activities': acts,
        'total': len(acts),
        'parts': len(acts) - len(whole),
        'group': group,
        'label': sports.stat_label(group),
        'done': len(mine),
        'best': min(mine, key=lambda r: r['movingTime']) if mine else None,
        'median': statistics.median([r['movingTime'] for r in recent]) if recent else None,
        'recent': len(recent),
        'last': acts[0],
        'first': acts[-1]['startDateLocal'],
        'series': [{'id': r['id'], 'd': str(r['startDateLocal'])[:10], 'secs': r['movingTime'], 'mps': _speed(r), 'name': r['name'],
                    'reversed': r['reversed']} for r in reversed(mine)],
    }


SEG_TOL_M = 40          # segments_on: how far a segment's shape may be from the route (GPS drift in either, the far side of a road)
SEG_SAMPLE_M = 50       # ... checked at a point about this often along the segment, between 5 and 40 of them
SEG_DETOUR = 1.35       # ... and between two of them the route may run at most this much further than the segment (segments.CLOSE_DETOUR)


def _xy(points, lat0):
    k = cos(radians(lat0)) * matched._M_PER_DEG
    return [(p[1] * k, p[0] * matched._M_PER_DEG) for p in points]


def _gap(p, a, b):
    """(metres from p to the part a-b, how far along a-b the nearest point is in metres)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if not ll else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    return ((a[0] + t * dx - p[0]) ** 2 + (a[1] + t * dy - p[1]) ** 2) ** 0.5, t * ll ** 0.5


def _along(route_xy, cum, p, lo, reach):
    """Where along the route (metres from its start) it next comes within SEG_TOL_M of p, from `lo` metres (give or take the tolerance: GPS
    wanders back a little) and no more than `reach` metres further; None when it doesn't."""
    for i in range(len(route_xy) - 1):
        if cum[i + 1] < lo - SEG_TOL_M:
            continue
        if cum[i] > lo + reach:
            return None
        d, t = _gap(p, route_xy[i], route_xy[i + 1])
        at = cum[i] + t
        if d <= SEG_TOL_M and at >= lo - SEG_TOL_M:
            return max(at, lo)
    return None


def _starts(route_xy, cum, p):
    """Each time the route passes within SEG_TOL_M of p, where (metres from its start): one place for each pass, as the parts of the route near p
    on one pass all put their nearest point within a few tolerances of each other, and a pass back the other way is further on."""
    near = []
    for i in range(len(route_xy) - 1):
        d, t = _gap(p, route_xy[i], route_xy[i + 1])
        if d <= SEG_TOL_M:
            near.append(cum[i] + t)
    out = []
    for at in near:
        if not out or at - prev > 2 * SEG_TOL_M:
            out.append(at)
        prev = at
    return out


def _follows_segment(route_xy, cum, shape_xy, step):
    """Metres along the route where it takes in the whole segment the same way round, or None: each of the segment's sample points within
    SEG_TOL_M of the route, in order, with no more than SEG_DETOUR times the gap between them (plus the tolerance either side) of route between.
    Tried from each place the route passes the segment's start, so a loop or an out-and-back that passes it twice is found on either pass."""
    reach = step * SEG_DETOUR + 2 * SEG_TOL_M
    for start in _starts(route_xy, cum, shape_xy[0]):
        at = start
        for p in shape_xy[1:]:
            at = _along(route_xy, cum, p, at, reach)
            if at is None:
                break
        else:
            return start
    return None


def segments_on(db, route_id, rider_id=None):
    """The segments (Segment) the route takes in from end to end, the same way round, in the order it reaches them: [{id, name, sport, distanceM,
    elevationGainM, at (metres along the route where it starts), shape ([[lat, lng], ...], simplified, for the map), efforts and bestSecs (the
    rider's), prDate}]. Of the route's family (a ride's
    segments for a ride, the ones on foot for a walk, run or hike), any family for a route with no sport. rider_id: whose efforts, when the
    route has no rider of its own."""
    route = db.execute('SELECT id, riderId, sportType, track, waypoints FROM PlannedRoute WHERE id=?', [route_id]).fetchone()
    if not route:
        return []
    pts = _points(route)
    if len(pts) < 2:
        return []
    fam = _family(route['sportType'])
    if fam == 'virtual':
        return []
    rider = route['riderId'] if route['riderId'] is not None else rider_id
    box = tracks.box_of(pts, SEG_TOL_M)
    if not box:
        return []
    segs = db.execute('''SELECT id, name, COALESCE(sport, 'ride') AS sport, distanceM, elevationGainM, startLat, startLng, endLat, endLng,
                                polyline
                         FROM Segment WHERE startLat BETWEEN ? AND ? AND startLng BETWEEN ? AND ? AND endLat BETWEEN ? AND ?
                                        AND endLng BETWEEN ? AND ?''', [*box, *box]).fetchall()
    if fam in ('ride', 'foot'):
        segs = [s for s in segs if s['sport'] == fam]
    if not segs:
        return []
    lat0 = pts[0][0]
    line = tracks.simplify(pts, 5)
    route_xy = _xy(line, lat0)
    cum = [0.0]
    for a, b in zip(route_xy, route_xy[1:]):
        cum.append(cum[-1] + ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)
    out = []
    for s in segs:
        try:
            shape = [[float(p[0]), float(p[1])] for p in json.loads(s['polyline'] or '[]') if isinstance(p, list) and len(p) >= 2]
        except (TypeError, ValueError):
            shape = []
        if len(shape) < 2:
            shape = [[s['startLat'], s['startLng']], [s['endLat'], s['endLng']]]
        length = s['distanceM'] or planned_routes.distance_m(shape)
        n = max(5, min(40, int(length / SEG_SAMPLE_M) + 1))
        at = _follows_segment(route_xy, cum, _xy(tracks.even(shape, n), lat0), length / (n - 1))
        if at is not None:
            out.append(dict(s, at=at, shape=[[round(p[0], 5), round(p[1], 5)] for p in tracks.simplify(shape, 5)]))
    if not out:
        return []
    ids = [s['id'] for s in out]
    stats = {r[0]: r for r in db.execute(f'''
        SELECT e.segmentId, COUNT(*), MIN(e.elapsedSecs), MAX(CASE WHEN e.isPR = 1 THEN e.activityDate END)
        FROM SegmentEffort e JOIN Activity a ON a.id = e.activityId
        WHERE a.riderId IS ? AND e.segmentId IN ({','.join('?' * len(ids))}) GROUP BY e.segmentId''', [rider, *ids])}
    for s in out:
        st = stats.get(s['id'])
        s.update(efforts=st[1] if st else 0, bestSecs=st[2] if st else None, prDate=st[3] if st else None)
        for k in ('startLat', 'startLng', 'endLat', 'endLng', 'polyline'):
            s.pop(k)
    return sorted(out, key=lambda s: s['at'])
