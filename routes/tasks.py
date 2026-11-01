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
                              lambda work_dir, report: copy.build(database, work_dir, no_gps=no_gps, no_streams=no_streams),
                              f"headwind-troubleshooting-{datetime.now():%Y-%m-%d-%H%M}.zip",
                              url_for('tasks.index') + '#copy', url_for('tasks.troubleshooting_copy_download'))
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


@bp.route('/tasks/background')
def background():
    """What the pill at the top of every page shows (templates/base.html): an import started on the Import page, and the files being made
    to download (services/downloads.py), while they run and until their outcome is dismissed."""
    from routes import import_rides
    from services import downloads
    items = []
    imp = import_rides.progress()
    if imp:
        state = 'failed' if imp.get('error') else 'running' if imp['running'] else 'done'
        items.append({'id': 'import', 'state': state, 'url': url_for('import_rides.index'),
                      'text': f"Import failed: {imp['error']}" if state == 'failed'
                      else (f"Importing {imp.get('done') or 0} / {imp['total']}" if imp.get('total') else 'Importing…') if state == 'running'
                      else f"✓ Import done · {imp.get('imported') or 0} imported",
                      'pct': round((imp.get('done') or 0) / imp['total'] * 100) if state == 'running' and imp.get('total') else None})
    for kind, d in downloads.notices().items():
        state = {'ready': 'done'}.get(d['state'], d['state'])
        items.append({'id': f'download:{kind}', 'state': state, 'url': d['url'] if state == 'done' else d['page'] if state == 'running' else url_for('tasks.index'),
                      'text': f"{d['label']} · {d['progress'] or 'Starting'}…" if state == 'running'
                      else f"✓ {d['label']} ready ({d['size_text']}): Download" if state == 'done'
                      else f"{d['label']} failed: {d['error']}",
                      'pct': d['pct'] if state == 'running' else None})
    return jsonify(items=items)


@bp.route('/tasks/background/dismiss', methods=['POST'])
def background_dismiss():
    from routes import import_rides
    from services import downloads
    item = request.form.get('id') or ''
    if item == 'import':
        import_rides.dismiss()
    elif item.startswith('download:'):
        downloads.dismiss(item.split(':', 1)[1])
    return jsonify(ok=True)


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
