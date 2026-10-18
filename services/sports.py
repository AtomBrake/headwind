"""Which activities are rides. Every activity, of every sport, is a row in Activity; the rides are the ones whose sport says so. The Ride view
(database.migrate_db) is built from RIDE_SQL and Python code asks is_ride, so the two can never disagree. Nothing else should test a sport for "ride".

A sport is a ride when it contains "ride" or "cycl", ignoring case: Headwind's own Ride and VirtualRide, Strava's "Virtual Ride", "E-Bike Ride",
"Gravel Ride" and "Mountain Bike Ride", Garmin's cycling types. A row with no sport counts as a ride, as the import treats it (routes/import_rides._insert).

Segments come in three families, and an activity is only matched against segments of its own (segment_family): rides, e-bike rides and anything on
foot. Indoor rides, swims, paddles, skis and the rest have no family and no segments."""

RIDE_SQL = "(sportType IS NULL OR sportType = '' OR lower(sportType) LIKE '%ride%' OR lower(sportType) LIKE '%cycl%')"
KIND_SQL = f"(CASE WHEN {RIDE_SQL} THEN 'ride' ELSE 'workout' END)"     # the phone API's and the bulk actions' 'ride' / 'workout'

# The sports Headwind itself writes: typed in by hand, recorded by the phone, picked in "change the type", saved by the Garmin sync.
RIDES = ('Ride', 'VirtualRide', 'EBikeRide')
ON_FOOT = ('Walk', 'Run', 'Hike')                     # what the phone records, and what calories can be estimated for (workouts.estimate_calories)
OTHER = ('Swim', 'Surf', 'Paddle', 'Row', 'Ski', 'Skate', 'Golf', 'Climb', 'Other')   # Garmin activities that are neither rides nor on foot
WORKOUTS = ON_FOOT + OTHER
SPORTS = RIDES + WORKOUTS
LABELS = {'VirtualRide': 'Indoor ride', 'EBikeRide': 'E-bike ride'}

FAMILIES = ('ride', 'eride', 'foot')
FAMILY_LABELS = {'ride': 'Ride', 'eride': 'E-bike', 'foot': 'On foot'}
FAMILY_ICONS = {'ride': '🚴', 'eride': '⚡', 'foot': '🏃'}
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


def label(sport):
    """What a person reads for a sport: 'Indoor ride' for VirtualRide, 'E-bike ride' for EBikeRide, else the sport itself."""
    return LABELS.get(sport, sport or 'Ride')


def _squash(sport):
    return ''.join(c for c in (sport or '').lower() if c.isalpha())


def is_ebike(sport):
    """Headwind's and Garmin's EBikeRide, Strava's "E-Bike Ride" and "E-Mountain Bike Ride"."""
    s = _squash(sport)
    return s.startswith('ebike') or s.startswith('emountainbike')


def segment_family(sport, bike_kind=None):
    """'ride', 'eride', 'foot' or None (no segments). Anything ridden on an e-bike is an e-ride, whether the sport says so or the bike does
    (services/gear.BIKE_KINDS 'ebike'); an indoor ride has no family, whatever its bike."""
    s = _squash(sport)
    if s in _FOOT:
        return 'foot'
    if not is_ride(sport) or 'virtual' in s or 'indoor' in s:
        return None
    return 'eride' if is_ebike(sport) or bike_kind == 'ebike' else 'ride'


def family_of(db, act_id):
    """segment_family for an activity id, from its sport and its bike. None when there is no such activity."""
    try:
        row = db.execute('SELECT a.sportType, b.kind FROM Activity a LEFT JOIN Bike b ON b.id = a.bikeId WHERE a.id=?', [act_id]).fetchone()
    except Exception:                                     # no Bike table (a bare test database)
        row = db.execute('SELECT sportType, NULL FROM Activity WHERE id=?', [act_id]).fetchone()
    return segment_family(row[0], row[1]) if row else None
