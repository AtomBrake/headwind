"""Which activities are rides. Every activity, of every sport, is a row in Activity; the rides are the ones whose sport says so. The Ride view
(database.migrate_db) is built from RIDE_SQL and Python code asks is_ride, so the two can never disagree. Nothing else should test a sport for "ride".

A sport is a ride when it contains "ride" or "cycl", ignoring case: Headwind's own Ride and VirtualRide, Strava's "Virtual Ride", "E-Bike Ride",
"Gravel Ride" and "Mountain Bike Ride", Garmin's cycling types. A row with no sport counts as a ride, as the import treats it (routes/import_rides._insert).

Segments come in two families, and an activity is only matched against segments of its own (segment_family): rides, e-bike rides included, and
anything on foot. Indoor rides, swims, paddles, skis and the rest have no family and no segments. On a ride segment, pedal and e-bike efforts are told
apart by segment_class: each keeps its own PRs and badges, and the leaderboards can show either or both.

Totals and charts add distances up by stat_group, which is wider: every ride (indoor and e-bike too), everything on foot, swims, and any other sport on
its own. A swim's distance never adds to a ride's (services/sport_filter)."""

RIDE_SQL = "(sportType IS NULL OR sportType = '' OR lower(sportType) LIKE '%ride%' OR lower(sportType) LIKE '%cycl%')"
KIND_SQL = f"(CASE WHEN {RIDE_SQL} THEN 'ride' ELSE 'workout' END)"     # the phone API's and the bulk actions' 'ride' / 'workout'

# The sports Headwind itself writes: typed in by hand, recorded by the phone, picked in "change the type", saved by the Garmin sync.
RIDES = ('Ride', 'VirtualRide', 'EBikeRide')
ON_FOOT = ('Walk', 'Run', 'Hike')                     # what the phone records, and what calories can be estimated for (workouts.estimate_calories)
OTHER = ('Swim', 'Surf', 'Paddle', 'Row', 'Ski', 'Skate', 'Golf', 'Climb', 'Other')   # Garmin activities that are neither rides nor on foot
WORKOUTS = ON_FOOT + OTHER
SPORTS = RIDES + WORKOUTS
LABELS = {'VirtualRide': 'Indoor ride', 'EBikeRide': 'E-bike ride'}

FAMILIES = ('ride', 'foot')
FAMILY_LABELS = {'ride': 'Ride', 'foot': 'On foot'}
FAMILY_ICONS = {'ride': '🚴', 'foot': '🏃'}
CLASSES = ('bike', 'ebike', 'foot')                    # segment_class: who an effort races for a PR
CLASS_LABELS = {'bike': 'Bike', 'ebike': 'E-bike', 'foot': 'On foot'}
CLASS_ICONS = {'bike': '🚴', 'ebike': '⚡', 'foot': '🏃'}
_FOOT = {'walk', 'run', 'hike', 'trailrun', 'virtualrun'}      # Strava's "Trail Run" and "Virtual Run" squashed (_squash)


def is_ride(sport):
    s = (sport or '').lower()
    return not s or 'ride' in s or 'cycl' in s


def kind(sport):
    """'ride' or 'workout'."""
    return 'ride' if is_ride(sport) else 'workout'


def kind_of(db, act_id):
    """'ride' or 'workout' for an activity id, or None when there is no such activity."""
    row = db.execute('SELECT sportType FROM Activity WHERE id=?', [act_id]).fetchone()
    return kind(row[0]) if row else None


def icon(sport):
    """An emoji for a sport, for lists and badges."""
    t = (sport or '').lower()
    if 'ride' in t or 'cycling' in t: return '🚴'
    if 'run'  in t: return '🏃'
    if 'swim' in t: return '🏊'
    if 'surf' in t: return '🏄'
    if 'paddl' in t or 'row' in t or 'kayak' in t or 'canoe' in t or 'water' in t: return '🛶'     # Strava's "Water Sport"
    if 'ski' in t: return '⛷️'
    if 'golf' in t: return '⛳'
    if 'climb' in t: return '🧗'
    if 'walk' in t or 'hike' in t or 'snowshoe' in t: return '🥾'
    if 'sail' in t: return '⛵'
    if 'yoga' in t: return '🧘'
    if 'weight' in t: return '🏋️'
    return '🏅'


_WATER = ('swim', 'surf', 'sail', 'paddl', 'kayak', 'canoe', 'row', 'water')     # 'water': Strava's "Water Sport" (whitewater kayaking, say)


def on_water(sport):
    """Swims, surfs, sails, paddles, rows."""
    t = (sport or '').lower()
    return any(w in t for w in _WATER)


def has_climbing(sport):
    """False on the water, where a track's "climbing" is the GPS bobbing up and down (a kitesurf with thousands of feet of it)."""
    return not on_water(sport)


def climb_sql(col='totalElevationGain', sport='sportType'):
    """SQL for an activity's climb that counts as climbing (has_climbing): 0 on the water, so a river's GPS noise doesn't add to a total."""
    water = ' OR '.join(f"lower(COALESCE({sport}, '')) LIKE '%{w}%'" for w in _WATER)
    return f'(CASE WHEN {water} THEN 0 ELSE {col} END)'


def label(sport):
    """What a person reads for a sport: 'Indoor ride' for VirtualRide, 'E-bike ride' for EBikeRide, else the sport itself."""
    return LABELS.get(sport, sport or 'Ride')


def _squash(sport):
    return ''.join(c for c in (sport or '').lower() if c.isalpha())


def is_ebike(sport):
    """Headwind's and Garmin's EBikeRide, Strava's "E-Bike Ride" and "E-Mountain Bike Ride"."""
    s = _squash(sport)
    return s.startswith('ebike') or s.startswith('emountainbike')


_TYPE_NEEDLES = (('run', 'Run'), ('walk', 'Walk'), ('hik', 'Hike'), ('mountaineer', 'Hike'), ('swim', 'Swim'), ('surf', 'Surf'),
                 ('paddl', 'Paddle'), ('kayak', 'Paddle'), ('canoe', 'Paddle'), ('raft', 'Paddle'), ('row', 'Row'),
                 ('ski', 'Ski'), ('snowboard', 'Ski'), ('skat', 'Skate'), ('golf', 'Golf'), ('climb', 'Climb'))
_INDOOR_SUBS = ('indoor_cycling', 'virtual_activity')


def from_type(type_key, sub=None):
    """A device's or service's name for a sport -> one of SPORTS. Garmin Connect's activity type ('mountain_biking', 'lap_swimming'), a FIT
    file's sport with its sub-sport ('cycling' + 'e_bike_mountain', 'alpine_skiing'), a GPX <type> ('EMountainBikeRide', 'trail_running',
    'StandUpPaddling') or a TCX Sport. Rides are Ride / VirtualRide / EBikeRide; anything not recognised is 'Other', never a ride: a ski day
    saved as a ride breaks the ride totals, the segments and the bike's mileage."""
    k = str(type_key if type_key is not None else '').lower()
    s = str(sub if sub is not None else '').lower()
    if 'motor' in k or 'snowmobil' in k:                      # motorcycling, motocross: 'cycl' but not a bike ride
        return 'Other'
    bike = 'cycl' in k or 'bik' in k or k in ('ride', 'bmx')
    if k in ('indoor_cycling', 'virtual_ride') or ('virtual' in k and (bike or 'ride' in k)) or (bike and s in _INDOOR_SUBS):
        return 'VirtualRide'
    if is_ebike(k) or (k.startswith('e_') and ('bik' in k or 'mtb' in k)) or (bike and s.startswith('e_bike')):
        return 'EBikeRide'                                    # e_bike_fitness, e_enduro_mtb, Strava's EMountainBikeRide, FIT's cycling + e_bike_mountain
    if bike:
        return 'Ride'
    for needle, sport in _TYPE_NEEDLES:
        if needle in k:
            return sport
    return 'Other'


def segment_family(sport):
    """'ride', 'foot' or None (no segments). Pedal and e-bike rides share the ride segments; an indoor ride has none."""
    s = _squash(sport)
    if s in _FOOT:
        return 'foot'
    if not is_ride(sport) or 'virtual' in s or 'indoor' in s:
        return None
    return 'ride'


def segment_class(sport, bike_kind=None):
    """'bike', 'ebike', 'foot' or None (no segments). Anything ridden on an e-bike is an e-bike effort, whether the sport says so or the bike does
    (services/gear.BIKE_KINDS 'ebike'). ebike_sql is the same test for a query."""
    fam = segment_family(sport)
    if fam != 'ride':
        return fam
    return 'ebike' if is_ebike(sport) or bike_kind == 'ebike' else 'bike'


def ebike_sql(sport='a.sportType', bike_kind='b.kind'):
    """SQL that is true for an e-bike ride (segment_class 'ebike'), on a query that has the activity's sport and its bike's kind (a LEFT JOIN Bike)."""
    s = f"replace(replace(replace(lower(COALESCE({sport}, '')), ' ', ''), '-', ''), '_', '')"
    return f"(COALESCE({bike_kind}, '') = 'ebike' OR {s} LIKE 'ebike%' OR {s} LIKE 'emountainbike%')"


def class_sql(cls, sport='a.sportType', bike_kind='b.kind'):
    """SQL that keeps one segment_class's efforts on a ride segment: 'bike' (pedal) or 'ebike'. Anything else ('foot', None: every effort) keeps all."""
    if cls == 'ebike':
        return ebike_sql(sport, bike_kind)
    if cls == 'bike':
        return f'NOT {ebike_sql(sport, bike_kind)}'
    return '1=1'


STAT_LABELS = {'ride': 'Rides', 'foot': 'On foot', 'swim': 'Swims'}
STAT_ICONS = {'ride': '🚴', 'foot': '🏃', 'swim': '🏊'}
_STAT_ORDER = {'ride': 0, 'foot': 1, 'swim': 2}


def stat_group(sport):
    """Which distances a sport's distance adds to: 'ride', 'foot', 'swim', or the sport itself ('Paddle', 'Ski', ...)."""
    if is_ride(sport):
        return 'ride'
    s = _squash(sport)
    if s in _FOOT:
        return 'foot'
    if 'swim' in s:
        return 'swim'
    return sport


def stat_label(group):
    return STAT_LABELS.get(group, group)


def stat_order(group):
    """Sort key: rides, on foot, swims, then the other sports by name."""
    return (_STAT_ORDER.get(group, 3), group)


def rate_style(sport=None, group=None):
    """How a sport's speed reads: 'speed' (mph / km/h) for rides and the rest, 'pace' (per mile / km) on foot, 'swim' (per 100 m) for swims."""
    g = group if group is not None else stat_group(sport)
    return {'foot': 'pace', 'swim': 'swim'}.get(g, 'speed')


def family_of(db, act_id):
    """segment_family for an activity id. None when there is no such activity, or it has no segments."""
    row = db.execute('SELECT sportType FROM Activity WHERE id=?', [act_id]).fetchone()
    return segment_family(row[0]) if row else None


def class_of(db, act_id):
    """segment_class for an activity id, from its sport and its bike. None when there is no such activity, or it has no segments."""
    try:
        row = db.execute('SELECT a.sportType, b.kind FROM Activity a LEFT JOIN Bike b ON b.id = a.bikeId WHERE a.id=?', [act_id]).fetchone()
    except Exception:                                     # no Bike table (a bare test database)
        row = db.execute('SELECT sportType, NULL FROM Activity WHERE id=?', [act_id]).fetchone()
    return segment_class(row[0], row[1]) if row else None
