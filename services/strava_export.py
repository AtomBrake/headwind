"""A rider's Strava export, kept after it's imported so it can be imported again without uploading it: many fixes only reach activities already
saved when the export is read again (photos, segments, Strava's own figures, files an older import couldn't read), and the export can be GBs.

One per rider, the latest (Strava's export is always the whole history): strava_exports/<riderId>.zip beside the database, like rideimg/
(services/photos.py), so it lives in the Docker data volume. Uploads are saved into the same folder first (UPLOAD_PREFIX), so keeping one is a
rename, not a copy. Not in the backup zip: the rider can download it from Strava again, and it would double the backup. A restored backup's
StravaExport rows whose file isn't here are dropped when next read (kept()).

Also which riders should import their export again (advice()): REIMPORT_ADVISED, kept by hand, against StravaExportRead, which outlives the kept
file (the rider can upload the export again)."""
import logging
import os
import time

log = logging.getLogger(__name__)

UPLOAD_PREFIX = '.upload-'
_STALE_UPLOAD_SECS = 86400          # an upload's file left behind by a crash or restart mid-import

# Releases whose fixes reach activities already saved only when the Strava export is imported again, each with the line the Import page shows.
# Add one when a release makes that worth asking for: not for every change to how files are read (reimport.reader_version() already makes the
# next import read every file again), only when a rider would want to know. Append only, never reorder or remove: a rider's place is the length
# of this list when they last imported their export.
REIMPORT_ADVISED = [
    # ('0.7.23-beta', "Strava's own moving time for runs and walks"),
]


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS StravaExport (
        riderId       INTEGER PRIMARY KEY,
        keptAt        TEXT NOT NULL,             -- when it was uploaded
        sizeBytes     INTEGER,
        activities    INTEGER,                   -- rows in its activities.csv
        readAt        TEXT,                      -- when it was last imported: the upload, or Import again
        readerVersion TEXT,                      -- services/reimport.reader_version() then: a different one now reads it differently
        segments      INTEGER DEFAULT 0,         -- the options it was last imported with
        photos        INTEGER DEFAULT 1
    )''')
    new = not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='StravaExportRead'").fetchone()
    db.execute('''CREATE TABLE IF NOT EXISTS StravaExportRead (
        riderId   INTEGER PRIMARY KEY,
        advised   INTEGER NOT NULL DEFAULT 0,    -- len(REIMPORT_ADVISED) when the rider's export was last imported
        dismissed INTEGER NOT NULL DEFAULT 0,    -- len(REIMPORT_ADVISED) when the advice was put off: shown again for a newer line only
        readAt    TEXT
    )''')
    # Riders who imported an export before it was recorded count as before every line. database.py makes StravaBike, StravaKit and ImportSeen first.
    if new:
        db.execute("""INSERT OR IGNORE INTO StravaExportRead (riderId)
                      SELECT riderId FROM StravaExport UNION SELECT riderId FROM StravaBike UNION SELECT riderId FROM StravaKit
                      UNION SELECT a.riderId FROM ImportSeen s JOIN Activity a ON a.id = s.activityId WHERE s.sourceKey LIKE 'strava:%'""")


def export_dir(db_path):
    d = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'strava_exports')
    os.makedirs(d, exist_ok=True)
    return d


def path_for(db_path, rider_id):
    return os.path.join(export_dir(db_path), f'{int(rider_id)}.zip')


def clear_stale_uploads(db_path):
    """Delete upload files a crash or restart left behind (over a day old)."""
    d = export_dir(db_path)
    for name in os.listdir(d):
        p = os.path.join(d, name)
        try:
            if name.startswith(UPLOAD_PREFIX) and time.time() - os.path.getmtime(p) > _STALE_UPLOAD_SECS:
                os.unlink(p)
                log.info('Deleted an upload left behind: %s', name)
        except OSError:
            pass


def keep(db, db_path, rider_id, upload_path, activities, segments, photos):
    """Move an imported export (upload_path, in export_dir) to the rider's place, replacing any older one, and record it. Commits."""
    from services.reimport import reader_version
    dest = path_for(db_path, rider_id)
    os.replace(upload_path, dest)
    db.execute('''INSERT OR REPLACE INTO StravaExport (riderId, keptAt, sizeBytes, activities, readAt, readerVersion, segments, photos)
                  VALUES (?, datetime('now'), ?, ?, datetime('now'), ?, ?, ?)''',
               [rider_id, os.path.getsize(dest), activities, reader_version(), int(bool(segments)), int(bool(photos))])
    db.commit()
    log.info('Strava export kept for rider %s: %d bytes, %s activities', rider_id, os.path.getsize(dest), activities)


def read_again(db, rider_id, activities, segments, photos):
    """Note that the kept export was imported again. Commits."""
    from services.reimport import reader_version
    db.execute("""UPDATE StravaExport SET readAt=datetime('now'), readerVersion=?, activities=COALESCE(?, activities), segments=?, photos=?
                  WHERE riderId=?""", [reader_version(), activities, int(bool(segments)), int(bool(photos)), rider_id])
    db.commit()


def kept(db, db_path):
    """[{riderId, riderName, keptAt, sizeBytes, activities, readAt, segments, photos, stale}] for the Import page. stale: this version of Headwind
    reads exports differently from the one that last imported it. A row whose file is gone (a restored backup) or whose rider is gone is dropped,
with its file. Commits if it drops one."""
    from services.reimport import reader_version
    out, gone = [], []
    for r in db.execute('SELECT e.*, r.name AS riderName FROM StravaExport e LEFT JOIN Rider r ON r.id = e.riderId ORDER BY e.riderId').fetchall():
        if r['riderName'] is None or not os.path.isfile(path_for(db_path, r['riderId'])):
            gone.append(r['riderId'])
            continue
        out.append({**dict(r), 'stale': r['readerVersion'] != reader_version()})
    for g in gone:                                      # its rider deleted some other way: the file goes too
        forget(db, db_path, g)
    if gone:
        db.commit()
    return out


def forget(db, db_path, rider_id):
    """Delete a rider's kept export and its row (Delete on the Import page, or the rider deleted). Does not commit."""
    p = path_for(db_path, rider_id)
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass
    db.execute('DELETE FROM StravaExport WHERE riderId=?', [rider_id])


def note_read(db, rider_id):
    """A Strava export of the rider's was imported to the end (uploaded, kept or not, or imported again): nothing advised so far is left. Commits."""
    db.execute('''INSERT INTO StravaExportRead (riderId, advised, readAt) VALUES (?, ?, datetime('now'))
                  ON CONFLICT(riderId) DO UPDATE SET advised=excluded.advised, readAt=excluded.readAt''', [rider_id, len(REIMPORT_ADVISED)])
    db.commit()


def dismiss(db, rider_id):
    """Put off the advice to import the export again until a newer release adds to it. Commits."""
    db.execute('UPDATE StravaExportRead SET dismissed=? WHERE riderId=?', [len(REIMPORT_ADVISED), rider_id])
    db.commit()


def advice(db, db_path):
    """[{riderId, riderName, readAt, kept, reasons: [(release, reason)]}]: riders whose export was last imported before a release in
    REIMPORT_ADVISED, and who haven't put it off since. kept: the export is here to import again without uploading it."""
    n = len(REIMPORT_ADVISED)
    if not n:
        return []
    rows = db.execute('''SELECT a.riderId, r.name AS riderName, a.readAt, a.advised, e.riderId IS NOT NULL AS kept
                          FROM StravaExportRead a JOIN Rider r ON r.id = a.riderId LEFT JOIN StravaExport e ON e.riderId = a.riderId
                          WHERE a.advised < ? AND a.dismissed < ? ORDER BY r.isDefault DESC, r.name''', [n, n]).fetchall()
    return [{'riderId': r['riderId'], 'riderName': r['riderName'], 'readAt': r['readAt'],
             'kept': bool(r['kept']) and os.path.isfile(path_for(db_path, r['riderId'])),
             'reasons': REIMPORT_ADVISED[r['advised']:]} for r in rows]


def forget_read(db, rider_id):
    """The rider is being deleted: what they last imported goes too (forget() takes the kept export). Does not commit."""
    db.execute('DELETE FROM StravaExportRead WHERE riderId=?', [rider_id])
