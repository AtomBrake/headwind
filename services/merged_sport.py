"""Merged activities whose two recordings disagree about the sport: worth a look, since only one of them can be right.

When the same activity is recorded twice (services/duplicates.py) the copy kept keeps its own sport, whatever the one set aside says. That is
often the wrong way round: a Garmin ride saved as a plain Ride while its Strava copy says "E-Bike Ride", a Strava "Virtual Ride" set aside behind
Garmin's `cycling`, a Strava "Yoga" behind Garmin's Other. And sometimes the copy kept is the right one (Strava's "Ride" behind Garmin's mountain
bike ride, or a Strava e-bike ride on a bike that isn't one). So nothing is taken on its own: each difference is listed (the activity's page, the
Import page, the dashboard) for the rider to settle: take the other recording's sport, or say the kept one is right (ActivityDuplicate.sportChecked).

The other recording's sport is the one it was saved with (ActivityDuplicate.sportType). Strava's spellings of Headwind's sports count as the same
sport, and a copy that says only Other or Workout has nothing to offer (sports.differ). Friends' activities are not ours to change.
"""
from services import convert, duplicates, origin
from services.friend_rides import FRIEND_RIDERS_SQL
from services.sports import canonical, differ, label


def _rows(db, rider_id=None, primary_id=None, dup_ids=None):
    duplicates.ensure_schema(db)
    where, args = ["d.status='parked'", 'COALESCE(d.sportChecked, 0)=0', "COALESCE(d.sportType, '') <> ''",
                   f'a.riderId NOT IN ({FRIEND_RIDERS_SQL})'], []
    if rider_id is not None:
        where.append('a.riderId=?'); args.append(rider_id)
    if primary_id is not None:
        where.append('d.primaryId=?'); args.append(primary_id)
    if dup_ids is not None:
        where.append(f"d.id IN ({','.join('?' * len(dup_ids))})"); args += list(dup_ids)
    return db.execute(f'''SELECT d.id AS dupId, d.source, d.sportType AS otherSport, a.id, a.originId, a.riderId, a.name, a.sportType, a.startDateLocal,
                                 a.distance
                          FROM ActivityDuplicate d JOIN Activity a ON a.id = d.primaryId
                          WHERE {' AND '.join(where)}
                          ORDER BY a.startDateLocal DESC''', args).fetchall()


def _by(act_id, origin_id=None, fallback='this recording'):
    """Who says it: 'Garmin' or 'Strava' when the id says so (services/origin.link), else `fallback`."""
    link = origin.link(act_id, origin_id)
    return link['name'] if link else fallback


def conflicts(db, rider_id=None, primary_id=None, dup_ids=None):
    """Every copy set aside whose sport differs from the activity kept in its place, newest first: dicts of the activity (id, name, sportType,
    startDateLocal, distance), dupId, other (the copy's sport, as Headwind saves it), keptBy and otherBy ('Garmin', 'Strava', or who else
    recorded it), and pair (kept sport, other sport): the same disagreement on many activities can be settled at once."""
    out = []
    for r in _rows(db, rider_id, primary_id, dup_ids):
        if not differ(r['sportType'], r['otherSport']):
            continue
        kept_by = _by(r['id'], r['originId'])
        other_by = _by(r['dupId'], fallback=r['source'] or 'the other recording')
        if other_by == kept_by:                         # two Strava uploads of one ride, say: name them by what they are
            kept_by, other_by = 'this recording', 'the other recording'
        other = canonical(r['otherSport'])
        out.append({'id': r['id'], 'name': r['name'], 'sportType': r['sportType'], 'startDateLocal': r['startDateLocal'], 'distance': r['distance'],
                    'dupId': r['dupId'], 'other': other, 'keptBy': kept_by, 'otherBy': other_by, 'pair': (r['sportType'] or '', other)})
    return out


def groups(found):
    """`found` (conflicts) by pair, the biggest first: [{'kept', 'other', 'rows'}]."""
    by = {}
    for c in found:
        by.setdefault(c['pair'], []).append(c)
    return [{'kept': k, 'other': o, 'rows': rows} for (k, o), rows in sorted(by.items(), key=lambda kv: (-len(kv[1]), label(kv[0][0]), label(kv[0][1])))]


def count(db, rider_id):
    if rider_id is None:
        return 0
    try:
        return len(conflicts(db, rider_id))
    except Exception:                                   # a bare database with no duplicate tables: nothing to check
        return 0


def use_other(db, found):
    """Give each kept activity in `found` (conflicts) its other recording's sport (convert.change_sport: a ride that becomes a run moves its
    derived data over, and keeps the copy set aside, which is the one that says so). Returns (changed, [(activity, reason)] that couldn't be).
    Does not commit."""
    changed, failed = 0, []
    for c in found:
        try:
            if convert.change_sport(db, None, c['id'], c['other'], keep_parked=True, any_sport=True)['changed']:
                changed += 1
        except ValueError as e:
            failed.append((c, str(e)))
    return changed, failed


def keep(db, found):
    """The kept activity's sport is right for each of `found` (conflicts): stop listing them. Does not commit."""
    ids = [c['dupId'] for c in found]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.execute(f"UPDATE ActivityDuplicate SET sportChecked=1 WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    return len(ids)
