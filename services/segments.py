import json
import logging
from functools import lru_cache
from math import atan2, ceil, cos, isfinite, radians, sin, sqrt

from services import tracks
from services.sports import FAMILIES, class_of, ebike_sql, family_of, segment_family

log = logging.getLogger(__name__)

TOLERANCE_M = 30  # metres — how close to a segment endpoint counts as a hit
CHECKPOINT_M = 60  # metres — tolerance for interior waypoints (wider to absorb GPS drift)
CHECKPOINT_N = 4   # number of evenly-spaced interior checkpoints to sample
MIN_SPEED_MPS = {'ride': 2.0, 'foot': 0.5}   # slower than this is a false match (4.5 mph on a bike; on foot, a steep hike's pace)
CLOSE_TOL_M = 75        # a ride counts as "on the shape" within this many metres (GPS drift, a different lane, a cycle path beside the road)
CLOSE_COVER = 0.85      # share of the segment's length the ride must follow, in order, to count as a close (approximate) match
CLOSE_DETOUR = 1.35     # the ride's own path over that stretch may be at most this much longer than the segment (no loops / wandering)
_BATCH = 50             # activities whose streams are read at a time in a full scan (~1 MB each)


def seg_sport(seg):
    """A segment's family (services/sports.FAMILIES). 'run' is what segments on foot were called before 0.7.3, and 'eride' what 0.7.3 called e-bike
    segments; a friend on an older version still sends them."""
    try:
        v = (seg['sport'] if 'sport' in seg.keys() else None) or 'ride'
    except AttributeError:
        v = seg.get('sport') or 'ride'
    return v if v in FAMILIES else ('foot' if v == 'run' else 'ride')


def _activity_family(db, activity):
    """sports.segment_family for an activity row (or a dict with its id, and its sportType or sport)."""
    try:
        keys = activity.keys()
    except AttributeError:
        keys = []
    st = activity['sportType'] if 'sportType' in keys else (activity['sport'] if 'sport' in keys else None)
    if st is None:
        return family_of(db, activity['id'])
    return segment_family(st)


def _haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl  = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


_M_PER_DEG = 6_371_000 * 3.141592653589793 / 180       # a degree of latitude, on _haversine's sphere


def _window(lat, lng, tol_m):
    """(lat, lng, d_lat, d_lng): a point further than d_lat degrees of latitude or d_lng of longitude from (lat, lng) is more than tol_m metres
    from it by _haversine, so the matchers skip the haversine for it. Exact, not an approximation: the great-circle distance is at least the
    latitude difference, and at least the longitude difference times the cosine of the larger latitude (the 0.99 covers rounding)."""
    d_lat = tol_m / _M_PER_DEG
    c = cos(radians(min(89.9, abs(lat) + d_lat)))
    return lat, lng, d_lat, tol_m / (_M_PER_DEG * c * 0.99)


def _near(win, lat, lng, tol_m):
    """The distance from the window's point to (lat, lng) when it is within tol_m, else None."""
    la, ln, d_lat, d_lng = win
    if abs(lat - la) >= d_lat or abs(lng - ln) >= d_lng:
        return None
    d = _haversine(lat, lng, la, ln)
    return d if d < tol_m else None


def _parsed(streams):
    """An activity's streams as a dict, from JSON text or already parsed, so a scan parses each activity once. {} when it doesn't parse."""
    if isinstance(streams, dict):
        return streams
    try:
        out = json.loads(streams or '{}')
    except Exception:
        return {}
    return out if isinstance(out, dict) else {}


@lru_cache(maxsize=4096)
def _poly(polyline_json):
    """A segment's stored shape, parsed once however many activities it is matched against. Read-only: the list is shared."""
    try:
        pts = json.loads(polyline_json) if polyline_json else []
    except Exception:
        return []
    return pts if isinstance(pts, list) else []


@lru_cache(maxsize=4096)
def _seg_reach(start_lat, start_lng, end_lat, end_lng, polyline_json):
    raw = _poly(polyline_json)
    poly = [p[:2] for p in raw if isinstance(p, list) and len(p) >= 2]
    if len(poly) != len(raw):                           # a shape with a bad point: don't skip anything on its account
        return None, None, None
    try:
        start, end = (float(start_lat), float(start_lng)), (float(end_lat), float(end_lng))
        poly = [(float(a), float(b)) for a, b in poly]
        box = tracks.box_of([start, end] + poly, CLOSE_TOL_M)
        head, tail = [start], [end]
        if len(poly) >= 4:                              # match_segment_close needs a shape this long
            shape, cum = _close_shape(poly)
            length = cum[-1]
            head += [q for q, c in zip(shape, cum) if not length or c <= (1 - CLOSE_COVER + 0.05) * length]
            tail += [q for q, c in zip(shape, cum) if not length or c >= (CLOSE_COVER - 0.05) * length]
        head, tail = tracks.cells_near(head), tracks.cells_near(tail)
        return box, (frozenset(head) if head else None), (frozenset(tail) if tail else None)
    except (TypeError, ValueError, IndexError):
        return None, None, None


def seg_reach(seg):
    """(box, head, tail): where an activity's track must go to have any chance on this segment, by either matcher. Both need GPS points within
    CLOSE_TOL_M (the larger tolerance) of the segment, near both of its ends: match_segment within TOLERANCE_M of the start and of the finish,
    match_segment_close of shape samples in the first and the last 1 - CLOSE_COVER of its length (it must cover CLOSE_COVER of it). So the track's
    box must overlap the segment's, widened by CLOSE_TOL_M, and its points must be in a cell next to one of `head` (around the start) and one
    of `tail` (around the finish; services/tracks.cells_near). Any is None when the segment has no usable position, and then nothing is skipped
    on its account."""
    keys = seg.keys() if hasattr(seg, 'keys') else []
    return _seg_reach(seg['startLat'], seg['startLng'], seg['endLat'], seg['endLng'], seg['polyline'] if 'polyline' in keys else None)


def can_reach(box, cells, reach):
    """Can a track with this box and these cells (a set, or None if unknown) be on the segment with this seg_reach? False only when it can't."""
    sbox, head, tail = reach
    if box and sbox and not tracks.overlaps(box, sbox):
        return False
    if cells is not None and head is not None and tail is not None and (head.isdisjoint(cells) or tail.isdisjoint(cells)):
        return False
    return True


def valid_coord(lat, lng):
    """(lat, lng) as floats if they are a real position, else None. Friends can supply segments, so never trust stored values."""
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (isfinite(la) and isfinite(ln)) or abs(la) > 90 or abs(ln) > 180:
        return None
    return [round(la, 6), round(ln, 6)]


def clean_polyline(raw, max_points=1500):
    """Parse + validate a segment shape (JSON text or list of [lat, lng]). Returns a clean list, downsampled if huge, or None if
    it is missing, malformed or contains any impossible point. Rejecting the whole shape beats drawing part of a bad one."""
    try:
        pts = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except ValueError:
        return None
    if not isinstance(pts, list):
        return None
    out = []
    for p in pts:
        try:
            c = valid_coord(p[0], p[1])
        except (TypeError, IndexError, KeyError):
            return None
        if c is None:
            return None
        out.append(c)
    if len(out) < 2:
        return None
    if len(out) > max_points:
        step = ceil(len(out) / max_points)
        out = out[::step] + ([out[-1]] if (len(out) - 1) % step else [])
    return out


def _path_length_m(pts):
    return sum(_haversine(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))


def _slice_between(streams_json, seg, tol_m=150, dist_tol=0.35):
    """The part of a ride's GPS trace that runs from the segment's start to its finish, or None if this ride doesn't clearly
    follow it: both ends must be near, in the right order, and the path length must agree with the segment distance."""
    try:
        ll = ((json.loads(streams_json or '{}').get('latlng') or {}).get('data')) or []
    except ValueError:
        return None
    pts = [valid_coord(p[0], p[1]) for p in ll if isinstance(p, (list, tuple)) and len(p) >= 2]
    pts = [p for p in pts if p]
    start, end = valid_coord(seg['startLat'], seg['startLng']), valid_coord(seg['endLat'], seg['endLng'])
    if len(pts) < 2 or not start or not end:
        return None
    si = min(range(len(pts)), key=lambda i: _haversine(start[0], start[1], pts[i][0], pts[i][1]))
    if _haversine(start[0], start[1], pts[si][0], pts[si][1]) > tol_m:
        return None
    after = range(si + 1, len(pts))
    if not after:
        return None
    ei = min(after, key=lambda i: _haversine(end[0], end[1], pts[i][0], pts[i][1]))
    if _haversine(end[0], end[1], pts[ei][0], pts[ei][1]) > tol_m:
        return None
    piece = pts[si:ei + 1]
    if len(piece) < 2:
        return None
    dist = seg['distanceM']
    if dist:
        length = _path_length_m(piece)
        if abs(length - float(dist)) / float(dist) > dist_tol:
            return None
    return clean_polyline(piece, max_points=400)


def recover_polyline(db, seg):
    """Rebuild a missing segment shape from the ride it was drawn on, else from the fastest matching efforts. None if no ride
    verifiably follows the segment — callers should then say the shape is unavailable rather than draw a straight line."""
    tried = set()
    ids = [seg['sourceActivityId']] if seg['sourceActivityId'] else []
    ids += [r[0] for r in db.execute(
        'SELECT activityId FROM SegmentEffort WHERE segmentId=? ORDER BY elapsedSecs ASC LIMIT 6', [seg['id']])]
    for aid in ids:
        if not aid or aid in tried:
            continue
        tried.add(aid)
        row = db.execute('SELECT streams FROM Activity WHERE id=?', [aid]).fetchone()
        if row and row[0]:
            shape = _slice_between(row[0], seg)
            if shape:
                return shape
    return None


def _sample_checkpoints(polyline_json, n=CHECKPOINT_N):
    """Return n evenly-spaced interior points from a segment polyline, skipping endpoints."""
    pts = _poly(polyline_json)
    if len(pts) < 4:
        return []
    interior = pts[1:-1]
    step = max(1, len(interior) // (n + 1))
    return [interior[min(i * step, len(interior) - 1)] for i in range(1, n + 1)]


def match_segment(activity_streams_json, seg):
    """
    Returns elapsed_secs (int) for the fastest valid effort on this segment,
    or None if the activity never traverses it. The streams are JSON text or already parsed (_parsed).

    Finds every entry into the start-zone (outside→inside TOLERANCE_M
    transition), tries each as a candidate start, then looks for the closest
    approach to the end *after* that candidate.  Taking the minimum elapsed
    time across all candidates means:
      - Loop rides (up + back down past start) are handled correctly
      - Direction is enforced (end must follow start in the GPS stream)
      - Multiple laps of the same segment return the fastest lap
    """
    streams = _parsed(activity_streams_json)
    latlng = (streams.get('latlng') or {}).get('data') or []
    times  = (streams.get('time')   or {}).get('data') or []

    if not latlng or not times:
        return None
    n = min(len(latlng), len(times))
    latlng = latlng[:n]
    times  = times[:n]

    dist_m      = seg['distanceM'] or 0
    checkpoints = [_window(cp[0], cp[1], CHECKPOINT_M) for cp in _sample_checkpoints(seg['polyline'])] if seg['polyline'] else []
    start_win   = _window(seg['startLat'], seg['startLng'], TOLERANCE_M)
    end_win     = _window(seg['endLat'], seg['endLng'], TOLERANCE_M)
    best_elapsed = None

    def _try_start(start_idx):
        nonlocal best_elapsed
        # Find the first entry into the end zone (mirrors start-zone logic).
        # Committing to the first crossing prevents a later near-miss on the
        # return leg from inflating the elapsed time.
        in_end_zone = False
        end_idx, end_dist = None, float('inf')
        for j in range(start_idx + 1, len(latlng)):
            d = _near(end_win, latlng[j][0], latlng[j][1], TOLERANCE_M)
            if d is not None:
                in_end_zone = True
                if d < end_dist:
                    end_dist = d
                    end_idx  = j
            elif in_end_zone:
                break  # exited end zone — use best point from this visit
        if end_idx is None:
            return
        elapsed = times[end_idx] - times[start_idx]
        if elapsed <= 0:
            return
        if dist_m and (dist_m / elapsed) < MIN_SPEED_MPS[seg_sport(seg)]:
            return  # too slow to be a real effort — false match
        if dist_m:
            # Reject shortcut routes: actual GPS distance must be ≥70% of
            # stored segment distance so riders who take a shorter road between
            # the same start/end coordinates don't appear on the leaderboard.
            actual_dist = sum(
                _haversine(latlng[j][0], latlng[j][1], latlng[j + 1][0], latlng[j + 1][1])
                for j in range(start_idx, end_idx)
            )
            if actual_dist < dist_m * 0.7:
                return
        # For segments with a polyline, require the activity to pass near each
        # sampled interior checkpoint in order. This catches rides that hit the
        # start and end zones via a completely different route (especially loops
        # where start ≈ end, so the endpoint check alone is not enough).
        if checkpoints:
            cp_cursor = start_idx
            for cp in checkpoints:
                hit = False
                for j in range(cp_cursor + 1, end_idx):
                    if _near(cp, latlng[j][0], latlng[j][1], CHECKPOINT_M) is not None:
                        cp_cursor = j
                        hit = True
                        break
                if not hit:
                    return
        if best_elapsed is None or elapsed < best_elapsed:
            best_elapsed = elapsed

    # Walk the stream, detecting each entry into the start zone and tracking
    # the closest approach within that visit.
    in_zone      = False
    zone_best_i  = None
    zone_best_d  = float('inf')

    for i, (lat, lng) in enumerate(latlng):
        d = _near(start_win, lat, lng, TOLERANCE_M)
        if d is not None:
            if not in_zone:
                in_zone = True
            if d < zone_best_d:
                zone_best_d = d
                zone_best_i = i
        else:
            if in_zone:
                _try_start(zone_best_i)
                in_zone = False
                zone_best_i = None
                zone_best_d = float('inf')

    # Ride ends while still inside the start zone
    if in_zone and zone_best_i is not None:
        _try_start(zone_best_i)

    return best_elapsed


def _close_shape(poly):
    """The samples of a segment's shape match_segment_close follows (~120 is plenty for a 75 m margin), and the distance along them to each."""
    step = max(1, len(poly) // 120)
    shape = poly[::step] + ([poly[-1]] if (len(poly) - 1) % step else [])
    cum = [0.0]
    for a, b in zip(shape, shape[1:]):
        cum.append(cum[-1] + _fast_m(a[0], a[1], b[0], b[1]))
    return shape, cum


def _fast_m(lat1, lng1, lat2, lng2):
    """Equirectangular distance in metres: ~0.1% off at these ranges and several times cheaper than haversine."""
    x = radians(lng2 - lng1) * cos(radians((lat1 + lat2) / 2))
    y = radians(lat2 - lat1)
    return 6_371_000 * sqrt(x * x + y * y)


def match_segment_close(activity_streams_json, seg):
    """
    The forgiving second chance for a ride that follows a segment but is not PERFECTLY on it (a stop short of the end marker,
    GPS drift, a lane or path beside the road). Returns (estimated_elapsed_secs, covered_fraction) or None.

    The ride must run along the stored shape in the right order, within CLOSE_TOL_M of it, for at least CLOSE_COVER of its
    length, without wandering (CLOSE_DETOUR) and at a believable speed. The time is the time over the part followed, scaled up
    to the whole segment, so it is an estimate: callers store it with approx=1 and never let it take a PR.
    Segments with no stored shape cannot be matched this way. The streams are JSON text or already parsed (_parsed).
    """
    poly = _poly(seg['polyline'])
    streams = _parsed(activity_streams_json)
    if len(poly) < 4:
        return None
    ll = (streams.get('latlng') or {}).get('data') or []
    tm = (streams.get('time') or {}).get('data') or []
    n = min(len(ll), len(tm))
    if n < 10:
        return None
    seg_len = float(seg['distanceM'] or 0) or _path_length_m(poly)
    if seg_len <= 0:
        return None
    shape, cum = _close_shape(poly)
    shape_len = cum[-1] or 1.0
    cell = 0.0015                                          # ~170 m grid: only ride points near the shape matter
    grid = {(int(q[0] / cell) + di, int(q[1] / cell) + dj) for q in shape for di in (-1, 0, 1) for dj in (-1, 0, 1)}   # each cell and its 8 neighbours
    near = []                                              # (ride index, lat, lng) in ride order
    for i in range(n):
        la, ln = ll[i][0], ll[i][1]
        if (int(la / cell), int(ln / cell)) in grid:
            near.append((i, la, ln))
    if len(near) < 5:
        return None
    cursor, hits = 0, []                                   # hits: (shape sample k, ride index)
    for k, q in enumerate(shape):
        for pos in range(cursor, len(near)):
            if _fast_m(near[pos][1], near[pos][2], q[0], q[1]) <= CLOSE_TOL_M:
                hits.append((k, near[pos][0]))
                cursor = pos
                break
    if len(hits) < 4:
        return None
    k0, i0 = hits[0]
    k1, i1 = hits[-1]
    span = cum[k1] - cum[k0]
    if span < CLOSE_COVER * shape_len or i1 <= i0:
        return None
    if len(hits) < CLOSE_COVER * (k1 - k0 + 1):            # skipped too much of the stretch it claims to cover
        return None
    path = sum(_fast_m(ll[j][0], ll[j][1], ll[j + 1][0], ll[j + 1][1]) for j in range(i0, i1))
    if path > CLOSE_DETOUR * span:
        return None
    secs = tm[i1] - tm[i0]
    if secs <= 0:
        return None
    est = secs * (shape_len / span)
    if seg_len / est < MIN_SPEED_MPS[seg_sport(seg)]:
        return None
    return int(round(est)), span / shape_len


def _refresh_prs(db, segment_id):
    """Mark each rider's personal best. On a ride segment a rider has two, one on a pedal bike and one on an e-bike (services/sports.segment_class),
    so an e-bike ride never takes a pedal PR. An approximate effort never takes one."""
    db.execute('UPDATE SegmentEffort SET isPR=0 WHERE segmentId=?', [segment_id])
    seg = db.execute('SELECT sport FROM Segment WHERE id=?', [segment_id]).fetchone()
    ebike = ebike_sql() if seg and seg_sport(seg) == 'ride' else '0'
    best = {}
    for r in db.execute(f'''
        SELECT e.id, a.riderId, {ebike} AS ebike
        FROM SegmentEffort e
        JOIN SegActivity a ON a.id = e.activityId
        LEFT JOIN Bike b ON b.id = a.bikeId
        WHERE e.segmentId=? AND a.riderId IS NOT NULL AND COALESCE(e.approx, 0) = 0
        ORDER BY e.elapsedSecs ASC, e.id ASC
    ''', [segment_id]):
        best.setdefault((r['riderId'], r['ebike']), r['id'])
    for eid in best.values():
        db.execute('UPDATE SegmentEffort SET isPR=1 WHERE id=?', [eid])


def scan_activity_against_segments(db, activity, segments, track=None):
    """Scan one activity against a list of segments. Commits nothing. The streams are parsed once, and a segment the track doesn't reach
    (seg_reach) is skipped without looking at a single point. `track`: (box, cells) when the caller already has them (ActivityTrack)."""
    matched = 0
    fam = _activity_family(db, activity)
    if fam is None:                                     # an indoor ride, a swim, ...: no segments
        return 0
    segments = [s for s in segments if seg_sport(s) == fam]    # rides (pedal and e-bike) only match ride segments, walks, runs and hikes foot ones
    if not segments:
        return 0
    streams = _parsed(activity['streams'])
    if track:
        box, cells = track
    else:
        ll = (streams.get('latlng') or {}).get('data') or []
        try:
            box = tracks.box_of(ll)
        except (TypeError, ValueError, IndexError):
            box = None                                  # a bad point somewhere: no box, so nothing is skipped and the matchers decide as before
        cells = tracks.cells_of(ll) if box and len(segments) > 1 else None   # for one segment, the box alone is cheaper than the cells
    for seg in segments:
        if not can_reach(box, cells, seg_reach(seg)):
            continue
        elapsed = match_segment(streams, seg)
        approx = 0
        if elapsed is None:
            close = match_segment_close(streams, seg)                  # not perfectly on it, but clearly rode it
            if close is None:
                continue
            elapsed, approx = close[0], 1
        dist_m     = seg['distanceM'] or 0
        avg_speed  = dist_m / elapsed if dist_m and elapsed else None
        db.execute('''
            INSERT INTO SegmentEffort
              (segmentId, activityId, activityDate, elapsedSecs, avgSpeedMps, approx)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(segmentId, activityId) DO UPDATE SET
              elapsedSecs=excluded.elapsedSecs,
              avgSpeedMps=excluded.avgSpeedMps,
              approx=excluded.approx
        ''', [
            seg['id'],
            activity['id'],
            str(activity['startDateLocal'] or '')[:10],
            elapsed,
            avg_speed,
            approx,
        ])
        matched += 1
    return matched


def scan_all_activities(db, segment_ids=None):
    """
    Scan every activity against all (or specific) segments.
    Returns the number of activities with a GPS track (all of them were considered).

    Only the activities whose track box (services/tracks.py) reaches one of the segments, and of a family that has segments among them, have their
    streams read, _BATCH at a time: a new segment on a big history reads a few dozen rides, not all of them.
    """
    if segment_ids:
        placeholders = ','.join('?' * len(segment_ids))
        segments = db.execute(
            f'SELECT * FROM Segment WHERE id IN ({placeholders})', segment_ids
        ).fetchall()
    else:
        segments = db.execute('SELECT * FROM Segment').fetchall()

    if not segments:
        return 0

    # Clear existing efforts for these segments so stale rows (e.g. from
    # previously looser matching) don't survive a rescan.
    seg_ids = [s['id'] for s in segments]
    placeholders = ','.join('?' * len(seg_ids))
    db.execute(f'DELETE FROM SegmentEffort WHERE segmentId IN ({placeholders})', seg_ids)

    db.commit()
    tracks.fill(db)                                       # every sport: rides and runs alike are Activity rows
    by_fam = {}
    for seg in segments:
        by_fam.setdefault(seg_sport(seg), []).append(seg_reach(seg))
    with_gps, todo = 0, {}
    for r in db.execute('SELECT t.activityId, t.minLat, t.maxLat, t.minLng, t.maxLng, t.cells, a.sportType FROM ActivityTrack t '
                        'JOIN Activity a ON a.id = t.activityId WHERE t.minLat IS NOT NULL').fetchall():
        with_gps += 1
        reaches = by_fam.get(segment_family(r['sportType']))
        if not reaches:
            continue
        box = (r['minLat'], r['maxLat'], r['minLng'], r['maxLng'])
        cells = set(r['cells'].split()) if r['cells'] else None
        if any(can_reach(box, cells, reach) for reach in reaches):
            todo[r['activityId']] = (box, cells)

    ids_all = list(todo)
    for i in range(0, len(ids_all), _BATCH):
        ids = ids_all[i:i + _BATCH]
        for act in db.execute(f"SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall():
            scan_activity_against_segments(db, act, segments, track=todo[act['id']])

    for seg in segments:
        _refresh_prs(db, seg['id'])

    db.commit()
    log.warning('Segment scan complete — %d activities with GPS, %d near enough to read, %d segments', with_gps, len(todo), len(segments))
    return with_gps


def scan_new_ride(db, act_id):
    """Match one freshly stored ride against every segment and refresh PRs. Call after any ingest path; never raises, does not commit."""
    try:
        act = db.execute('SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id=?', [act_id]).fetchone()
        segments = db.execute('SELECT * FROM Segment').fetchall()
        if not act or not act['streams'] or not segments:
            return 0
        n = scan_activity_against_segments(db, act, segments)
        if n:                                           # only the segments it is on can have a new PR
            for (sid,) in db.execute('SELECT segmentId FROM SegmentEffort WHERE activityId=?', [act_id]).fetchall():
                _refresh_prs(db, sid)
        return n
    except Exception:
        return 0


def rescan_activity(db, act_id):
    """Match one activity again from scratch, against the segments of its family as it is now (its sport changed), and re-pick the PRs of every
    segment it was or now is on. Returns how many it matched. Does not commit."""
    old = [r[0] for r in db.execute('SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId=?', [act_id])]
    db.execute('DELETE FROM SegmentEffort WHERE activityId=?', [act_id])
    act = db.execute('SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id=?', [act_id]).fetchone()
    fam = _activity_family(db, act) if act and act['streams'] else None
    segs = db.execute("SELECT * FROM Segment WHERE COALESCE(sport, 'ride') = ?", [fam]).fetchall() if fam else []
    n = scan_activity_against_segments(db, act, segs) if segs else 0
    new = [r[0] for r in db.execute('SELECT segmentId FROM SegmentEffort WHERE activityId=?', [act_id])]
    for sid in set(old) | set(new):
        _refresh_prs(db, sid)
    return n


def reclassed(db, act_id, before):
    """After an activity's sport or bike changed: `before` is its services/sports.segment_class from before the change. A new family (a ride
    becoming an indoor ride or a walk) means new segments, so it is matched again; a pedal ride becoming an e-bike ride, or back, stays on the same
    segments but races for the other PR, so those are picked again. Does not commit."""
    now = class_of(db, act_id)
    if now == before:
        return
    fam = {'bike': 'ride', 'ebike': 'ride'}
    if fam.get(now, now) != fam.get(before, before):
        rescan_activity(db, act_id)
        return
    for r in db.execute('SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId=?', [act_id]).fetchall():
        _refresh_prs(db, r[0])


def regroup(db):
    """Run once (Settings.segmentFamiliesDone), when segments went from ride / run to ride / on foot: run segments become foot segments; efforts
    that are now on the wrong family's segments go (walks, hikes, indoor rides, swims, ... on ride segments); every walk, run and hike is matched
    against the foot segments (walks never were, and the slowest efforts were turned away); and every PR is picked again.
    Commits. Returns {'ran', 'removed', 'foot', 'scanned', 'prs_moved'}."""
    s = db.execute('SELECT segmentFamiliesDone FROM Settings WHERE id=1').fetchone()
    if not s or s['segmentFamiliesDone']:
        return {'ran': False}
    db.execute("UPDATE Segment SET sport='foot' WHERE sport='run'")
    db.execute("UPDATE Segment SET sport='ride' WHERE sport IS NULL OR sport NOT IN ('ride', 'eride', 'foot')")
    prs = {(r[0], r[1]) for r in db.execute('SELECT segmentId, activityId FROM SegmentEffort WHERE isPR=1')}
    seg_fam = {r[0]: r[1] for r in db.execute('SELECT id, sport FROM Segment')}
    fams = {}
    removed = 0
    for e in db.execute('SELECT id, segmentId, activityId FROM SegmentEffort').fetchall():
        if e['activityId'] not in fams:
            fams[e['activityId']] = family_of(db, e['activityId'])
        if fams[e['activityId']] != seg_fam.get(e['segmentId']):
            db.execute('DELETE FROM SegmentEffort WHERE id=?', [e['id']])
            removed += 1
    foot = db.execute("SELECT * FROM Segment WHERE sport='foot'").fetchall()
    scanned = found = 0
    if foot:
        before = db.execute("SELECT COUNT(*) FROM SegmentEffort e JOIN Segment s ON s.id=e.segmentId WHERE s.sport='foot'").fetchone()[0]
        for act in db.execute("SELECT id, startDateLocal, streams, sportType FROM Activity WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')"):
            if segment_family(act['sportType']) == 'foot':
                scan_activity_against_segments(db, act, foot)
                scanned += 1
        found = db.execute("SELECT COUNT(*) FROM SegmentEffort e JOIN Segment s ON s.id=e.segmentId WHERE s.sport='foot'").fetchone()[0] - before
    for sid in seg_fam:
        _refresh_prs(db, sid)
    after = {(r[0], r[1]) for r in db.execute('SELECT segmentId, activityId FROM SegmentEffort WHERE isPR=1')}
    moved = len(after - prs)                             # PRs now held by another effort (a rider can hold a pedal and an e-bike PR on one segment)
    db.execute('UPDATE Settings SET segmentFamiliesDone=1 WHERE id=1')
    db.commit()
    if removed or found or moved:
        log.warning('Segment families: %d efforts left segments of another family, %d new efforts on foot segments, %d PRs moved', removed, found, moved)
    return {'ran': True, 'removed': removed, 'foot': found, 'scanned': scanned, 'prs_moved': moved}


def merge_bikes(db):
    """Run once (Settings.segmentBikesMergedDone): 0.7.3's e-bike segments become ride segments. Pedal rides are matched against the segments that
    were e-bike ones, e-bike rides against those that were always ride ones, and every ride segment's PRs are picked again, one pedal and one e-bike
    PR per rider (_refresh_prs). Commits. Returns {'ran', 'merged', 'found', 'scanned', 'prs_moved'}."""
    s = db.execute('SELECT segmentBikesMergedDone FROM Settings WHERE id=1').fetchone()
    if not s or s['segmentBikesMergedDone']:
        return {'ran': False}
    was_e = {r[0] for r in db.execute("SELECT id FROM Segment WHERE sport='eride'")}
    db.execute("UPDATE Segment SET sport='ride' WHERE sport='eride'")
    rides = db.execute("SELECT * FROM Segment WHERE COALESCE(sport, 'ride') = 'ride'").fetchall()
    prs = {r[0] for r in db.execute("SELECT e.id FROM SegmentEffort e JOIN Segment s ON s.id=e.segmentId WHERE e.isPR=1 AND COALESCE(s.sport, 'ride')='ride'")}
    found = scanned = 0
    if rides:
        before = db.execute('SELECT COUNT(*) FROM SegmentEffort').fetchone()[0]
        for act in db.execute("SELECT id, startDateLocal, streams, sportType FROM Activity WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')").fetchall():
            cls = class_of(db, act['id'])
            if cls not in ('bike', 'ebike'):
                continue
            new_to_it = [g for g in rides if (g['id'] in was_e) == (cls == 'bike')]
            if new_to_it:
                scan_activity_against_segments(db, act, new_to_it)
                scanned += 1
        found = db.execute('SELECT COUNT(*) FROM SegmentEffort').fetchone()[0] - before
        for g in rides:
            _refresh_prs(db, g['id'])
    after = {r[0] for r in db.execute("SELECT e.id FROM SegmentEffort e JOIN Segment s ON s.id=e.segmentId WHERE e.isPR=1 AND COALESCE(s.sport, 'ride')='ride'")}
    moved = len(after - prs)                             # PRs now held by another effort, or held for the first time (an e-bike PR on an old ride segment)
    db.execute('UPDATE Settings SET segmentBikesMergedDone=1 WHERE id=1')
    db.commit()
    if was_e or found or moved:
        log.warning('Segment bikes merged: %d e-bike segments became ride segments, %d new efforts, %d PRs changed', len(was_e), found, moved)
    return {'ran': True, 'merged': len(was_e), 'found': found, 'scanned': scanned, 'prs_moved': moved}


# ---------- segments from a Strava export (segments.csv) ----------
IMPORT_TOL_M = 50       # a Strava segment's ends sit on the track it was drawn on; allow for a different recording of the same road


def shape_from_streams(streams, start, end, tol_m=IMPORT_TOL_M):
    """(polyline, distance_m, elevation_gain_m) of the stretch of a track from near `start` to near `end` after it, or None if the track doesn't
    go from one to the other. Of every pass by the start, the one that comes closest to both ends is taken (a Strava segment's ends are points
    of the track it was drawn on, so another pass that only skirts them is a different line); of passes as close as that, the shortest, so a
    loop that passes the start twice gives the segment, not the loop."""
    s = _parsed(streams)
    ll = (s.get('latlng') or {}).get('data') or []
    alt = (s.get('altitude') or {}).get('data') or []
    pts, els = [], []
    for i, p in enumerate(ll):
        c = valid_coord(p[0], p[1]) if isinstance(p, (list, tuple)) and len(p) >= 2 else None
        if c:
            pts.append(c)
            els.append(alt[i] if i < len(alt) and isinstance(alt[i], (int, float)) else None)
    if len(pts) < 2:
        return None
    sw, ew = _window(start[0], start[1], tol_m), _window(end[0], end[1], tol_m)
    ds = [_near(sw, la, ln, tol_m) for la, ln in pts]
    de = [_near(ew, la, ln, tol_m) for la, ln in pts]
    found = []                                          # (how far from the two ends, length, si, ei) of each pass
    i, n = 0, len(pts)
    while i < n:
        if ds[i] is None:
            i += 1
            continue
        j = i                                           # one pass through the start zone: its closest point
        while j + 1 < n and ds[j + 1] is not None:
            j += 1
        si = min(range(i, j + 1), key=lambda k: ds[k])
        k = si + 1
        while k < n and de[k] is None:
            k += 1
        if k < n:
            m = k
            while m + 1 < n and de[m + 1] is not None:
                m += 1
            ei = min(range(k, m + 1), key=lambda q: de[q])
            if ei > si:
                found.append((ds[si] + de[ei], _path_length_m(pts[si:ei + 1]), si, ei))
        i = j + 1
    if not found:
        return None
    closest = min(f[0] for f in found)
    _, length, si, ei = min((f for f in found if f[0] <= closest + 10), key=lambda f: f[1])
    shape = clean_polyline(pts[si:ei + 1], max_points=400)
    if not shape:
        return None
    gain, last = 0.0, None
    for e in els[si:ei + 1]:
        if e is None:
            continue
        if last is not None and e > last:
            gain += e - last
        last = e
    return shape, round(length, 1), (round(gain, 1) if last is not None else None)


def _tracks_through(db, start, end, limit=40):
    """Ids of activities whose track box holds both points, newest first: the ones worth reading to find a segment's shape."""
    tracks.fill(db)
    lo_lat, hi_lat = min(start[0], end[0]), max(start[0], end[0])
    lo_lng, hi_lng = min(start[1], end[1]), max(start[1], end[1])
    return [r[0] for r in db.execute(
        'SELECT t.activityId FROM ActivityTrack t JOIN Activity a ON a.id = t.activityId '
        'WHERE t.minLat <= ? AND t.maxLat >= ? AND t.minLng <= ? AND t.maxLng >= ? ORDER BY a.startDateLocal DESC LIMIT ?',
        [lo_lat, hi_lat, lo_lng, hi_lng, limit])]


def _segment_here(db, start, end, tol_m=TOLERANCE_M):
    """True if a segment with both ends within tol_m of these is already saved."""
    sw, ew = _window(start[0], start[1], tol_m), _window(end[0], end[1], tol_m)
    for r in db.execute('SELECT startLat, startLng, endLat, endLng FROM Segment WHERE startLat BETWEEN ? AND ? AND startLng BETWEEN ? AND ?',
                        [sw[0] - sw[2], sw[0] + sw[2], sw[1] - sw[3], sw[1] + sw[3]]):
        if _near(sw, r[0], r[1], tol_m) is not None and _near(ew, r[2], r[3], tol_m) is not None:
            return True
    return False


def import_strava(db, rows):
    """Make a segment for each row of a Strava export's segments.csv (Segment Name, Activity ID, Starting/Ending Latitude/Longitude) that isn't
    here yet. Its shape, length and climb come from the activity it was made on, or, when that isn't here (or the row names none), from another
    activity that rode it. A row with no position, one already saved (both ends within TOLERANCE_M), or one no activity here rode, is skipped.
    Returns {'created': [ids], 'existing': n, 'unridden': n, 'invalid': n}. Matches nothing yet (scan_all_activities with the new ids does) and
    does not commit."""
    out = {'created': [], 'existing': 0, 'unridden': 0, 'invalid': 0}
    for row in rows:
        start = valid_coord(row.get('Starting Latitude'), row.get('Starting Longitude'))
        end = valid_coord(row.get('Ending Latitude'), row.get('Ending Longitude'))
        if not start or not end or start == end:
            out['invalid'] += 1
            continue
        if _segment_here(db, start, end):
            out['existing'] += 1
            continue
        source = str(row.get('Activity ID') or '').strip()
        tried, found = set(), None
        for aid in ([source] if source else []) + _tracks_through(db, start, end):
            if aid in tried:
                continue
            tried.add(aid)
            fam = family_of(db, aid)
            if fam is None:                                 # not here, or an indoor ride / swim: no segments
                continue
            r = db.execute('SELECT streams FROM Activity WHERE id=?', [aid]).fetchone()
            shape = shape_from_streams(r[0], start, end) if r and r[0] else None
            if shape:
                found = (aid, fam, shape)
                break
        if not found:
            out['unridden'] += 1
            continue
        aid, fam, (poly, dist, gain) = found
        name = (row.get('Segment Name') or '').strip()[:200] or 'Strava segment'
        db.execute('INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, sourceActivityId, polyline, elevationGainM, sport) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?)', [name, start[0], start[1], end[0], end[1], dist, aid, json.dumps(poly), gain, fam])
        out['created'].append(db.execute('SELECT last_insert_rowid()').fetchone()[0])
    return out
