"""Which activities are rides. Every activity, of every sport, is a row in Activity; the rides are the ones whose sport says so. The Ride and
Workout views (database.migrate_db) are built from RIDE_SQL and Python code asks is_ride, so the two can never disagree.

A sport is a ride when it contains "ride" or "cycl", ignoring case: Headwind's own Ride and VirtualRide, Strava's "Virtual Ride", "E-Bike Ride",
"Gravel Ride" and "Mountain Bike Ride", Garmin's cycling types. A row with no sport counts as a ride, as the import treats it (routes/import_rides._insert)."""

RIDE_SQL = "(sportType IS NULL OR sportType = '' OR lower(sportType) LIKE '%ride%' OR lower(sportType) LIKE '%cycl%')"


def is_ride(sport):
    s = (sport or '').lower()
    return not s or 'ride' in s or 'cycl' in s
