"""Put right the sport of activities an older Garmin sync saved as rides. That sync turned every Garmin type it did not know into a ride, so swims, surf
sessions, trail and treadmill runs were saved as rides, count in the ride totals and get flagged by the ride sanity checks; and runs, walks and hikes it did
know were still kept with the rides rather than the workouts. The original Garmin type was never stored, so it is fetched again (the activity list gives 100 per
call), each wrong one is written down as a proposal, and nothing moves until the rider has looked at the list and applied it."""
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
    from services.sports import RIDES
    from services.garmin import garmin_sport
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
    kept = {r[0] for r in db.execute("SELECT rideId FROM SportFix WHERE status='kept'")}
    db.execute("DELETE FROM SportFix WHERE riderId=? AND status='pending'", [rider_id])
    proposed = 0
    for aid, key in types.items():
        r, new = rows[aid], garmin_sport(key)
        if not key or new == r['sportType'] or aid in kept:
            continue
        if new in RIDES and r['sportType'] in RIDES and new == 'Ride':      # an MTB / gravel label on a ride is fine; indoor and e-bike are what matter
            continue
        db.execute('INSERT OR REPLACE INTO SportFix (rideId, riderId, name, startDateLocal, distance, oldSport, newSport, typeKey) VALUES (?,?,?,?,?,?,?,?)',
                   [aid, rider_id, r['name'], r['startDateLocal'], r['distance'], r['sportType'], new, key])
        proposed += 1
    db.commit()
    log.warning('Sport check: %d Garmin rides checked, %d found on Garmin, %d with the wrong sport', len(rows), len(types), proposed)
    return {'checked': len(rows), 'found': len(types), 'proposed': proposed}


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
            convert.change_sport(db, 'ride', p['rideId'], p['newSport'], discard_parked=True)
            db.execute('DELETE FROM SportFix WHERE rideId=?', [p['rideId']])
            changed += 1
        except ValueError as e:                     # gone already
            db.execute('UPDATE SportFix SET error=? WHERE rideId=?', [str(e), p['rideId']])
            failed += 1
    db.commit()
    return {'changed': changed, 'failed': failed, 'kept': kept}
