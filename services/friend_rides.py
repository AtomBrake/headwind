"""Activities synced from a friend (routes/friends._store_ride): shown here, changed only on their instance. The next sync takes every shared
field again, and this instance's bikes, kit, notes, photos or AI coach mean nothing on someone else's ride, so the activity page offers none
of it and every route that changes an activity refuses one of these."""

FRIEND_RIDERS_SQL = 'SELECT riderId FROM Friend WHERE riderId IS NOT NULL'
REFUSED = "This is a friend's activity: it can only be changed on their instance."


def friend_of(db, act_id):
    """The Friend row (name, lastSynced, ...) whose activity this is, or None for one of this instance's own (or no such activity)."""
    return db.execute('SELECT f.* FROM Activity a JOIN Friend f ON f.riderId = a.riderId WHERE a.id=?', [str(act_id)]).fetchone()


def refuse(db, act_id):
    """Raises ValueError(REFUSED) for a friend's activity, so the service that changes it stops before writing anything."""
    if friend_of(db, act_id):
        raise ValueError(REFUSED)
