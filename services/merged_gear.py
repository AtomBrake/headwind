"""Merged activities whose two recordings disagree about the gear: worth a look, since only one of them can be right.

When the same activity is recorded twice (services/duplicates.py) the copy set aside hands its bike or kit to the one kept only when that one has
none. When both have one and they differ, the one kept wins without a word, and that is often the wrong way round: a Garmin ride given the
default bike, its Strava copy naming the bike actually ridden. So the difference is listed (Gear page, dashboard, the activity) for the rider to
settle: use the other recording's gear, or say the kept one is right (ActivityDuplicate.gearChecked).

The other recording's gear is what was chosen on it (ActivityDuplicate.bikeId / kitId: duplicates.chosen_gear, never a default it was given), else
the Strava bike or shoes its Strava export names (StravaGear), once matched to one of the rider's. A ride is compared by bike, anything else by
kit, by the sport of the activity kept (as duplicates.park does). Gear since deleted doesn't count.
"""
from services import duplicates, gear, kit, strava_gear
from services.friend_rides import FRIEND_RIDERS_SQL
from services.sports import is_ride


def _rows(db, rider_id=None, primary_id=None, dup_ids=None):
    duplicates.ensure_schema(db)
    strava_gear.ensure_schema(db)
    where, args = ["d.status='parked'", 'COALESCE(d.gearChecked, 0)=0', f'a.riderId NOT IN ({FRIEND_RIDERS_SQL})'], []     # a friend's: not ours to change
    if rider_id is not None:
        where.append('a.riderId=?'); args.append(rider_id)
    if primary_id is not None:
        where.append('d.primaryId=?'); args.append(primary_id)
    if dup_ids is not None:
        where.append(f"d.id IN ({','.join('?' * len(dup_ids))})"); args += list(dup_ids)
    return db.execute(f'''SELECT d.id AS dupId, d.source, d.bikeId AS copyBike, d.kitId AS copyKit, g.gear AS stravaName,
                                 sb.bikeId AS stravaBike, sk.kitId AS stravaKit,
                                 a.id, a.riderId, a.name, a.sportType, a.startDateLocal, a.bikeId, a.kitId
                          FROM ActivityDuplicate d JOIN Activity a ON a.id = d.primaryId
                          LEFT JOIN StravaGear g ON g.activityId = d.id
                          LEFT JOIN StravaBike sb ON sb.riderId = a.riderId AND sb.name = g.gear AND sb.status = 'matched'
                          LEFT JOIN StravaKit sk ON sk.riderId = a.riderId AND sk.name = g.gear AND sk.status = 'matched'
                          WHERE {' AND '.join(where)}
                          ORDER BY a.startDateLocal DESC''', args).fetchall()


def conflicts(db, rider_id=None, primary_id=None, dup_ids=None):
    """Every copy set aside whose gear differs from the activity kept in its place, newest first: dicts of the activity (id, name, sportType,
    startDateLocal), dupId, source, ride (bike or kit), kept and other ({'id', 'name', 'retired'}), and fromStrava (the other's gear is the one
    its Strava export names)."""
    rows = _rows(db, rider_id, primary_id, dup_ids)
    if not rows:
        return []
    names = {}
    for r in {r['riderId'] for r in rows}:
        names.update({('bike', b['id']): {'id': b['id'], 'name': b['name'], 'retired': bool(b['archived'])} for b in gear.list_bikes(db, r, include_archived=True)})
        names.update({('kit', k['id']): {'id': k['id'], 'name': k['name'], 'retired': bool(k['retiredOn'])} for k in kit.list_kit(db, r, include_retired=True)})
    out = []
    for r in rows:
        ride = is_ride(r['sportType'])
        what = 'bike' if ride else 'kit'
        kept = names.get((what, r['bikeId'] if ride else r['kitId']))
        own = names.get((what, r['copyBike'] if ride else r['copyKit']))
        other = own or names.get((what, r['stravaBike'] if ride else r['stravaKit']))
        if not kept or not other or kept['id'] == other['id']:
            continue
        out.append({'id': r['id'], 'name': r['name'], 'sportType': r['sportType'], 'startDateLocal': r['startDateLocal'], 'dupId': r['dupId'],
                    'source': r['source'], 'ride': ride, 'kept': kept, 'other': other, 'fromStrava': not own})
    return out


def count(db, rider_id):
    if rider_id is None:
        return 0
    try:
        return len(conflicts(db, rider_id))
    except Exception:                                   # a bare database with no gear tables: nothing to check
        return 0


def use_other(db, found):
    """Put each kept activity in `found` (conflicts) on the gear of its other recording. Returns how many changed. Does not commit."""
    by_gear = {}
    for c in found:
        by_gear.setdefault((c['ride'], c['other']['id']), []).append(c['id'])
    riders = set()
    n = 0
    for (ride, gid), ids in by_gear.items():
        if ride:
            n += gear.set_rides_bike(db, ids, gid)
            riders.add(gear.get_bike(db, gid)['riderId'])
        else:
            n += kit.set_activities_kit(db, ids, gid)
    for r in riders:
        gear.evaluate_alerts(db, rider_id=r)            # the bike's parts may be due now
    return n


def keep(db, found):
    """The kept activity's gear is right for each of `found` (conflicts): stop listing them. Does not commit."""
    ids = [c['dupId'] for c in found]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.execute(f"UPDATE ActivityDuplicate SET gearChecked=1 WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    return len(ids)
