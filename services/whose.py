"""Whose data a request is about: the one place that decides it (docs/MULTI-USER-PLAN.md, release A1). A route never picks a rider itself.

rider_id() is the rider the request is about. Today that's the owner (the isDefault rider); once there are logins (release C) it's the signed-in
user's. So a caller mustn't take it to mean "the owner": for "is this the owner?" on screen there's page_facts' ownerId, and for what really
belongs to the instance (the feed a friend's Headwind reads, the Home Assistant sensors) there's rider_mode.owner_rider_id().

viewable(want) says whether ?rider=N, or a form's rider, may be shown, and how.

Only inside a request. Background work (the Garmin loops, MQTT, the jobs) is handed its rider as an argument instead, so both raise there: a
caller that was missed fails loudly rather than quietly working on the owner's data."""
from collections import namedtuple

from flask import has_request_context

from database import get_db, query_db

OWN, LOCAL, FRIEND, FRIENDS = 'own', 'local', 'friend', 'friends'

# id: the rider's id ('friends' for FRIENDS); how: one of the four above; ids: FRIENDS' rider ids, else (id,)
View = namedtuple('View', 'id how ids')


class OutsideRequest(RuntimeError):
    """whose was asked outside a request, where there's nobody it could be about."""


def _in_request():
    if not has_request_context():
        raise OutsideRequest('whose: no request, so no rider to be about. Background work is given its rider as an argument.')


def rider_id():
    """The id of the rider this request is about (today the owner's), or None before there is one (the setup wizard)."""
    _in_request()
    from services.rider_mode import owner_rider_id
    return owner_rider_id()


def rider():
    """rider_id()'s Rider row, or None."""
    rid = rider_id()
    return query_db('SELECT * FROM Rider WHERE id=?', [rid], one=True) if rid is not None else None


def viewable(want, friends=False):
    """How ?rider=want (or a form's rider) may be shown: a View, or None when it may not be.
      OWN      the request's own rider, which is also the answer for no want at all ('' or None)
      LOCAL    another rider who lives here: shown and changed as your own, in multi-rider mode only (services/rider_mode)
      FRIEND   a friend's rider, made by friend sync: shown, never changed (services/friend_rides)
      FRIENDS  only with friends=True (the dashboard's and Activities' ?rider=friends): every friend's rider together, None until one has synced
    None for anything else: not a number, no such rider, or another rider in single-rider mode. The caller decides what that means: most pages
    show the request's own rider instead, the phone's API answers 404."""
    _in_request()
    own = rider_id()
    if want is None or (isinstance(want, str) and not want.strip()):
        return View(own, OWN, (own,))
    db = get_db()
    if friends and want == FRIENDS:
        from services import friend_rides
        ids = tuple(friend_rides.friend_riders(db))
        return View(FRIENDS, FRIENDS, ids) if ids else None
    try:
        rid = int(want)
    except (TypeError, ValueError):
        return None
    if rid == own:
        return View(own, OWN, (own,))
    if not db.execute('SELECT 1 FROM Rider WHERE id=?', [rid]).fetchone():
        return None
    from services import friend_rides
    if friend_rides.is_friend_rider(db, rid):
        return View(rid, FRIEND, (rid,))
    from services.rider_mode import multi_rider
    return View(rid, LOCAL, (rid,)) if multi_rider() else None
