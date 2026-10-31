import json
import logging
from math import atan2, cos, radians, sin, sqrt

log = logging.getLogger(__name__)

BRACKETS_MI = [5, 10, 20, 30, 50, 75, 100]
BRACKETS_M  = [mi * 1609.344 for mi in BRACKETS_MI]


def _haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl  = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _dist_from_latlng(latlng):
    """Build cumulative distance array (metres) from latlng stream data."""
    out = [0.0]
    for i in range(1, len(latlng)):
        out.append(out[-1] + _haversine(
            latlng[i-1][0], latlng[i-1][1],
            latlng[i][0],   latlng[i][1],
        ))
    return out


# The quickest a best time can go, in m/s, one sample to the next: 30 for a ride (108 km/h), 10 on foot, 2.5 in the water. Anything faster is a
# GPS jump or a speed sensor gone wrong, never a real effort.
CEILING_MPS = {'ride': 30.0, 'run': 10.0, 'swim': 2.5}
AHEAD_M = 20            # the device's distance may run this far ahead of the GPS in one step (and half as much again) before the GPS is believed


SENSOR_FAULT_M = 500   # this much distance the device logged beyond the GPS, over the whole activity, is a speed sensor gone wrong


def sensor_excess_m(streams):
    """Metres the device's distance ran ahead of the GPS, counting only the steps where it ran well ahead (more than half as much again, plus
    AHEAD_M). 0 when there is no device distance or no GPS to hold it against."""
    t = (streams.get('time') or {}).get('data') or []
    d = (streams.get('distance') or {}).get('data') or []
    ll = (streams.get('latlng') or {}).get('data') or []
    if not d or len(d) != len(t) or len(ll) != len(t):
        return 0.0
    excess = 0.0
    for i in range(1, len(d)):
        a, b = ll[i - 1], ll[i]
        if not (a and b and a[0] is not None and b[0] is not None) or d[i] is None or d[i - 1] is None:
            continue
        step, gps = d[i] - d[i - 1], _haversine(a[0], a[1], b[0], b[1])
        if step > gps * 1.5 + AHEAD_M:
            excess += step - gps
    return excess


def effort_series(streams, ceiling):
    """(distance, time) for the best-time search, or (None, None): the cumulative distance with the stretches that can't be real taken out.

    The distance is the device's (a wheel sensor, or the watch's own), else measured along the GPS. A step where the device's distance runs well
    ahead of the GPS takes the GPS's instead: an Edge's speed sensor that went wrong logged 134 km/h for five minutes, adding 10 km and a 5-mile
    best of 3:35 to a ride the GPS shows was 33 km. Then any step faster than `ceiling` counts for nothing, so a GPS jump can't make a best time."""
    t = (streams.get('time') or {}).get('data') or []
    d = (streams.get('distance') or {}).get('data') or []
    ll = (streams.get('latlng') or {}).get('data') or []
    gps_ok = len(ll) == len(t) and all(isinstance(p, (list, tuple)) and len(p) >= 2 and p[0] is not None and p[1] is not None for p in ll)
    if not d and gps_ok and t:
        d = _dist_from_latlng(ll)
        gps_ok = False                                    # it is the GPS already
    if not d or not t or len(d) != len(t) or len(d) < 2:
        return None, None
    out = [0.0]
    for i in range(1, len(d)):
        step = (d[i] or 0) - (d[i - 1] or 0)
        if gps_ok:
            gps = _haversine(ll[i - 1][0], ll[i - 1][1], ll[i][0], ll[i][1])
            if step > gps * 1.5 + AHEAD_M:
                step = gps
        dt = t[i] - t[i - 1]
        if step < 0 or dt <= 0 or step / dt > ceiling:
            step = 0.0
        out.append(out[-1] + step)
    return out, t


def fastest(d, t, target):
    """The fewest seconds any continuous stretch of `target` metres took, or None. A two-pointer sliding window over cumulative distance."""
    if d[-1] - d[0] < target:
        return None
    best, lo = None, 0
    for hi in range(1, len(d)):
        while lo + 1 < hi and d[hi] - d[lo + 1] >= target:
            lo += 1
        if d[hi] - d[lo] >= target:
            e = t[hi] - t[lo]
            if e > 0 and (best is None or e < best):
                best = e
    return best


def compute_best_efforts(streams_json):
    """[{distanceMi, elapsedSecs, avgSpeedMps}] for each bracket the ride is long enough to contain (effort_series: impossible stretches left out)."""
    try:
        streams = json.loads(streams_json or '{}')
    except Exception:
        return []
    d, t = effort_series(streams, CEILING_MPS['ride'])
    if not d:
        return []
    results = []
    for dist_mi, target_m in zip(BRACKETS_MI, BRACKETS_M):
        best_secs = fastest(d, t, target_m)
        if best_secs is None:
            if d[-1] - d[0] < target_m:
                break
            continue
        results.append({'distanceMi': dist_mi, 'elapsedSecs': best_secs, 'avgSpeedMps': target_m / best_secs})
    return results


def save_best_efforts(db, activity_id, activity_date, streams_json):
    """Compute and upsert best efforts for one activity. Does not commit."""
    efforts = compute_best_efforts(streams_json)
    date_str = str(activity_date or '')[:10]
    db.execute('DELETE FROM BestEffort WHERE activityId=?', [activity_id])       # a bracket it no longer reaches must not keep an old time
    for e in efforts:
        db.execute('''
            INSERT INTO BestEffort (activityId, activityDate, distanceMi, elapsedSecs, avgSpeedMps)
            VALUES (?,?,?,?,?)
            ON CONFLICT(activityId, distanceMi) DO UPDATE SET
                elapsedSecs=excluded.elapsedSecs,
                avgSpeedMps=excluded.avgSpeedMps,
                activityDate=excluded.activityDate
        ''', [activity_id, date_str, e['distanceMi'], e['elapsedSecs'], e['avgSpeedMps']])
    return len(efforts)


def scan_all_best_efforts(db):
    """Backfill every activity. Commits at the end."""
    activities = db.execute(
        "SELECT id, startDateLocal, streams FROM Ride "
        "WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')"
    ).fetchall()
    total = 0
    for act in activities:
        total += save_best_efforts(db, act['id'], act['startDateLocal'], act['streams'])
    db.commit()
    log.warning('Best efforts scan — %d efforts across %d activities', total, len(activities))
    return len(activities)


def rescan_clean(db):
    """Run once (Settings.bestEffortsCleanDone): every ride's best times worked out again with the impossible stretches left out (effort_series),
    and every run's and swim's left to be worked out again (services/sport_records.ensure, which runs next). Commits.
    Returns {'ran', 'scanned', 'changed': [(miles, old secs, new secs)]}: the rider records that moved, per bracket."""
    s = db.execute('SELECT bestEffortsCleanDone FROM Settings WHERE id=1').fetchone()
    if not s or s['bestEffortsCleanDone']:
        return {'ran': False}
    before = {(r[2], r[0]): r[1] for r in db.execute(
        'SELECT e.distanceMi, MIN(e.elapsedSecs), a.riderId FROM BestEffort e JOIN Ride a ON a.id = e.activityId GROUP BY a.riderId, e.distanceMi')}
    ids = [r[0] for r in db.execute("SELECT id FROM Ride WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')")]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        for r in db.execute(f"SELECT id, startDateLocal, streams FROM Activity WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall():
            save_best_efforts(db, r['id'], r['startDateLocal'], r['streams'])
        db.commit()
    after = {(r[2], r[0]): r[1] for r in db.execute(
        'SELECT e.distanceMi, MIN(e.elapsedSecs), a.riderId FROM BestEffort e JOIN Ride a ON a.id = e.activityId GROUP BY a.riderId, e.distanceMi')}
    db.execute('DELETE FROM SportEffort')
    db.execute('UPDATE Settings SET bestEffortsCleanDone=1 WHERE id=1')
    db.commit()
    owner = db.execute('SELECT id FROM Rider WHERE isDefault=1 ORDER BY id LIMIT 1').fetchone()   # friends' riders have their own records, not news here
    changed = sorted(((k[1], before.get(k), after.get(k)) for k in set(before) | set(after)
                      if before.get(k) != after.get(k) and (not owner or k[0] == owner[0])),
                     key=lambda c: c[0])            # by distance alone: a bracket new to a rider has no old time, and None can't be compared
    return {'ran': True, 'scanned': len(ids), 'changed': changed}
