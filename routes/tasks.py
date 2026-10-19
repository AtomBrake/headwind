"""The Tasks page: what Headwind is doing in the background and what the start-up repairs changed (services/tasks.py)."""
from flask import Blueprint, flash, redirect, render_template, url_for

from database import get_db

bp = Blueprint('tasks', __name__)


@bp.route('/tasks')
def index():
    from services import tasks
    db = get_db()
    view = tasks.overview(db)
    db.execute("UPDATE TaskLog SET seen=1 WHERE task LIKE 'startup:%' AND seen=0")      # the notice has done its job
    db.commit()
    return render_template('tasks.html', **view)


@bp.route('/tasks/run/<job>', methods=['POST'])
def run_now(job):
    """Wake a waiting job instead of letting it sleep out its interval or its retry delay."""
    from services import garmin
    db = get_db()
    if job == 'garmin':
        garmin.SYNC_WAKE.set()
        flash('Garmin sync started. Refresh in a minute to see how it went.', 'success')
    elif job == 'garmin-retry':
        from services import garmin_failures
        n = garmin_failures.retry_all(db)
        db.commit()
        garmin.SYNC_WAKE.set()
        flash(f"Trying {n} activit{'y' if n == 1 else 'ies'} again: the Garmin sync has started. Refresh in a minute to see how it went.", 'success')
    elif job in ('history', 'weights'):
        db.execute(f"UPDATE Settings SET {'garminHistoryRetryAt' if job == 'history' else 'garminWeightsRetryAt'}=NULL WHERE id=1")
        db.commit()
        garmin.HISTORY_WAKE.set()
        flash('Trying again now.', 'success')
    return redirect(url_for('tasks.index'))
