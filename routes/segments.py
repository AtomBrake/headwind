import json
import logging

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from database import get_db, query_db
from services.segments import (scan_all_activities, scan_activity_against_segments, _refresh_prs,
                               clean_polyline, recover_polyline, seg_sport, valid_coord)
from services.sports import CLASS_ICONS, CLASS_LABELS, FAMILIES, FAMILY_ICONS, FAMILY_LABELS, class_sql, ebike_sql, family_of

log = logging.getLogger(__name__)

bp = Blueprint('segments', __name__)


import math as _math

_TIER_ORDER  = ['Easy', 'Moderate', 'Hard', 'Very Hard', 'Brutal']
_TIER_COLOUR = {
    'Easy':      '#10b981',
    'Moderate':  '#3b82f6',
    'Hard':      '#f59e0b',
    'Very Hard': '#ef4444',
    'Brutal':    '#8b5cf6',
}
_TIER_BUMP = {'Brutal': 2.0, 'Very Hard': 1.0, 'Hard': 0.5, 'Moderate': 0.25}


def _base_tier(dist_m, elev_m):
    """Geometry-only score → tier index (0-4)."""
    if not dist_m or not elev_m or dist_m <= 0 or elev_m <= 0:
        return None
    gradient_pct = (elev_m / dist_m) * 100
    elev_ft      = elev_m * 3.28084
    score        = elev_ft * gradient_pct
    if score < 200:  return 0
    if score < 700:  return 1
    if score < 1500: return 2
    if score < 3000: return 3
    return 4


def _haversine_simple(la1, lo1, la2, lo2):
    R = 6_371_000
    f1, f2 = _math.radians(la1), _math.radians(la2)
    dp = _math.radians(la2 - la1)
    dl = _math.radians(lo2 - lo1)
    a  = _math.sin(dp/2)**2 + _math.cos(f1)*_math.cos(f2)*_math.sin(dl/2)**2
    return 2 * R * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))


def _contained_in(child, parent_polyline, tol=40):
    """Return True if child's start and end both lie on parent_polyline in order."""
    if not parent_polyline:
        return False
    start_idx = end_idx = None
    for i, (lat, lng) in enumerate(parent_polyline):
        if start_idx is None and _haversine_simple(lat, lng, child['startLat'], child['startLng']) < tol:
            start_idx = i
        if start_idx is not None and _haversine_simple(lat, lng, child['endLat'], child['endLng']) < tol:
            end_idx = i
            break
    return start_idx is not None and end_idx is not None and end_idx > start_idx


def _difficulty(seg, all_segs):
    """
    Returns (label, colour, sub_segments) where sub_segments is a list of
    (name, label) for each segment contained within this one.
    Tier is bumped up for each contained segment based on its difficulty.
    """
    base = _base_tier(seg['distanceM'], seg['elevationGainM'])
    if base is None:
        return None, None, []

    # Parse this segment's polyline for containment checks
    try:
        polyline = json.loads(seg['polyline']) if seg['polyline'] else []
    except Exception:
        polyline = []

    sub_segs = []
    bump     = 0.0
    for other in all_segs:
        if other['id'] == seg['id']:
            continue
        other_base = _base_tier(other['distanceM'], other['elevationGainM'])
        if other_base is None:
            continue
        other_label = _TIER_ORDER[other_base]
        if _contained_in(other, polyline):
            sub_segs.append((other['name'], other_label, _TIER_COLOUR[other_label]))
            bump += _TIER_BUMP.get(other_label, 0)

    final = min(4, int(base + bump))
    label = _TIER_ORDER[final]
    return label, _TIER_COLOUR[label], sub_segs


def _only(family, value):
    """The leaderboard filter on ride segments (?only=bike / ebike): pedal or e-bike efforts only. None shows every effort, and is all there is on foot."""
    return value if family == 'ride' and value in ('bike', 'ebike') else None


def _only_links(endpoint, only, counts=None, **kw):
    """The All / Bike / E-bike chips, each a link to the same page with ?only= set. `counts` is {class: efforts} when the chips show them."""
    out = []
    for value, label, icon in ((None, 'All', '🚴⚡'), ('bike', CLASS_LABELS['bike'], CLASS_ICONS['bike']), ('ebike', CLASS_LABELS['ebike'], CLASS_ICONS['ebike'])):
        n = None if counts is None else (sum(counts.values()) if value is None else counts.get(value, 0))
        out.append({'label': label, 'icon': icon, 'active': only == value, 'n': n, 'href': url_for(endpoint, only=value, **kw)})
    return out


@bp.route('/segments')
def index():
    sport = request.args.get('sport')
    only = request.args.get('only')
    if sport == 'eride':                                # a bookmark from 0.7.3, when e-bike rides had segments of their own
        sport, only = 'ride', 'ebike'
    sport = 'foot' if sport == 'run' else (sport if sport in FAMILIES else 'ride')      # ?sport=run: a bookmark from before 0.7.3
    only = _only(sport, only)
    # A segment is listed as before (no efforts yet, or some of the owner's); its numbers count the owner's efforts that the filter keeps.
    keep = class_sql(only)
    segs = query_db(f'''
        SELECT s.*,
               SUM(CASE WHEN e.id IS NOT NULL AND {keep} THEN 1 ELSE 0 END) AS effort_count,
               MIN(CASE WHEN {keep} THEN e.elapsedSecs END) AS best_secs,
               MAX(CASE WHEN e.isPR=1 AND {keep} THEN e.activityDate END) AS pr_date,
               f.name             AS friend_name
        FROM Segment s
        LEFT JOIN SegmentEffort e ON e.segmentId = s.id
        LEFT JOIN SegActivity a ON a.id = e.activityId
        LEFT JOIN Bike b ON b.id = a.bikeId
        LEFT JOIN Rider r ON r.id = a.riderId
        LEFT JOIN Friend f ON f.id = s.friendId
        WHERE (e.id IS NULL OR r.isDefault = 1) AND COALESCE(s.sport, 'ride') = ?
        GROUP BY s.id
        ORDER BY s.createdAt DESC
    ''', [sport])
    # Fetch all KOM holders per segment (handles ties), among the efforts the filter keeps
    db = get_db()
    kom_map = {}
    for seg in segs:
        best = db.execute(f'''
            SELECT MIN(e.elapsedSecs) as t FROM SegmentEffort e JOIN SegActivity a ON a.id = e.activityId LEFT JOIN Bike b ON b.id = a.bikeId
            WHERE e.segmentId=? AND {keep}
        ''', [seg['id']]).fetchone()
        if best and best['t']:
            koms = query_db(f'''
                SELECT DISTINCT r.id AS rider_id, r.name AS rider_name, r.avatarPath AS rider_avatar,
                                r.isDefault AS rider_is_default
                FROM SegmentEffort e
                JOIN SegActivity a ON a.id = e.activityId
                LEFT JOIN Bike b ON b.id = a.bikeId
                LEFT JOIN Rider r ON r.id = a.riderId
                WHERE e.segmentId=? AND e.elapsedSecs=? AND {keep}
            ''', [seg['id'], best['t']])
            if koms:
                kom_map[seg['id']] = koms
    counts = {r[0]: r[1] for r in db.execute("SELECT COALESCE(sport, 'ride'), COUNT(*) FROM Segment GROUP BY 1")}
    tabs = [{'family': f, 'label': FAMILY_LABELS[f], 'icon': FAMILY_ICONS[f], 'n': counts.get(f, 0)} for f in FAMILIES]
    only_links = _only_links('segments.index', only, sport='ride') if sport == 'ride' else []
    return render_template('segments.html', segments=segs, kom_map=kom_map, sport=sport, tabs=tabs, only=only, only_links=only_links)


@bp.route('/segments/create', methods=['POST'])
def create():
    db = get_db()
    name = (request.form.get('name') or '').strip() or 'My Segment'
    try:
        start_lat   = float(request.form['startLat'])
        start_lng   = float(request.form['startLng'])
        end_lat     = float(request.form['endLat'])
        end_lng     = float(request.form['endLng'])
        distance_m  = float(request.form.get('distanceM') or 0)
        activity_id = request.form.get('activityId') or None
        sport       = request.form.get('sport')
        polyline    = request.form.get('polyline') or None
        if not valid_coord(start_lat, start_lng) or not valid_coord(end_lat, end_lng):
            abort(400)
        shape = clean_polyline(polyline)
        polyline = json.dumps(shape) if shape else None
        elev_gain   = request.form.get('elevGainM')
        elev_gain   = float(elev_gain) if elev_gain else None
    except (KeyError, ValueError):
        abort(400)
    # The family is the activity's own (a segment made on a walk is a foot segment, on any outdoor ride a ride segment); the form's value is only
    # used when there is no activity to ask.
    fam = family_of(db, activity_id) if activity_id else None
    if fam is None and activity_id and db.execute('SELECT 1 FROM Activity WHERE id=?', [activity_id]).fetchone():
        abort(400)                                      # an indoor ride, a swim, ...: no segments
    sport = fam or seg_sport({'sport': sport})

    db.execute('''
        INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM,
                             sourceActivityId, polyline, elevationGainM, sport)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    ''', [name, start_lat, start_lng, end_lat, end_lng, distance_m,
          activity_id, polyline, elev_gain, sport])
    db.commit()

    seg_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

    # Retroactively scan all activities for this new segment
    scan_all_activities(db, segment_ids=[seg_id])

    return redirect(url_for('segments.detail', sid=seg_id))


@bp.route('/segments/<int:sid>')
def detail(sid):
    db  = get_db()
    seg = query_db('''
        SELECT s.*, f.name AS friend_name
        FROM Segment s
        LEFT JOIN Friend f ON f.id = s.friendId
        WHERE s.id=?
    ''', [sid], one=True)
    if not seg:
        abort(404)

    # Auto-compute elevation gain for segments created before this field existed
    if seg['elevationGainM'] is None and seg['sourceActivityId']:
        try:
            src = db.execute('SELECT streams FROM Activity WHERE id=?', [seg['sourceActivityId']]).fetchone()
            if src and src['streams']:
                s = json.loads(src['streams'])
                latlng = (s.get('latlng') or {}).get('data') or []
                alt    = (s.get('altitude') or {}).get('data') or []
                if latlng and alt:
                    n = min(len(latlng), len(alt))
                    latlng, alt = latlng[:n], alt[:n]
                if latlng and alt:
                    def _nearest(lat, lng):
                        bi, bd = 0, float('inf')
                        for i, (la, ln) in enumerate(latlng):
                            d = (la - lat) ** 2 + (ln - lng) ** 2
                            if d < bd:
                                bd, bi = d, i
                        return bi
                    si = _nearest(seg['startLat'], seg['startLng'])
                    ei = _nearest(seg['endLat'],   seg['endLng'])
                    if si > ei:
                        si, ei = ei, si
                    gain = sum(
                        max(0, alt[j + 1] - alt[j])
                        for j in range(si, min(ei, len(alt) - 1))
                    )
                    db.execute('UPDATE Segment SET elevationGainM=? WHERE id=?',
                               [round(gain, 1), sid])
                    db.commit()
                    seg = query_db('SELECT * FROM Segment WHERE id=?', [sid], one=True)
        except Exception:
            pass

    # Shape for the map: validated stored shape, else rebuilt from the source ride / a matching effort (and saved so matching
    # gets its interior checkpoints back). If neither works the page says so — it never invents a straight line.
    shape = clean_polyline(seg['polyline'])
    if shape is None:
        shape = recover_polyline(db, seg)
        if shape:
            db.execute('UPDATE Segment SET polyline=? WHERE id=?', [json.dumps(shape), sid])
            db.commit()
    map_data = {'start': valid_coord(seg['startLat'], seg['startLng']),
                'end': valid_coord(seg['endLat'], seg['endLng']), 'shape': shape}

    family = seg_sport(seg)
    # Every effort says whether it was pedalled or on an e-bike (services/sports.segment_class); ?only= keeps one of the two, for the leaderboard,
    # the PR and averages above it and the trend chart alike. Each keeps its own PRs (services/segments._refresh_prs).
    cls = f"CASE WHEN {ebike_sql()} THEN 'ebike' ELSE 'bike' END" if family == 'ride' else "'foot'"
    efforts = query_db(f'''
        SELECT e.*, a.name AS ride_name, a.sportType, a.id AS ride_id, {cls} AS cls,
               r.id AS rider_id, r.name AS rider_name, r.avatarPath AS rider_avatar, r.isDefault AS rider_is_default
        FROM SegmentEffort e
        JOIN SegActivity a ON a.id = e.activityId
        LEFT JOIN Bike b ON b.id = a.bikeId
        LEFT JOIN Rider r ON r.id = a.riderId
        WHERE e.segmentId = ?
        ORDER BY e.elapsedSecs ASC
    ''', [sid])
    only = _only(family, request.args.get('only'))
    class_counts = {}
    for e in efforts:
        class_counts[e['cls']] = class_counts.get(e['cls'], 0) + 1
    if only:
        efforts = [e for e in efforts if e['cls'] == only]

    speeds = [e['avgSpeedMps'] for e in efforts if e['avgSpeedMps'] is not None]
    stats = {'avgSecs': sum(e['elapsedSecs'] for e in efforts) / len(efforts) if efforts else None,
             'avgSpeedMps': sum(speeds) / len(speeds) if speeds else None,
             'total': len(efforts)}

    trend = sorted(({'activityDate': e['activityDate'], 'elapsedSecs': e['elapsedSecs']} for e in efforts), key=lambda t: t['activityDate'] or '')

    # 3-effort rolling average for the trend chart
    secs_list = [e['elapsedSecs'] for e in trend]
    trend_rolling = []
    for i in range(len(secs_list)):
        window = secs_list[max(0, i - 2):i + 1]
        trend_rolling.append(round(sum(window) / len(window)))

    all_segs = query_db("SELECT * FROM Segment WHERE COALESCE(sport, 'ride') = ?", [family])
    diff_label, diff_colour, sub_segs = _difficulty(seg, all_segs)

    return render_template('segment.html', seg=seg, efforts=efforts, map_data=map_data,
                           trend=trend, trend_rolling=trend_rolling, family=family, family_label=FAMILY_LABELS[family],
                           stats=stats, diff_label=diff_label, on_foot=(family == 'foot'),
                           only=only, only_links=_only_links('segments.detail', only, class_counts, sid=sid) if family == 'ride' else [],
                           diff_colour=diff_colour, sub_segs=sub_segs)


@bp.route('/segments/<int:sid>/delete', methods=['POST'])
def delete(sid):
    db = get_db()
    fam = db.execute("SELECT COALESCE(sport, 'ride') FROM Segment WHERE id=?", [sid]).fetchone()
    db.execute('DELETE FROM SegmentEffort WHERE segmentId=?', [sid])
    db.execute('DELETE FROM Segment WHERE id=?', [sid])
    db.commit()
    return redirect(url_for('segments.index', sport=fam[0] if fam else None))


@bp.route('/segments/<int:sid>/efforts/<int:eid>/delete', methods=['POST'])
def delete_effort(sid, eid):
    db = get_db()
    db.execute('DELETE FROM SegmentEffort WHERE id=? AND segmentId=?', [eid, sid])
    _refresh_prs(db, sid)
    db.commit()
    only = request.args.get('only')
    return redirect(url_for('segments.detail', sid=sid, only=only if only in ('bike', 'ebike') else None))


@bp.route('/segments/scan', methods=['POST'])
def scan():
    db = get_db()
    n = scan_all_activities(db)
    return jsonify({'ok': True, 'scanned': n})
