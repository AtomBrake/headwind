"""Kit: the gear that isn't a bike. Shoes first, then wetsuits, skis, boards, boats and anything else an activity is done in or on. Bikes and
their parts stay in services/gear.py; this is the same idea for every other sport, without the parts.

Design rules, as for bikes:
* Distance and time are COMPUTED, never stored: an item's distance is its starting distance plus the distance of the activities it's on, so
  moving an activity to other shoes corrects both pairs at once.
* Each rider has a default item per sport (KitDefault: runs -> road shoes, hikes -> boots), given to a new activity of that sport when it
  arrives (stamp_new_activity, from gear.on_ride_added, which every ingest path calls). Changing a default later never rewrites history.
* An item can have a "replace at" distance (running shoes: about 500-800 km). Passing 90% of it, then 100% and 125%, raises an alert once
  each (KitAlert), through the same notifications and Home Assistant push as bike parts (gear.evaluate_alerts).
* Retiring an item keeps its history and its activities; it stops being a default, stops alerting and leaves the pickers.
* Rides never get kit: they have a bike (Activity.bikeId). Kit is for everything else (services/sports.is_ride says which is which).
"""
import logging
from datetime import date

from services import sports

log = logging.getLogger(__name__)

KINDS = [('shoes', 'Shoes'), ('wetsuit', 'Wetsuit'), ('skis', 'Skis'), ('snowboard', 'Snowboard'), ('board', 'Board'), ('boat', 'Kayak, canoe or boat'),
         ('other', 'Other')]
KIND_ICONS = {'shoes': '👟', 'wetsuit': '🤿', 'skis': '⛷️', 'snowboard': '🏂', 'board': '🏄', 'boat': '🛶', 'other': '🎒'}
REPLACE_DEFAULT_M = {'shoes': 700_000}       # running shoes are usually done somewhere between 500 and 800 km
SOON, DUE, OVERDUE = 0.9, 1.0, 1.25
LEVEL_ORDER = {'ok': 0, 'soon': 1, 'due': 2, 'overdue': 3}
# The sports a default can be set for: what Headwind records, Strava's names for the same, then the rest
DEFAULT_SPORTS = ['Run', 'TrailRun', 'Walk', 'Hike', 'Swim', 'Ski', 'AlpineSki', 'NordicSki', 'Snowboard', 'Surf', 'Paddle', 'Row', 'Skate', 'Other']


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS Kit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, riderId INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'shoes', name TEXT NOT NULL, brand TEXT, model TEXT,
        boughtOn TEXT, startMeters REAL DEFAULT 0, replaceAtM REAL, notes TEXT, retiredOn TEXT, createdAt TEXT DEFAULT (datetime('now')))''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_kit_rider ON Kit(riderId)')
    db.execute('''CREATE TABLE IF NOT EXISTS KitDefault (
        riderId INTEGER NOT NULL, sport TEXT NOT NULL, kitId INTEGER NOT NULL, PRIMARY KEY (riderId, sport))''')
    db.execute('''CREATE TABLE IF NOT EXISTS KitAlert (
        kitId INTEGER NOT NULL, level TEXT NOT NULL, cycle TEXT NOT NULL, notifiedAt TEXT DEFAULT (datetime('now')), PRIMARY KEY (kitId, level, cycle))''')
    act = {r[1] for r in db.execute('PRAGMA table_info(Activity)').fetchall()}
    if 'kitId' not in act:
        db.execute('ALTER TABLE Activity ADD COLUMN kitId INTEGER')
    db.execute('CREATE INDEX IF NOT EXISTS idx_activity_kit ON Activity(kitId)')


def _clean(s, n=80):
    s = (s or '').strip()
    return s[:n] or None


def _num(v, name):
    if v in (None, ''):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number')
    if x < 0:
        raise ValueError(f'{name} is out of range')
    return x


def _date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValueError('that is not a valid date')


def _req_name(v):
    v = _clean(v)
    if not v:
        raise ValueError('give it a name')
    return v


def kind_label(kind):
    return dict(KINDS).get(kind, 'Other')


def sport_key(sport):
    """The sport a default is kept under: Strava's "Trail Run" and Headwind's TrailRun are the same."""
    return ''.join(c for c in (sport or '') if c.isalnum())


# ---------- items ----------
def create(db, rider_id, name, kind='shoes', brand=None, model=None, bought_on=None, start_meters=0, replace_m=None, notes=None, sports_=None):
    """A new item. replace_m None gives shoes the usual 700 km; 0 means never. sports_: the sports it becomes the default for. Returns its id."""
    name = _clean(name)
    if not name:
        raise ValueError('give it a name')
    kind = kind if kind in dict(KINDS) else 'other'
    replace = REPLACE_DEFAULT_M.get(kind) if replace_m is None else (_num(replace_m, 'replace at') or None)
    kid = db.execute('INSERT INTO Kit (riderId, kind, name, brand, model, boughtOn, startMeters, replaceAtM, notes) VALUES (?,?,?,?,?,?,?,?,?)',
                     [rider_id, kind, name, _clean(brand), _clean(model), _date(bought_on), _num(start_meters, 'starting distance') or 0, replace,
                      _clean(notes, 1000)]).lastrowid
    if sports_:
        set_defaults(db, kid, sports_)
    return kid


def update(db, kit_id, **f):
    cols = {'name': _req_name, 'kind': lambda v: v if v in dict(KINDS) else 'other',
            'brand': _clean, 'model': _clean, 'boughtOn': _date, 'startMeters': lambda v: _num(v, 'starting distance') or 0,
            'replaceAtM': lambda v: _num(v, 'replace at') or None, 'notes': lambda v: _clean(v, 1000)}
    sets, args = [], []
    for k, v in f.items():
        if k in cols:
            sets.append(f'{k}=?'); args.append(cols[k](v))
    if sets:
        db.execute(f"UPDATE Kit SET {', '.join(sets)} WHERE id=?", args + [kit_id])


def get(db, kit_id):
    return db.execute('SELECT * FROM Kit WHERE id=?', [kit_id]).fetchone()


def list_kit(db, rider_id, include_retired=False):
    q = 'SELECT * FROM Kit WHERE riderId=?' + ('' if include_retired else ' AND retiredOn IS NULL') + ' ORDER BY retiredOn IS NOT NULL, kind, name COLLATE NOCASE'
    return db.execute(q, [rider_id]).fetchall()


def retire(db, kit_id, retired=True):
    """Retire (or bring back) an item. Retired, it is nobody's default and raises no alerts; its activities keep it."""
    k = get(db, kit_id)
    if not k:
        return
    if retired:
        from services import tz
        db.execute('UPDATE Kit SET retiredOn=? WHERE id=? AND retiredOn IS NULL', [tz.today().isoformat(), kit_id])
        db.execute('DELETE FROM KitDefault WHERE kitId=?', [kit_id])
    else:
        db.execute('UPDATE Kit SET retiredOn=NULL WHERE id=?', [kit_id])


def delete(db, kit_id):
    """Removes the item. Its activities simply have no kit any more; a Strava shoe matched to it is left out of later imports."""
    db.execute('UPDATE Activity SET kitId=NULL WHERE kitId=?', [kit_id])
    db.execute('DELETE FROM KitDefault WHERE kitId=?', [kit_id])
    db.execute('DELETE FROM KitAlert WHERE kitId=?', [kit_id])
    try:
        db.execute("UPDATE StravaKit SET kitId=NULL, status='ignored' WHERE kitId=?", [kit_id])
    except Exception:                                       # no StravaKit table (a bare test database)
        log.debug('Unmatching Strava shoes from deleted kit failed', exc_info=True)
    db.execute('DELETE FROM Kit WHERE id=?', [kit_id])


# ---------- defaults ----------
def defaults(db, rider_id):
    """{sport key: kit id} for this rider."""
    return {r['sport']: r['kitId'] for r in db.execute('SELECT sport, kitId FROM KitDefault WHERE riderId=?', [rider_id]).fetchall()}


def defaults_of(db, kit_id):
    """The sports this item is the default for."""
    return [r[0] for r in db.execute('SELECT sport FROM KitDefault WHERE kitId=? ORDER BY sport', [kit_id]).fetchall()]


def set_defaults(db, kit_id, sports_):
    """Make this item the default for exactly these sports (taking them from whatever had them), and for no others."""
    k = get(db, kit_id)
    if not k:
        raise ValueError('that kit is not available')
    keys = sorted({sport_key(s) for s in sports_ or [] if sport_key(s)})
    if keys and k['retiredOn']:
        raise ValueError('a retired item cannot be a default')
    db.execute('DELETE FROM KitDefault WHERE kitId=?', [kit_id])
    for s in keys:
        db.execute('INSERT OR REPLACE INTO KitDefault (riderId, sport, kitId) VALUES (?,?,?)', [k['riderId'], s, kit_id])


def default_for(db, rider_id, sport):
    r = db.execute('SELECT d.kitId FROM KitDefault d JOIN Kit k ON k.id = d.kitId WHERE d.riderId=? AND d.sport=? AND k.retiredOn IS NULL',
                   [rider_id, sport_key(sport)]).fetchone()
    return r[0] if r else None


# ---------- which kit did which activity ----------
def _check(db, act_ids, kit_id):
    """The activities, if the kit belongs to their rider and none of them is a ride. Raises ValueError otherwise."""
    rows = []
    for i in range(0, len(act_ids), 500):
        chunk = act_ids[i:i + 500]
        rows += db.execute(f"SELECT id, riderId, sportType FROM Activity WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
    if kit_id is not None:
        k = get(db, kit_id)
        if not k or any(r['riderId'] != k['riderId'] for r in rows):
            raise ValueError('that kit belongs to a different rider')
    if any(sports.is_ride(r['sportType']) for r in rows):
        raise ValueError('a ride has a bike, not kit')
    return [r['id'] for r in rows]


def set_activity_kit(db, act_id, kit_id):
    """Set (or clear, with None) the kit on one activity. Does not commit."""
    ids = _check(db, [act_id], kit_id)
    if not ids:
        raise ValueError('activity not found')
    db.execute('UPDATE Activity SET kitId=? WHERE id=?', [kit_id, act_id])
    evaluate_alerts_for(db, kit_id)


def set_activities_kit(db, act_ids, kit_id):
    """Put many activities on one item (or clear them). Rides are refused. Returns how many. Does not commit."""
    ids = _check(db, list(act_ids), kit_id)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.execute(f"UPDATE Activity SET kitId=? WHERE id IN ({','.join('?' * len(chunk))})", [kit_id] + chunk)
    evaluate_alerts_for(db, kit_id)
    return len(ids)


def stamp_new_activity(db, act_id):
    """A new activity that isn't a ride and has no kit gets the rider's default for its sport. Returns the kit id given, or None."""
    a = db.execute('SELECT riderId, sportType, kitId FROM Activity WHERE id=?', [act_id]).fetchone()
    if not a or a['kitId'] or not a['riderId'] or sports.is_ride(a['sportType']):
        return None
    kid = default_for(db, a['riderId'], a['sportType'])
    if kid:
        db.execute('UPDATE Activity SET kitId=? WHERE id=?', [kid, act_id])
    return kid


def choices_for(db, activity):
    """The items the activity page offers: the rider's kit that isn't retired, and whatever the activity is on now even if it is."""
    items = list_kit(db, activity['riderId']) if activity['riderId'] else []
    if activity['kitId'] and all(k['id'] != activity['kitId'] for k in items):
        k = get(db, activity['kitId'])
        if k:
            items.append(k)
    return items


# ---------- distance, time, wear ----------
def stats(db, kit_id):
    r = db.execute('''SELECT COUNT(*) n, COALESCE(SUM(distance),0) dist, COALESCE(SUM(movingTime),0) moving, COALESCE(SUM(totalElevationGain),0) gain,
                             MAX(distance) longest, MIN(substr(startDateLocal,1,10)) first, MAX(substr(startDateLocal,1,10)) last
                      FROM Activity WHERE kitId=?''', [kit_id]).fetchone()
    by_sport = db.execute('SELECT sportType, COUNT(*) n, COALESCE(SUM(distance),0) d FROM Activity WHERE kitId=? GROUP BY sportType ORDER BY n DESC',
                          [kit_id]).fetchall()
    return {'n': r['n'], 'distance': r['dist'], 'moving': r['moving'], 'gain': r['gain'], 'longest': r['longest'], 'first': r['first'], 'last': r['last'],
            'by_sport': [{'sport': s['sportType'], 'n': s['n'], 'distance': s['d']} for s in by_sport]}


def all_stats(db, rider_id):
    """{kit id: {'n', 'distance', 'moving', 'last'}} for every item of the rider in one query, for the Gear page."""
    rows = db.execute('''SELECT k.id, COUNT(a.id) n, COALESCE(SUM(a.distance),0) dist, COALESCE(SUM(a.movingTime),0) moving, MAX(substr(a.startDateLocal,1,10)) last
                         FROM Kit k LEFT JOIN Activity a ON a.kitId = k.id WHERE k.riderId=? GROUP BY k.id''', [rider_id]).fetchall()
    return {r['id']: {'n': r['n'], 'distance': r['dist'], 'moving': r['moving'], 'last': r['last']} for r in rows}


def odometer(db, k, used_m=None):
    if used_m is None:
        used_m = db.execute('SELECT COALESCE(SUM(distance),0) FROM Activity WHERE kitId=?', [k['id']]).fetchone()[0]
    return (k['startMeters'] or 0) + (used_m or 0)


def _level(ratio):
    if ratio is None:
        return 'ok'
    return 'overdue' if ratio >= OVERDUE else 'due' if ratio >= DUE else 'soon' if ratio >= SOON else 'ok'


def status(db, k, used_m=None):
    """{'meters', 'ratio', 'level'}: how far the item has gone against its replace-at distance. A retired item is always 'ok'."""
    m = odometer(db, k, used_m)
    ratio = m / k['replaceAtM'] if k['replaceAtM'] else None
    return {'meters': m, 'ratio': ratio, 'level': 'ok' if k['retiredOn'] else _level(ratio)}


def due_items(db, rider_id, include_soon=True):
    """The rider's kit that needs replacing (or soon will), worst first: [{'kit', 'status'}]."""
    used = all_stats(db, rider_id)
    out = []
    for k in list_kit(db, rider_id):
        st = status(db, k, used.get(k['id'], {}).get('distance', 0))
        if st['level'] == 'ok' or (st['level'] == 'soon' and not include_soon):
            continue
        out.append({'kit': k, 'status': st})
    out.sort(key=lambda x: -LEVEL_ORDER[x['status']['level']])
    return out


def _headline(k, st, level):
    from services import units
    state = {'soon': 'is nearly due for', 'due': 'is due for', 'overdue': 'is overdue for'}[level]
    return f"{k['name']} {state} replacement ({units.fmt_dist(st['meters'], places=0)} of {units.fmt_dist(k['replaceAtM'], places=0)})"


def evaluate_alerts(db, rider_id=None):
    """Items that have newly passed a level, remembered so each fires once per item (KitAlert). Returns them in gear.evaluate_alerts' shape
    ({'kitId', 'riderId', 'what', 'level', 'text'}); gear.evaluate_alerts sends them with the bike parts'. Does not commit."""
    q, args = 'SELECT * FROM Kit WHERE retiredOn IS NULL AND replaceAtM > 0', []
    if rider_id:
        q += ' AND riderId=?'; args.append(rider_id)
    new = []
    for k in db.execute(q, args).fetchall():
        st = status(db, k)
        lvl = st['level']
        if lvl == 'ok':
            continue
        cycle = k['boughtOn'] or k['createdAt'] or ''
        if db.execute('SELECT 1 FROM KitAlert WHERE kitId=? AND level=? AND cycle=?', [k['id'], lvl, cycle]).fetchone():
            continue
        for l in LEVEL_ORDER:                             # this and every lower level count as announced; only the current one is sent
            if l != 'ok' and LEVEL_ORDER[l] <= LEVEL_ORDER[lvl]:
                db.execute('INSERT OR IGNORE INTO KitAlert (kitId, level, cycle) VALUES (?,?,?)', [k['id'], l, cycle])
        new.append({'kitId': k['id'], 'riderId': k['riderId'], 'what': 'replace', 'level': lvl, 'text': _headline(k, st, lvl)})
    return new


def evaluate_alerts_for(db, kit_id):
    """After activities move onto an item: alert (with the bike parts) if that pushed it over a level."""
    k = get(db, kit_id) if kit_id else None
    if k:
        from services import gear
        gear.evaluate_alerts(db, rider_id=k['riderId'])
