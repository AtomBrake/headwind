"""Privacy zones: places (home, work) whose surroundings are cut out of every track that leaves Headwind. Settings → Sharing → Privacy zones.

A zone is a point and a radius the rider chooses (RADII). What's cut is a circle around a centre moved a random way off the point, made larger
by as much as it was moved, so everything within the radius of the point is always inside it: nothing within 400 m of home is shown with a
400 m zone, and more on one side than the other. Many tracks cut at a circle's edge draw the circle, and its centre is then easy to find;
moved off the point, it doesn't lead to the door. The way and how far (bearing, shift: SHIFT of the radius) are drawn once, when the zone is
made, and kept, so a new radius doesn't give a second circle to compare with the first.

Where it's applied, each with the rider whose activity or link it is:
  - a friend's feed (routes/friends.feed): the streams (every stream's samples at the positions inside, so they stay in step), the start
    point, and segments that start or end inside;
  - a live tracking link (services/live_share.view), besides the start of its own track;
  - the tracks sent to Home Assistant (services/mqtt._ride_route_payloads, services/run_stats.payloads);
  - the heatmap's HD export (routes/heatmap.data with hd=1), whose lines are cut at a zone's edge into pieces (Hider.pieces).
Never on the rider's own pages: they're the rider's. A zone made, changed or removed moves on the updatedAt of the rider's activities that
go near it (touch_near), so a friend's Headwind fetches them again, cut the new way.

The zones themselves say where home is: the troubleshooting copy (services/troubleshooting_copy.py) leaves them out."""
import math
import random
import time

from services import tracks

RADII = (200, 400, 600, 800, 1000, 1600)    # metres the rider can choose
DEFAULT_RADIUS = 400
SHIFT = (0.2, 0.5)                          # how far the circle's centre is moved off the point, as a share of the radius
MAX_ZONES = 10
MAX_NAME = 40
STEP_M = 20                                 # a simplified line is cut at a zone's edge to within this
_M_PER_DEG = 111_320.0
SUGGEST_MIN = 5                             # a start place offered as a zone once this many activities began there
SUGGEST_CELL = 0.003                        # degrees (~330 m north-south): activities that start within this are counted together


def ensure_schema(db):
    """Does not commit."""
    db.execute('''
        CREATE TABLE IF NOT EXISTS PrivacyZone (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId     INTEGER NOT NULL,
            name        TEXT NOT NULL,
            lat         REAL NOT NULL,              -- the point the rider chose
            lng         REAL NOT NULL,
            radiusM     INTEGER NOT NULL,           -- nothing within this of the point is shown
            bearing     REAL NOT NULL,              -- degrees: the way the hidden circle's centre is moved off the point
            shift       REAL NOT NULL,              -- and how far, as a share of the radius (SHIFT)
            createdAt   REAL NOT NULL
        )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_privacyzone_rider ON PrivacyZone(riderId)')


def _metres(a, b):
    kx = _M_PER_DEG * math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * _M_PER_DEG, (a[1] - b[1]) * kx)


def _moved(lat, lng, bearing_deg, metres):
    b = math.radians(bearing_deg)
    return (lat + metres * math.cos(b) / _M_PER_DEG,
            lng + metres * math.sin(b) / (_M_PER_DEG * max(math.cos(math.radians(lat)), 1e-6)))


def circle(zone):
    """(lat, lng, radius in metres) of what a zone hides."""
    d = zone['shift'] * zone['radiusM']
    lat, lng = _moved(zone['lat'], zone['lng'], zone['bearing'], d)
    return lat, lng, zone['radiusM'] + d


def _public(row):
    lat, lng, r = circle(row)
    return {'id': row['id'], 'name': row['name'], 'lat': row['lat'], 'lng': row['lng'], 'radius': row['radiusM'],
            'hidden': {'lat': round(lat, 6), 'lng': round(lng, 6), 'radius': round(r)}}


def listing(db, rider_id):
    """The rider's zones, by name: [{id, name, lat, lng, radius, hidden: {lat, lng, radius}}]."""
    return [_public(r) for r in _rows(db, rider_id)]


def _rows(db, rider_id):
    return db.execute('SELECT * FROM PrivacyZone WHERE riderId=? ORDER BY name COLLATE NOCASE, id', [rider_id]).fetchall()


class Hider:
    """The zones of one rider, for asking of points and lines whether they're inside. Falsy when there are none, so a caller can skip the work."""

    def __init__(self, zones):
        self.circles = []
        for z in zones:
            lat, lng, r = circle(z)
            kx = _M_PER_DEG * math.cos(math.radians(lat))
            self.circles.append((lat, lng, r, kx, r / _M_PER_DEG, r / max(kx, 1e-6)))

    def __bool__(self):
        return bool(self.circles)

    def inside(self, lat, lng):
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return False
        for clat, clng, r, kx, dlat, dlng in self.circles:
            if abs(lat - clat) <= dlat and abs(lng - clng) <= dlng and \
                    ((lat - clat) * _M_PER_DEG) ** 2 + ((lng - clng) * kx) ** 2 < r * r:
                return True
        return False

    def near_box(self, min_lat, max_lat, min_lng, max_lng):
        """Whether a bounding box comes within any zone (so a track inside it may need cutting). True when the box is unknown."""
        if None in (min_lat, max_lat, min_lng, max_lng):
            return True
        return any(min_lat - dlat <= clat <= max_lat + dlat and min_lng - dlng <= clng <= max_lng + dlng
                   for clat, clng, r, kx, dlat, dlng in self.circles)

    def cells(self):
        """The map cells (services/tracks.cell_of) any part of a zone is in, or None when one is too near a pole for cells."""
        if not hasattr(self, '_cells'):
            self._cells = self._cells_of()
        return self._cells

    def may_cross(self, box, cells):
        """Whether a track with this box ([minLat, maxLat, minLng, maxLng]) and these cells (ActivityTrack.cells, space-separated) may go
        into a zone: True unless one of them says it can't."""
        if box is not None and not self.near_box(*box):
            return False
        mine = self.cells()
        return mine is None or cells is None or not mine.isdisjoint(cells.split())

    def _cells_of(self):
        out = set()
        for clat, clng, r, kx, dlat, dlng in self.circles:
            if abs(clat) + dlat > tracks.MAX_CELL_LAT:
                return None
            for i in range(int((clat - dlat) // tracks.CELL), int((clat + dlat) // tracks.CELL) + 1):
                for j in range(int((clng - dlng) // tracks.CELL), int((clng + dlng) // tracks.CELL) + 1):
                    out.add(f'{i}:{j}')
        return out

    def _near(self, a, b, margin):
        """Whether the straight line from a to b comes within margin metres of a zone."""
        for clat, clng, r, kx, dlat, dlng in self.circles:
            ax, ay = (a[1] - clng) * kx, (a[0] - clat) * _M_PER_DEG
            bx, by = (b[1] - clng) * kx, (b[0] - clat) * _M_PER_DEG
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = 0.0 if not ll else max(0.0, min(1.0, -(ax * dx + ay * dy) / ll))
            ex, ey = ax + t * dx, ay + t * dy
            if ex * ex + ey * ey < (r + margin) ** 2:
                return True
        return False

    def pieces(self, line, step=STEP_M):
        """A [lat, lng] line (a simplified one, whose points can be far apart) as the pieces of it outside every zone. A stretch that comes
        near a zone is given a point every `step` metres first, so the line is cut at the zone's edge (to within `step`) rather than at
        the nearest point it happened to keep. Pieces of fewer than two points are left out."""
        out, cur = [], []

        def take(p):
            nonlocal cur
            if self.inside(p[0], p[1]):
                if len(cur) >= 2:
                    out.append(cur)
                cur = []
            else:
                cur.append(p)

        for i, p in enumerate(line):
            if i and self._near(line[i - 1], p, step):
                a = line[i - 1]
                n = int(_metres(a, p) // step)
                for k in range(1, n + 1):
                    f = k / (n + 1)
                    take([round(a[0] + (p[0] - a[0]) * f, 5), round(a[1] + (p[1] - a[1]) * f, 5)])
            take(p)
        if len(cur) >= 2:
            out.append(cur)
        return out

    def keep(self, latlng):
        """For each position of a recorded track ([lat, lng] or not a pair), whether it's shown: a position inside a zone isn't."""
        return [not (isinstance(p, (list, tuple)) and len(p) >= 2 and self.inside(p[0], p[1])) for p in latlng]

    def points(self, latlng):
        """A recorded track's positions without those inside a zone. Recorded points are close together, so none is checked for between."""
        return [p for p, k in zip(latlng, self.keep(latlng)) if k]

    def streams(self, streams):
        """An activity's streams ({name: {data: [...]}}) with every sample taken at a position inside a zone taken out of each stream as
        long as latlng, so they stay in step. A stream of another length (a recording out of step) keeps its samples. None when nothing
        was inside, so the caller can send the streams as they were."""
        if not isinstance(streams, dict):
            return None
        ll = (streams.get('latlng') or {}).get('data') if isinstance(streams.get('latlng'), dict) else None
        if not ll:
            return None
        keep = self.keep(ll)
        if all(keep):
            return None
        n = len(ll)
        out = {}
        for name, s in streams.items():
            data = s.get('data') if isinstance(s, dict) else None
            if isinstance(data, list) and len(data) == n:
                out[name] = {**s, 'data': [v for v, k in zip(data, keep) if k]}
            else:
                out[name] = s
        return out

    def start(self, lat, lng, latlng=None):
        """An activity's start point as shown: as it is outside every zone; inside one, the first shown position of its track, or none."""
        if lat is None or lng is None or not self.inside(lat, lng):
            return lat, lng
        for p in latlng or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2 and p[0] is not None and p[1] is not None and not self.inside(p[0], p[1]):
                return p[0], p[1]
        return None, None


def hider(db, rider_id):
    """The rider's zones as a Hider (empty, and falsy, when they have none)."""
    if rider_id is None:
        return Hider([])
    return Hider(_rows(db, rider_id))


def hiders(db):
    """{riderId: Hider} for every rider with zones."""
    by = {}
    for z in db.execute('SELECT * FROM PrivacyZone').fetchall():
        by.setdefault(z['riderId'], []).append(z)
    return {rid: Hider(zs) for rid, zs in by.items()}


def _checked(name, lat, lng, radius):
    name = ' '.join(str(name or '').split())[:MAX_NAME] or 'Home'
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError('Choose the place on the map, or give it as a latitude and longitude ("51.5072, -0.1276").')
    if not (-85 <= lat <= 85 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError(f'{lat}, {lng} is not a place on the map.')
    try:
        radius = int(radius)
    except (TypeError, ValueError):
        radius = DEFAULT_RADIUS
    if radius not in RADII:
        raise ValueError('Choose one of the sizes offered.')
    return name, round(lat, 6), round(lng, 6), radius


def radius_label(m):
    """'400 m', with miles beside it for a rider on miles: '400 m (0.25 mi)'."""
    from services import units
    return f'{m:,} m' if units.current() == 'metric' else f'{m:,} m ({units.fmt_dist(m, places=2)})'


def page(db, rider_id):
    """What Settings → Privacy zones shows: the zones, the sizes to choose from, and the start places to offer."""
    rows = _rows(db, rider_id)
    return {'zones': [_public(r) for r in rows], 'radii': [{'m': m, 'label': radius_label(m)} for m in RADII], 'default': DEFAULT_RADIUS,
            'suggest': suggestions(db, rider_id, zones=Hider(rows)), 'max': MAX_ZONES}


def parse_place(text):
    """'lat, lng' as typed or pasted (a map app's "51.50722, -0.12750"), as (lat, lng) strings, or (None, None)."""
    parts = [p for p in str(text or '').replace(';', ',').replace(' ', ',').split(',') if p]
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def touch_near(db, rider_id, zones):
    """Move on the updatedAt of the rider's activities whose track goes near any of these zones (PrivacyZone rows), so friends fetch them
    again (routes/friends.feed's manifest). Returns how many. Does not commit."""
    h = Hider(zones)
    if not h:
        return 0
    tracks.fill(db)
    rows = db.execute('SELECT a.id, t.minLat, t.maxLat, t.minLng, t.maxLng, t.cells FROM Activity a JOIN ActivityTrack t ON t.activityId = a.id '
                      'WHERE a.riderId=? AND t.minLat IS NOT NULL', [rider_id]).fetchall()
    # By the cells a track passes through as well as its box: a loop whose box takes in home needn't go near it
    ids = [r['id'] for r in rows if h.may_cross([r['minLat'], r['maxLat'], r['minLng'], r['maxLng']], r['cells'])]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        db.execute(f"UPDATE Activity SET updatedAt=strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id IN ({','.join('?' * len(part))})", part)
    return len(ids)


def _row(db, rider_id, zone_id):
    return db.execute('SELECT * FROM PrivacyZone WHERE id=? AND riderId=?', [zone_id, rider_id]).fetchone()


def add(db, rider_id, name, lat, lng, radius=DEFAULT_RADIUS, now=None, rng=random):
    """Add a zone. Returns it as listing() gives it. Raises ValueError with why not, fit to show. Commits."""
    ensure_schema(db)
    name, lat, lng, radius = _checked(name, lat, lng, radius)
    if db.execute('SELECT COUNT(*) FROM PrivacyZone WHERE riderId=?', [rider_id]).fetchone()[0] >= MAX_ZONES:
        raise ValueError(f'{MAX_ZONES} zones is the most.')
    cur = db.execute('INSERT INTO PrivacyZone (riderId, name, lat, lng, radiusM, bearing, shift, createdAt) VALUES (?,?,?,?,?,?,?,?)',
                     [rider_id, name, lat, lng, radius, rng.uniform(0, 360), rng.uniform(*SHIFT), time.time() if now is None else now])
    row = _row(db, rider_id, cur.lastrowid)
    touch_near(db, rider_id, [row])
    db.commit()
    return _public(row)


def update(db, rider_id, zone_id, name=None, radius=None):
    """Rename a zone or change its size (the point stays: to move it, remove it and add another). Returns it as listing() gives it, or
    None when it isn't the rider's. Raises ValueError with why not. Commits."""
    ensure_schema(db)
    was = _row(db, rider_id, zone_id)
    if not was:
        return None
    name, _, _, radius = _checked(was['name'] if name is None else name, was['lat'], was['lng'], was['radiusM'] if radius is None else radius)
    db.execute('UPDATE PrivacyZone SET name=?, radiusM=? WHERE id=?', [name, radius, zone_id])
    row = _row(db, rider_id, zone_id)
    if radius != was['radiusM']:
        touch_near(db, rider_id, [was, row])
    db.commit()
    return _public(row)


def remove(db, rider_id, zone_id):
    """Remove a zone. Returns whether there was one. Commits."""
    ensure_schema(db)
    was = _row(db, rider_id, zone_id)
    if not was:
        return False
    db.execute('DELETE FROM PrivacyZone WHERE id=?', [zone_id])
    touch_near(db, rider_id, [was])
    db.commit()
    return True


def suggestions(db, rider_id, n=3, zones=None):
    """The places the rider's activities most often start from that no zone covers yet: [{lat, lng, count}], most first, each started from by
    at least SUGGEST_MIN activities. Counted in SUGGEST_CELL squares, each given as the middle of its starts."""
    rows = db.execute('SELECT CAST(startLat / ? AS INTEGER) AS i, CAST(startLng / ? AS INTEGER) AS j, AVG(startLat) AS lat, '
                      'AVG(startLng) AS lng, COUNT(*) AS n FROM Activity WHERE riderId=? AND startLat IS NOT NULL AND startLng IS NOT NULL '
                      'AND NOT (startLat = 0 AND startLng = 0) GROUP BY i, j HAVING n >= ? ORDER BY n DESC LIMIT 20',
                      [SUGGEST_CELL, SUGGEST_CELL, rider_id, SUGGEST_MIN]).fetchall()
    h = hider(db, rider_id) if zones is None else zones
    out = []
    for r in rows:
        if h.inside(r['lat'], r['lng']) or any(abs(o['lat'] - r['lat']) < 2 * SUGGEST_CELL and abs(o['lng'] - r['lng']) < 2 * SUGGEST_CELL
                                                for o in out):
            continue
        out.append({'lat': round(r['lat'], 5), 'lng': round(r['lng'], 5), 'count': r['n']})
        if len(out) == n:
            break
    return out
