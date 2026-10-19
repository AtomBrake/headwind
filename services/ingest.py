"""What every newly stored ride gets, whichever way it arrived (Garmin sync, file import, phone upload): matched against segments, and checked by the
sanity rails. One place, so a new import path cannot forget one of them. Never raises; does not commit."""
import logging

log = logging.getLogger(__name__)


def after_ride_added(db, act_id):
    from services import sanity
    from services.segments import scan_new_ride
    try:
        sanity.flag(db, act_id)
    except Exception:
        log.warning('Sanity check of a new activity failed', exc_info=True)
    scan_new_ride(db, act_id)


def after_ride_removed():
    """What every deleted ride gets, once the delete is committed: the Home Assistant sensors are re-published, so their totals drop now rather than
    at the next ride. (The web pages need nothing: they work everything out from Activity on each load.) Never raises."""
    try:
        from services.mqtt import push_update
        push_update(background=True)
    except Exception:
        log.warning('Home Assistant update after a delete failed', exc_info=True)
