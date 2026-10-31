"""One-off repair: rides imported from files (FIT, GPX, a Strava export) were saved with their UTC start time as if it were UK local time, so all summer
they sit an hour early. Besides the wrong time of day (and weather looked up for the wrong hour), the same ride from Garmin then didn't overlap its
imported twin, the duplicate check never matched them, and both counted in every total.

The signature of such a ride is startDate == startDateLocal: the import stored the naive time in both. Every path that knows the real local time
(Garmin, the phone app, a GPX with a 'Z') stores the UTC instant and the local time separately, and they differ all summer; in winter they are equal
but UTC is UK time then, so moving those changes nothing. Garmin, manual, converted and demo rides, and friends' synced rides, are left alone.

Also here: fix_local_zones (once: every activity's local time taken where it happened, and Garmin's zoneless times read as UTC), move_local and
retime_copies (copies of a RunKeeper file whose clock was out, put right when the file is imported again)."""
import logging
from datetime import datetime, timezone
from services import tz

log = logging.getLogger(__name__)

_SKIP = ('garmin_%', 'man_%', 'conv_%', 'demo_%')


def fix_utc_starts(db):
    """Run once (Settings.utcStartFixDone). Moves each such ride's start to local time, keeps the UTC instant in startDate, and runs the duplicate
    check on every ride it moved, so the Garmin twin of an imported ride is found and the weaker copy is set aside (not deleted; it can be swapped
    back from the ride page). Commits. Returns {'moved', 'duplicates', 'ran'}."""
    from services import duplicates
    s = db.execute('SELECT utcStartFixDone FROM Settings WHERE id=1').fetchone()
    if not s or s['utcStartFixDone']:
        return {'moved': 0, 'duplicates': 0, 'ran': False}
    skip_sql = ' AND '.join('a.id NOT LIKE ?' for _ in _SKIP)
    rows = db.execute(f'''SELECT a.id, a.startDateLocal, a.startLat, a.startLng, a.sportType FROM Activity a
                          WHERE {skip_sql} AND a.riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)
                            AND (a.startDate IS NULL OR substr(a.startDate, 1, 19) = substr(a.startDateLocal, 1, 19))''', list(_SKIP)).fetchall()
    moved = []
    for r in rows:
        try:
            utc = datetime.fromisoformat(str(r['startDateLocal'])[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        local = tz.local_at(utc, r['startLat'], r['startLng'], r['sportType'])
        db.execute('UPDATE Activity SET startDate=?, startDateLocal=? WHERE id=?', [utc.strftime('%Y-%m-%dT%H:%M:%S'), local, r['id']])
        if local != str(r['startDateLocal'])[:19]:
            moved.append(r['id'])
    found = 0
    for act_id in moved:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():      # may have been set aside already as another's twin
            if duplicates.resolve(db, act_id):
                found += 1
    db.execute('UPDATE Settings SET utcStartFixDone=1 WHERE id=1')
    db.commit()
    if moved:
        log.info('Start times: moved %d imported ride(s) from UTC to local time; %d turned out to be a ride already here', len(moved), found)
    return {'moved': len(moved), 'duplicates': found, 'ran': True}


def recheck_away_starts(db):
    """Run once (Settings.awayStartRecheckDone). The duplicate check used to read Garmin's local start time in the home time zone, but it is the clock
    where the ride happened: on a trip abroad (a Vancouver walk with London as home) the Garmin copy sat hours away from its Strava or file twin, and
    both were kept. Matching now uses the stored UTC instant; this re-runs the check on every ride whose two start times disagree that way, so those
    twins are found and the weaker copy is set aside (not deleted; it can be swapped back from the ride page). Commits.
    Returns {'checked', 'duplicates', 'ran'}."""
    from services import duplicates
    s = db.execute('SELECT awayStartRecheckDone FROM Settings WHERE id=1').fetchone()
    if not s or s['awayStartRecheckDone']:
        return {'checked': 0, 'duplicates': 0, 'ran': False}
    rows = db.execute('''SELECT id, startDate, startDateLocal FROM Activity
                         WHERE startDate IS NOT NULL AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)''').fetchall()
    away = [r['id'] for r in rows if duplicates.start_instant(r) != duplicates.instant(r['startDateLocal'])]
    found = 0
    for act_id in away:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():      # may have been set aside already as another's twin
            if duplicates.resolve(db, act_id):
                found += 1
    db.execute('UPDATE Settings SET awayStartRecheckDone=1 WHERE id=1')
    db.commit()
    if found:
        log.warning('Start times: %d ride(s) recorded away from the home time zone turned out to be a ride already here', found)
    return {'checked': len(away), 'duplicates': found, 'ran': True}


_WEATHER = ('weatherTempC', 'weatherWindKph', 'weatherGustKph', 'weatherWindDir', 'weatherHumidity', 'weatherRainMm', 'weatherCode', 'weatherSummary',
            'weatherWindRel')
_DATED = (('BestEffort', 'activityId', 'activityDate'), ('SegmentEffort', 'activityId', 'activityDate'), ('SportEffort', 'activityId', 'activityDate'),
          ('RideMemory', 'rideId', 'rideDate'))


def _utc_str(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def move_local(db, act_id, old_local, new_local, new_utc=None):
    """Give an activity a new local start (and UTC start, when given). The day kept with its best times, segment times and memory follows it,
    and its weather goes: Open-Meteo is asked for the hour at the place (timezone=auto), so it was looked up for the wrong hour. The weather
    service fills it in again (services/weather.backfill_missing); a condition the rider picked, or a named storm's, stays. Does not commit."""
    if new_utc:
        db.execute('UPDATE Activity SET startDate=?, startDateLocal=? WHERE id=?', [new_utc, new_local, act_id])
    else:
        db.execute('UPDATE Activity SET startDateLocal=? WHERE id=?', [new_local, act_id])
    if str(old_local or '')[:10] != new_local[:10]:
        have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, key, col in _DATED:
            if table in have:
                db.execute(f'UPDATE {table} SET {col}=? WHERE {key}=?', [new_local[:10], act_id])
    if str(old_local or '')[:19] != new_local[:19]:
        db.execute(f"UPDATE Activity SET {', '.join(c + '=NULL' for c in _WEATHER)} WHERE id=? AND weatherSummary IS NOT NULL "
                   "AND COALESCE(weatherSource, '') NOT IN ('manual', 'storm')", [act_id])


def retime_copies(db, rider_id, wrong_utc, right_utc, distance_m):
    """A RunKeeper file whose clock was out (services/parser.runkeeper_shift) was saved before with the wrong start, and so were its copies:
    Strava's (activities.csv has the same wrong time) and Garmin's (the file re-uploaded there). Each live activity of the rider that starts at
    `wrong_utc` (to within 2 s) and agrees on distance (within 2%) is moved to `right_utc`, then checked for duplicates again: on the right time
    it meets the copies that had it right all along. Returns the ids moved. Does not commit."""
    from datetime import timedelta
    from services import duplicates
    from services.weather import origin
    if not distance_m:
        return []
    days = [(wrong_utc + timedelta(days=d)).strftime('%Y-%m-%d') for d in (-1, 0, 1)]
    who = ' AND riderId=?' if rider_id else ' AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)'
    rows = db.execute(f"""SELECT id, startDate, startDateLocal, startLat, startLng, sportType, distance, streams FROM Activity
                          WHERE substr(startDate, 1, 10) IN (?,?,?){who}""", days + ([rider_id] if rider_id else [])).fetchall()
    moved = []
    for r in rows:
        at = duplicates.start_instant(r)
        dist = float(r['distance'] or 0)
        if not at or abs((at - wrong_utc).total_seconds()) > 2 or not dist or abs(dist - distance_m) > 0.02 * max(dist, distance_m):
            continue
        lat, lng = origin(r)
        move_local(db, r['id'], r['startDateLocal'], tz.local_at(right_utc, lat, lng, r['sportType']), _utc_str(right_utc))
        moved.append(r['id'])
    for act_id in moved:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():
            duplicates.resolve(db, act_id)
    if moved:
        log.warning('Start times: %s moved from %s to %s (a RunKeeper file whose clock was out)', ', '.join(moved), _utc_str(wrong_utc), _utc_str(right_utc))
    return moved


_OWN_SKIP = ('man_%', 'conv_%', 'demo_%')
_OWN_SQL = (' AND '.join('id NOT LIKE ?' for _ in _OWN_SKIP) + " AND COALESCE(source, '') <> 'manual'"
            ' AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)')


def _flatten_parked(db):
    """Copies set aside under a copy that was itself set aside later (before park() moved them on) now hang off the activity kept in the end.
    Returns how many moved."""
    n = 0
    for _ in range(10):                                 # chains are short; each pass moves them up one level
        c = db.execute("""UPDATE ActivityDuplicate SET primaryId = (SELECT p.primaryId FROM ActivityDuplicate p WHERE p.id = ActivityDuplicate.primaryId)
                          WHERE status='parked' AND primaryId IN (SELECT id FROM ActivityDuplicate WHERE status='parked' AND primaryId <> '')""").rowcount
        n += c
        if not c:
            break
    return n


def fix_local_zones(db):
    """Run once (Settings.localZoneFixDone). Until now every import put an activity's local time in the home zone, and a Garmin activity with no
    zone of its own (Garmin then gives its UTC time as the local time too) was read as home-zone time: all summer it sat an hour before its
    Strava copy, both were kept, and the Garmin one, without the Strava bike, counted as a ride on no bike. Pieces of rides recorded by a phone
    app with a speed sensor (no GPS) were never matched with the ride either. For the rider's own activities (not typed in, not friends'):
    1. the local time again, from the UTC instant (a Garmin activity's equal times count as UTC) in the zone where it started (left alone with no
    position when the device knew its zone); 2. the weather of each one that moved cleared, to be looked up again for the right hour; 3. those
    checked for duplicates again; 4. then every other activity, pieces of rides among them;
    5. copies set aside under a copy that was itself set aside moved to the one kept, and the Strava bikes and shoes put on what has none. Commits. Returns {'ran', 'moved', 'duplicates', 'fragments', 'repointed', 'bikes', 'kit', 'moved_ids', 'parked'}."""
    from services import duplicates, strava_gear
    from services.weather import origin
    s = db.execute('SELECT localZoneFixDone FROM Settings WHERE id=1').fetchone()
    if not s or s['localZoneFixDone']:
        return {'ran': False}
    duplicates.ensure_schema(db)
    rows = db.execute(f'SELECT id, startDate, startDateLocal, startLat, startLng, sportType FROM Activity WHERE startDateLocal IS NOT NULL AND {_OWN_SQL}',
                      list(_OWN_SKIP)).fetchall()
    moved = []                                          # (id, old local, new local)
    for r in rows:
        at = duplicates.start_instant(r)
        if not at:
            continue
        lat, lng = r['startLat'], r['startLng']
        if lat is None or lng is None:                  # older imports kept only the track
            st = db.execute('SELECT streams FROM Activity WHERE id=?', [r['id']]).fetchone()
            lat, lng = origin({'startLat': None, 'startLng': None, 'streams': st[0] if st else None})
        if lat is None and r['startDate'] and str(r['startDate'])[:19] != str(r['startDateLocal'])[:19]:
            continue                                    # nowhere to look up, and the device knew its zone (a Garmin ride abroad with no GPS)
        local = tz.local_at(at, lat, lng, r['sportType'])
        if local != str(r['startDateLocal'])[:19]:
            move_local(db, r['id'], r['startDateLocal'], local, _utc_str(at))
            moved.append((r['id'], str(r['startDateLocal'])[:19], local))
    before = {r[0] for r in db.execute("SELECT id FROM ActivityDuplicate WHERE status='parked'")}
    # The ones that moved first, then every other own activity (pieces of rides, services/duplicates.fragment_of, among them): the check only
    # ever ran as an activity arrived, and pairs that came in before it (or by a path that missed it) were never compared, like a 2017 Garmin
    # upload and its Strava copy with the same start and distance
    rest = [r[0] for r in db.execute(f'SELECT id FROM Activity WHERE {_OWN_SQL} ORDER BY startDate', list(_OWN_SKIP)).fetchall()]
    for act_id in [m[0] for m in moved] + rest:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():      # may have been set aside already as another's twin
            duplicates.resolve(db, act_id)
    repointed = _flatten_parked(db)
    strava_gear.ensure_schema(db)
    bikes = kit = 0
    for (rider_id,) in db.execute('SELECT id FROM Rider WHERE id NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)').fetchall():
        bikes += strava_gear.apply_matched(db, rider_id)
        kit += strava_gear.apply_kit(db, rider_id)['filled']
    parked = [tuple(r) for r in db.execute("SELECT id, primaryId, reason FROM ActivityDuplicate WHERE status='parked'") if r[0] not in before]
    frags = sum(1 for p in parked if (p[2] or '').startswith('Kept the whole ride'))
    found = len(parked) - frags
    db.execute('UPDATE Settings SET localZoneFixDone=1 WHERE id=1')
    db.commit()
    if moved or parked:
        log.warning('Start times: %d activit%s moved to the local time where %s happened; %d duplicate(s) and %d piece(s) of a ride set aside; '
                    '%d ride(s) put on their Strava bike, %d activit(ies) on their shoes', len(moved), 'y' if len(moved) == 1 else 'ies',
                    'it' if len(moved) == 1 else 'they', found, frags, bikes, kit)
    return {'ran': True, 'moved': len(moved), 'duplicates': found, 'fragments': frags, 'repointed': repointed, 'bikes': bikes, 'kit': kit,
            'moved_ids': moved, 'parked': parked}
