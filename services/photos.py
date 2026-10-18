"""Photos on an activity: one ActivityPhoto row per picture, the files beside the database in rideimg/ (like bikeimg/, services/gear.py).

Every picture is decoded and saved again as a JPEG, which drops its EXIF (where it was taken, the phone that took it), turned upright first so a
portrait shot doesn't come out on its side. Each gets a full-size copy (`act_<hex>.jpg`, up to FULL px) and a thumbnail (`act_<hex>_t.jpg`).
A picture that came from somewhere else keeps where it came from in sourceKey (a Strava export's 'media/<uuid>.jpg'), so importing the same
export again adds nothing twice."""
import io
import os
import re
import secrets

_NAME_RE = re.compile(r'^act_[a-f0-9]{12}(_t)?\.jpg$')
MAX_BYTES = 25 * 1024 * 1024
FULL = 1600
THUMB = 360
PHOTO_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
MAX_UPLOAD = 20                                         # pictures in one upload from the activity page


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ActivityPhoto (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        activityId TEXT NOT NULL,
        filename   TEXT NOT NULL,                       -- act_<hex>.jpg; the thumbnail is act_<hex>_t.jpg
        caption    TEXT,
        sourceKey  TEXT UNIQUE,                         -- where it came from ('strava:media/<uuid>.jpg'), or NULL
        position   INTEGER DEFAULT 0,
        createdAt  TEXT DEFAULT (datetime('now'))
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_photo_activity ON ActivityPhoto(activityId, position)')


def photo_dir(db_path):
    d = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'rideimg')
    os.makedirs(d, exist_ok=True)
    return d


def valid_name(name):
    return bool(_NAME_RE.match(name or ''))


def thumb_name(name):
    return name[:-4] + '_t.jpg'


def have(db, source_key):
    return bool(db.execute('SELECT 1 FROM ActivityPhoto WHERE sourceKey=?', [source_key]).fetchone())


def save(db, activity_id, data, db_path, caption=None, source_key=None, position=0):
    """Store a picture on an activity. Returns the new filename, or None when this source_key is already here. Raises ValueError for something
    that isn't a picture. Does not commit."""
    from PIL import Image, ImageOps
    if source_key and have(db, source_key):
        return None
    if len(data) > MAX_BYTES:
        raise ValueError('that picture is too large')
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img)              # upright, before the EXIF (and its orientation tag) goes
    except Exception:
        raise ValueError('that does not look like a picture')
    img = img.convert('RGB')                            # also drops EXIF (location etc.)
    name = f'act_{secrets.token_hex(6)}.jpg'
    d = photo_dir(db_path)
    full = img.copy()
    full.thumbnail((FULL, FULL), Image.LANCZOS)
    full.save(os.path.join(d, name), 'JPEG', quality=84, optimize=True)
    img.thumbnail((THUMB, THUMB), Image.LANCZOS)
    img.save(os.path.join(d, thumb_name(name)), 'JPEG', quality=80, optimize=True)
    db.execute('INSERT INTO ActivityPhoto (activityId, filename, caption, sourceKey, position) VALUES (?,?,?,?,?)',
               [str(activity_id), name, (caption or '').strip() or None, source_key, position])
    return name


def next_position(db, activity_id):
    """Where a photo added now goes: after the ones already on the activity."""
    return db.execute('SELECT COALESCE(MAX(position), -1) + 1 FROM ActivityPhoto WHERE activityId=?', [str(activity_id)]).fetchone()[0]


def for_activity(db, activity_id):
    return db.execute('SELECT id, filename, caption FROM ActivityPhoto WHERE activityId=? ORDER BY position, id', [str(activity_id)]).fetchall()


def _remove_files(db_path, names):
    d = photo_dir(db_path)
    for name in names:
        if valid_name(name):
            for f in (name, thumb_name(name)):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass


def delete(db, photo_id, activity_id, db_path):
    """Remove one photo from an activity. Returns True if it was there. Does not commit."""
    row = db.execute('SELECT filename FROM ActivityPhoto WHERE id=? AND activityId=?', [photo_id, str(activity_id)]).fetchone()
    if not row:
        return False
    db.execute('DELETE FROM ActivityPhoto WHERE id=?', [photo_id])
    _remove_files(db_path, [row[0]])
    return True


def delete_for(db, activity_ids, db_path):
    """Remove every photo on these activities (they are being deleted). Does not commit."""
    ids = [str(i) for i in activity_ids]
    names = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ','.join('?' * len(chunk))
        names += [r[0] for r in db.execute(f'SELECT filename FROM ActivityPhoto WHERE activityId IN ({q})', chunk)]
        db.execute(f'DELETE FROM ActivityPhoto WHERE activityId IN ({q})', chunk)
    _remove_files(db_path, names)


def move(db, from_id, to_id):
    """An activity's photos now belong to another one (it was parked as a duplicate of it). Does not commit."""
    db.execute('UPDATE ActivityPhoto SET activityId=? WHERE activityId=?', [str(to_id), str(from_id)])
