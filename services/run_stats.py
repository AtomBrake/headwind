"""Running stats, derived from the recorded runs themselves: best times for the standard distances, pace, totals, weekly
volume, recent runs and the latest route.

A run is an Activity row whose sport is a run (Run, Trail Run, Virtual Run: services/sport_records.kind), from the phone app, a Garmin or a Strava
export. Its best times are the ones services/sport_records keeps for every run and swim, so publishing to Home Assistant only reads them.
"""
import json
from datetime import timedelta

from database import get_db, query_db
from services import sport_records, tz

DISTANCES = sport_records.RUN_DISTANCES
KM_PER_MILE = 1.609344
MIN_RUN_M, MIN_RUN_S = 400, 120          # a 9-second test recording is not a run


def _runs(rid):
    """Every run for the rider, newest first, from any source (streams left out: only the latest run's track is wanted)."""
    return [dict(r) for r in query_db("SELECT id, name, startDateLocal d, distance, movingTime, totalElevationGain gain, averageHeartrate hr, 'workout' kind "
                                      f"FROM Activity WHERE riderId=? AND {sport_records.kind_sql()}='run' AND distance>=? AND movingTime>=? "
                                      "ORDER BY startDateLocal DESC", [rid, MIN_RUN_M, MIN_RUN_S])]


def _thin(points, n):
    pts = [p for p in points if isinstance(p, (list, tuple)) and len(p) >= 2 and p[0] is not None and p[1] is not None]
    if len(pts) > n:
        step = (len(pts) - 1) / (n - 1)
        pts = [pts[round(i * step)] for i in range(n)]
    return [[round(float(p[0]), 5), round(float(p[1]), 5)] for p in pts]


def payloads(rid):
    """{'nutrition_run_stats': {...}, 'nutrition_run_route': {...}} for the rider (empty-but-valid when they have no runs)."""
    runs = _runs(rid)
    s = query_db('SELECT units FROM Settings WHERE id=1', one=True)
    units = (s['units'] if s and s['units'] else 'imperial')
    if not runs:
        return {'nutrition_run_stats': {'runs': 0, 'units': units}, 'nutrition_run_route': {'pts': []}, 'nutrition_run_segments': {'efforts': []}}
    today = tz.today()
    mon = today - timedelta(days=today.weekday())
    month0, year0 = today.replace(day=1), today.replace(month=1, day=1)

    def tot(since):
        sel = [r for r in runs if since is None or (r['d'] or '')[:10] >= since.isoformat()]
        return {'n': len(sel), 'm': round(sum(r['distance'] or 0 for r in sel)), 's': int(sum(r['movingTime'] or 0 for r in sel)),
                'gain': round(sum(r['gain'] or 0 for r in sel))}

    weeks = []
    for k in range(11, -1, -1):
        w0 = mon - timedelta(weeks=k)
        w1 = w0 + timedelta(days=7)
        sel = [r for r in runs if w0.isoformat() <= (r['d'] or '')[:10] < w1.isoformat()]
        weeks.append({'d': w0.isoformat(), 'm': round(sum(r['distance'] or 0 for r in sel)), 'n': len(sel)})

    sport_records.ensure(get_db(), rid)
    ids = {r['id'] for r in runs}
    by_dist = {}
    for e in sport_records.efforts(get_db(), rid, 'run'):
        if e['activityId'] in ids:                        # test recordings and the like are left out, as from the totals
            by_dist.setdefault(e['distanceM'], []).append(e)
    bests = []
    for dist, label in DISTANCES:
        rows = by_dist.get(dist)
        if rows:
            b = rows[0]
            bests.append({'label': label, 'm': dist, 'secs': b['elapsedSecs'], 'date': b['activityDate'], 'run': b['activityId'],
                          'next': next((r['elapsedSecs'] for r in rows[1:] if r['activityId'] != b['activityId']), None)})

    def card(r):
        return {'id': r['id'], 'name': r['name'] or 'Run', 'date': (r['d'] or '')[:10], 'm': round(r['distance'] or 0), 's': int(r['movingTime'] or 0),
                'gain': round(r['gain'] or 0), 'hr': round(r['hr']) if r['hr'] else None}

    latest = runs[0]
    latest['streams'] = (query_db('SELECT streams FROM Activity WHERE id=?', [latest['id']], one=True) or {'streams': None})['streams']
    longest = max(runs, key=lambda r: r['distance'] or 0)
    fastest = max((r for r in runs if (r['distance'] or 0) >= 1000 and r['movingTime']), key=lambda r: (r['distance'] or 0) / r['movingTime'], default=None)
    try:
        ll = (json.loads(latest['streams'] or '{}').get('latlng') or {}).get('data') or []
    except Exception:
        ll = []
    stats = {'runs': len(runs), 'units': units, 'week': tot(mon), 'month': tot(month0), 'year': tot(year0), 'all': tot(None), 'weeks': weeks, 'bests': bests,
             'recent': [card(r) for r in runs[:10]], 'longest': card(longest), 'fastest': card(fastest) if fastest else None}
    efforts, segs = _segment_efforts(rid, latest)
    route = {'id': latest['id'], 'name': latest['name'] or 'Run', 'date': (latest['d'] or '')[:10], 'm': round(latest['distance'] or 0), 'pts': _thin(ll, 140), 'segs': segs}
    seg_payload = {'id': latest['id'], 'name': latest['name'] or 'Run', 'date': (latest['d'] or '')[:10], 'sport': 'run', 'efforts': efforts}
    return {'nutrition_run_stats': stats, 'nutrition_run_route': route, 'nutrition_run_segments': seg_payload}


def _segment_efforts(rid, run):
    """The foot segments a run crossed, with time, rank and gap to the runner's best (walks and hikes on the same segment count: one leaderboard on
    foot), plus each segment's shape for the map overlay."""
    rows = query_db("""SELECT e.segmentId, e.elapsedSecs, e.isPR, s.name, s.distanceM, s.polyline
                        FROM SegmentEffort e JOIN Segment s ON s.id=e.segmentId WHERE e.activityId=? AND s.sport='foot' ORDER BY s.name""", [run['id']])
    efforts, segs = [], []
    for e in rows:
        own = query_db("""SELECT e2.elapsedSecs secs, a2.startDateLocal d FROM SegmentEffort e2 JOIN SegActivity a2 ON a2.id=e2.activityId
                          WHERE e2.segmentId=? AND a2.riderId=? ORDER BY a2.startDateLocal""", [e['segmentId'], rid])
        times = [o['secs'] for o in own]
        before = [o['secs'] for o in own if o['d'] < (run['d'] or '')]
        best = min(times) if times else e['elapsedSecs']
        efforts.append({'n': e['name'], 'secs': e['elapsedSecs'], 'm': round(e['distanceM'] or 0), 'pr': bool(e['isPR']), 'best': best,
                        'prev_best': min(before) if before else None, 'last': before[-1] if before else None,
                        'rank': sorted(times).index(e['elapsedSecs']) + 1, 'tries': len(times)})
        try:
            sp = json.loads(e['polyline'] or '[]')
        except Exception:
            sp = []
        if sp:
            segs.append({'n': e['name'], 'pr': bool(e['isPR']), 'pts': _thin(sp, 22)})
    return efforts, segs
