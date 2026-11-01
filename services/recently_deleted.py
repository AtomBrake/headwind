"""Recently deleted: an activity deleted here is kept whole for DAYS, so it can be put back as it was.

The bin is ActivityDuplicate rows with status 'deleted', the same rows that have always remembered a deleted id so no sync brings it back
(duplicates.is_deleted). A row in the bin has the whole Activity row in rowJson, as a copy set aside does (duplicates.park); a bare tombstone has
'{}' (one purged from the bin, one deleted before the bin, a Garmin activity left out on the Import page). Its photos stay on disk and in
ActivityPhoto under its id, and the copies set aside behind it stay parked behind it, so they come back with it. Its segment times, best times
and the rest are worked out again when it is restored (duplicates.rebuild_derived), as they would be for any activity that arrives.

After DAYS, purge() cuts each one down to the bare tombstone and deletes its photo files then."""
import json
import logging

log = logging.getLogger(__name__)
DAYS = 30
_BINNED = "status='deleted' AND rowJson<>'{}'"


def put(db, row):
    """Put a deleted activity in the bin: `row` is its Activity row as it was, read before the delete. One the rider kept apart from another
    recording ('kept_both') keeps that other id in primaryId, so the two are still kept apart when it is restored. Does not commit."""
    from services import duplicates
    duplicates.ensure_schema(db)
    apart = db.execute("SELECT primaryId FROM ActivityDuplicate WHERE id=? AND status='kept_both'", [row['id']]).fetchone()
    db.execute("INSERT OR REPLACE INTO ActivityDuplicate (id, primaryId, riderId, source, reason, status, rowJson) VALUES (?,?,?,?,?,?,?)",
               [row['id'], apart[0] if apart else '', row['riderId'], 'deleted', 'deleted by you', 'deleted', json.dumps(dict(row))])


def listing(db):
    """What's in the bin, most recently deleted first: id, riderId, riderName, deletedAt, and the date, name, sport and distance it had. Only these
    are read out of rowJson, not its streams. One that is live again (imported from a file since) isn't listed."""
    from services import duplicates
    duplicates.ensure_schema(db)
    return [dict(r) for r in db.execute(f"""
        SELECT d.id, d.riderId, r.name AS riderName, d.parkedAt AS deletedAt, date(d.parkedAt, '+{DAYS} days') AS until,
               json_extract(d.rowJson, '$.startDateLocal') AS startDateLocal, json_extract(d.rowJson, '$.name') AS name,
               json_extract(d.rowJson, '$.sportType') AS sportType, json_extract(d.rowJson, '$.distance') AS distance
        FROM ActivityDuplicate d LEFT JOIN Rider r ON r.id = d.riderId
        WHERE d.{_BINNED} AND d.id NOT IN (SELECT id FROM Activity) ORDER BY d.parkedAt DESC, d.id""")]


def restore(db, act_id):
    """Put an activity in the bin back as it was: its row (notes, gear, commute, AI analysis), photos and the copies set aside behind it; then
    what's derived from it is worked out again. A bike or kit deleted since is taken off it, and it gets the default instead, as a new activity
    would. If another recording of the same session arrived while it was in the bin, the better of the two is kept and the other set aside
    (duplicates.resolve). Returns the id that now stands for it (its own, or the one it was set aside behind), or None when there is nothing to
    restore. Commits."""
    from services import duplicates, gear, ingest
    from services.sports import is_ride
    d = db.execute(f'SELECT primaryId FROM ActivityDuplicate WHERE id=? AND {_BINNED}', [act_id]).fetchone()
    if not d or db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():
        return None
    _, row = duplicates._restore(db, act_id)
    if d['primaryId']:                                  # kept apart from another recording before it was deleted: still kept apart
        db.execute("UPDATE ActivityDuplicate SET status='kept_both' WHERE id=?", [act_id])
    else:
        db.execute('DELETE FROM ActivityDuplicate WHERE id=?', [act_id])
    lost = False
    for col, table in (('bikeId', 'Bike'), ('kitId', 'Kit')):
        if row.get(col) and not db.execute(f'SELECT 1 FROM {table} WHERE id=?', [row[col]]).fetchone():
            db.execute(f'UPDATE Activity SET {col}=NULL WHERE id=?', [act_id])
            lost = True
    duplicates.rebuild_derived(db, act_id)
    dup = duplicates.resolve(db, act_id)
    kept = (dup or {}).get('kept', act_id)
    gear.on_ride_added(db, kept, stamp=lost)            # also attaches a phone's sensor recording, let go of when it was deleted
    ingest.after_ride_added(db, kept)
    db.commit()
    if kept == act_id and row.get('aiKudos') and is_ride(row.get('sportType')):
        from services.context import save_ride_memory
        save_ride_memory(row, row['aiKudos'])           # the coach's memory of it (commits)
    log.warning('Recently deleted: %s restored%s', act_id, f', set aside behind {kept}, the same session' if kept != act_id else '')
    return kept


def empty(db, ids, db_path):
    """Cut these bin entries down to the bare tombstone now: their photos (files too) and the copies set aside behind them go; the id stays
    remembered, so no sync brings it back. Returns how many. Does not commit."""
    from services import photos
    done = []
    for act_id in ids:
        if not db.execute(f'SELECT 1 FROM ActivityDuplicate WHERE id=? AND {_BINNED}', [act_id]).fetchone():
            continue
        if not db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():     # one live again (a file imported since) keeps its own
            db.execute("UPDATE ActivityDuplicate SET rowJson='{}', status='discarded' WHERE primaryId=? AND status='parked' AND id<>?", [act_id, act_id])
            db.execute("UPDATE ActivityDuplicate SET primaryId='' WHERE primaryId=? AND status='kept_both'", [act_id])
            photos.delete_for(db, [act_id], db_path)
            db.execute('DELETE FROM BestEffort WHERE activityId=?', [act_id])     # a run's from a Strava export, which workouts.forget leaves
        db.execute("UPDATE ActivityDuplicate SET rowJson='{}', primaryId='' WHERE id=? AND status='deleted'", [act_id])
        done.append(act_id)
    return len(done)


def purge(db, db_path):
    """Everything deleted more than DAYS ago: emptied (empty). Run at start-up and hourly. Commits. Returns how many."""
    from services import duplicates
    duplicates.ensure_schema(db)
    ids = [r[0] for r in db.execute(f"SELECT id FROM ActivityDuplicate WHERE {_BINNED} AND parkedAt < datetime('now', '-{DAYS} days')")]
    n = empty(db, ids, db_path)
    db.commit()
    if n:
        log.warning('Recently deleted: %d activit%s deleted more than %d days ago emptied from the bin', n, 'y' if n == 1 else 'ies', DAYS)
    return n
