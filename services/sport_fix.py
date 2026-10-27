"""Put right the sport of activities an older Garmin sync saved as rides. That sync turned every Garmin type it did not know into a ride, so swims, surf
sessions, trail and treadmill runs were saved as rides, count in the ride totals and get flagged by the ride sanity checks; and runs, walks and hikes it did
know were still kept with the rides rather than the workouts. The original Garmin type was never stored, so it is fetched again (the activity list gives 100 per
call), each wrong one is written down as a proposal, and nothing moves until the rider has looked at the list and applied it. Mountain bike and gravel
rides the sync saved as a plain Ride are offered their own kind too, so they can follow the rider's default bike for them (services/gear.pick_bike).

Also here, with no review: rides and runs from Zwift's made-up worlds saved as outdoor ones (fix_misfiled), since nobody rides out at sea."""
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
        if new == 'Ride' and r['sportType'] in RIDES:      # a ride already labelled more closely (indoor, e-bike, mountain, gravel) stays so
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
