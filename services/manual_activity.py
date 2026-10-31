"""Activities typed in by hand, or timed on the phone or the Watch with no track: a ride you forgot to record, a turbo session, a walk without
GPS, a strength session, a pool swim.

Walk / Run / Hike / VirtualRun (an indoor run), Swim, Strength / HIIT / Yoga and Ride / VirtualRide are Activity rows like everything recorded by a device; the ride ones get a bike. A manual ride has no
GPS track, so it has no map or best efforts, but it counts in the totals. If a real recording of the same ride arrives later (Garmin sync, phone
upload) the duplicate logic keeps the recording and parks the typed-in copy.
"""
import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services import duplicates
from services import tz
from services.sports import INDOOR_RUN, NO_DISTANCE, ON_FOOT, RIDES, is_ride

SPORTS = RIDES + ON_FOOT + (INDOOR_RUN, 'Swim') + NO_DISTANCE
SOURCES = ('manual', 'ios', 'android')                # who made it: typed in, or timed by a phone app (its own recording, so not "manual")
MAX_DURATION_S, MAX_DISTANCE_M, MAX_ELEV_M = 48 * 3600, 1_500_000, 20_000


def _local_start(local_iso):
    try:
        dt = datetime.fromisoformat(str(local_iso)[:19])
    except ValueError:
        raise ValueError('that date and time are not valid')
    if dt.tzinfo:
        dt = dt.astimezone(tz.zone()).replace(tzinfo=None)
    if dt > tz.now().replace(tzinfo=None) + timedelta(days=1):
        raise ValueError('that is in the future')
    if dt.year < 2000:
        raise ValueError('that date is too far in the past')
    return dt


def _num(v, name, lo=0, hi=None, required=False):
    if v in (None, ''):
        if required:
            raise ValueError(f'{name} is required')
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number')
    if x < lo or (hi is not None and x > hi):
        raise ValueError(f'{name} is out of range')
    return x


def create(db, rider_id, sport, local_iso, duration_s, distance_m, elev_m=None, calories=None, name=None, notes=None, client_id=None,
           source='manual', avg_hr=None):
    """Store one manual activity. Returns {'kind', 'id', 'created', 'duplicate'}; raises ValueError with a readable reason. Commits.
    Strength, HIIT and Yoga need no distance. `source` is SOURCES; a phone's timed session also gives its average heart rate."""
    if sport not in SPORTS:
        raise ValueError('sport must be one of ' + ', '.join(SPORTS))
    if source not in SOURCES:
        source = 'manual'
    start = _local_start(local_iso)
    secs = int(_num(duration_s, 'duration', 60, MAX_DURATION_S, required=True))
    dist = (0.0 if sport in NO_DISTANCE else _num(distance_m, 'distance', 0, MAX_DISTANCE_M, required=True)) or 0.0
    hr = _num(avg_hr, 'heart rate', 25, 250)
    gain = _num(elev_m, 'elevation', 0, MAX_ELEV_M) or 0
    kcal = _num(calories, 'calories', 0, 20_000)
    name = (name or '').strip()[:80] or None
    notes = (notes or '').strip()[:1000] or None
    local = start.strftime('%Y-%m-%dT%H:%M:%S')
    utc = start.replace(tzinfo=tz.zone()).astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S')
    key = client_id or f'{local}|{sport}|{round(dist)}|{secs}'
    aid = ('man_' if is_ride(sport) else 'wk_') + hashlib.sha1(f'{rider_id}|manual|{key}'.encode()).hexdigest()[:16]
    avg = dist / secs if secs else 0
    from services import goal_model
    kg = goal_model.current_weight_kg(rider_id) or 70.0

    if not is_ride(sport):
        if duplicates.exists_anywhere(db, aid):
            return {'kind': 'workout', 'id': aid, 'created': False, 'duplicate': None}
        from services.workouts import estimate_calories, estimate_met_calories
        from services.calorie_adjust import pair as _kcal_pair
        kcal_raw = None                                  # a number the user typed (or the Watch measured) is theirs: never adjusted
        if kcal is None:
            kcal_raw, kcal = _kcal_pair(estimate_calories(sport, dist, secs, gain, kg) or estimate_met_calories(sport, secs, kg))
        db.execute('''INSERT INTO Activity (id, riderId, type, sportType, name, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain,
                                            averageSpeed, averageHeartrate, calories, source, caloriesRaw, rawData) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'{}')''',
                   [aid, rider_id, sport, sport, name, utc, local, dist, secs, secs, gain, avg, hr, kcal, source, kcal_raw])
        dup = duplicates.resolve(db, aid)                # already recorded by a device? the recording wins over typed-in numbers
        db.commit()
        return {'kind': 'workout', 'id': (dup or {}).get('kept', aid), 'created': True, 'duplicate': dup}

    if duplicates.exists_anywhere(db, aid):
        return {'kind': 'ride', 'id': aid, 'created': False, 'duplicate': None}
    kcal_raw = None                                      # a number the user typed is theirs: never adjusted
    if kcal is None:
        from services.parser import estimate_ride_calories
        from services.calorie_adjust import pair as _kcal_pair
        kcal_raw, kcal = _kcal_pair(estimate_ride_calories(dist, secs, kg))
    db.execute('''INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain,
                                        averageSpeed, maxSpeed, calories, notes, rawData, riderId, caloriesRaw, createdAt, updatedAt)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))''',
               [aid, name or ('Indoor ride' if sport == 'VirtualRide' else 'Ride'), sport, sport, utc, local, dist, secs, secs, gain, avg, 0, kcal, notes, '{}', rider_id, kcal_raw])
    dup = None
    try:
        dup = duplicates.resolve(db, aid)
        from services import gear
        gear.on_ride_added(db, (dup or {}).get('kept', aid))
    except Exception:
        db.rollback()
        raise
    db.commit()
    return {'kind': 'ride', 'id': aid, 'created': True, 'duplicate': dup}
