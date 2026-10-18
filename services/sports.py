"""Which activities are rides. Every activity, of every sport, is a row in Activity; the rides are the ones whose sport says so. The Ride view
(database.migrate_db) is built from RIDE_SQL and Python code asks is_ride, so the two can never disagree. Nothing else should test a sport for "ride".

A sport is a ride when it contains "ride" or "cycl", ignoring case: Headwind's own Ride and VirtualRide, Strava's "Virtual Ride", "E-Bike Ride",
"Gravel Ride" and "Mountain Bike Ride", Garmin's cycling types. A row with no sport counts as a ride, as the import treats it (routes/import_rides._insert)."""

RIDE_SQL = "(sportType IS NULL OR sportType = '' OR lower(sportType) LIKE '%ride%' OR lower(sportType) LIKE '%cycl%')"
KIND_SQL = f"(CASE WHEN {RIDE_SQL} THEN 'ride' ELSE 'workout' END)"     # the phone API's and the bulk actions' 'ride' / 'workout'

# The sports Headwind itself writes: typed in by hand, recorded by the phone, picked in "change the type", saved by the Garmin sync.
RIDES = ('Ride', 'VirtualRide')
ON_FOOT = ('Walk', 'Run', 'Hike')                     # what the phone records, and what calories can be estimated for (workouts.estimate_calories)
OTHER = ('Swim', 'Surf', 'Paddle', 'Row', 'Ski', 'Skate', 'Golf', 'Climb', 'Other')   # Garmin activities that are neither rides nor on foot
WORKOUTS = ON_FOOT + OTHER
SPORTS = RIDES + WORKOUTS


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
