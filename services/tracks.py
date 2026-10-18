"""Where each activity went, without reading its streams. An activity's streams are its whole recording as JSON (often most of a megabyte for a
ride), so anything that only needs to know where it went keeps a small summary here instead, one ActivityTrack row per activity:

  - its bounding box and the map cells it passes through (CELL degrees square), so a new segment is matched only against the activities that
    went near it (services/segments.scan_all_activities);
  - the sampled lines the heatmap draws (routes/heatmap.py), worked out exactly as the heatmap used to on every request.

A row is made from the streams the first time it is needed (fill), and triggers drop it when the streams change or the activity is deleted, so it
is never stale. An activity with no GPS gets a row with no box, so it is not read again."""
import json
from math import cos, isfinite, radians

SAMPLE = 50       # points per activity for the live heatmap
SAMPLE_HD = 250   # points per activity for the HD export
_BATCH = 50       # activities read at a time while filling: streams are large
CELL = 0.005      # degrees: ~550 m north-south, ~350 m east-west in the UK; larger than any matcher tolerance (75 m) below MAX_CELL_LAT
MAX_CELL_LAT = 80 # nearer the poles a cell gets narrower than the tolerances, so cells aren't used there


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ActivityTrack (
        activityId TEXT PRIMARY KEY,
        minLat REAL, maxLat REAL, minLng REAL, maxLng REAL,     -- NULL: no GPS track
        line   TEXT,                                            -- JSON [[lat, lng], ...], SAMPLE points at 4 places, or NULL
        lineHd TEXT,                                            -- the same at SAMPLE_HD points and 5 places
        cells  TEXT                                             -- the cells (cell_of) of every point, space-separated; NULL: unknown
    )''')
    # Any write that can change an activity's track, or its id, drops the summary; fill() makes it again when it's next needed. AFTER INSERT
    # covers INSERT OR REPLACE, whose implicit delete fires no trigger.
    db.execute('''CREATE TRIGGER IF NOT EXISTS ActivityTrack_insert AFTER INSERT ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = NEW.id; END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS ActivityTrack_update AFTER UPDATE OF streams, id ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = OLD.id; END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS ActivityTrack_delete AFTER DELETE ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = OLD.id; END''')


def latlng_of(streams):
    """The [lat, lng] list from an activity's streams: JSON text or already parsed. [] when there is none or it doesn't parse."""
    if isinstance(streams, (str, bytes)):
        try:
            streams = json.loads(streams or '{}')
        except Exception:
            return []
    if not isinstance(streams, dict):
        return []
    return (streams.get('latlng') or {}).get('data') or []


def _sample(latlng, n, places):
    step = max(1, len(latlng) // n)
    return [[round(p[0], places), round(p[1], places)] for p in latlng[::step]]


def cell_of(lat, lng):
    return f'{int(lat // CELL)}:{int(lng // CELL)}'


def cells_near(points):
    """The cells any point within the matchers' tolerances of these points can be in: each point's cell and the eight around it. None when a point
    is too near a pole for cells to be safe."""
    out = set()
    for lat, lng in points:
        if abs(lat) > MAX_CELL_LAT:
            return None
        i, j = int(lat // CELL), int(lng // CELL)
        out.update(f'{i + di}:{j + dj}' for di in (-1, 0, 1) for dj in (-1, 0, 1))
    return out


def cells_of(latlng):
    """The set of cells a track's points are in, or None when that can't be trusted: a point that isn't a number pair (the box leaves it out,
    but a matcher could still see it), or one too near a pole."""
    try:
        if any(abs(p[0]) > MAX_CELL_LAT for p in latlng):
            return None
        return {f'{int(p[0] // CELL)}:{int(p[1] // CELL)}' for p in latlng}
    except (TypeError, IndexError, KeyError, ValueError, OverflowError):
        return None


def summarize(latlng):
    """(minLat, maxLat, minLng, maxLng, line, lineHd, cells) for a list of [lat, lng]; all None when there are fewer than two good points."""
    pts = [p for p in latlng if isinstance(p, (list, tuple)) and len(p) >= 2 and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))
           and isfinite(p[0]) and isfinite(p[1])]           # a point that isn't can never be within a tolerance of anything
    if len(pts) < 2:
        return None, None, None, None, None, None, None
    lats = [p[0] for p in pts]
    lngs = [p[1] for p in pts]
    try:
        line, line_hd = _sample(latlng, SAMPLE, 4), _sample(latlng, SAMPLE_HD, 5)
    except Exception:                                   # a bad point somewhere: the heatmap skipped such a track
        line = line_hd = None
    cells = cells_of(latlng) if len(pts) == len(latlng) else None
    cells = ' '.join(sorted(cells)) if cells is not None else None
    return (min(lats), max(lats), min(lngs), max(lngs),
            json.dumps(line, separators=(',', ':')) if line and len(line) >= 2 else None,
            json.dumps(line_hd, separators=(',', ':')) if line_hd and len(line_hd) >= 2 else None,
            cells)


def store(db, activity_id, streams):
    """Summarize streams (JSON text, parsed, or None) we already have in hand for an activity. Does not commit."""
    db.execute('INSERT OR REPLACE INTO ActivityTrack (activityId, minLat, maxLat, minLng, maxLng, line, lineHd, cells) VALUES (?,?,?,?,?,?,?,?)',
               [activity_id, *summarize(latlng_of(streams))])


def fill(db):
    """Make the missing summaries, reading those activities' streams once. Returns how many it made. Commits."""
    todo = [r[0] for r in db.execute('SELECT a.id FROM Activity a LEFT JOIN ActivityTrack t ON t.activityId = a.id WHERE t.activityId IS NULL')]
    for i in range(0, len(todo), _BATCH):
        ids = todo[i:i + _BATCH]
        for aid, streams in db.execute(f"SELECT id, streams FROM Activity WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall():
            store(db, aid, streams)
        db.commit()
    return len(todo)


def box_of(points, margin_m=0.0):
    """(minLat, maxLat, minLng, maxLng) around [lat, lng] points, widened by margin_m on every side, or None. None too when any point isn't a
    finite number pair, so a box is never smaller than what the matchers would look at."""
    if not points:
        return None
    lats, lngs = [float(p[0]) for p in points], [float(p[1]) for p in points]
    if not all(map(isfinite, lats)) or not all(map(isfinite, lngs)):
        return None
    d_lat = margin_m / 111_000.0
    d_lng = margin_m / (111_000.0 * max(0.01, cos(radians(max(abs(min(lats)), abs(max(lats))) + d_lat))))
    return min(lats) - d_lat, max(lats) + d_lat, min(lngs) - d_lng, max(lngs) + d_lng


def overlaps(a, b):
    """Do two (minLat, maxLat, minLng, maxLng) boxes overlap? A missing box overlaps nothing."""
    if not a or not b or None in a or None in b:
        return False
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]
