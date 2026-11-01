"""What the frame of every page needs from the database (units, appearance, the rider mode, the Tasks and Import badges), read in one statement
and kept in g for the rest of the request, where it used to be six queries a page. Only inside a request: a background job's app context can
live for minutes, and these can change under it.

get() returns None when there's no request or the statement fails (tables not made yet, the very first request): each caller then reads its
own value the way it did before."""
import logging

from flask import g, has_request_context

log = logging.getLogger(__name__)


def _statement():
    from services import strava_export, tasks
    n = len(strava_export.REIMPORT_ADVISED)
    advised = f'({strava_export.ADVISED_COUNT_SQL})' if n else '0'
    return (f'''SELECT (SELECT units FROM Settings WHERE id=1) AS units,
                       (SELECT appearance FROM Settings WHERE id=1) AS appearance,
                       (SELECT COUNT(*) FROM Rider r WHERE NOT EXISTS (SELECT 1 FROM Friend f WHERE f.riderId = r.id)) AS localRiders,
                       (SELECT id FROM Rider WHERE isDefault=1 ORDER BY id LIMIT 1) AS ownerId,
                       ({tasks.UNSEEN_STARTUP_SQL}) AS startupUnseen,
                       {advised} AS reimportAdvised''', [n, n] if n else [])


def get():
    """The row (units, appearance, localRiders, ownerId, startupUnseen, reimportAdvised) for this request, or None."""
    if not has_request_context():
        return None
    if '_page_facts' not in g:
        try:
            from database import get_db
            g._page_facts = get_db().execute(*_statement()).fetchone()
        except Exception:
            log.debug('Page facts unavailable', exc_info=True)
            g._page_facts = None
    return g._page_facts
