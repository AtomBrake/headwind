import csv
import gzip
import hmac
import io
import json
import logging
import os
import tempfile
import time
import traceback
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, render_template, request

from database import get_db, query_db
from services.parser import ACTIVITY_EXTENSIONS, parse_activity_file
from services.limits import safe_gunzip, safe_zip_read, check_zip
from services.sports import RIDES, canonical, label
from services import jobs
from services import streams as _streams

log = logging.getLogger(__name__)

bp = Blueprint('import_rides', __name__)


@bp.route('/import')
def index():
    from database import query_db
    from services import reimport, strava_gear
    from services import strava_export
    from services import whose
    from services import garmin, garmin_changes, merged_sport, recently_deleted, sport_fix, sport_guess, tasks
    riders = query_db('SELECT id, name FROM Rider ORDER BY isDefault DESC, name ASC')
    return render_template('import.html', riders=riders, changes=reimport.pending(get_db()), problems=reimport.problems(get_db()),
                           binned=recently_deleted.listing(get_db()), bin_days=recently_deleted.DAYS,
                           garmin_changes=garmin_changes.pending(get_db()), garmin_check=tasks.last(get_db(), garmin_changes.TASK),
                           garmin_missing=garmin_changes.not_here(get_db()), garmin_deleted=garmin_changes.not_here(get_db(), deleted=True),
                           garmin_full=bool(query_db("SELECT 1 FROM Settings WHERE id=1 AND garminSyncMode='full'", one=True)),
                           strava_pending=strava_gear.pending(get_db(), whose.rider_id()),
                           sport_groups=merged_sport.groups(merged_sport.conflicts(get_db())), sport_fixes=sport_fix.count(get_db(), whose.rider_id()),
                           sport_guesses=sport_guess.pending(get_db()),
                           kept=strava_export.kept(get_db(), current_app.config['DATABASE']),
                           advice=strava_export.advice(get_db(), current_app.config['DATABASE']),
                           out_of_step=reimport.out_of_step(get_db()),
                           garmin_on=garmin.connected(query_db('SELECT garminEmail, garminPassword FROM Settings WHERE id=1', one=True)))


@bp.route('/import/deleted/<path:act_id>/<choice>', methods=['POST'])
def deleted_resolve(act_id, choice):
    """Recently deleted (services/recently_deleted.py): 'restore' puts one back as it was; 'empty' deletes it for good now (its id stays
    remembered, so no sync brings it back)."""
    from flask import abort, flash, redirect, url_for
    from services import recently_deleted
    db = get_db()
    if choice == 'restore':
        kept = recently_deleted.restore(db, act_id)
        if kept:
            row = db.execute('SELECT name, sportType FROM Activity WHERE id=?', [kept]).fetchone()
            from services.sports import label
            what = (row['name'] or label(row['sportType'])) if row else 'the activity'
            flash(f'Restored {what}.' if kept == act_id else
                  f'Restored, and set aside as another recording of {what}, which arrived while it was deleted.', 'success')
            try:
                from services.mqtt import push_later
                push_later()                             # the Home Assistant totals take it back now, not at the next ride
            except Exception:
                log.warning('Home Assistant update after a restore failed', exc_info=True)
    elif choice == 'empty':
        recently_deleted.empty(db, [act_id], current_app.config['DATABASE'])
        db.commit()
    else:
        abort(400)
    return redirect(url_for('import_rides.index') + '#deleted')


@bp.route('/import/sports/<path:dup_id>/<choice>', methods=['POST'])
def sports_resolve(dup_id, choice):
    """Merged activities whose two recordings disagree about the sport (services/merged_sport.py). choice 'other': take the other recording's
    sport; 'kept': the kept one's is right. dup_id 'all' settles every one with the sports in the form's `kept` and `other`. Back to the
    activity's page when it came from there."""
    from flask import abort, flash, redirect, url_for
    from services import merged_sport
    from services.ingest import after_ride_removed
    from services.sports import label
    if choice not in ('other', 'kept'):
        abort(400)
    db = get_db()
    if dup_id == 'all':
        pair = (request.form.get('kept') or '', request.form.get('other') or '')
        found = [c for c in merged_sport.conflicts(db) if c['pair'] == pair]
    else:
        found = merged_sport.conflicts(db, dup_ids=[dup_id])
    failed = []
    if choice == 'other':
        n, failed = merged_sport.use_other(db, found)
    else:
        n = merged_sport.keep(db, found)
    db.commit()
    if choice == 'other' and n:
        after_ride_removed()                            # the Home Assistant totals follow an activity that became another sport
    back = request.form.get('back') or ''
    if dup_id != 'all' and back.startswith('/') and not back.startswith('//'):
        if failed:
            flash(failed[0][1], 'error')
        return redirect(back)
    if choice == 'other':
        flash(f"{n:,} activit{'y' if n == 1 else 'ies'} now {'has' if n == 1 else 'have'} the other recording's sport"
              + (f"; {len(failed)} couldn't be changed: {failed[0][1]}" if failed else '') + '.', 'error' if failed else 'success')
    else:
        flash(f"{n:,} activit{'y' if n == 1 else 'ies'} left as {label(found[0]['sportType']) if found else 'they are'}.", 'success')
    return redirect(url_for('import_rides.index') + '#sports')


@bp.route('/import/sport-guess/<path:act_id>/<choice>', methods=['POST'])
def sport_guess_resolve(act_id, choice):
    """An upload whose file didn't say its sport but that moved like a run or a walk (services/sport_guess.py). choice 'use': make it that;
    'keep': the file was right. act_id 'all': every one still asked about. Back to the activity's page when it came from there."""
    from flask import abort, flash, redirect, url_for
    from services import sport_guess
    from services.ingest import after_ride_removed
    if choice not in ('use', 'keep'):
        abort(400)
    db = get_db()
    ids = [g['activityId'] for g in sport_guess.pending(db)] if act_id == 'all' else [act_id]
    n, failed = sport_guess.answer(db, ids, choice == 'use')
    db.commit()
    if choice == 'use' and n:
        after_ride_removed()                            # the Home Assistant ride totals drop the runs that moved out
    back = request.form.get('back') or ''
    if act_id != 'all' and back.startswith('/') and not back.startswith('//'):
        if failed:
            flash(failed[0][1], 'error')
        return redirect(back)
    if choice == 'use':
        flash(f"{n:,} activit{'y' if n == 1 else 'ies'} changed to what {'its' if n == 1 else 'their'} pace says"
              + (f"; {len(failed)} couldn't be changed: {failed[0][1]}" if failed else '') + '.', 'error' if failed else 'success')
    else:
        flash(f"{n:,} activit{'y' if n == 1 else 'ies'} left as {'it is' if n == 1 else 'they are'}.", 'success')
    return redirect(url_for('import_rides.index') + '#sport-guess')


@bp.route('/import/problems/clear', methods=['POST'])
def clear_problems():
    """Take the list of files the imports couldn't read off the Import page (the activities stay as they are)."""
    from flask import redirect, url_for
    db = get_db()
    db.execute('DELETE FROM ImportProblem')
    db.commit()
    return redirect(url_for('import_rides.index'))


@bp.route('/import/changes/<path:ride_id>/<choice>', methods=['POST'])
def resolve_change(ride_id, choice):
    """Settle a re-imported ride that differs from the saved one: keep | replace | fill (services/reimport.py). ride_id 'all' settles every one,
    or for fill every one with a gap to fill: the rest stay to be chosen."""
    from flask import flash, redirect, url_for
    from services import reimport
    db = get_db()
    ids = [c['activityId'] for c in reimport.pending(db) if choice != 'fill' or c['fills']] if ride_id == 'all' else [ride_id]
    try:
        changed = sum(1 for i in ids if reimport.resolve(db, i, choice))
    except ValueError as e:
        db.rollback()
        flash(str(e), 'error')
        return redirect(url_for('import_rides.index'))
    db.commit()
    if changed:
        try:
            from services.mqtt import push_later
            push_later()
        except Exception:
            log.warning('Home Assistant update after the import failed', exc_info=True)
    n = len(ids)
    flash({'keep': f"Kept the saved version of {n} ride{'s' if n != 1 else ''}.",
           'replace': f"Updated {changed} ride{'s' if changed != 1 else ''} from the import.",
           'fill': f"Filled in missing data on {changed} ride{'s' if changed != 1 else ''}."}[choice], 'success')
    return redirect(url_for('import_rides.index') + '#changes')


@bp.route('/import/upload', methods=['POST'])
def upload():
    """Save the upload and queue its import for the background worker: {job} for the page to follow (static/js/app.js followJob), or
    {error}. The import goes on whether or not the page stays open."""
    f = request.files.get('zipfile')
    if not f or not f.filename:
        return jsonify(error='No file selected')
    if _active(get_db()):
        return jsonify(error='An import is already running')

    from services import strava_export, whose
    try:
        rider_id = int(request.form.get('riderId') or 0) or None
    except ValueError:
        rider_id = None
    if rider_id is None:
        rider_id = whose.rider_id()

    name_lower = f.filename.lower()
    is_single = name_lower.endswith(ACTIVITY_EXTENSIONS)
    suffix = next((e for e in ACTIVITY_EXTENSIONS if name_lower.endswith(e)), '.zip')
    db_path = current_app.config['DATABASE']
    # beside the database, where the worker reads it: a Strava export kept for Import again is moved, not copied (GBs)
    strava_export.clear_stale_uploads(db_path)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=strava_export.UPLOAD_PREFIX, dir=strava_export.export_dir(db_path))
    f.save(tmp)
    tmp.close()
    return _queue({'upload': tmp.name, 'filename': f.filename, 'single': is_single, 'rider': rider_id,
                   'segments': request.form.get('importSegments') == '1',       # a Strava export's segments.csv: off unless asked for
                   'routes': request.form.get('importRoutes') == '1',           # its routes/*.gpx, into the planner: off unless asked for
                   'photos': request.form.get('importPhotos', '1') == '1',      # its photos: on unless turned off
                   'keep': request.form.get('keepExport', '1') == '1'})         # a Strava export kept for Import again: on unless turned off


@bp.route('/import/strava-export/<int:rider_id>/again', methods=['POST'])
def import_again(rider_id):
    """Import a rider's kept Strava export again (services/strava_export.py), with the options ticked on the page. The file stays kept."""
    from services import strava_export
    if _active(get_db()):
        return jsonify(error='An import is already running')
    path = strava_export.path_for(current_app.config['DATABASE'], rider_id)
    if not os.path.isfile(path) or not get_db().execute('SELECT 1 FROM StravaExport WHERE riderId=?', [rider_id]).fetchone():
        return jsonify(error='That export is no longer kept')
    return _queue({'again': rider_id, 'segments': request.form.get('importSegments') == '1', 'routes': request.form.get('importRoutes') == '1',
                   'photos': request.form.get('importPhotos', '1') == '1'})


def _queue(args):
    job = jobs.enqueue(get_db(), 'import', args)
    if job is None:                                     # another got in first
        if args.get('upload'):
            _unlink(args['upload'])
        return jsonify(error='An import is already running')
    return jsonify(job=job)


def _active(db):
    return jobs.active(db, 'import')


def clear_uploads(db):
    """When the worker starts: the uploads of imports a restart cut short (gigabytes, for a Strava export), not a day later. Not one a queued
    import will read, nor one still arriving from a browser."""
    from services import strava_export
    waiting = {json.loads(r[0]).get('upload') for r in db.execute("SELECT args FROM Job WHERE kind='import' AND state='queued'")}
    strava_export.clear_stale_uploads(current_app.config['DATABASE'], waiting, idle=600)


def _unlink(path):
    try:
        os.unlink(path)                                 # gone already when the export was kept
    except FileNotFoundError:
        pass


class _Log:
    """What an import says, as the page reads it: each event (_event's text) in order, through jobs.Events, with its fields merged into the
    job's progress for the indicator on every page. Progress counts go at most once a second (and the last one at the end): a big export has
    thousands."""

    def __init__(self, ev):
        self.ev, self.held, self.sent = ev, None, 0.0

    @property
    def state(self):
        return {**self.ev.state, **(self.held or {})}

    def put(self, item):
        d = json.loads(item[len('data: '):])
        if 'done' in d and 'complete' not in d:
            self.held = d
            if time.monotonic() - self.sent < 1:
                return
        self.flush()
        if self.held is not d:
            self.ev.emit(d)

    def flush(self):
        if self.held is not None:
            self.ev.emit(self.held)
            self.held, self.sent = None, time.monotonic()


@jobs.handler('import')
def _import_job(job):
    """An upload (args: upload, filename, single, rider, segments, routes, photos, keep) or a kept Strava export read again (args: again, the
    rider)."""
    a = job['args']
    with jobs.Events(job, state=True) as ev:
        out = _Log(ev)
        try:
            if a.get('again'):
                _read_again(out, a['again'], a['segments'], a['photos'], a.get('routes'))
            else:
                _read_upload(out, a)
        except zipfile.BadZipFile:
            log.error('Import failed: bad zip file')
            out.flush()
            ev.emit({'error': 'Not a valid zip file'})
            raise
        except Exception as e:
            log.error('Import failed: %s\n%s', e, traceback.format_exc())
            out.flush()
            ev.emit({'error': str(e)})
            raise
        finally:
            out.flush()
            if a.get('upload'):
                _unlink(a['upload'])


def _read_upload(out, a):
    from services import strava_export
    path, rider_id = a['upload'], a['rider']
    if a['single']:
        for item in _process_single_file(path, a['filename'], rider_id):
            out.put(item)
        return
    done = None
    with zipfile.ZipFile(path) as zf:
        check_zip(zf)
        names = set(zf.namelist())
        log.info('Import started — %d files in zip, has_csv=%s', len(names), 'activities.csv' in names)
        strava = 'activities.csv' in names
        if strava:
            gen = _process_strava_export(zf, names, rider_id, segments=a['segments'], photos=a['photos'], routes=a.get('routes'))
        else:
            gen = _process_generic_zip(zf, names, rider_id)
        for item in gen:
            if strava and '"complete": true' in item:
                done = json.loads(item[len('data: '):])     # held back until the zip is closed and kept, so the summary can say so
            else:
                out.put(item)
    if done is not None:
        if rider_id:
            strava_export.note_read(get_db(), rider_id)
        if a['keep'] and rider_id:
            try:
                strava_export.keep(get_db(), current_app.config['DATABASE'], rider_id, path, out.state.get('total'), a['segments'], a['photos'])
                done['kept'] = True
            except OSError as e:
                log.error('Strava import: could not keep the export (%s)', e)
        out.put(_event(done))


def _read_again(out, rider_id, segments, photos, routes=False):
    from services import strava_export
    with zipfile.ZipFile(strava_export.path_for(current_app.config['DATABASE'], rider_id)) as zf:
        check_zip(zf)
        names = set(zf.namelist())
        log.info('Import again of the kept Strava export for rider %s — %d files in zip', rider_id, len(names))
        for item in _process_strava_export(zf, names, rider_id, segments=segments, photos=photos, routes=routes):
            out.put(item)
    strava_export.read_again(get_db(), rider_id, out.state.get('total'), segments, photos)
    strava_export.note_read(get_db(), rider_id)


@bp.route('/import/strava-export/<int:rider_id>/not-now', methods=['POST'])
def advice_not_now(rider_id):
    """Put off the advice to import the export again (services/strava_export.advice) until a newer release adds to it."""
    from flask import redirect, url_for
    from services import strava_export
    strava_export.dismiss(get_db(), rider_id)
    return redirect(url_for('import_rides.index'))


@bp.route('/import/strava-export/<int:rider_id>/delete', methods=['POST'])
def delete_kept(rider_id):
    from flask import flash, redirect, url_for
    from services import strava_export
    if _active(get_db()):
        flash('An import is running: delete the export once it has finished.', 'error')
        return redirect(url_for('import_rides.index'))
    db = get_db()
    strava_export.forget(db, current_app.config['DATABASE'], rider_id)
    db.commit()
    flash('Deleted the kept Strava export. Its activities stay as they are.', 'success')
    return redirect(url_for('import_rides.index'))


def _latest(db):
    """The last import's job, unless its outcome has been shown (the page that followed it to the end, or the indicator dismissed)."""
    job = jobs.last(db, 'import')
    if job is None or (job['state'] in ('done', 'failed') and (job['progress'] or {}).get('delivered')):
        return None
    return job


@bp.route('/import/status')
def status():
    """{job} of the import still running after the page was left, or of one that finished while nobody was watching, shown once; {} when
    there is neither. The page follows it as it does one it started."""
    job = _latest(get_db())
    return jsonify(job=job['id']) if job else jsonify({})


@bp.route('/import/progress')
def progress():
    """Snapshot of the background import for the indicator every page shows: {} when there is nothing to show."""
    job = _latest(get_db())
    if job is None:
        return {}
    state = {k: v for k, v in (job['progress'] or {}).items() if k != 'delivered'}
    if job['state'] == 'failed' and not state.get('error'):
        state['error'] = job['error']                   # cut short by a restart (jobs.fail_orphans), or failed before it said why
    return dict(state, running=job['state'] in ('queued', 'running'))


@bp.route('/import/progress/dismiss', methods=['POST'])
def dismiss():
    db = get_db()
    job = jobs.last(db, 'import')
    if job is not None and job['state'] in ('done', 'failed'):
        jobs.progress(db, job['id'], delivered=True)
    return {}


@bp.route('/import/api/upload-ride', methods=['POST'])
def api_upload_ride():
    """Token-authenticated ride upload for headless senders (e.g. the Raspberry Pi that sees a Garmin plugged in).

    POST multipart: `file` (.fit / .gpx / .tcx, optionally .gz) and `rider` (a Rider name, case-insensitive — required, so a ride can never
    land on the wrong rider by default). Auth: header `X-Upload-Token` must equal RIDE_UPLOAD_TOKEN from .env (endpoint is disabled
    when the variable is unset). Goes through the same pipeline as the web import, so it is idempotent: a file already imported
    (same start time + distance) is reported as skipped, never duplicated.
    Returns JSON {status: imported|skipped|error, ...}.
    """
    expected = os.environ.get('RIDE_UPLOAD_TOKEN', '')
    given = request.headers.get('X-Upload-Token', '')
    if not expected or not hmac.compare_digest(expected.encode(), given.encode()):
        return {'status': 'error', 'error': 'unauthorised'}, 401
    f = request.files.get('file')
    name = (request.form.get('rider') or '').strip()
    if not f or not f.filename:
        return {'status': 'error', 'error': 'no file'}, 400
    if not name:
        return {'status': 'error', 'error': 'rider is required'}, 400
    rider = query_db('SELECT id, name FROM Rider WHERE lower(name)=lower(?)', [name], one=True)
    if not rider:
        return {'status': 'error', 'error': f'unknown rider {name!r}'}, 400
    suffix = '.gz' if f.filename.lower().endswith('.gz') else os.path.splitext(f.filename)[1].lower()
    if suffix not in ('.fit', '.gpx', '.tcx', '.gz'):
        return {'status': 'error', 'error': 'only .fit / .gpx / .tcx files'}, 400
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        f.save(tmp.name)
    try:
        result = {'imported': 0, 'skipped': 0, 'errors': 0}
        for ev in _process_single_file(tmp.name, f.filename, rider['id']):
            payload = json.loads(ev[len('data: '):]) if ev.startswith('data: ') else {}
            if payload.get('complete'):
                result = {k: payload.get(k, 0) for k in ('imported', 'skipped', 'errors')}
            elif payload.get('error'):
                return {'status': 'error', 'error': payload['error']}, 422
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    log.warning('API ride upload: rider=%s file=%s -> %s', rider['name'], f.filename, result)
    if result['errors']:
        return {'status': 'error', 'error': 'import failed', **result}, 500
    return {'status': 'imported' if result['imported'] else 'skipped', 'rider': rider['name'], **result}


def _process_single_file(path, original_name, rider_id=None, bike_id=None, client_id=None):
    """bike_id (the phone app's choice, already checked to be the rider's) goes on the ride instead of the default bike. client_id is the phone's
    id for the upload (services/uploads.py), kept on the ride before the duplicate check, so a copy set aside keeps it too."""
    yield _event({'total': 1, 'source': 'files'})
    db = get_db()
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
        name_lower = original_name.lower()
        if name_lower.endswith('.gz'):
            data = safe_gunzip(data)
        if not name_lower.endswith(ACTIVITY_EXTENSIONS):
            yield _event({'error': 'Unsupported file type'})
            return
        act = parse_activity_file(name_lower, data)

        if not act or not act.get('startDateLocal'):
            yield _event({'error': 'Could not parse activity from file'})
            return

        act_summary = {'id': act.get('id'), 'name': act.get('name'), 'distance': act.get('distance')}

        from services import duplicates
        if not duplicates.exists_anywhere(db, act['id']):
            _weather_first(act)                         # before the first write: the weather service is slow
        _retime_file_copies(db, rider_id, act)
        if duplicates.exists_anywhere(db, act['id']):
            differs = _offer_change(db, act, original_name)
            db.commit()
            log.warning('Single file import: already exists id=%s%s', act['id'], ' (differs: waiting for review)' if differs else '')
            yield _progress(1, 1, 0, 0 if differs else 1, 0)
            yield _event({'complete': True, 'imported': 0, 'skipped': 0 if differs else 1, 'changed': 1 if differs else 0, 'errors': 0, 'activity': act_summary})
            return

        _insert(db, act, rider_id)
        if client_id:
            db.execute('UPDATE Activity SET clientId=? WHERE id=?', [client_id, act['id']])
        if bike_id:                                     # before the segment scan, so an e-bike's efforts race for e-bike PRs from the start
            db.execute('UPDATE Activity SET bikeId=? WHERE id=?', [bike_id, act['id']])
            from services import gear as _gear
            _gear.ebike_sport(db, [act['id']])          # a ride on an e-bike is an e-bike ride
        from services.best_efforts import save_best_efforts
        save_best_efforts(db, act.get('id'), act.get('startDateLocal'), act.get('streams'))
        from services import sport_records
        sport_records.index(db, act.get('id'), act.get('startDateLocal'), act.get('sportType'), act.get('streams'))   # a run's or swim's best times
        db.commit()
        log.info('Single file import: imported id=%s name=%s', act['id'], act.get('name'))

        try:
            from services import sanity
            sanity.flag(db, act['id'])
            db.commit()
        except Exception:
            log.warning('Sanity check of an imported activity failed', exc_info=True)
        try:
            from services.segments import scan_activity_against_segments, _refresh_prs
            segments = db.execute('SELECT * FROM Segment').fetchall()
            if segments:
                act_row = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [act['id']]).fetchone()
                if act_row:
                    scan_activity_against_segments(db, act_row, segments)
                    for seg in segments:
                        _refresh_prs(db, seg['id'])
                    db.commit()
        except Exception:
            log.warning('Segment scan of an imported activity failed: its segment efforts are missing', exc_info=True)

        dup = None
        try:                                            # same ride already recorded by another device? keep the better one
            dup = duplicates.resolve(db, act['id'])
            from services import gear
            kept = (dup or {}).get('kept', act['id'])
            if bike_id and kept != act['id'] and not db.execute('SELECT bikeId FROM Activity WHERE id=?', [kept]).fetchone()['bikeId']:
                gear.set_ride_bike(db, kept, bike_id)   # the other copy was kept: give it the chosen bike unless it already has one
            gear.on_ride_added(db, kept, stamp=not bike_id)
            db.commit()
        except Exception as e:
            log.error('Duplicate resolution failed for %s: %s', act['id'], e)
            db.rollback()
        kept = (dup or {}).get('kept', act['id'])
        asked = None
        if kept == act['id'] and act.get('sportGuess'):     # the file didn't say it was a run, but it moved like one: ask (services/sport_guess.py)
            from services import sport_guess
            sport_guess.note(db, kept, act)
            db.commit()
            asked = sport_guess.for_activity(db, kept)
        from services import auto_analyse
        auto_analyse.queue_ride(db, kept)               # this path does its own sanity and segment steps, not services/ingest.after_ride_added
        try:
            from services.mqtt import push_update
            act_row = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [kept]).fetchone()
            if act_row:
                push_update(act_row)
        except Exception:
            log.warning('Home Assistant update after an import failed', exc_info=True)
        yield _progress(1, 1, 1, 0, 0)
        yield _event({'complete': True, 'imported': 0 if (dup and dup['parked'] == act['id']) else 1, 'skipped': 0, 'errors': 0,
                      'activity': dict(act_summary, id=kept), 'duplicate': dup,
                      **({'sport_guess': {'id': kept, 'guess': label(asked['guess']), 'saved': label(asked['savedSport']), 'file': asked['fileSport']}} if asked else {})})
    except Exception as e:
        log.error('Single file import failed: %s\n%s', e, traceback.format_exc())
        yield _progress(1, 1, 0, 0, 1)
        yield _event({'complete': True, 'imported': 0, 'skipped': 0, 'errors': 1})


def _strava_csv_rows(f):
    """activities.csv rows as dicts. Strava repeats some headers (Distance, Elapsed Time, Max Heart Rate, ...): a summary block first, then the
    detailed block. csv.DictReader keeps only the last of each, so name the repeats 'Distance (2)' etc. and keep both."""
    reader = csv.reader(f)
    header = next(reader, [])
    seen, keys = {}, []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        keys.append(h if seen[h] == 1 else f'{h} ({seen[h]})')
    return [dict(zip(keys, r)) for r in reader]


def _strava_csv_distance_m(row):
    """The ride's distance in metres from an activities.csv row, or None. The summary 'Distance' is in km; the detailed 'Distance (2)' is in metres."""
    for key, scale in (('Distance (2)', 1), ('Distance', 1000)):
        v = (row.get(key) or '').strip().replace(',', '')
        try:
            if v and float(v) > 0:
                return float(v) * scale
        except ValueError:
            pass
    return None


def _strava_captions(zf, names):
    """{'media/<uuid>.jpg': caption} from the export's media.csv."""
    if 'media.csv' not in names:
        return {}
    with zf.open('media.csv') as f:
        return {(r.get('Media Filename') or '').strip(): (r.get('Media Caption') or '').strip()
                for r in csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='replace'))}


def _strava_extras(db, zf, names, row, ride_id, photos_on, captions):
    """What activities.csv says about a ride besides its numbers: tick it as a commute (unless the rider has already said either way), and add its
    photos (the 'Media' column, '|'-separated paths into the zip; videos are left out). A photo already imported is not added again.
    Returns (photos added, 1 if the commute was ticked). Does not commit."""
    ticked = 0
    if (row.get('Commute') or '').strip().lower() == 'true' or (row.get('Commute (2)') or '').strip() in ('1', '1.0'):
        ticked = db.execute('UPDATE Activity SET commute=1 WHERE id=? AND commute IS NULL', [ride_id]).rowcount
        if ticked:                                  # the default bike was stamped on before the tick: the commute one, if the rider has one
            from services import gear
            gear.regear(db, ride_id)
    added = 0
    if photos_on:
        from services import photos
        media = [m.strip() for m in (row.get('Media') or '').split('|') if m.strip()]
        for pos, m in enumerate(media):
            if not m.lower().endswith(photos.PHOTO_EXTENSIONS) or m not in names or photos.have(db, 'strava:' + m):
                continue
            try:
                if photos.save(db, ride_id, safe_zip_read(zf, m, photos.MAX_BYTES), current_app.config['DATABASE'], caption=captions.get(m), source_key='strava:' + m, position=pos):
                    added += 1
            except Exception as e:
                log.warning('Strava import: could not add photo %s to %s (%s)', m, ride_id, e)
    return added, ticked


def _strava_segments(zf, names, db):
    """Segments from the export's segments.csv (services/segments.import_strava), then every activity matched against the new ones."""
    from services import segments as seg_svc
    with zf.open('segments.csv') as f:
        seg_rows = list(csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='replace')))
    res = seg_svc.import_strava(db, seg_rows)
    db.commit()
    if res['created']:
        seg_svc.scan_all_activities(db, segment_ids=res['created'])
    log.warning('Strava import: segments created=%d already here=%d not ridden=%d without a position=%d',
                len(res['created']), res['existing'], res['unridden'], res['invalid'])
    return {'segments_created': len(res['created']), 'segments_existing': res['existing'], 'segments_unridden': res['unridden']}


def _process_strava_export(zf, names, rider_id=None, segments=False, photos=True, routes=False):
    with zf.open('activities.csv') as f:
        rows = _strava_csv_rows(io.TextIOWrapper(f, 'utf-8', errors='replace'))

    total = len(rows)
    yield _event({'total': total, 'source': 'strava'})

    db = get_db()
    imported = skipped = errors = changed = unchanged = 0
    n_photos = n_commutes = 0
    parked, unread, photos_missing, kinds = [], [], 0, set()     # what the summary says besides the counts
    new_ids = set()                                     # saved by this import and still here (_count_new)
    from services import reimport, duplicates as _dups
    from services.sports import is_ride
    _dups.ensure_schema(db)

    def extras(ride_id, row):
        """Photos and the commute tick for a ride already saved (cheap: from the row, not the file). Returns (photos added, commutes ticked)."""
        try:                                            # an export imported before these were read: add them to the saved ride
            p, c = _strava_extras(db, zf, names, row, ride_id, photos, captions)
            db.commit()
            return p, c
        except Exception as e:
            log.error('Strava import: photos / commute for %s failed: %s', ride_id, e)
            db.rollback()
            return 0, 0

    try:
        captions = _strava_captions(zf, names) if photos else {}
    except Exception as e:
        log.warning('Strava import: could not read media.csv (%s)', e)
        captions = {}
    from services import strava_gear
    try:                                                # which bike Strava says rode each ride: those rides wait for it, not the default bike
        ride_gear = strava_gear.record(db, zf, names, rows, rider_id)
        db.commit()
    except Exception as e:
        log.error('Strava import: could not read the bikes (%s)', e)
        db.rollback()
        ride_gear = {}

    for i, row in enumerate(rows):
        act_id = str(row.get('Activity ID', '')).strip()
        if not act_id:
            skipped += 1
            yield _progress(i + 1, total, imported, skipped, errors)
            continue

        already = bool(db.execute('SELECT id FROM Activity WHERE id = ?', [act_id]).fetchone())      # read it anyway: it may differ from what's saved

        filename = row.get('Filename', '').strip()
        kinds.add('ride' if is_ride(row.get('Activity Type')) else 'other')
        if photos:                                      # Strava leaves some out of the zip: say so, or it looks as if the import lost them
            photos_missing += sum(1 for m in (row.get('Media') or '').split('|') if m.strip() and m.strip() not in names)
        if not filename:                                # typed in on Strava (no file was ever uploaded): a manual entry, which the duplicate
            _mark_manual(db, act_id)                    # check must not take for a recording (services/duplicates.is_manual)
        else:                                           # it has a file: a recording, whatever an upgrade guessed (services/strava_manual)
            db.execute("UPDATE Activity SET source=NULL WHERE id=? AND source='manual'", [act_id])
        db.commit()                                     # not held through reading the file (seconds, for a big FIT): the worker's other jobs
        seen_key = 'strava:' + act_id                   # and the pages write meanwhile
        seen_fp = reimport.fingerprint(rider_id, row, reimport.zip_fingerprint(zf, filename) if filename in names else '')
        if reimport.unchanged(db, seen_key, seen_fp):                # the same file and row, read before by the same code: nothing new in it
            unchanged += 1
            if db.execute('SELECT 1 FROM ImportChange WHERE activityId=?', [act_id]).fetchone():
                changed += 1                            # its differences from last time still wait on the Import page
            else:
                skipped += 1
            p, c = extras(act_id, row)
            n_photos, n_commutes = n_photos + p, n_commutes + c
            yield _progress(i + 1, total, imported, skipped, errors)
            continue

        act, read_ok = {}, True
        if filename and filename in names:
            try:
                data = safe_zip_read(zf, filename)
                if filename.endswith('.gz'):
                    data = safe_gunzip(data)
                act = parse_activity_file(filename, data, strava_export=True) or {}
                if not act:
                    raise ValueError('not a file Headwind can read')
            except Exception as e:
                read_ok, act = False, {}                # not remembered: the next import tries the file again
                log.warning('Strava import: could not read %s (%s); using activities.csv only', filename, e)

        act['id'] = act_id
        act['name'] = row.get('Activity Name', 'Imported Activity').strip() or 'Imported Activity'
        act['sportType'] = canonical(row.get('Activity Type', 'Ride').strip() or 'Ride')     # Headwind's VirtualRide, not Strava's "Virtual Ride"
        if not filename:
            act['source'] = 'manual'
        def csv_num(key):
            v = row.get(key, '').strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None

        start_dt = _parse_strava_date(row.get('Activity Date', ''))
        if start_dt:                                    # activities.csv gives the start in UTC
            start_dt = start_dt.replace(tzinfo=timezone.utc)
            shift = _clock_shift(act)
            if shift:                                   # a RunKeeper file whose clock was out: Strava took the same wrong time from it
                start_dt += shift
                _retime_copies(db, rider_id, act, start_dt - shift, start_dt, _strava_csv_distance_m(row) or act.get('distance'))
            if act.get('streams'):                      # cropped on Strava: the file is the whole recording, activities.csv the window kept
                from services.parser import crop
                act = crop(act, start_dt, csv_num('Elapsed Time (2)') or csv_num('Elapsed Time'), _strava_csv_distance_m(row))
            act['startDateLocal'] = start_dt.isoformat()
        cropped = act.get('cropped', False)              # kept on the act: accepting it on the Import page takes Strava's 0 m climb as a figure
        if not already and not db.execute("SELECT 1 FROM ActivityDuplicate WHERE id=? AND status IN ('parked', 'discarded', 'deleted')",
                                          [act_id]).fetchone():
            _weather_first(act)                         # a new one, before its first write (below): the weather service is slow
        if read_ok:
            reimport.problem_solved(db, act_id)
        else:
            reimport.note_problem(db, act_id, rider_id, act['name'], filename, 'saved from activities.csv only: no track')
            unread.append({'id': act_id, 'name': act['name'], 'file': filename})
        if not already and not filename and _unpark_manual(db, act_id):
            already = True                              # a manual entry set aside behind a ride it isn't a copy of: back as its own activity
        if not already and db.execute("SELECT 1 FROM ActivityDuplicate WHERE id=? AND status IN ('parked', 'discarded', 'deleted')", [act_id]).fetchone():
            # set aside as a copy of another activity (or thrown away, or deleted here: Recently deleted on this page puts it back): adding it
            # again would undo that, and a "use the other recording" choice with it. Its photos and commute go on the activity kept in its
            # place. (Read all the same, for a clock that was out above.)
            kept_for = db.execute("""SELECT a.id FROM ActivityDuplicate d JOIN Activity a ON a.id = d.primaryId
                                     WHERE d.id=? AND d.status='parked'""", [act_id]).fetchone()
            if kept_for:
                p, c = extras(kept_for[0], row)
                n_photos, n_commutes = n_photos + p, n_commutes + c
            if read_ok:
                reimport.remember(db, seen_key, act_id, seen_fp)
            db.commit()
            skipped += 1
            yield _progress(i + 1, total, imported, skipped, errors)
            continue

        # Strava's own distance and moving time win over the file's: they carry the rider's crops and "correct distance" on Strava, its moving
        # time from the track, and a ski day's distance without the lifts. The file's are what the device wrote (a speed sensor gone wrong,
        # auto-pause off). The track itself is kept as the file has it.
        strava_moving, strava_dist = csv_num('Moving Time'), _strava_csv_distance_m(row)
        if strava_moving:
            act['movingTime'] = int(strava_moving)
            raw = json.loads(act.get('rawData') or '{}')
            raw['stravaMoving'] = int(strava_moving)     # so a repair that works moving time out from the track leaves it (services/moving_time)
            act['rawData'] = json.dumps(raw)
        elif not act.get('movingTime'):
            t = csv_num('Elapsed Time')
            if t:
                act['movingTime'] = int(t)
        if strava_dist:
            act['distance'] = round(strava_dist, 1)
        if (strava_moving or strava_dist) and act.get('distance') and act.get('movingTime'):
            act['averageSpeed'] = round(act['distance'] / act['movingTime'], 4)
        if not act.get('elapsedTime'):
            t = csv_num('Elapsed Time')
            if t:
                act['elapsedTime'] = int(t)
        if cropped and csv_num('Elevation Gain') is not None:
            act['totalElevationGain'] = csv_num('Elevation Gain')          # Strava's, 0 included
        if cropped and csv_num('Max Speed'):
            act['maxSpeed'] = csv_num('Max Speed')                          # m/s; the track's is read off a few points, Strava's off the original
        elif act.get('totalElevationGain') is None:
            act['totalElevationGain'] = csv_num('Elevation Gain') or 0
        _strava_climb_if_impossible(act, csv_num('Elevation Gain'))
        if act.get('averageHeartrate') is None:
            act['averageHeartrate'] = csv_num('Average Heart Rate')
        if act.get('averageWatts') is None:
            act['averageWatts'] = csv_num('Average Watts')
        if act.get('calories') is None:
            act['calories'] = csv_num('Calories')

        if already:
            try:
                _keep_strava_figures(db, act_id, act)
                differs = _offer_change(db, act, 'Strava export')
                if read_ok:
                    reimport.remember(db, seen_key, act_id, seen_fp)
                db.commit()
            except Exception as e:
                log.error('Re-import compare failed for %s: %s', act_id, e)
                db.rollback()
                differs = False
            changed += bool(differs)
            skipped += not differs
            p, c = extras(act_id, row)
            n_photos, n_commutes = n_photos + p, n_commutes + c
            yield _progress(i + 1, total, imported, skipped, errors)
            continue

        try:
            _insert(db, act, rider_id)
            from services.best_efforts import save_best_efforts
            save_best_efforts(db, act.get('id'), act.get('startDateLocal'), act.get('streams'))
            from services import sport_records
            sport_records.index(db, act.get('id'), act.get('startDateLocal'), act.get('sportType'), act.get('streams'))   # a run's or swim's best times
            from services import duplicates
            dup = duplicates.resolve(db, act.get('id'))
            from services import gear
            gear.on_ride_added(db, act.get('id'), stamp=act_id not in ride_gear)
            from services.ingest import after_ride_added
            kept = (dup or {}).get('kept', act.get('id'))
            after_ride_added(db, kept)
            p, c = _strava_extras(db, zf, names, row, kept, photos, captions)     # on the ride that was kept, if this one was a duplicate
            n_photos, n_commutes = n_photos + p, n_commutes + c
            if read_ok:
                reimport.remember(db, seen_key, act_id, seen_fp)
            db.commit()
            imported += _count_new(dup, act_id, kept, act['name'], new_ids, parked)
        except Exception as e:
            log.error('Insert failed for activity %s: %s', act.get('id'), e)
            db.rollback()               # drop what this one wrote before it failed: the next activity's commit mustn't keep it
            errors += 1

        yield _progress(i + 1, total, imported, skipped, errors)

    segs = {}
    if segments and 'segments.csv' in names:
        yield _event({'stage': 'Matching your Strava segments against every activity…'})
        try:
            segs = _strava_segments(zf, names, db)
        except Exception as e:
            log.error('Strava import: segments failed: %s\n%s', e, traceback.format_exc())
            db.rollback()

    planned = {}
    if routes and 'routes.csv' in names:                # into the route planner (services/planned_routes.import_strava)
        try:
            from services import planned_routes
            planned = planned_routes.import_strava(db, zf, names, rider_id)
            db.commit()
            log.warning('Strava import: routes created=%d already here=%d not read=%d',
                        planned['routes_created'], planned['routes_existing'], planned['routes_unread'])
        except Exception as e:
            log.error('Strava import: routes failed: %s\n%s', e, traceback.format_exc())
            db.rollback()

    bikes = {}
    if ride_gear and rider_id:
        try:                                            # shoes: an item for each, and their walks, runs and hikes put on it (services/strava_gear.apply_kit)
            k = strava_gear.apply_kit(db, rider_id)
            bikes.update({'kit_added': k['added'], 'kit_filled': k['filled']})
            db.commit()
        except Exception as e:
            log.error('Strava import: could not put activities on their shoes (%s)', e)
            db.rollback()
        try:                                            # rides of the Strava bikes already matched go on their bike; the rest wait for /gear/strava
            bikes.update({'bikes_filled': strava_gear.apply_matched(db, rider_id), 'bikes_to_match': strava_gear.pending(db, rider_id),
                          'bikes_url': f'/gear/strava?rider={rider_id}'})
            db.commit()
        except Exception as e:
            log.error('Strava import: could not put rides on their bikes (%s)', e)
            db.rollback()
    log.info('Strava import done — imported=%d set aside as duplicates=%d skipped=%d (unchanged since the last import, not read: %d) changed=%d '
             'errors=%d files not read=%d photos=%d (not in the zip: %d) commutes=%d bikes=%s',
             imported, len(parked), skipped, unchanged, changed, errors, len(unread), n_photos, photos_missing, n_commutes, bikes)
    yield _event({'complete': True, 'imported': imported, 'skipped': skipped, 'unchanged': unchanged, 'changed': changed, 'errors': errors, **bikes,
                  'photos': n_photos, 'commutes': n_commutes, **segs, **planned, 'parked': parked, 'unread': unread, 'photos_missing': photos_missing,
                  'noun': _noun(kinds)})


def _count_new(dup, act_id, kept, name, new_ids, parked):
    """How much an activity just saved adds to an import's count of new activities (1 or 0), noting in `parked` any activity the duplicate
    check (dup: duplicates.resolve's result) set aside: the new one, behind one already here, adds nothing; nor does one that took the place
    of an activity this same import saved earlier, which was counted then."""
    gone = (dup or {}).get('parked')
    if gone:
        parked.append({'id': gone, 'kept': kept, 'name': name})
    if gone == act_id:
        return 0
    new_ids.add(act_id)
    if gone in new_ids:
        new_ids.discard(gone)
        return 0
    return 1


def _noun(kinds):
    """'rides' when every activity in an import was a ride, else 'activities'."""
    return 'rides' if kinds == {'ride'} else 'activities'


def _mark_manual(db, act_id):
    """A Strava export's row with no file was typed in on Strava: say so on the saved activity, or on its copy set aside as a duplicate."""
    db.execute("UPDATE Activity SET source='manual' WHERE id=? AND source IS NULL", [act_id])
    row = db.execute("SELECT rowJson FROM ActivityDuplicate WHERE id=? AND status='parked'", [act_id]).fetchone()
    if row:
        try:
            data = json.loads(row['rowJson'])
        except ValueError:
            return
        if data and data.get('source') is None:
            data['source'] = 'manual'
            db.execute('UPDATE ActivityDuplicate SET rowJson=? WHERE id=?', [json.dumps(data), act_id])


def _unpark_manual(db, act_id):
    """A manual entry set aside as a duplicate before manual entries were known by their missing file: if, seen as manual (_mark_manual has
    run), it isn't the same ride as the one kept in its place, bring it back as its own activity. True if it did. Commits."""
    from services import duplicates
    d = db.execute("SELECT primaryId, rowJson, streams FROM ActivityDuplicate WHERE id=? AND status='parked'", [act_id]).fetchone()
    if not d:
        return False
    kept = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [d['primaryId']]).fetchone()
    try:
        row = _streams.together(d['rowJson'], d['streams'])
    except ValueError:
        return False
    if not row or not kept or duplicates.same_ride(row, kept):
        return False
    duplicates.keep_both(db, act_id)
    db.commit()
    log.warning('Strava import: %s, typed in on Strava, was set aside behind %s, which it is not a copy of: kept as its own activity', act_id, d['primaryId'])
    return True


_STRAVA_FIGURES = ('stravaClimb', 'stravaMoving')


def _keep_strava_figures(db, act_id, act):
    """Strava's own figures (rawData.stravaClimb, .stravaMoving) onto a ride saved before they were kept, whatever else its rawData holds: "Use
    Strava's climb" on the dashboard, and the moving-time repairs knowing a moving time is Strava's (services/moving_time.stravas). Does not commit."""
    new = {k: v for k, v in json.loads(act.get('rawData') or '{}').items() if k in _STRAVA_FIGURES}
    saved = db.execute('SELECT rawData FROM Activity WHERE id=?', [act_id]).fetchone()
    if not new or not saved:
        return
    try:
        raw = json.loads(saved['rawData'] or '{}') or {}
    except ValueError:
        raw = {}
    if not isinstance(raw, dict) or all(raw.get(k) == v for k, v in new.items()):
        return
    db.execute('UPDATE Activity SET rawData=? WHERE id=?', [json.dumps({**raw, **new}), act_id])


def _strava_climb_if_impossible(act, strava_climb):
    """The file's climb when it can't be real (over services/sanity's MAX_ELEV_M or MAX_GRADE, or an altitude stream that can't be: parser.
    altitude_broken) replaced by Strava's from activities.csv, which recalculated it. The altitude stream goes too: no elevation profile, and no
    climb for segments and best climbs from it. Strava's figure is kept in rawData either way, for the dashboard's "Use Strava's climb"."""
    from services import sanity
    from services.parser import altitude_broken
    if strava_climb is None:
        return
    raw = json.loads(act.get('rawData') or '{}')
    raw['stravaClimb'] = strava_climb
    try:
        streams = json.loads(act.get('streams') or '{}')
    except ValueError:
        streams = {}
    climb, dist = float(act.get('totalElevationGain') or 0), float(act.get('distance') or 0)
    broken = altitude_broken(streams)
    if broken or climb > sanity.MAX_ELEV_M or (dist >= 1000 and climb / dist > sanity.MAX_GRADE):
        if climb != strava_climb:
            raw['fileClimb'] = climb
            act['totalElevationGain'] = strava_climb
        if broken and 'altitude' in streams:
            streams.pop('altitude')
            act['streams'] = json.dumps(streams)
            raw['altitudeDropped'] = True
    act['rawData'] = json.dumps(raw)


def _process_generic_zip(zf, names, rider_id=None):
    activity_files = [
        n for n in names
        if n.lower().endswith(ACTIVITY_EXTENSIONS)
    ]
    total = len(activity_files)
    yield _event({'total': total, 'source': 'files'})

    db = get_db()
    imported = skipped = errors = changed = unchanged = guessed = 0
    parked, unread, kinds, new_ids = [], [], set(), set()
    from services import reimport
    from services.sports import is_ride

    for i, name in enumerate(activity_files):
        try:
            seen_key = 'file:' + reimport.zip_fingerprint(zf, name)          # by its contents: the same file under another name is the same file
            seen_fp = reimport.fingerprint(rider_id, seen_key)
            if reimport.unchanged(db, seen_key, seen_fp):                     # read before by the same code, and its activity is still here
                unchanged += 1
                skipped += 1
                yield _progress(i + 1, total, imported, skipped, errors)
                continue
            data = safe_zip_read(zf, name)
            if name.lower().endswith('.gz'):
                data = safe_gunzip(data)
            act = parse_activity_file(name, data)
            if act and act.get('startDateLocal'):
                from services import duplicates as _d
                if not _d.exists_anywhere(db, act['id']):
                    _weather_first(act)                 # before the first write: the weather service is slow
                _retime_file_copies(db, rider_id, act)
                if _d.exists_anywhere(db, act['id']):
                    differs = _offer_change(db, act, name)
                    reimport.remember(db, seen_key, act['id'], seen_fp)
                    db.commit()
                    log.info('Import %s: %s', 'differs from the saved activity' if differs else 'skip (duplicate)', name)
                    changed += bool(differs)
                    skipped += not differs
                else:
                    _insert(db, act, rider_id)
                    from services.best_efforts import save_best_efforts
                    save_best_efforts(db, act.get('id'), act.get('startDateLocal'), act.get('streams'))
                    from services import sport_records
                    sport_records.index(db, act.get('id'), act.get('startDateLocal'), act.get('sportType'), act.get('streams'))   # a run's or swim's best times
                    from services import duplicates
                    dup = duplicates.resolve(db, act.get('id'))
                    from services import gear
                    gear.on_ride_added(db, act.get('id'))
                    from services.ingest import after_ride_added
                    kept = (dup or {}).get('kept', act.get('id'))
                    after_ride_added(db, kept)
                    if kept == act['id'] and act.get('sportGuess'):
                        from services import sport_guess
                        guessed += sport_guess.note(db, kept, act)
                    reimport.remember(db, seen_key, act['id'], seen_fp)
                    db.commit()
                    imported += _count_new(dup, act['id'], kept, act.get('name'), new_ids, parked)
                    kinds.add('ride' if is_ride(act.get('sportType')) else 'other')
            else:
                log.warning('Import skip (no parseable activity): %s', name)
                skipped += 1
                unread.append({'file': name})
        except Exception as e:
            log.error('Import error for %s: %s\n%s', name, e, traceback.format_exc())
            db.rollback()               # drop what this file wrote before it failed: the next file's commit mustn't keep it
            errors += 1

        yield _progress(i + 1, total, imported, skipped, errors)

    log.info('Generic import done — imported=%d set aside as duplicates=%d skipped=%d (unchanged since the last import, not read: %d) '
             'files not read=%d errors=%d', imported, len(parked), skipped, unchanged, len(unread), errors)
    yield _event({'complete': True, 'imported': imported, 'skipped': skipped, 'unchanged': unchanged, 'changed': changed, 'errors': errors,
                  'parked': parked, 'unread': unread, 'noun': _noun(kinds), 'sport_guessed': guessed})


def _clock_shift(act):
    """How far the file's clock was out (services/parser.runkeeper_shift), as a timedelta, or None."""
    if not act.get('clockShiftedFrom'):
        return None
    from services.duplicates import instant
    was, now = instant(act['clockShiftedFrom']), instant(act.get('startDateLocal'))
    return (now - was) if was and now and now != was else None


def _retime_copies(db, rider_id, act, wrong, right, distance_m):
    """Copies saved with the wrong time move to the right one (services/start_times.retime_copies). Never breaks an import. Commits."""
    try:
        from services.start_times import retime_copies
        retime_copies(db, rider_id, wrong, right, distance_m)
        db.commit()
    except Exception:
        log.warning('Re-timing the saved copies of %s failed', act.get('id'), exc_info=True)
        db.rollback()


def _retime_file_copies(db, rider_id, act):
    """A file read on its own (not from a Strava export) whose clock was out: its saved copies move too."""
    shift = _clock_shift(act)
    if shift:
        from services.duplicates import instant
        right = instant(act['startDateLocal'])
        _retime_copies(db, rider_id, act, right - shift, right, act.get('distance'))


def _split_start(act):
    """(startDate, startDateLocal) for the Activity row. A GPX/FIT time with a timezone (a phone recording is UTC 'Z') is stored as
    the UTC instant plus the local time where it started (services/tz.zone_at; the home zone without a position), like Garmin rides; a naive
    time is local already and stays as is."""
    from services import tz
    from services.duplicates import instant
    raw = act.get('startDateLocal')
    try:
        aware = datetime.fromisoformat(str(raw).replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        aware = False
    if not aware:
        return raw, raw
    utc = instant(raw)
    return utc.strftime('%Y-%m-%dT%H:%M:%S'), tz.local_at(utc, act.get('startLat'), act.get('startLng'), act.get('sportType'))


def _offer_change(db, act, source):
    """A ride with this id is already saved: compare the import with it (services/reimport.py). Returns True if it differs (it now waits on the
    Import page), False if it is the same ride, None if nothing is saved under that id (so import it as new)."""
    saved = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [act.get('id')]).fetchone()
    if not saved:
        return None
    from services import reimport
    norm = dict(act)
    norm['startDate'], norm['startDateLocal'] = _split_start(act)
    return reimport.propose(db, saved, norm, source)


def _insert(db, act, rider_id=None):
    sport = act.get('sportType') or 'Ride'
    start_utc, start_local = _split_start(act)
    avg_speed = act.get('averageSpeed') or 0
    calories = act.get('calories')
    # A GPX has no calorie field at all (unlike FIT), so any GPX-sourced ride — a phone recording is the common
    # case now, but this also covers a plain user-uploaded GPX — lands with calories=NULL. That's not just a
    # blank number on the ride card: services.goal_model.day_burn() filters WHERE calories IS NOT NULL, so an
    # un-estimated ride is invisible to the day's burn total, not counted as zero. Estimate one rather than
    # leave that silently wrong when we have enough to go on.
    if not calories and rider_id and sport in RIDES:
        try:
            from services.goal_model import current_weight_kg
            from services.parser import estimate_ride_calories
            calories = estimate_ride_calories(act.get('distance'), act.get('movingTime'), current_weight_kg(rider_id))
        except Exception:
            log.debug('Ride calorie estimate failed', exc_info=True)
    from services.calorie_adjust import pair as _kcal_pair
    calories_raw, calories = _kcal_pair(calories)     # global burn adjustment, applied as the figure is pulled in
    result = db.execute('''
        INSERT OR IGNORE INTO Activity
          (id, name, type, sportType, startDate, startDateLocal,
           distance, movingTime, elapsedTime,
           totalElevationGain, averageSpeed, maxSpeed,
           averageHeartrate, averageWatts,
           averageCadence, calories, startLat, startLng,
           rawData, riderId, maxHeartrate, maxWatts, caloriesRaw, source, createdAt, updatedAt)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
    ''', [
        act.get('id'),            act.get('name'),          sport,
        sport,                    start_utc, start_local,
        act.get('distance') or 0, act.get('movingTime') or 0, act.get('elapsedTime') or 0,
        act.get('totalElevationGain') or 0, avg_speed, act.get('maxSpeed') or 0,   # true max (was the average)
        act.get('averageHeartrate'), act.get('averageWatts'),
        act.get('averageCadence'), calories,
        act.get('startLat'),      act.get('startLng'),
        act.get('rawData') or '{}',
        rider_id, act.get('maxHeartrate'), act.get('maxWatts'), calories_raw, act.get('source'),
    ])
    if result.rowcount:
        _streams.save(db, act.get('id'), act.get('streams'))
        from services.garmin import save_laps
        save_laps(db, act.get('id'), act.get('laps'))
    if '_weather' not in act:                           # a caller that didn't ask first: asked now, inside its transaction
        _weather_first(act)
    w = act.pop('_weather')
    if result.rowcount and w:
        from services.weather import save_weather
        save_weather(db, act['id'], w)


def _weather_first(act):
    """Ask the weather service about a new activity before anything of it is written, into act['_weather'] (None when there's nothing), for
    _insert to store. The service takes a fifth of a second or more an activity, and holding an import's write lock across it made every
    page's save wait behind the import."""
    act['_weather'] = None
    if act.get('startLat') and act.get('startLng'):
        try:
            from services.weather import fetch_weather
            act['_weather'] = fetch_weather(act['startLat'], act['startLng'], _split_start(act)[1], act.get('streams'),
                                            act.get('sportType') or 'Ride')
        except Exception:
            log.warning('Weather for an imported activity failed', exc_info=True)


def _event(obj):
    return f'data: {json.dumps(obj)}\n\n'


def _progress(done, total, imported, skipped, errors):
    return _event({'done': done, 'total': total,
                   'imported': imported, 'skipped': skipped, 'errors': errors})


def _parse_strava_date(s):
    for fmt in ('%b %d, %Y, %I:%M:%S %p', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None
