"""Bikes from a Strava export: which bike Strava says rode each ride, and matching those bikes to the rider's Headwind bikes.

A Strava export names the gear on each activity ('Activity Gear' in activities.csv) and lists the bikes in bikes.csv (name, brand, model,
default sport types) and the shoes in shoes.csv. An import records the Strava bike of every ride, new and already saved alike (StravaGear),
and the bikes themselves (StravaBike). The rider then matches each Strava bike on the Gear page (/gear/strava): one of their bikes, a new
one, or left out (a loan or hire bike). A match is remembered, so the next export puts its rides on the right bike by itself.

Rules:
* A Strava bike named like one of the rider's bikes (ignoring case and spacing) is matched to it straight away; the rest wait to be matched.
* A ride that names a Strava bike never gets the default bike when it is imported: until its bike is matched it has none, so the default
  bike's mileage never takes rides that were on something else.
* Saving a match fills in the rides that have no bike, and moves the rides the previous match put on a bike. A bike set any other way (by
  hand, by the calendar, the default stamped on when it was first imported) is changed only when asked (`replace`).
* Shoes are left alone until shoe tracking exists; only rides take a bike.
"""
import csv
import io
import logging
import re
from collections import Counter
from datetime import timedelta

from services import gear
from services.sports import is_ride

log = logging.getLogger(__name__)
NEW, MATCHED, IGNORED = 'new', 'matched', 'ignored'
RETIRE_AFTER_DAYS = 365          # a new bike last ridden longer ago than this is suggested as retired


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS StravaBike (
        riderId INTEGER NOT NULL,
        name    TEXT NOT NULL,                    -- Strava's name for the bike, exactly as the export writes it
        brand   TEXT, model TEXT,
        sports  TEXT,                             -- bikes.csv 'Bike Default Sport Types', e.g. 'Mountain Bike Ride'
        bikeId  INTEGER,                          -- the Headwind bike it is matched to
        status  TEXT NOT NULL DEFAULT 'new',      -- new (not matched yet) | matched | ignored (its rides get no bike)
        PRIMARY KEY (riderId, name))''')
    db.execute('''CREATE TABLE IF NOT EXISTS StravaGear (
        activityId TEXT PRIMARY KEY,
        gear       TEXT NOT NULL)                 -- StravaBike.name''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_stravagear_gear ON StravaGear(gear)')


def norm(name):
    return re.sub(r'\s+', ' ', (name or '').strip()).lower()


def _csv(zf, names, filename):
    if filename not in names:
        return []
    with zf.open(filename) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='replace')))


# ---------- recording, at import ----------
def record(db, zf, names, rows, rider_id):
    """Read the bikes, the shoes and each ride's gear from a Strava export (rows: activities.csv as dicts). Returns {activity id: Strava bike
    name} for the rides that name a bike. A new Strava bike named like one of the rider's bikes is matched to it. Does not commit."""
    if not rider_id:
        return {}
    shoes = {norm(r.get('Shoe Name')) for r in _csv(zf, names, 'shoes.csv')} - {''}
    for r in _csv(zf, names, 'bikes.csv'):
        name = (r.get('Bike Name') or '').strip()
        if name:
            _upsert(db, rider_id, name, r.get('Bike Brand'), r.get('Bike Model'), r.get('Bike Default Sport Types'))
    by_id = {}
    for row in rows:
        act_id = str(row.get('Activity ID') or '').strip()
        name = (row.get('Activity Gear') or '').strip()
        if not act_id or not name or norm(name) in shoes or not is_ride((row.get('Activity Type') or '').strip() or 'Ride'):
            continue
        by_id[act_id] = name
    for name in set(by_id.values()):                 # a bike the export names on a ride but leaves out of bikes.csv
        _upsert(db, rider_id, name)
    db.executemany('INSERT OR REPLACE INTO StravaGear (activityId, gear) VALUES (?,?)', list(by_id.items()))
    _match_by_name(db, rider_id)
    return by_id


def _upsert(db, rider_id, name, brand=None, model=None, sports=None):
    db.execute('INSERT OR IGNORE INTO StravaBike (riderId, name) VALUES (?,?)', [rider_id, name])
    if brand or model or sports:
        db.execute('UPDATE StravaBike SET brand=?, model=?, sports=? WHERE riderId=? AND name=?',
                   [(brand or '').strip() or None, (model or '').strip() or None, (sports or '').strip() or None, rider_id, name])


def _match_by_name(db, rider_id):
    mine = {}
    for b in gear.list_bikes(db, rider_id, include_archived=True):
        mine.setdefault(norm(b['name']), b['id'])
    for sb in db.execute('SELECT name FROM StravaBike WHERE riderId=? AND status=?', [rider_id, NEW]).fetchall():
        if norm(sb['name']) in mine:
            db.execute('UPDATE StravaBike SET bikeId=?, status=? WHERE riderId=? AND name=?', [mine[norm(sb['name'])], MATCHED, rider_id, sb['name']])


def apply_matched(db, rider_id):
    """After an import: put the rides of every matched Strava bike that have no bike yet on it. Returns how many rides changed. Does not commit."""
    n = 0
    for sb in db.execute('SELECT name, bikeId FROM StravaBike WHERE riderId=? AND status=? AND bikeId IS NOT NULL', [rider_id, MATCHED]).fetchall():
        if gear.get_bike(db, sb['bikeId']):
            n += _move(db, rider_id, sb['name'], sb['bikeId'])
    if n:
        gear.evaluate_alerts(db, rider_id=rider_id)
    return n


def _rides(db, rider_id, name):
    """The rider's saved rides that Strava says were on this bike (id, bikeId, sportType, day). A Strava ride parked as a duplicate stands for the
    ride kept in its place, unless that one has Strava gear of its own."""
    cols = 'a.id, a.bikeId, a.sportType, substr(a.startDateLocal,1,10) AS day'
    return db.execute(f'''SELECT {cols} FROM StravaGear g JOIN Activity a ON a.id = g.activityId WHERE g.gear=? AND a.riderId=?
                          UNION
                          SELECT {cols} FROM StravaGear g JOIN ActivityDuplicate d ON d.id = g.activityId AND d.status = 'parked'
                            JOIN Activity a ON a.id = d.primaryId
                          WHERE g.gear=? AND a.riderId=? AND NOT EXISTS (SELECT 1 FROM StravaGear g2 WHERE g2.activityId = a.id)''',
                      [name, rider_id, name, rider_id]).fetchall()


def _move(db, rider_id, name, bike_id, prev=None, replace=False):
    """Put this Strava bike's rides on bike_id (None: no bike): those with no bike, those on `prev` (what the previous match put them on), and
    with replace every one. Returns how many changed."""
    ids = [r['id'] for r in _rides(db, rider_id, name)
           if r['bikeId'] != bike_id and ((r['bikeId'] is None and bike_id) or (prev and r['bikeId'] == prev) or replace)]
    return gear.set_rides_bike(db, ids, bike_id) if ids else 0


# ---------- the match page ----------
def guess_kind(sports, ride_sports):
    """A Headwind bike kind (gear.BIKE_KINDS) for a new bike, from what it was ridden for and Strava's default sport types for it."""
    total = sum(ride_sports.values())
    squash = lambda s: re.sub(r'[\s_-]', '', (s or '').lower())
    ebike = sum(n for s, n in ride_sports.items() if squash(s).startswith(('ebike', 'emountainbike')))
    virtual = sum(n for s, n in ride_sports.items() if squash(s).startswith('virtual'))
    if total and ebike * 2 > total:
        return 'ebike'
    if total and virtual * 2 > total:
        return 'turbo'
    defaults = [squash(s) for s in (sports or '').split('|') if s.strip()]
    if len(defaults) == 1:                         # a bike set as the default for everything says nothing about what it is
        d = defaults[0]
        for prefix, kind in (('ebike', 'ebike'), ('emountainbike', 'ebike'), ('mountainbike', 'mtb'), ('gravel', 'gravel'), ('virtual', 'turbo'), ('ride', 'road')):
            if d.startswith(prefix):
                return kind
    return 'other'


def overview(db, rider_id):
    """Every Strava bike of this rider, with its rides and what the page should suggest for it."""
    bikes = db.execute('SELECT * FROM StravaBike WHERE riderId=? ORDER BY name COLLATE NOCASE', [rider_id]).fetchall()
    stats = {}
    for name in [b['name'] for b in bikes]:
        rides = _rides(db, rider_id, name)
        days = [r['day'] for r in rides if r['day']]
        stats[name] = {'rides': len(rides), 'none': sum(1 for r in rides if r['bikeId'] is None),
                       'bikes': Counter(r['bikeId'] for r in rides if r['bikeId'] is not None),
                       'sports': Counter(r['sportType'] or 'Ride' for r in rides), 'first': min(days, default=None), 'last': max(days, default=None)}
    mine = gear.list_bikes(db, rider_id, include_archived=True)
    by_name = {}
    for b in mine:
        by_name.setdefault(norm(b['name']), b['id'])
    ids = {b['id'] for b in mine}
    stale = (gear.today() - timedelta(days=RETIRE_AFTER_DAYS)).isoformat()
    out = []
    for b in bikes:
        st = stats[b['name']]
        if b['status'] == MATCHED and b['bikeId'] in ids:
            choice = str(b['bikeId'])
        elif b['status'] == IGNORED:
            choice = 'ignore'
        elif norm(b['name']) in by_name:
            choice = str(by_name[norm(b['name'])])
        else:
            choice = 'new' if st['rides'] else 'ignore'
        target = int(choice) if choice.isdigit() else None
        out.append({'name': b['name'], 'brand': b['brand'], 'model': b['model'], 'status': b['status'], 'choice': choice,
                    'kind': guess_kind(b['sports'], st['sports']), 'retire': bool(st['last'] and st['last'] < stale),
                    'rides': st['rides'], 'none': st['none'], 'first': st['first'], 'last': st['last'],
                    'elsewhere': sum(n for bid, n in st['bikes'].items() if bid != target)})
    return out


def pending(db, rider_id):
    """How many of this rider's Strava bikes have not been matched yet."""
    return db.execute('SELECT COUNT(*) FROM StravaBike WHERE riderId=? AND status=?', [rider_id, NEW]).fetchone()[0]


def save(db, rider_id, choices, replace=False):
    """choices = {Strava bike name: {'match': 'new' | 'ignore' | Headwind bike id, 'kind': ..., 'retired': bool}}. Creates the new bikes, remembers
    every match and moves the rides to follow it. A rider with no default bike gets the most recently ridden bike that isn't retired (or a turbo).
    Returns {'created': [names], 'moved': rides changed}. Does not commit."""
    had_default = db.execute('SELECT defaultBikeId FROM Rider WHERE id=?', [rider_id]).fetchone()[0]
    rows = {b['name']: b for b in db.execute('SELECT * FROM StravaBike WHERE riderId=?', [rider_id]).fetchall()}
    created, retire, moved, last_ride = [], [], 0, {}
    for name, c in choices.items():
        sb = rows.get(name)
        if not sb:
            continue
        match = str(c.get('match') or '')
        prev = sb['bikeId'] if sb['status'] == MATCHED else None
        if match == 'new':
            bid = gear.create_bike(db, rider_id, name, c.get('kind') or 'other', sb['brand'], sb['model'])
            created.append(name)
            if c.get('retired'):
                retire.append(bid)
        elif match == 'ignore':
            bid = None
        else:
            b = gear.get_bike(db, int(match)) if match.isdigit() else None
            if not b or b['riderId'] != rider_id:
                raise ValueError(f'pick a bike for {name}')
            bid = b['id']
        db.execute('UPDATE StravaBike SET bikeId=?, status=? WHERE riderId=? AND name=?', [bid, MATCHED if bid else IGNORED, rider_id, name])
        moved += _move(db, rider_id, name, bid, prev=prev, replace=replace)
        if bid and bid not in retire:
            d = db.execute('SELECT MAX(startDateLocal) FROM Activity WHERE bikeId=?', [bid]).fetchone()[0]
            last_ride[bid] = max(last_ride.get(bid) or '', d or '')
    if not had_default and last_ride:                  # a turbo only when there's nothing else: the default goes on every new ride, outdoors too
        kind = {bid: gear.get_bike(db, bid)['kind'] for bid in last_ride}
        gear.set_default(db, rider_id, max(last_ride, key=lambda bid: (kind[bid] != 'turbo', last_ride[bid])))
    for bid in retire:
        gear.archive_bike(db, bid)
    if moved:
        gear.evaluate_alerts(db, rider_id=rider_id)
    return {'created': created, 'moved': moved}


def strava_name(db, bike_id):
    """The Strava bike matched to this Headwind bike, or None."""
    r = db.execute('SELECT name FROM StravaBike WHERE bikeId=? AND status=? LIMIT 1', [bike_id, MATCHED]).fetchone()
    return r[0] if r else None
