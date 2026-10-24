"""Many activities at once, picked on an activity list (rides and workouts can be mixed). Every action goes through the code a single activity uses,
so derived data stays right: deletes leave tombstones and re-pick segment PRs, a type change between a ride and a workout drops or rebuilds what only a ride has, and so on.
Nothing here commits; the caller commits once."""
MAX_IDS = 5000
ACTIONS = ('delete', 'sport', 'bike', 'kit', 'rider', 'rename', 'dismiss', 'commute')


def own_riders(db):
    """Riders that live here (not ones synced from a friend): the only ones an activity can be moved to."""
    return db.execute('SELECT id, name FROM Rider WHERE id NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL) ORDER BY isDefault DESC, name').fetchall()


def apply(db, action, ids, sport=None, bike_id=None, rider_id=None, name=None, commute=None, kit_id=None):
    """Returns {'done': n, 'skipped': n, 'friends': n of those skipped as a friend's, 'kinds': {'ride', 'workout'} touched}. Raises ValueError
    for a bad action or missing parameter."""
    from services import convert, duplicates, friend_rides, gear, kit, sanity, workouts
    from services.sports import kind_of
    if action not in ACTIONS:
        raise ValueError('unknown action')
    if action == 'sport' and sport not in convert.SPORTS:
        raise ValueError('pick one of: ' + ', '.join(convert.SPORTS))
    if action == 'rider' and not any(r['id'] == rider_id for r in own_riders(db)):
        raise ValueError('pick one of your riders')
    if action == 'rename' and not (name or '').strip():
        raise ValueError('type a name')
    if action == 'commute' and commute not in ('0', '1'):
        raise ValueError('pick commute or not a commute')
    done = skipped = friends = 0
    kinds = set()
    for act_id in list(dict.fromkeys(ids))[:MAX_IDS]:
        kind = kind_of(db, act_id)
        if not kind:
            skipped += 1
            continue
        if friend_rides.friend_of(db, act_id):            # shown here, changed only on their instance
            skipped += 1
            friends += 1
            continue
        try:
            if action == 'delete':
                if kind == 'ride':
                    duplicates.delete_activity(db, act_id)
                    db.execute('DELETE FROM RideMemory WHERE rideId=?', [act_id])
                else:
                    owner = db.execute('SELECT riderId FROM Activity WHERE id=?', [act_id]).fetchone()['riderId']
                    workouts.delete(db, act_id, owner)
            elif action == 'sport':
                res = convert.change_sport(db, kind, act_id, sport)
                kinds.add(res['kind'])
                if not res.get('changed'):
                    skipped += 1
                    continue
            elif action == 'bike':
                if kind != 'ride':
                    skipped += 1                             # only rides have a bike
                    continue
                gear.set_ride_bike(db, act_id, bike_id)
            elif action == 'kit':
                if kind == 'ride':
                    skipped += 1                             # a ride has a bike, not shoes
                    continue
                kit.set_activity_kit(db, act_id, kit_id)
            elif action == 'rider':
                _move_to_rider(db, kind, act_id, rider_id)
            elif action == 'rename':
                db.execute('UPDATE Activity SET name=? WHERE id=?', [name.strip()[:200], act_id])
            elif action == 'commute':                       # 0, not NULL, for "not a commute": a Strava import then leaves it alone (routes/rides.set_commute)
                db.execute('UPDATE Activity SET commute=? WHERE id=?', [int(commute), act_id])
            elif action == 'dismiss':
                if kind != 'ride':
                    skipped += 1
                    continue
                sanity.dismiss(db, act_id)
        except ValueError:                                   # e.g. a bike that belongs to another rider, a ride with a duplicate parked under it
            skipped += 1
            continue
        kinds.add(kind)
        done += 1
    return {'done': done, 'skipped': skipped, 'friends': friends, 'kinds': kinds}


def _move_to_rider(db, kind, act_id, rider_id):
    """Give an activity to another of this instance's riders: its bike and kit (the old rider's) are cleared, and segment PRs are re-picked for both."""
    from services.segments import _refresh_prs
    db.execute('UPDATE Activity SET riderId=?, bikeId=NULL, kitId=NULL WHERE id=?', [rider_id, act_id])
    for (sid,) in db.execute('SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId=?', [act_id]).fetchall():
        _refresh_prs(db, sid)
