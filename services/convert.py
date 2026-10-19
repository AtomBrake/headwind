"""Change what kind of activity something is: a walk that was recorded as a ride, a ride that was typed in as a run, and so on.

Every sport is a row in Activity, so a change keeps the row and its id. Between the two families (rides, and the rest: services/sports.is_ride) it
is more than a label: what only a ride has (best efforts, ride segments, the bike) goes or comes back, and calories are re-estimated for the new sport
(a walk logged as a ride carries a cycling estimate, which badly over-counts). Nothing here commits: the caller does.
"""

from services.sports import RIDES, SPORTS, is_ride

_GENERIC_NAMES = {'', 'ride', 'walk', 'run', 'hike', 'virtualride', 'garmin activity', 'ride activity'}


def _kg(rider_id):
    try:
        from services import goal_model
        return goal_model.current_weight_kg(rider_id) or 70.0
    except Exception:
        return 70.0


def _ride_to_workout(db, row, sport, discard_parked=False):
    """Same row, new sport: what only a ride has goes (best efforts, ride segment efforts, the AI's ride memory, the bike), calories are re-estimated
    for the new sport, and a run gets its best times, and a walk, run or hike its foot-segment efforts."""
    from services import duplicates
    from services.segments import _refresh_prs
    from services.workouts import estimate_calories
    parked = [d['id'] for d in duplicates.parked_for(db, row['id'])]
    if parked and not discard_parked:
        raise ValueError('this ride has another recording set aside under it: settle that first (open the ride and choose which recording to keep)')
    for dup_id in parked:                                # another device's copy of the same session: not a ride either, so it goes (its id stays remembered)
        duplicates.discard(db, dup_id)
    dist, secs, gain = row['distance'] or 0, int(row['movingTime'] or 0), row['totalElevationGain'] or 0
    from services.calorie_adjust import pair as _kcal_pair
    kcal_raw, kcal = _kcal_pair(estimate_calories(sport, dist, secs, gain, _kg(row['riderId'])))
    if kcal is None:                                     # no estimate possible: keep the ride's figure
        kcal_raw, kcal = row['caloriesRaw'], row['calories']
    name = row['name'] if (row['name'] or '').strip().lower() not in _GENERIC_NAMES else None
    for sid in duplicates._drop_derived(db, row['id']):  # best efforts, segment efforts, ride memory
        _refresh_prs(db, sid)
    db.execute("UPDATE Activity SET type=?, sportType=?, name=?, calories=?, caloriesRaw=?, bikeId=NULL, flagReason=NULL, source=COALESCE(source, 'converted'), "
               "updatedAt=datetime('now') WHERE id=?", [sport, sport, name, kcal, kcal_raw, row['id']])
    from services import workouts as _wk
    _wk.refresh_derived(db, row['id'])
    return {'kind': 'workout', 'id': row['id'], 'sport': sport}


def _workout_to_ride(db, row, sport):
    from services import duplicates, gear, workouts
    from services.parser import estimate_ride_calories
    dist, secs = row['distance'] or 0, int(row['movingTime'] or 0)
    from services.calorie_adjust import pair as _kcal_pair
    kcal_raw, kcal = _kcal_pair(estimate_ride_calories(dist, secs, _kg(row['riderId'])))
    if kcal is None:                                     # no estimate possible: keep the workout's figure
        kcal_raw, kcal = row['caloriesRaw'], row['calories']
    name = row['name'] if (row['name'] or '').strip() else workouts.label({'name': None, 'sport': row['sportType'], 'startDateLocal': row['startDateLocal']})
    workouts.forget(db, row['id'])                       # run best times and foot-segment efforts
    db.execute("UPDATE Activity SET type=?, sportType=?, name=?, calories=?, caloriesRaw=?, updatedAt=datetime('now') WHERE id=?",
               [sport, sport, name, kcal, kcal_raw, row['id']])
    duplicates.rebuild_derived(db, row['id'])           # best efforts + segment efforts, now that it is a ride
    gear.on_ride_added(db, row['id'])                   # the rider's default bike
    return {'kind': 'ride', 'id': row['id'], 'sport': sport}


def change_sport(db, kind, act_id, sport, discard_parked=False):
    """Returns {'kind', 'id', 'sport', 'changed'}. `kind` is what the caller has in hand ('ride' or 'workout'), checked against the row, or None to
    take the row as it is; the id never changes now that every sport is a row in Activity. Raises ValueError with a readable reason. A ride with
    another recording set aside under it is refused unless `discard_parked`, which throws those recordings away as it changes the ride."""
    if sport not in SPORTS:
        raise ValueError('pick one of: ' + ', '.join(SPORTS))
    if kind not in ('ride', 'workout', None):
        raise ValueError('kind must be ride or workout')
    row = db.execute('SELECT * FROM Activity WHERE id=?', [act_id]).fetchone()
    if row and kind is None:
        kind = 'ride' if is_ride(row['sportType']) else 'workout'
    if not row or is_ride(row['sportType']) != (kind == 'ride'):
        raise ValueError('that ride was not found' if kind == 'ride' else 'that activity was not found')
    if (row['sportType'] or '') == sport:
        return {'kind': kind, 'id': act_id, 'sport': sport, 'changed': False}
    if kind == 'ride' and sport in RIDES:                # Ride <-> VirtualRide <-> EBikeRide (or an MTB ride becoming a plain Ride): the label,
        from services.segments import reclassed         # and its segments (none indoors) or its PRs (pedal or e-bike: services/sports.segment_class)
        from services.sports import class_of
        before = class_of(db, act_id)
        db.execute('UPDATE Activity SET sportType=?, type=? WHERE id=?', [sport, sport, act_id])
        reclassed(db, act_id, before)
        return {'kind': 'ride', 'id': act_id, 'sport': sport, 'changed': True}
    if kind == 'ride':
        return dict(_ride_to_workout(db, row, sport, discard_parked), changed=True)
    if sport in RIDES:
        return dict(_workout_to_ride(db, row, sport), changed=True)
    db.execute('UPDATE Activity SET sportType=?, type=? WHERE id=?', [sport, sport, act_id])
    from services import workouts as _wk
    _wk.refresh_derived(db, act_id)                      # walks, runs and hikes share foot segments; a swim has none; runs and swims have best times
    from services.workouts import estimate_calories
    from services.calorie_adjust import pair as _kcal_pair
    kcal_raw, kcal = _kcal_pair(estimate_calories(sport, row['distance'] or 0, int(row['movingTime'] or 0), row['totalElevationGain'] or 0, _kg(row['riderId'])))
    if kcal is not None and (row['source'] != 'manual' or not row['calories']):
        db.execute('UPDATE Activity SET calories=?, caloriesRaw=? WHERE id=?', [kcal, kcal_raw, act_id])
    return {'kind': 'workout', 'id': act_id, 'sport': sport, 'changed': True}
