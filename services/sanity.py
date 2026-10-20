"""Safety rails for junk rides. A bad import (a 3-second moving time against a real distance, a GPS blip, a unit slip) can produce a ride at 2,500 mph that
wrecks every chart's axis. Each new ride is checked against generous upper and lower limits; one that breaks them is FLAGGED (not deleted, not hidden
from its own page) with the reason, left out of the speed and weather analytics until the rider looks at it, and the rider can dismiss the flag
("it is right") or delete the ride. A dismissed ride is never flagged again.

The limits are deliberately loose: they catch the impossible, not the unusual. Typical hard-but-real rides (a 40 mph average on a descent-heavy club run, a 7,000 m
day) pass.
"""
MI = 1609.344

# upper / lower limits for a ride
MAX_AVG_MPH = 45          # average speed over the whole ride
MAX_TOP_MPH = 80          # fastest instant (GPS spikes are common, so this is above any real bike speed)
MIN_AVG_MPH = 0.9         # slower than a crawl for a recording this long means it never really moved
MIN_DIST_M = 160          # about 0.1 mile: a start-stop blip, not a ride
MAX_DIST_MI = 1500
MAX_ELEV_M = 9000
MAX_GRADE = 0.35          # climb / distance, once past a kilometre
MAX_HOURS = 72
MAX_KCAL = 15000

SANE_SQL = "(flagReason IS NULL OR flagDismissed = 1)"      # for charts: rides nobody has flagged, or that the rider cleared


def reasons(r, system=None):
    """List of readable reasons a ride looks wrong (empty = fine), worded in the rider's units. `r` is a mapping with the Activity columns.
    The limits themselves are in mph and miles."""
    from services import units
    from services.sports import is_ride
    if not is_ride(r['sportType']):
        return []
    dist = float(r['distance'] or 0)
    moving = float(r['movingTime'] or 0)
    elapsed = float(r['elapsedTime'] or 0)
    avg = float(r['averageSpeed'] or 0) * 2.23694
    top = float(r['maxSpeed'] or 0) * 2.23694
    elev = float(r['totalElevationGain'] or 0)
    out = []
    spd = lambda mps: units.fmt_speed(mps, system, places=0)
    if avg > MAX_AVG_MPH:
        out.append('average speed of %s is not possible on a bike' % spd(r['averageSpeed']))
    if top > MAX_TOP_MPH:
        out.append('top speed of %s is a GPS glitch' % spd(r['maxSpeed']))
    if 0 < dist < MIN_DIST_M:
        out.append('only %d m long' % round(dist))
    elif dist >= 1000 and 0 < avg < MIN_AVG_MPH:
        out.append('barely moved (%s average over %s)' % (units.fmt_speed(r['averageSpeed'], system), units.fmt_dist(dist, system)))
    if dist >= 1000 and 0 < moving < 60:
        out.append('moving time of %d s against %s' % (moving, units.fmt_dist(dist, system)))
    if dist / MI > MAX_DIST_MI:
        out.append('%s is beyond any ride' % units.fmt_dist(dist, system, places=0))
    if elev > MAX_ELEV_M or (dist >= 1000 and elev / dist > MAX_GRADE):
        out.append('climb of %s does not fit %s' % (units.fmt_elev(elev, system), units.fmt_dist(dist, system)))
    if elapsed > MAX_HOURS * 3600:
        out.append('lasts %d hours' % round(elapsed / 3600))
    if float(r['calories'] or 0) > MAX_KCAL:
        out.append('%s kcal is too many for one ride' % f'{float(r["calories"]):,.0f}')
    return out


def flag(db, act_id):
    """Check one ride and record the verdict. A ride the rider has dismissed keeps its all-clear. Returns the reason text or None. Does not commit."""
    r = db.execute('SELECT id, sportType, distance, movingTime, elapsedTime, averageSpeed, maxSpeed, totalElevationGain, calories, flagDismissed FROM Activity WHERE id=?', [act_id]).fetchone()
    if not r or r['flagDismissed']:
        return None
    why = '; '.join(reasons(r)) or None
    db.execute('UPDATE Activity SET flagReason=? WHERE id=?', [why, act_id])
    return why


def scan_all(db, riders=None):
    """Check every ride (new limits, old data). Returns the number flagged. Safe to repeat. Commits."""
    n = 0
    for (rid,) in db.execute('SELECT id FROM Ride WHERE flagDismissed IS NULL OR flagDismissed = 0').fetchall():
        if flag(db, rid):
            n += 1
    db.commit()
    return n


def dismiss(db, act_id):
    """"It is right": clear the flag for good. Does not commit."""
    db.execute('UPDATE Activity SET flagDismissed=1, flagReason=NULL WHERE id=?', [act_id])


def strava_climb(row):
    """Strava's climb for an activity from a Strava export (kept in rawData at import), or None."""
    import json
    try:
        v = json.loads(row['rawData'] or '{}').get('stravaClimb')
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        return None
    return float(v) if isinstance(v, (int, float)) else None


def flagged(db, rider_id):
    """The rider's flagged rides, newest first. `isBlip`: shorter than MIN_DIST_M, a start-stop by mistake (the dashboard offers to delete them all).
    `stravaClimb`: Strava's climb, when the ride came from a Strava export and Strava's differs from the one saved (offered in its place)."""
    out = []
    for r in db.execute('SELECT id, name, startDateLocal, distance, averageSpeed, totalElevationGain, flagReason, rawData FROM Ride '
                        'WHERE riderId=? AND flagReason IS NOT NULL AND COALESCE(flagDismissed,0)=0 ORDER BY startDateLocal DESC', [rider_id]).fetchall():
        sc = strava_climb(r)
        d = {k: r[k] for k in r.keys() if k != 'rawData'}
        d['isBlip'] = bool(r['distance'] is not None and 0 < r['distance'] < MIN_DIST_M)
        d['stravaClimb'] = sc if sc is not None and abs(sc - float(r['totalElevationGain'] or 0)) > 1 else None
        out.append(d)
    return out


def use_strava_climb(db, act_id):
    """"Use Strava's climb" on a flagged ride: Strava's figure in place of the file's, and the altitude stream dropped when it can't be real
    (services/parser.altitude_broken), so no profile or segment climb is read from it. Checked again, and its best and segment efforts rebuilt.
    Returns False when there's no Strava figure. Does not commit."""
    import json
    from services.parser import altitude_broken
    r = db.execute('SELECT id, totalElevationGain, streams, rawData FROM Activity WHERE id=?', [act_id]).fetchone()
    sc = strava_climb(r) if r else None
    if sc is None:
        return False
    raw = json.loads(r['rawData'] or '{}')
    raw.setdefault('fileClimb', r['totalElevationGain'])
    sets = {'totalElevationGain': sc}
    try:
        streams = json.loads(r['streams'] or '{}')
    except ValueError:
        streams = {}
    if altitude_broken(streams):
        streams.pop('altitude', None)
        sets['streams'] = json.dumps(streams)
        raw['altitudeDropped'] = True
    sets['rawData'] = json.dumps(raw)
    db.execute(f"UPDATE Activity SET {', '.join(f'{k}=?' for k in sets)}, updatedAt=datetime('now') WHERE id=?", [*sets.values(), act_id])
    flag(db, act_id)
    from services import duplicates
    duplicates.rebuild_derived(db, act_id)
    return True


def blip_ids(db, rider_id):
    return [f['id'] for f in flagged(db, rider_id) if f['isBlip']]
