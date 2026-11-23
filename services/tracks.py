"""Where each activity went, without reading its streams. An activity's streams are its whole recording as JSON (often most of a megabyte for a
ride), so anything that only needs to know where it went keeps a small summary here instead, one ActivityTrack row per activity:

  - its bounding box and the map cells it passes through (CELL degrees square), so a new segment is matched only against the activities that
    went near it (services/segments.scan_all_activities);
  - the simplified lines the heatmap draws (routes/heatmap.py): only the points needed to keep within SIMPLIFY_M of the recorded track, so
    straight roads take a few points and bends keep theirs (services/matched.py spaces them out evenly again to compare routes);
  - how far its GPS and time streams are out of step (services/reimport.out_of_step: the Import page lists those segments can't time).

A row is made from the streams the first time it is needed (fill), and triggers drop it when the streams change or the activity is deleted, so it
is never stale. An activity with no GPS gets a row with no box, so it is not read again."""
import json
from math import cos, isfinite, radians

SIMPLIFY_M = 10     # metres the live heatmap's line may stray from the recorded track
SIMPLIFY_HD_M = 5   # the same for the HD export's
VERSION = 2         # how the summaries are made: rows made another way (version 1: every nth point, 50 and 250 a track) are made again
_BATCH = 50       # activities read at a time while filling: streams are large
CELL = 0.005      # degrees: ~550 m north-south, ~350 m east-west in the UK; larger than any matcher tolerance (75 m) below MAX_CELL_LAT
MAX_CELL_LAT = 80 # nearer the poles a cell gets narrower than the tolerances, so cells aren't used there
_M_PER_DEG = 111_320.0


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ActivityTrack (
        activityId TEXT PRIMARY KEY,
        minLat REAL, maxLat REAL, minLng REAL, maxLng REAL,     -- NULL: no GPS track
        line   TEXT,                                            -- JSON [[lat, lng], ...] within SIMPLIFY_M of the track, at 5 places, or NULL
        lineHd TEXT,                                            -- the same within SIMPLIFY_HD_M
        cells  TEXT,                                            -- the cells (cell_of) of every point, space-separated; NULL: unknown
        outOfStep INTEGER,                                      -- how many more times than positions (stored before 0.7.7); 0 in step
        version INTEGER                                         -- VERSION when it was made
    )''')
    have = {r[1] for r in db.execute('PRAGMA table_info(ActivityTrack)')}
    for col in ('outOfStep', 'version'):
        if col not in have:
            db.execute(f'ALTER TABLE ActivityTrack ADD COLUMN {col} INTEGER')
    # Rows made before a column or another way of making them: made again from the streams (app._track_summaries, or the next fill)
    db.execute('DELETE FROM ActivityTrack WHERE version IS NOT ?', [VERSION])
    # Any write that can change an activity's track, or its id, drops the summary; fill() makes it again when it's next needed. AFTER INSERT
    # covers INSERT OR REPLACE, whose implicit delete fires no trigger. The streams are in ActivityStream (services/streams.py, made first).
    db.execute('''CREATE TRIGGER IF NOT EXISTS ActivityTrack_insert AFTER INSERT ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = NEW.id; END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS ActivityTrack_id AFTER UPDATE OF id ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = OLD.id; END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS ActivityTrack_delete AFTER DELETE ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = OLD.id; END''')
    for op, row in (('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')):
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS ActivityTrack_streams_{op.lower()} AFTER {op} ON ActivityStream
                       BEGIN DELETE FROM ActivityTrack WHERE activityId = {row}.activityId; END''')


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


def simplify(points, tol_m):
    """The points of a [lat, lng] track needed to keep the line through them within tol_m metres of every point (Ramer-Douglas-Peucker): the
    first and last, and each bend. Iterative, so a long track can't overflow the stack."""
    if len(points) < 3:
        return list(points)
    kx, ky = _M_PER_DEG * cos(radians(points[0][0])), _M_PER_DEG
    xs, ys = [p[1] * kx for p in points], [p[0] * ky for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    tol2 = tol_m * tol_m
    todo = [(0, len(points) - 1)]
    while todo:
        a, b = todo.pop()
        ax, ay, dx, dy = xs[a], ys[a], xs[b] - xs[a], ys[b] - ys[a]
        ll = dx * dx + dy * dy
        worst, at = tol2, None
        for i in range(a + 1, b):
            px, py = xs[i] - ax, ys[i] - ay
            t = 0.0 if not ll else max(0.0, min(1.0, (px * dx + py * dy) / ll))     # to the segment, not its line: a track can double back
            ex, ey = px - t * dx, py - t * dy
            d2 = ex * ex + ey * ey
            if d2 > worst:
                worst, at = d2, i
        if at is not None:
            keep[at] = True
            todo += [(a, at), (at, b)]
    return [p for p, k in zip(points, keep) if k]


def even(line, n):
    """n points evenly spaced along a [lat, lng] line by distance, first and last included (a simplified line has few points on straight roads
    and many on bends; something that counts points, like services/matched.py, wants them spread by distance)."""
    if len(line) < 2 or n < 2:
        return list(line)
    kx = cos(radians(line[0][0]))
    run = [0.0]
    for p, q in zip(line, line[1:]):
        run.append(run[-1] + ((q[0] - p[0]) ** 2 + ((q[1] - p[1]) * kx) ** 2) ** 0.5)
    if not run[-1]:
        return [line[0]] * n
    out, j = [], 0
    for k in range(n):
        at = run[-1] * k / (n - 1)
        while j < len(line) - 2 and run[j + 1] < at:
            j += 1
        seg = run[j + 1] - run[j]
        f = (at - run[j]) / seg if seg else 0.0
        out.append([line[j][0] + (line[j + 1][0] - line[j][0]) * f, line[j][1] + (line[j + 1][1] - line[j][1]) * f])
    return out


def _line_json(pts, tol_m):
    line = [[round(p[0], 5), round(p[1], 5)] for p in simplify(pts, tol_m)]
    return json.dumps(line, separators=(',', ':')) if len(line) >= 2 else None


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
    line, line_hd = _line_json(pts, SIMPLIFY_M), _line_json(pts, SIMPLIFY_HD_M)
    cells = cells_of(latlng) if len(pts) == len(latlng) else None
    cells = ' '.join(sorted(cells)) if cells is not None else None
    return min(lats), max(lats), min(lngs), max(lngs), line, line_hd, cells


def out_of_step(streams):
    """How many more points the time stream has than the GPS (records with no fix, kept by a parser before 0.7.7), or fewer as a negative; 0
    with no GPS. Streams as JSON text or parsed."""
    if isinstance(streams, (str, bytes)):
        try:
            streams = json.loads(streams or '{}')
        except Exception:
            return 0
    if not isinstance(streams, dict):
        return 0
    ll, tm = latlng_of(streams), (streams.get('time') or {}).get('data') or []
    return len(tm) - len(ll) if ll and tm else 0


def _row(activity_id, streams):
    """The ActivityTrack values for streams (JSON text, parsed, or None), in _INSERT's order."""
    if isinstance(streams, (str, bytes)):
        try:
            streams = json.loads(streams or '{}')
        except Exception:
            streams = {}
    return [activity_id, *summarize(latlng_of(streams)), out_of_step(streams), VERSION]


_INSERT = ('INSERT OR REPLACE INTO ActivityTrack (activityId, minLat, maxLat, minLng, maxLng, line, lineHd, cells, outOfStep, version) '
           'VALUES (?,?,?,?,?,?,?,?,?,?)')


def store(db, activity_id, streams):
    """Summarize streams (JSON text, parsed, or None) we already have in hand for an activity. Does not commit."""
    db.execute(_INSERT, _row(activity_id, streams))


def fill(db, on_batch=None):
    """Make the missing summaries, reading those activities' streams once. Returns how many it made. Commits. on_batch(done, total) is called
    before each batch's commit (app._track_summaries: the Tasks page's progress bar).
    Each batch is worked out before anything is written (about 12 ms a track), so the write lock is held only for the
    inserts: holding it through the work made every other write, a page's included, wait up to seconds while all were made again."""
    from services.streams import sql as streams_sql
    todo = [r[0] for r in db.execute('SELECT a.id FROM Activity a LEFT JOIN ActivityTrack t ON t.activityId = a.id WHERE t.activityId IS NULL')]
    for i in range(0, len(todo), _BATCH):
        ids = todo[i:i + _BATCH]
        rows = [_row(aid, streams) for aid, streams in
                db.execute(f"SELECT id, {streams_sql()} FROM Activity WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()]
        db.executemany(_INSERT, rows)
        if on_batch:
            on_batch(i + len(ids), len(todo))
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
