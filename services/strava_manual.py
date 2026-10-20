"""Manual entries in a database a Strava export was imported into before they were known. An import now marks a row of activities.csv with no
file as typed in (source 'manual', services/duplicates.is_manual), so the duplicate check never takes it for a recording, nor for a whole ride
another recording is a piece of: a manual entry is a top-up for distance the device missed (a flat battery, started late, stopped early). An
older import, Headwind's or upstream's, saved no such mark and upgrading has no export to read, so it's told from the row: a Strava id, no
track, and one duration (moving time = elapsed time; a recording with no track that Headwind couldn't read still has Strava's stops). Not a
virtual ride or one with no distance (a gym session), which have no stops to tell them by."""
import json


def _typed_in(row):
    if not str(row.get('id') or '').isdigit() or row.get('source'):
        return False
    if row.get('streams') not in (None, '', 'null', '{}'):
        return False
    if 'virtual' in str(row.get('sportType') or '').lower() or not (row.get('distance') or 0) > 0:
        return False                                    # Zwift and a gym session never stop either: one duration says nothing
    try:
        if json.loads(row.get('rawData') or '{}').get('manual') is False:         # Strava's API says whether it was
            return False
    except (TypeError, ValueError, AttributeError):
        pass
    el, mv = row.get('elapsedTime') or 0, row.get('movingTime') or 0
    return el > 0 and el == mv


def fix(db):
    """Run once (Settings.stravaManualDone): mark the manual entries saved without a mark, then bring back each one set aside behind an
    activity it isn't a copy of, as the import does (routes/import_rides._unpark_manual). Commits. Returns {'marked', 'restored': [(id, name)]},
    or None when it has run before."""
    from services import duplicates
    s = db.execute('SELECT stravaManualDone FROM Settings WHERE id=1').fetchone()
    if not s or s['stravaManualDone']:
        return None
    marked = 0
    for r in db.execute("SELECT id, sportType, distance, source, streams, rawData, elapsedTime, movingTime FROM Activity WHERE source IS NULL "
                        "AND (streams IS NULL OR streams IN ('', 'null', '{}'))").fetchall():
        if _typed_in(dict(r)):
            db.execute("UPDATE Activity SET source='manual' WHERE id=?", [r['id']])
            marked += 1
    restored = []
    for d in db.execute("SELECT id, primaryId, rowJson FROM ActivityDuplicate WHERE status='parked'").fetchall():
        try:
            row = json.loads(d['rowJson'])
        except (TypeError, ValueError):
            continue
        if not row or not _typed_in(row):
            continue
        row['source'] = 'manual'
        db.execute('UPDATE ActivityDuplicate SET rowJson=? WHERE id=?', [json.dumps(row), d['id']])
        marked += 1
        kept = db.execute('SELECT * FROM Activity WHERE id=?', [d['primaryId']]).fetchone()
        if kept and not duplicates.same_ride(row, kept):
            duplicates.keep_both(db, d['id'])
            restored.append((d['id'], row.get('name')))
    db.execute('UPDATE Settings SET stravaManualDone=1 WHERE id=1')
    db.commit()
    return {'marked': marked, 'restored': restored}
