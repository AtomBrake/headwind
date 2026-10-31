"""The Tasks page: what Headwind is doing in the background and what the start-up repairs changed (services/tasks.py)."""
from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for

from database import get_db

bp = Blueprint('tasks', __name__)


@bp.route('/tasks')
def index():
    from services import tasks
    db = get_db()
    view = tasks.overview(db)
    db.execute("UPDATE TaskLog SET seen=1 WHERE task LIKE 'startup:%' AND seen=0")      # the notice has done its job
    db.commit()
    from services import downloads, logs, troubleshooting_copy
    return render_template('tasks.html', log_file=logs.file_path(), copy=downloads.status(troubleshooting_copy.KIND), **view)


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


@bp.route('/tasks/diagnostics')
def diagnostics():
    """One zip to attach to a bug report: recent logs, version, settings without secrets, row counts, recent runs (services/diagnostics.py)."""
    import io
    from services import diagnostics as diag
    data = diag.build_zip(get_db(), current_app.config['DATABASE'])
    return send_file(io.BytesIO(data), mimetype='application/zip', as_attachment=True,
                     download_name=f"headwind-diagnostics-{datetime.now():%Y-%m-%d-%H%M}.zip")


@bp.route('/tasks/troubleshooting-copy', methods=['POST'])
def troubleshooting_copy():
    """Start making the database copy for someone helping with a problem (services/troubleshooting_copy.py), in the background
    (services/downloads.py): on a big database it can take longer than a proxy waits. The card polls the status and offers the download."""
    from services import downloads, troubleshooting_copy as copy
    no_gps, no_streams = bool(request.form.get('no_gps')), bool(request.form.get('no_streams'))
    database = current_app.config['DATABASE']
    started = downloads.start(current_app._get_current_object(), copy.KIND, 'Copy for troubleshooting',
                              lambda work_dir: copy.build(database, work_dir, no_gps=no_gps, no_streams=no_streams),
                              f"headwind-troubleshooting-{datetime.now():%Y-%m-%d-%H%M}.zip")
    if not started:
        flash('A copy is already being made: it will be offered here when it\'s ready.', 'error')
    return redirect(url_for('tasks.index') + '#copy')


@bp.route('/tasks/troubleshooting-copy/status')
def troubleshooting_copy_status():
    from services import downloads, troubleshooting_copy as copy
    return jsonify(downloads.status(copy.KIND))


@bp.route('/tasks/troubleshooting-copy/download')
def troubleshooting_copy_download():
    from services import downloads, troubleshooting_copy as copy
    made = downloads.ready(copy.KIND)
    if not made:
        flash('That copy is no longer kept: make it again.', 'error')
        return redirect(url_for('tasks.index') + '#copy')
    return send_file(made[0], mimetype='application/zip', as_attachment=True, download_name=made[1])


@bp.route('/tasks/troubleshooting-copy/delete', methods=['POST'])
def troubleshooting_copy_delete():
    from services import downloads, troubleshooting_copy as copy
    downloads.discard(copy.KIND)
    return redirect(url_for('tasks.index') + '#copy')


@bp.route('/tasks/logs')
def logs_json():
    """The Logs card: the newest log records, filtered by level and by text (a request id finds that request's lines)."""
    from services import logs
    if not logs.file_path():
        return jsonify(records=[], more=False, files=0, off=True)
    try:
        limit = max(1, min(int(request.args.get('limit') or 200), 1000))
    except ValueError:
        limit = 200
    return jsonify(logs.read(limit, (request.args.get('level') or 'INFO').upper(), request.args.get('q') or ''))
