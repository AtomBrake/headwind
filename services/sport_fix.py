"""Put right the sport of activities an older Garmin sync saved as rides. That sync turned every Garmin type it did not know into a ride, so swims, surf
sessions, trail and treadmill runs were saved as rides, count in the ride totals and get flagged by the ride sanity checks; and runs, walks and hikes it did
know were still kept with the rides rather than the workouts. The original Garmin type was never stored, so it is fetched again (the activity list gives 100 per
call), each wrong one is written down as a proposal, and nothing moves until the rider has looked at the list and applied it. Mountain bike and gravel
rides the sync saved as a plain Ride are offered their own kind too, so they can follow the rider's default bike for them (services/gear.pick_bike).
The same proposals are made at every start from the type the sync last read (from_seen), with no call to Garmin, and the dashboard says when
there are some to review.

Also here, with no review: rides and runs from Zwift's made-up worlds saved as outdoor ones (fix_misfiled), since nobody rides out at sea, and
Strava's spellings of sports Headwind has its own name for (fix_spellings)."""
import json
import logging

log = logging.getLogger(__name__)
TASK = 'sport_check'        # its TaskLog rows (the check runs in the background: routes/garmin.py)


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS SportFix (
        rideId         TEXT PRIMARY KEY,
        riderId        INTEGER NOT NULL,
        name           TEXT,
        startDateLocal TEXT,
        distance       REAL,
        oldSport       TEXT,
        newSport       TEXT NOT NULL,
        typeKey        TEXT,
        status         TEXT NOT NULL DEFAULT 'pending',     -- pending | kept (the rider chose to leave it as it is)
        error          TEXT
    )''')


def scan(db, api, rider_id):
    """Ask Garmin for the type of every Garmin activity this rider has as a ride, and record the ones that are wrong. Commits.
    Returns {'checked', 'found', 'proposed'}."""
    rows = {r['id']: r for r in db.execute("SELECT id, name, startDateLocal, distance, sportType FROM Activity WHERE riderId=? AND id LIKE 'garmin\\_%' ESCAPE '\\'",
                                            [rider_id]).fetchall()}
    if not rows:
        return {'checked': 0, 'found': 0, 'proposed': 0}
    oldest = min(str(r['startDateLocal'] or '')[:10] for r in rows.values())
    types, offset = {}, 0
    while len(types) < len(rows):
        page = api.get_activities(start=offset, limit=100) or []
        for a in page:
            aid = f"garmin_{a.get('activityId')}"
            if aid in rows:
                types[aid] = ((a.get('activityType') or {}).get('typeKey') or '').lower()
        if len(page) < 100 or str(page[-1].get('startTimeLocal') or '')[:10] < oldest:
            break
        offset += 100
    db.execute("DELETE FROM SportFix WHERE riderId=? AND status='pending'", [rider_id])
    proposed = _propose(db, rider_id, rows, types)
    db.commit()
    log.warning('Sport check: %d Garmin rides checked, %d found on Garmin, %d with the wrong sport', len(rows), len(types), proposed)
    return {'checked': len(rows), 'found': len(types), 'proposed': proposed}


def _same_sport(saved, new):
    """True when an activity saved as `saved` already has Garmin's sport `new`, under that name or another name for it: Strava's "Stand Up
    Paddling" or "Trail Run" against Garmin's stand_up_paddleboarding_v2 (Paddle) or trail_running (Run). Applying it would change only the name,
    and remove any recording set aside under it."""
    from services.sports import from_type
    return new == saved or new == from_type(saved)


def _propose(db, rider_id, rows, types, only_generic=()):
    """Write down a proposal for each of `rows` ({id: Activity row}) whose sport isn't the one its Garmin type (`types`: {id: typeKey}) gives,
    unless the rider has already said to keep it. For the ids in `only_generic`, only when the activity has no sport in particular (Other,
    Workout) and Garmin's type is a sport of its own that isn't a ride. Returns how many."""
    from services.sports import GENERIC, RIDES, is_ride
    from services.garmin import garmin_sport
    kept = {r[0] for r in db.execute("SELECT rideId FROM SportFix WHERE status='kept'")}
    proposed = 0
    for aid, key in types.items():
        r, new = rows[aid], garmin_sport(key)
        if not key or _same_sport(r['sportType'], new) or aid in kept:
            continue
        if new == 'Ride' and r['sportType'] in RIDES:      # a ride already labelled more closely (indoor, e-bike, mountain, gravel) stays so
            continue
        if new in GENERIC and not is_ride(r['sportType']):   # Garmin's "other" says nothing better than the workout's own sport
            continue
        if aid in only_generic and (r['sportType'] not in GENERIC or is_ride(new)):
            continue
        db.execute('INSERT OR REPLACE INTO SportFix (rideId, riderId, name, startDateLocal, distance, oldSport, newSport, typeKey) VALUES (?,?,?,?,?,?,?,?)',
                   [aid, rider_id, r['name'], r['startDateLocal'], r['distance'], r['sportType'], new, key])
        proposed += 1
    return proposed


def from_seen(db):
    """Every start, without asking Garmin: what the sync last read from Garmin's list for each activity (GarminSeen, services/garmin_changes)
    already has its type, so a Garmin activity saved with another sport is proposed the way scan proposes it. That catches the ones saved before
    Headwind knew their type (e-bike rides saved as rides before 0.7.3) and never mapped again. Proposals made stale by a change of sport since,
    or by the activity going, are dropped. Friends' activities are left alone. Does not commit. Returns {rider id: proposals added}.

    A Garmin ride changed into a workout before every sport was a row of Activity has an id of its own, and the Garmin one in originId
    (services/origin.py). Those are matched too, but only proposed when they were given no sport in particular: the older sync saved HIIT,
    yoga and strength sessions as rides, and the type check of the day could only make them Other. A sport picked for one by hand stays."""
    from services import garmin_changes
    garmin_changes.ensure_schema(db)
    db.execute("""DELETE FROM SportFix WHERE status='pending' AND NOT EXISTS (SELECT 1 FROM Activity a WHERE a.id = SportFix.rideId
                                                                              AND a.sportType IS NOT SportFix.newSport)""")
    for r in db.execute("SELECT rideId, oldSport, newSport FROM SportFix WHERE status='pending'").fetchall():
        if _same_sport(r['oldSport'], r['newSport']):       # proposed before _same_sport knew another name for one sport
            db.execute('DELETE FROM SportFix WHERE rideId=?', [r['rideId']])
    pending = {r[0] for r in db.execute("SELECT rideId FROM SportFix WHERE status='pending'")}
    by_rider, converted = {}, set()
    cols = 'a.id, a.riderId, a.name, a.startDateLocal, a.distance, a.sportType, s.summary'
    not_friends = 'a.riderId IS NOT NULL AND a.riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)'
    for r in db.execute(rf"""SELECT {cols}, 0 AS conv FROM Activity a JOIN GarminSeen s ON a.id = 'garmin_' || s.garminId WHERE {not_friends}
                             UNION ALL
                             SELECT {cols}, 1 FROM Activity a JOIN GarminSeen s ON a.originId = 'garmin_' || s.garminId
                             WHERE a.id NOT LIKE 'garmin\_%' ESCAPE '\' AND {not_friends}"""):
        if r['id'] in pending:
            continue
        try:
            key = (json.loads(r['summary']).get('typeKey') or '').lower()
        except (ValueError, AttributeError):
            continue
        rows, types = by_rider.setdefault(r['riderId'], ({}, {}))
        rows[r['id']], types[r['id']] = r, key
        if r['conv']:
            converted.add(r['id'])
    out = {}
    for rider_id, (rows, types) in by_rider.items():
        n = _propose(db, rider_id, rows, types, only_generic=converted)
        if n:
            out[rider_id] = n
    if out:
        log.warning('Sport check from what Garmin last listed: %s', ', '.join(f'rider {r}: {n}' for r, n in out.items()))
    return out


def count(db, rider_id):
    """How many proposals this rider has still to review (the dashboard's notice)."""
    if rider_id is None:
        return 0
    try:
        return db.execute("SELECT COUNT(*) FROM SportFix WHERE riderId=? AND status='pending'", [rider_id]).fetchone()[0]
    except Exception:                                   # no SportFix table yet (a bare database)
        return 0


def pending(db, rider_id):
    """The proposals still to review, each with `parked`: how many other recordings of it are set aside (they are thrown away when it is changed)."""
    from services import duplicates
    duplicates.ensure_schema(db)
    return [dict(r) for r in db.execute('''SELECT f.*, (SELECT COUNT(*) FROM ActivityDuplicate d WHERE d.primaryId=f.rideId AND d.status='parked') AS parked
                                           FROM SportFix f WHERE f.riderId=? AND f.status='pending' ORDER BY f.newSport, f.startDateLocal DESC''', [rider_id])]


def apply(db, rider_id, ride_ids):
    """Change the picked rides to their proposed sport (runs, swims, ... move to Workouts through convert.change_sport, which keeps the derived data
    right and remembers the old id so a re-sync can't bring it back as a ride). A recording set aside under a picked ride is the same session from another
    device, so it is not a ride either and is thrown away with it. The ones not picked are marked 'kept' and not proposed again.
    Commits. Returns {'changed', 'failed', 'kept'}."""
    from services import convert
    picked = set(ride_ids)
    changed = failed = kept = 0
    for p in pending(db, rider_id):
        if p['rideId'] not in picked:
            db.execute("UPDATE SportFix SET status='kept' WHERE rideId=?", [p['rideId']])
            kept += 1
            continue
        try:
            convert.change_sport(db, None, p['rideId'], p['newSport'], discard_parked=True)     # a workout saved as Other, too
            db.execute('DELETE FROM SportFix WHERE rideId=?', [p['rideId']])
            changed += 1
        except ValueError as e:                     # gone already
            db.execute('UPDATE SportFix SET error=? WHERE rideId=?', [str(e), p['rideId']])
            failed += 1
    db.commit()
    return {'changed': changed, 'failed': failed, 'kept': kept}


def _made_up_sql():
    from services.zwift import SLACK, WORLDS
    boxes = [w['box'] for w in WORLDS if w['madeUp']]
    return '(' + ' OR '.join('(startLat BETWEEN ? AND ? AND startLng BETWEEN ? AND ?)' for _ in boxes) + ')', \
        [v for s, n, west, east in boxes for v in (s - SLACK, n + SLACK, west - SLACK, east + SLACK)]


def fix_misfiled(db):
    """Every start, cheap when there is nothing to do. 1. A ride or run of the rider's own saved as an outdoor one though it starts in a made-up
    world (services/zwift.indoor_sport: a file that didn't say, a Garmin sync from before VirtualRun) becomes an indoor one: its bike or shoes
    are picked again for that, and a local time taken at the world's spot on the globe (Watopia keeps the Solomon Islands' clock, 11 hours
    ahead of London) goes back to the home clock. Its weather is cleared by the startup step after this one. Its best times stay: they are now
    the indoor ones'. 2. Every indoor activity's segment efforts go (Strava's "Virtual Run"s were matched against the foot segments, and a ride
    just made indoor has its ride segments' efforts), and those segments' PRs are picked again.
    Does not commit. Returns {'moved': [(id, name, old sport, new sport)], 'efforts': segment efforts removed}."""
    from services import duplicates, gear, sports, tz
    from services.segments import _refresh_prs
    from services.start_times import move_local
    from services.zwift import indoor_sport
    where, params = _made_up_sql()
    rows = db.execute(f"""SELECT id, name, sportType, startDate, startDateLocal, startLat, startLng FROM Activity
                          WHERE {where} AND NOT {sports.virtual_sql()}
                          AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)""", params).fetchall()
    moved = []
    for r in rows:
        new = indoor_sport(r['sportType'], r['startLat'], r['startLng'])
        if new == r['sportType']:
            continue
        db.execute('UPDATE Activity SET sportType=?, type=? WHERE id=?', [new, new, r['id']])
        gear.regear(db, r['id'])                        # the indoor bike, or the treadmill shoes
        at = duplicates.start_instant(r)
        if at:
            there = tz.local_at(at, r['startLat'], r['startLng'], r['sportType'])
            home = tz.local_at(at, r['startLat'], r['startLng'], new)
            if str(r['startDateLocal'] or '')[:19] == there and home != there:      # not a time the device gave from its own clock
                move_local(db, r['id'], r['startDateLocal'], home)
        moved.append((r['id'], r['name'], r['sportType'], new))
    segs = [x[0] for x in db.execute(f"""SELECT DISTINCT e.segmentId FROM SegmentEffort e JOIN Activity a ON a.id = e.activityId
                                         WHERE {sports.virtual_sql('a.sportType')}""")]
    n = 0
    if segs:
        n = db.execute(f"DELETE FROM SegmentEffort WHERE activityId IN (SELECT id FROM Activity WHERE {sports.virtual_sql()})").rowcount
        for sid in segs:
            _refresh_prs(db, sid)
    if moved or n:
        log.warning('Sport fix: %d activit%s from a made-up world made indoor ones; %d segment effort(s) on indoor activities removed',
                    len(moved), 'y' if len(moved) == 1 else 'ies', n)
    return {'moved': moved, 'efforts': n}


def fix_spellings(db):
    """Every start, cheap when there is nothing to do: activities saved under Strava's name for a sport Headwind has a name of its own for
    (sports.STRAVA_NAMES: an older Strava import's "Virtual Ride" beside the Garmin sync's VirtualRide) take Headwind's, so the sport filter
    shows the sport once. Every sport test reads a spelling and Headwind's name alike, and gear defaults are kept under a key that does
    (kit.sport_key), except for the sports that are more than a spelling: Strava's "Weight Training" is Strength here, so a default for it
    moves to Strength's key (one Strength already has stays). Does not commit. Returns {Strava's name: activities renamed}."""
    import sqlite3
    from services.kit import sport_key
    from services.sports import STRAVA_NAMES
    out = {}
    for strava, ours in STRAVA_NAMES.items():
        n = db.execute('UPDATE Activity SET sportType=? WHERE sportType=?', [ours, strava]).rowcount
        db.execute('UPDATE Activity SET type=? WHERE type=?', [ours, strava])
        if n:
            out[strava] = n
        if sport_key(strava) != sport_key(ours):
            for table in ('KitDefault', 'BikeDefault'):
                try:
                    db.execute(f'UPDATE OR IGNORE {table} SET sport=? WHERE sport=?', [sport_key(ours), sport_key(strava)])
                    db.execute(f'DELETE FROM {table} WHERE sport=?', [sport_key(strava)])
                except sqlite3.OperationalError:        # a bare database: no gear tables yet
                    pass
    if out:
        log.warning('Sport fix: Strava spellings renamed: %s', ', '.join(f'{s} ({n})' for s, n in out.items()))
    return out
