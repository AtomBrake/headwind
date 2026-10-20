"""A rider's Strava export, kept after it's imported so it can be imported again without uploading it: many fixes only reach activities already
saved when the export is read again (photos, segments, Strava's own figures, files an older import couldn't read), and the export can be GBs.

One per rider, the latest (Strava's export is always the whole history): strava_exports/<riderId>.zip beside the database, like rideimg/
(services/photos.py), so it lives in the Docker data volume. Uploads are saved into the same folder first (UPLOAD_PREFIX), so keeping one is a
rename, not a copy. Not in the backup zip: the rider can download it from Strava again, and it would double the backup. A restored backup's
StravaExport rows whose file isn't here are dropped when next read (kept())."""
import logging
import os
import time

log = logging.getLogger(__name__)

UPLOAD_PREFIX = '.upload-'
_STALE_UPLOAD_SECS = 86400          # an upload's file left behind by a crash or restart mid-import


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
