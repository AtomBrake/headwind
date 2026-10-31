"""Safety rails for junk activities. A bad import (a 3-second moving time against a real distance, a GPS blip, a unit slip) can produce a ride at
2,500 mph that wrecks every chart's axis. Each new activity is checked against generous upper and lower limits; one that breaks them is FLAGGED (not
deleted, not hidden from its own page) with the reason, left out of the speed and weather analytics until the rider looks at it, and the rider can
dismiss the flag ("it is right") or delete it. A dismissed activity is never flagged again.

The limits are deliberately loose: they catch the impossible, not the unusual. Typical hard-but-real rides (a 40 mph average on a descent-heavy club
run, a 7,000 m day) pass, and so do a 2:10 marathon, a race walk and a 25 km open-water swim. Rides, runs, walks, hikes and swims have limits of their
own; every sport, those included, is checked for a heart rate no heart has, a moving time of seconds against a real distance, a recording left
running for days and a day's worth of calories several times over. Other sports (skiing, paddling, golf, ...) have only those: a ski run's speed
or a paddle's distance can be anything.
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

# on foot and in the water: above the world records, with room to spare
MAX_RUN_AVG_MPH = 19      # 30 km/h over the whole run (the mile record averages 16 mph)
MAX_WALK_AVG_MPH = 11     # 18 km/h for a walk or hike (the 20 km race-walk record averages under 10 mph)
MAX_FOOT_TOP_MPH = 40     # 64 km/h at any instant on foot (a sprinter's top speed is under 28 mph)
MAX_FOOT_DIST_MI = 400    # in one go on foot
MAX_FOOT_GRADE = 1.0      # climb / distance once past a kilometre: a vertical-kilometre race is steep, but not this steep
MAX_SWIM_AVG_MPH = 8      # 13 km/h (the 50 m freestyle record averages 5.4 mph)
MAX_SWIM_DIST_MI = 150    # 240 km (the longest swims on record are under that)

# every sport
MIN_AVG_HR = 30           # bpm: an average below this is a strap that lost contact, not a heart
MAX_HR = 230              # bpm: above any heart's maximum

SANE_SQL = "(flagReason IS NULL OR flagDismissed = 1)"      # for charts: activities nobody has flagged, or that the rider cleared
COLS = ('id, sportType, distance, movingTime, elapsedTime, averageSpeed, maxSpeed, totalElevationGain, calories, averageHeartrate, maxHeartrate, '
        'flagDismissed')


def _family(sport):
    """'ride', 'run', 'walk' (walks and hikes), 'swim', or None for a sport with no limits of its own."""
    from services.sports import is_ride, stat_group
    if is_ride(sport):
        return 'ride'
    g = stat_group(sport)
    if g == 'foot':
        s = (sport or '').lower()
        return 'walk' if 'walk' in s or 'hik' in s else 'run'
    return 'swim' if g == 'swim' else None


def _get(r, key):
    return r[key] if key in r.keys() else None


def reasons(r, system=None):
    """List of readable reasons an activity looks wrong (empty = fine), worded in the rider's units. `r` is a mapping with the Activity columns.
    The limits themselves are in mph and miles."""
    from services import units
    fam = _family(r['sportType'])
    dist = float(r['distance'] or 0)
    moving = float(r['movingTime'] or 0)
    elapsed = float(r['elapsedTime'] or 0)
    avg_mps = float(r['averageSpeed'] or 0) or (dist / moving if fam not in (None, 'ride') and dist > 0 and moving > 0 else 0)
    avg = avg_mps * 2.23694
    top = float(r['maxSpeed'] or 0) * 2.23694
    elev = float(r['totalElevationGain'] or 0)
    out = []
    spd = lambda mps: units.fmt_speed(mps, system, places=0)
    if fam == 'ride':
        if avg > MAX_AVG_MPH:
            out.append('average speed of %s is not possible on a bike' % spd(r['averageSpeed']))
        if top > MAX_TOP_MPH:
            out.append('top speed of %s is a GPS glitch' % spd(r['maxSpeed']))
        if 0 < dist < MIN_DIST_M:
            out.append('only %d m long' % round(dist))
        elif dist >= 1000 and 0 < avg < MIN_AVG_MPH:
            out.append('barely moved (%s average over %s)' % (units.fmt_speed(r['averageSpeed'], system), units.fmt_dist(dist, system)))
    elif fam in ('run', 'walk'):
        doing = 'running' if fam == 'run' else 'walking'
        if avg > (MAX_RUN_AVG_MPH if fam == 'run' else MAX_WALK_AVG_MPH):
            out.append('average speed of %s is not possible %s' % (spd(avg_mps), doing))
        if top > MAX_FOOT_TOP_MPH:
            out.append('top speed of %s is not possible on foot' % spd(r['maxSpeed']))
    elif fam == 'swim' and avg > MAX_SWIM_AVG_MPH:
        out.append('average speed of %s is not possible swimming' % spd(avg_mps))
    if fam and dist <= 0 and moving <= 0 and elapsed <= 0:
        out.append('no distance and no time: nothing was recorded')
    if dist >= 1000 and 0 < moving < 60:
        out.append('moving time of %d s against %s' % (moving, units.fmt_dist(dist, system)))
    max_mi, what = {'ride': (MAX_DIST_MI, 'any ride'), 'run': (MAX_FOOT_DIST_MI, 'anything on foot'), 'walk': (MAX_FOOT_DIST_MI, 'anything on foot'),
                    'swim': (MAX_SWIM_DIST_MI, 'any swim')}.get(fam, (None, None))
    if max_mi and dist / MI > max_mi:
        out.append('%s is beyond %s' % (units.fmt_dist(dist, system, places=0), what))
    grade = {'ride': MAX_GRADE, 'run': MAX_FOOT_GRADE, 'walk': MAX_FOOT_GRADE}.get(fam)
    if grade and (elev > MAX_ELEV_M or (dist >= 1000 and elev / dist > grade)):
        out.append('climb of %s does not fit %s' % (units.fmt_elev(elev, system), units.fmt_dist(dist, system)))
    if elapsed > MAX_HOURS * 3600:
        out.append('lasts %d hours' % round(elapsed / 3600))
    if float(r['calories'] or 0) > MAX_KCAL:
        out.append('%s kcal is too many for one %s' % (f'{float(r["calories"]):,.0f}', 'ride' if fam == 'ride' else 'activity'))
    hr_avg, hr_max = float(_get(r, 'averageHeartrate') or 0), float(_get(r, 'maxHeartrate') or 0)
    if 0 < hr_avg < MIN_AVG_HR or hr_avg > MAX_HR:
        out.append('average heart rate of %d bpm is a sensor fault' % round(hr_avg))
    if hr_max > MAX_HR:
        out.append('top heart rate of %d bpm is a sensor fault' % round(hr_max))
    return out


def flag(db, act_id):
    """Check one activity and record the verdict. One the rider has dismissed keeps its all-clear. Returns the reason text or None. Does not commit."""
    r = db.execute(f'SELECT {COLS} FROM Activity WHERE id=?', [act_id]).fetchone()
    if not r or r['flagDismissed']:
        return None
    why = '; '.join(reasons(r)) or None
    db.execute('UPDATE Activity SET flagReason=? WHERE id=?', [why, act_id])
    return why


def scan_all(db, riders=None):
    """Check every activity of every sport (new limits, old data). Returns the number flagged. Safe to repeat. Commits."""
    n = 0
    for (rid,) in db.execute('SELECT id FROM Activity WHERE flagDismissed IS NULL OR flagDismissed = 0').fetchall():
        if flag(db, rid):
            n += 1
    db.commit()
    return n


def scan_every_sport(db):
    """Run once (Settings.sanityAllSportsDone): the limits for runs, walks, hikes and swims, and the heart-rate and moving-time checks for every
    sport, are new, and only rides were ever checked. Every activity is checked once against today's limits, a ride already flagged included (its
    reason may now say more); dismissed ones are left alone. Commits. Returns {'flagged': [(id, name, sport, reason)], 'ran'}: those flagged by
    this run that weren't before."""
    s = db.execute('SELECT sanityAllSportsDone FROM Settings WHERE id=1').fetchone()
    if not s or s['sanityAllSportsDone']:
        return {'flagged': [], 'ran': False}
    before = {r[0] for r in db.execute('SELECT id FROM Activity WHERE flagReason IS NOT NULL')}
    scan_all(db)
    new = [tuple(r) for r in db.execute('SELECT id, name, sportType, flagReason FROM Activity WHERE flagReason IS NOT NULL '
                                        'AND COALESCE(flagDismissed, 0) = 0 ORDER BY startDateLocal DESC') if r[0] not in before]
    db.execute('UPDATE Settings SET sanityAllSportsDone=1 WHERE id=1')
    db.commit()
    return {'flagged': new, 'ran': True}


def dismiss(db, act_id):
    """"It is right": clear the flag for good. Does not commit."""
    db.execute('UPDATE Activity SET flagDismissed=1, flagReason=NULL WHERE id=?', [act_id])


def elapsed_fix(r):
    """The elapsed time, in seconds, when it can stand in for a moving time a broken file made seconds, or None. A GPX whose timestamps bunch at
    the start and the end (11.8 km "moving" for 9 s of a 70-minute run) leaves the track no use, so the moving-time repairs (services/moving_time)
    can't put it right. Offered only when the moving time is what's wrong and the elapsed time cures it: none of the activity's figures newly look
    wrong with it. `r` is a mapping with the COLS columns."""
    dist, moving, elapsed = float(r['distance'] or 0), float(r['movingTime'] or 0), float(r['elapsedTime'] or 0)
    if not (dist >= 1000 and 0 < moving < 60 and elapsed >= 60):
        return None
    now = reasons(r)
    fixed = reasons({**{k: r[k] for k in r.keys()}, 'movingTime': elapsed, 'averageSpeed': dist / elapsed})
    return int(elapsed) if all(x in now for x in fixed) else None


def use_elapsed_time(db, act_id):
    """"Use the elapsed time" on a flagged activity (elapsed_fix): the elapsed time as its moving time, and the average speed that goes with it.
    The file's moving time is kept in rawData.fileMoving. Checked again. Returns False when it isn't offered. Does not commit."""
    import json
    r = db.execute(f'SELECT {COLS}, rawData FROM Activity WHERE id=?', [act_id]).fetchone()
    secs = elapsed_fix(r) if r else None
    if secs is None:
        return False
    raw = json.loads(r['rawData'] or '{}') or {}
    raw.setdefault('fileMoving', r['movingTime'])
    db.execute("UPDATE Activity SET movingTime=?, averageSpeed=?, rawData=?, updatedAt=datetime('now') WHERE id=?",
               [secs, round(float(r['distance']) / secs, 4), json.dumps(raw), act_id])
    flag(db, act_id)
    return True


def strava_climb(row):
    """Strava's climb for an activity from a Strava export (kept in rawData at import), or None."""
    import json
    try:
        v = json.loads(row['rawData'] or '{}').get('stravaClimb')
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        return None
    return float(v) if isinstance(v, (int, float)) else None


def flagged(db, rider_id):
    """The rider's flagged activities of every sport, newest first. `isBlip`: a ride shorter than MIN_DIST_M, a start-stop by mistake (the dashboard
    offers to delete them all). `stravaClimb`: Strava's climb, when the activity came from a Strava export and Strava's differs from the one saved
    (offered in its place). `elapsedFix`: the elapsed time, when it can stand in for a broken moving time (elapsed_fix)."""
    from services.sports import is_ride, label
    out = []
    for r in db.execute(f'SELECT {COLS}, name, startDateLocal, flagReason, rawData FROM Activity '
                        'WHERE riderId=? AND flagReason IS NOT NULL AND COALESCE(flagDismissed,0)=0 ORDER BY startDateLocal DESC', [rider_id]).fetchall():
        sc = strava_climb(r)
        d = {k: r[k] for k in r.keys() if k != 'rawData'}
        d['isRide'] = is_ride(r['sportType'])
        d['sportLabel'] = label(r['sportType'])
        d['isBlip'] = bool(d['isRide'] and r['distance'] is not None and 0 < r['distance'] < MIN_DIST_M)
        d['stravaClimb'] = sc if sc is not None and abs(sc - float(r['totalElevationGain'] or 0)) > 1 else None
        d['elapsedFix'] = elapsed_fix(r)
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
