"""Activities changed or deleted in Garmin Connect after they were imported. The sync only reads forward, so without this a deletion, a rename, a new
sport or a crop in Garmin never reaches Headwind. Nothing is applied on its own: what was added here (name, notes, photos, gear, segment efforts) would be
lost, and a deletion in Garmin may only be someone tidying Garmin. Each change is flagged for review on the Import page and the activity's own page.

What Garmin said about each activity is kept (GarminSeen): at import, or the first time a check sees one imported before this existed (a baseline,
nothing flagged). A later check compares Garmin's list with that, not with Headwind's copy, which the rider may have edited:
- missing from Garmin: deleted. Keep it here, or delete it (the usual delete, so a sync never brings it back).
- another name or sport: use Garmin's or keep Headwind's. Only offered while Headwind's still matches Garmin's old value; one changed here wins.
- another distance or length: cropped or recalculated, so the file is read again and handed to the re-import review (services/reimport.propose).
Only a successful listing counts, and only for the days it reaches: an error raises, an empty listing judges nothing, and an activity older than
the oldest one listed isn't judged. A Garmin copy set aside as a duplicate (ActivityDuplicate) isn't live, so it and the activity kept in its place
are left alone.

Full re-sync also finds activities in Garmin that aren't here at all and that the sync has gone past (_left_behind): one of a type the sync used to
skip is brought in, any other is listed (GarminMissing) to bring in or leave out. Those deleted here that are still in Garmin are listed too,
with Garmin's name and date (Headwind keeps only the id), to bring back."""
import json
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

TASK = 'garmin_changes'         # its TaskLog rows
RECENT_DAYS = 90                # every daily check reads this far back
OLDER_DAYS = 60                 # and one block this long further back, a little older each day, starting over at the newest when it runs out
MASS = 5                        # more missing than this, and more than half of those expected: a wrong account or a broken listing, not deletions


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS GarminSeen (
        garminId  TEXT PRIMARY KEY,          -- Garmin's activity id
        summary   TEXT NOT NULL,             -- summary(): Garmin's name, type, distance, length and start, as last accepted
        seenAt    TEXT DEFAULT (datetime('now'))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS GarminChange (
        rideId    TEXT PRIMARY KEY,
        garminId  TEXT NOT NULL,
        riderId   INTEGER,
        rideName  TEXT,
        kind      TEXT NOT NULL,             -- deleted | edited
        diffs     TEXT NOT NULL DEFAULT '[]',     -- edited: [{field: name | sport, old, new}]
        garmin    TEXT,                      -- edited: Garmin's summary now, the baseline once it's settled
        status    TEXT NOT NULL DEFAULT 'pending',  -- pending | kept (deleted in Garmin, kept here: not flagged again)
        foundAt   TEXT DEFAULT (datetime('now'))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS GarminMissing (
        garminId  TEXT PRIMARY KEY,          -- Garmin's activity id: in Garmin, not here, and older than the sync's cursor
        riderId   INTEGER,
        name      TEXT,
        typeKey   TEXT,
        startDateLocal TEXT,
        distance  REAL,
        activity  TEXT NOT NULL,             -- the entry in Garmin's list, as garmin.save_activity takes it
        deleted   INTEGER NOT NULL DEFAULT 0,     -- 1: deleted here (or left out), still in Garmin; offered to bring back, never brought in by itself
        foundAt   TEXT DEFAULT (datetime('now'))
    )''')


def summary(a):
    """What a check compares, from an entry in Garmin's activity list."""
    return {'name': (a.get('activityName') or '').strip(), 'typeKey': ((a.get('activityType') or {}).get('typeKey') or '').lower(),
            'distance': a.get('distance') or 0, 'duration': a.get('elapsedDuration') or a.get('duration') or 0,
            'start': (a.get('startTimeGMT') or '')[:19]}


def remember(db, a, replace=True):
    """Keep Garmin's summary of an activity: at import (replace), or as a baseline when there's none yet. Does not commit."""
    ensure_schema(db)
    db.execute(f"INSERT OR {'REPLACE' if replace else 'IGNORE'} INTO GarminSeen (garminId, summary, seenAt) VALUES (?,?,datetime('now'))",
               [str(a.get('activityId')), json.dumps(summary(a))])


def _seen(db, gid):
    r = db.execute('SELECT summary FROM GarminSeen WHERE garminId=?', [gid]).fetchone()
    return json.loads(r['summary']) if r else None


def _accept(db, gid, now):
    db.execute("UPDATE GarminSeen SET summary=?, seenAt=datetime('now') WHERE garminId=?", [json.dumps(now), gid])


def _garmin_rows(db, rider_id):
    """{Garmin id: row} for this rider's live activities that came from Garmin (under its id, or kept in originId by an older sport change)."""
    out = {}
    for r in db.execute(r"""SELECT id, originId, name, sportType, startDateLocal FROM Activity
                            WHERE riderId=? AND (id LIKE 'garmin\_%' ESCAPE '\' OR originId LIKE 'garmin\_%' ESCAPE '\')""", [rider_id]):
        src = r['id'] if str(r['id']).startswith('garmin_') else r['originId']
        out[str(src)[7:]] = r
    return out


def _moved(old, new):
    """Distance or length different enough to be a crop or a recalculation, not rounding."""
    d0, d1 = float(old.get('distance') or 0), float(new.get('distance') or 0)
    t0, t1 = float(old.get('duration') or 0), float(new.get('duration') or 0)
    return abs(d1 - d0) > max(50, 0.01 * max(d0, d1)) or abs(t1 - t0) > 60


def _edits(row, old, new):
    """[{field, old, new}] for a rename or new sport in Garmin that Headwind can still take: its own value is still Garmin's old one."""
    from services.garmin import garmin_sport
    out = []
    if new['name'] and new['name'] != old['name'] and (row['name'] or '').strip() == old['name']:
        out.append({'field': 'name', 'old': old['name'], 'new': new['name']})
    was, now = garmin_sport(old['typeKey']), garmin_sport(new['typeKey'])
    if new['typeKey'] and now != was and row['sportType'] == was:
        out.append({'field': 'sport', 'old': was, 'new': now})
    return out


def _starts(a, parsed):
    """(UTC start, local start) the way the sync saves them."""
    from services.garmin import _local_where, garmin_sport
    local = (a.get('startTimeLocal') or '')[:19].replace(' ', 'T')
    gmt = (a.get('startTimeGMT') or '')[:19].replace(' ', 'T')
    if gmt and gmt == local:                           # no zone in Garmin: its "local" time is UTC
        lat, lng = (a.get('startLatitude'), a.get('startLongitude')) if a.get('startLatitude') is not None else (parsed.get('startLat'), parsed.get('startLng'))
        local = _local_where(gmt, lat, lng, garmin_sport(summary(a)['typeKey']))
    return gmt or local, local


def _recording_changed(db, api, a, act_id):
    """Read the activity's file again and offer the difference for review (services/reimport). True when it was read (whether or not anything
    differs), False when it couldn't be: try again next time."""
    from services import reimport
    from services.garmin import read_recording
    parsed, fail = read_recording(api, a)
    if not parsed:
        log.warning('Garmin activity %s changed in Garmin, but reading it again failed (%s): %s', a.get('activityId'), *fail)
        return False
    saved = db.execute('SELECT * FROM Activity WHERE id=?', [act_id]).fetchone()
    if not saved:
        return True
    act = dict(parsed)
    act['startDate'], act['startDateLocal'] = _starts(a, parsed)
    reimport.propose(db, saved, act, 'Garmin')
    return True


def _complete(api, listing):
    """True when Garmin counts exactly as many activities as the listing holds: then it's the whole account, not one cut short."""
    try:
        return api.count_activities() == len(listing)
    except Exception:
        log.warning('Garmin changes: counting the activities in Garmin failed', exc_info=True)
        return False


def check(db, api, rider_id, start, end, whole=False):
    """Compare Garmin's list for start..end (YYYY-MM-DD) with this rider's Garmin activities, and flag what changed. Raises when Garmin can't be
    listed. Commits. Returns {'listed', 'baseline', 'deleted', 'edited', 'recordings', 'back', 'suspect', 'whole'}.
    `whole`: start..end is all of Garmin (full()). When Garmin's own count says the listing is complete, every activity is judged, the oldest
    ones too, and many missing at once is taken as deleted; only none of them listed at all (another account) is suspect. `whole` in the
    result: that was so."""
    ensure_schema(db)
    res = {'listed': 0, 'baseline': 0, 'deleted': 0, 'edited': 0, 'recordings': 0, 'back': 0, 'suspect': False, 'whole': False,
           'imported': 0, 'failed': 0, 'missing': 0, 'deleted_here': 0}
    end_q = (date.fromisoformat(end) + timedelta(days=1)).isoformat()           # a day either side: Headwind's local date can differ from Garmin's
    listing = api.get_activities_by_date(start, end_q) or []
    if not listing:
        return res
    res['listed'] = len(listing)
    res['whole'] = whole and _complete(api, listing)
    rows = _garmin_rows(db, rider_id)
    flags = {r['garminId']: r for r in db.execute('SELECT * FROM GarminChange WHERE riderId=?', [rider_id])}
    listed = set()
    for a in listing:
        gid = str(a.get('activityId'))
        listed.add(gid)
        row = rows.get(gid)
        if not row:
            continue
        flag = flags.get(gid)
        if flag and flag['kind'] == 'deleted':                 # back in Garmin's list: it wasn't deleted after all
            db.execute('DELETE FROM GarminChange WHERE rideId=?', [flag['rideId']])
            res['back'] += 1
            flag = None
        old, new = _seen(db, gid), summary(a)
        if old is None:
            remember(db, a)
            res['baseline'] += 1
            continue
        diffs = _edits(row, old, new)
        if diffs and not (flag and json.loads(flag['diffs']) == diffs):
            db.execute('INSERT OR REPLACE INTO GarminChange (rideId, garminId, riderId, rideName, kind, diffs, garmin) VALUES (?,?,?,?,?,?,?)',
                       [row['id'], gid, rider_id, row['name'], 'edited', json.dumps(diffs), json.dumps(new)])
            res['edited'] += 1
        elif not diffs and flag:                                # put back in Garmin before it was reviewed
            db.execute('DELETE FROM GarminChange WHERE rideId=?', [flag['rideId']])
        if _moved(old, new) and _recording_changed(db, api, a, row['id']):
            _accept(db, gid, {**old, 'distance': new['distance'], 'duration': new['duration'], 'start': new['start']})
            res['recordings'] += 1

    covered = '' if res['whole'] else min((a.get('startTimeLocal') or '9999')[:10] for a in listing)
    missing = [(gid, r) for gid, r in rows.items() if gid not in listed and covered < str(r['startDateLocal'] or '')[:10] <= end]
    expected = sum(1 for r in rows.values() if covered < str(r['startDateLocal'] or '')[:10] <= end)
    if res['whole'] and missing and len(missing) == expected:
        log.warning('Garmin changes: none of %d activities are in Garmin\'s whole list; another account? Not taken as deleted', expected)
        res['suspect'] = True
        missing = []
    elif not res['whole'] and len(missing) > MASS and len(missing) * 2 > expected:
        log.warning('Garmin changes: %d of %d activities from %s to %s are missing from Garmin\'s list; not taken as deleted', len(missing), expected, covered, end)
        res['suspect'] = True
        missing = []
    for gid, r in missing:
        flag = flags.get(gid)
        if flag and flag['kind'] == 'deleted':
            continue                                            # flagged already, or kept here
        db.execute("INSERT OR REPLACE INTO GarminChange (rideId, garminId, riderId, rideName, kind) VALUES (?,?,?,?,'deleted')",
                   [r['id'], gid, rider_id, r['name']])
        res['deleted'] += 1
    db.commit()
    if whole and not res['suspect']:
        _left_behind(db, api, rider_id, listing, rows, res)
    return res


def _left_behind(db, api, rider_id, listing, rows, res):
    """Activities in Garmin's list that aren't here, older than the sync's cursor, so it won't fetch them. One of a type the sync used to skip
    (garmin.ONCE_SKIPPED) was never here, so it can't have been deleted: it's brought in now. Any other may be one deleted before Headwind
    remembered deletions (upstream didn't), or a Garmin copy an older sync left out beside a Strava one: those are listed (GarminMissing) for the
    rider to bring in or leave out. One deleted here (duplicates.is_deleted) is listed as such, whatever its date, since no sync will fetch it.
    The list is made afresh each time. Commits."""
    from services import duplicates, garmin, garmin_failures
    s = db.execute('SELECT garminActivitySyncDate FROM Settings WHERE id=1').fetchone()
    cursor = s['garminActivitySyncDate'] if s else None
    db.execute('DELETE FROM GarminMissing WHERE riderId=?', [rider_id])

    def listed(a, gid, deleted):
        key = summary(a)['typeKey']
        db.execute('INSERT OR REPLACE INTO GarminMissing (garminId, riderId, name, typeKey, startDateLocal, distance, activity, deleted) VALUES (?,?,?,?,?,?,?,?)',
                   [gid, rider_id, summary(a)['name'], key, (a.get('startTimeLocal') or '')[:19].replace(' ', 'T'), a.get('distance') or 0, json.dumps(a), int(deleted)])

    for a in listing:
        gid = str(a.get('activityId') or '')
        day = (a.get('startTimeLocal') or '')[:10]
        if not gid or gid in rows or day < '2005-01-01':       # here (under a newer id too); the sync's own rule for bogus dates
            continue
        if duplicates.exists_anywhere(db, f'garmin_{gid}') or garmin.garmin_twin(db, a, rider_id):
            continue
        if duplicates.is_deleted(db, f'garmin_{gid}'):
            listed(a, gid, True)
            res['deleted_here'] += 1
            continue
        if not cursor or day >= cursor:                         # never synced, or from the cursor on: the sync's to fetch
            continue
        fail = garmin_failures.get(db, gid)
        if fail and not garmin_failures.due(fail):
            continue
        if summary(a)['typeKey'] not in garmin.ONCE_SKIPPED:
            listed(a, gid, False)
            res['missing'] += 1
            continue
        err = garmin.save_activity(db, api, a, rider_id)
        if err:
            log.warning('Garmin activity %s %s failed: %s', gid, *err)
            garmin_failures.record(db, gid, *err, day, a.get('activityName'))
            res['failed'] += 1
        else:
            res['imported'] += 1
        db.commit()                                         # one at a time: each is a download
    db.commit()


def not_here(db, rider_id=None, deleted=False):
    """The activities in Garmin that Full re-sync found and didn't bring in, newest first: never here, or (deleted) deleted here."""
    from services.garmin import garmin_sport
    ensure_schema(db)
    return [dict(r, sportType=garmin_sport(r['typeKey'])) for r in db.execute(f"""SELECT garminId, name, typeKey, startDateLocal, distance FROM GarminMissing
                                            WHERE deleted=? {'AND riderId=?' if rider_id else ''} ORDER BY startDateLocal DESC""",
                                                                              [int(deleted)] + ([rider_id] if rider_id else []))]


def bring_in(db, api, garmin_ids):
    """Fetch and save these listed activities (garmin.save_activity); one deleted here is no longer remembered as deleted. Returns (brought in,
    failed). One that fails is recorded like a sync failure and stays listed, to try again. Commits."""
    from services import garmin, garmin_failures
    ensure_schema(db)
    done = failed = 0
    for gid in garmin_ids:
        r = db.execute('SELECT * FROM GarminMissing WHERE garminId=?', [str(gid)]).fetchone()
        if not r:
            continue
        a = json.loads(r['activity'])
        err = garmin.save_activity(db, api, a, r['riderId'])
        if err:
            log.warning('Garmin activity %s %s failed: %s', gid, *err)
            garmin_failures.record(db, gid, *err, (a.get('startTimeLocal') or '')[:10], a.get('activityName'))
            failed += 1
        else:
            db.execute("DELETE FROM ActivityDuplicate WHERE id=? AND status='deleted'", [f'garmin_{gid}'])     # brought back on purpose
            db.execute('DELETE FROM GarminMissing WHERE garminId=?', [str(gid)])
            done += 1
        db.commit()
    return done, failed


def leave_out(db, garmin_ids):
    """Never bring these in: remembered as deleted (duplicates.tombstone), so a sync never fetches them, and moved to the deleted ones, to bring
    back from there. Returns how many. Does not commit."""
    from services import duplicates
    ensure_schema(db)
    n = 0
    for gid in garmin_ids:
        r = db.execute('SELECT riderId FROM GarminMissing WHERE garminId=? AND deleted=0', [str(gid)]).fetchone()
        if r:
            duplicates.tombstone(db, f'garmin_{gid}', r['riderId'])
            db.execute('UPDATE GarminMissing SET deleted=1 WHERE garminId=?', [str(gid)])
            n += 1
    return n


def run(db, api, rider_id, today=None):
    """The daily check: the last RECENT_DAYS, and one OLDER_DAYS block further back (Settings.garminChangesBefore, a little older each time). Commits.
    Returns check()'s counts, added up."""
    today = today or date.today()
    recent = today - timedelta(days=RECENT_DAYS)
    total = check(db, api, rider_id, recent.isoformat(), today.isoformat())
    s = db.execute('SELECT garminChangesBefore FROM Settings WHERE id=1').fetchone()
    before = date.fromisoformat(s['garminChangesBefore']) if s and s['garminChangesBefore'] else recent
    oldest = min((str(r['startDateLocal'] or '')[:10] for r in _garmin_rows(db, rider_id).values()), default=None)
    if oldest and before.isoformat() > oldest:
        start = before - timedelta(days=OLDER_DAYS)
        older = check(db, api, rider_id, start.isoformat(), (before + timedelta(days=2)).isoformat())   # overlapping the block after it
        total = {k: (total[k] or older[k]) if k in ('suspect', 'whole') else total[k] + older[k] for k in total}
        nxt = start.isoformat() if start.isoformat() > oldest else None         # past the oldest: start again from the newest next time
    else:
        nxt = None
    db.execute('UPDATE Settings SET garminChangesBefore=? WHERE id=1', [nxt])
    db.commit()
    return total


EARLIEST = '2000-01-01'         # the full check lists Garmin from here: before any activity it can hold (the sync skips anything before 2005)


def full(db, api, rider_id, today=None):
    """The whole history at once, for someone who tidied Garmin (Settings' Full re-sync): every activity, the oldest too. Commits. Returns check()'s
    counts, and 'full'."""
    return {**check(db, api, rider_id, EARLIEST, (today or date.today()).isoformat(), whole=True), 'full': True}


def describe(res):
    """One line for the task log."""
    bits = [f"{res[k]} {label}" for k, label in (('deleted', 'deleted in Garmin'), ('edited', 'renamed or given a new sport'),
                                                 ('recordings', 'with a changed recording')) if res[k]]
    line = ('Flagged for review: ' + ', '.join(bits) + '.') if bits else 'Nothing changed in Garmin.'
    if res.get('imported') or res.get('failed'):
        line += f" Brought in {res['imported']} strength, yoga or other gym activit{'ies' if res['imported'] != 1 else 'y'} an older sync skipped" + \
                (f" ({res['failed']} couldn't be read: tried again next time)." if res['failed'] else '.')
    if res.get('missing'):
        n = res['missing']
        line += f" {n} other activit{'ies' if n != 1 else 'y'} in Garmin {'are' if n != 1 else 'is'}n't here: listed to bring in or leave out."
    if res.get('deleted_here'):
        n = res['deleted_here']
        line += f" {n} you deleted here {'are' if n != 1 else 'is'} still in Garmin: listed to bring back."
    if res.get('whole'):
        line = f"Checked all {res['listed']} activities in Garmin. " + line
    elif res.get('full') and res['listed']:
        line += " Garmin's count of your activities didn't match its list, so ones older than the oldest listed weren't judged."
    if res['suspect']:
        line += (" None of your Garmin activities were in Garmin's list: signed in to another account? None were taken as deleted." if res.get('whole') else
                 " Many activities were missing from Garmin's list at once, so none were taken as deleted.")
    return line


def pending(db, rider_id=None):
    """The changes still to review, newest first, each with `parked`: other recordings set aside behind it."""
    ensure_schema(db)
    from services import duplicates
    duplicates.ensure_schema(db)
    rows = db.execute(f"""SELECT c.*, a.startDateLocal, a.distance, a.sportType,
                                 (SELECT COUNT(*) FROM ActivityDuplicate d WHERE d.primaryId=c.rideId AND d.status='parked') AS parked
                          FROM GarminChange c JOIN Activity a ON a.id = c.rideId
                          WHERE c.status='pending' {'AND c.riderId=?' if rider_id else ''}
                          ORDER BY c.kind, a.startDateLocal DESC""", [rider_id] if rider_id else []).fetchall()
    return [dict(r, diffs=json.loads(r['diffs'] or '[]')) for r in rows]


def for_ride(db, ride_id):
    """The pending change for one activity (its page shows it), or None."""
    ensure_schema(db)
    r = db.execute("SELECT * FROM GarminChange WHERE rideId=? AND status='pending'", [ride_id]).fetchone()
    return dict(r, diffs=json.loads(r['diffs'] or '[]')) if r else None


def resolve(db, ride_id, choice):
    """Settle one flag. Deleted in Garmin: 'keep' (never flagged again) or 'delete' (the usual delete). Renamed or new sport: 'garmin' (take Garmin's)
    or 'keep'; either way Garmin's values become the baseline, so the same change isn't flagged again. Returns 'deleted', 'changed' or None.
    Raises ValueError for a choice that doesn't fit the flag or a sport change that can't be made. Does not commit."""
    r = db.execute("SELECT * FROM GarminChange WHERE rideId=? AND status='pending'", [ride_id]).fetchone()
    if not r:
        return None
    if r['kind'] == 'deleted':
        if choice == 'keep':
            db.execute("UPDATE GarminChange SET status='kept' WHERE rideId=?", [ride_id])
            return None
        if choice != 'delete':
            raise ValueError('choose keep or delete')
        from services import duplicates
        db.execute('DELETE FROM GarminChange WHERE rideId=?', [ride_id])
        duplicates.delete_activity(db, ride_id)
        db.execute('DELETE FROM RideMemory WHERE rideId=?', [ride_id])
        return 'deleted'
    if choice not in ('garmin', 'keep'):
        raise ValueError("choose garmin or keep")
    changed = None
    if choice == 'garmin':
        from services import convert
        for d in json.loads(r['diffs'] or '[]'):
            if d['field'] == 'name':
                db.execute("UPDATE Activity SET name=?, updatedAt=datetime('now') WHERE id=?", [d['new'], ride_id])
            elif d['field'] == 'sport':
                convert.change_sport(db, None, ride_id, d['new'], discard_parked=True)     # its set-aside copies are the same session: not that sport either
            changed = 'changed'
    seen = _seen(db, r['garminId']) or {}
    now = json.loads(r['garmin'] or '{}')
    _accept(db, r['garminId'], {**seen, 'name': now.get('name', seen.get('name')), 'typeKey': now.get('typeKey', seen.get('typeKey'))})
    db.execute('DELETE FROM GarminChange WHERE rideId=?', [ride_id])
    return changed
