import csv
import gzip
import hmac
import io
import json
import logging
import os
import tempfile
import threading
import traceback
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, render_template, request, stream_with_context

from database import get_db, query_db
from services.parser import ACTIVITY_EXTENSIONS, parse_activity_file
from services.limits import safe_gunzip, safe_zip_read, check_zip
from services.sports import RIDES

log = logging.getLogger(__name__)

bp = Blueprint('import_rides', __name__)


@bp.route('/import')
def index():
    from database import query_db
    from services import reimport, strava_gear
    from services import strava_export
    from services.rider_mode import owner_rider_id
    from services import garmin_changes, tasks
    riders = query_db('SELECT id, name FROM Rider ORDER BY isDefault DESC, name ASC')
    return render_template('import.html', riders=riders, changes=reimport.pending(get_db()), problems=reimport.problems(get_db()),
                           garmin_changes=garmin_changes.pending(get_db()), garmin_check=tasks.last(get_db(), garmin_changes.TASK),
                           garmin_missing=garmin_changes.not_here(get_db()), garmin_deleted=garmin_changes.not_here(get_db(), deleted=True),
                           garmin_full=bool(query_db("SELECT 1 FROM Settings WHERE id=1 AND garminSyncMode='full'", one=True)),
                           strava_pending=strava_gear.pending(get_db(), owner_rider_id()),
                           kept=strava_export.kept(get_db(), current_app.config['DATABASE']),
                           advice=strava_export.advice(get_db(), current_app.config['DATABASE']))


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
    """Settle a re-imported ride that differs from the saved one: keep | replace | fill (services/reimport.py). ride_id 'all' settles every one."""
    from flask import flash, redirect, url_for
    from services import reimport
    db = get_db()
    ids = [c['rideId'] for c in reimport.pending(db)] if ride_id == 'all' else [ride_id]
    try:
        changed = sum(1 for i in ids if reimport.resolve(db, i, choice))
    except ValueError as e:
        db.rollback()
        flash(str(e), 'error')
        return redirect(url_for('import_rides.index'))
    db.commit()
    if changed:
        try:
            from services.mqtt import push_update
            push_update(background=True)
        except Exception:
            log.warning('Home Assistant update after the import failed', exc_info=True)
    n = len(ids)
    flash({'keep': f"Kept the saved version of {n} ride{'s' if n != 1 else ''}.",
           'replace': f"Updated {changed} ride{'s' if changed != 1 else ''} from the import.",
           'fill': f"Filled in missing data on {changed} ride{'s' if changed != 1 else ''}."}[choice], 'success')
    return redirect(url_for('import_rides.index') + '#changes')


@bp.route('/import/upload', methods=['POST'])
def upload():
    f = request.files.get('zipfile')
    if not f or not f.filename:
        return Response('data: {"error":"No file selected"}\n\n', mimetype='text/event-stream')

    from database import query_db as _qdb
    from services import strava_export
    try:
        rider_id = int(request.form.get('riderId') or 0) or None
    except ValueError:
        rider_id = None
    if rider_id is None:
        default = _qdb('SELECT id FROM Rider WHERE isDefault=1 LIMIT 1', one=True)
        rider_id = default['id'] if default else None

    opt_segments = request.form.get('importSegments') == '1'         # a Strava export's segments.csv: off unless asked for
    opt_photos = request.form.get('importPhotos', '1') == '1'        # its photos: on unless turned off
    opt_keep = request.form.get('keepExport', '1') == '1'            # a Strava export kept for Import again: on unless turned off

    name_lower = f.filename.lower()
    is_single = name_lower.endswith(ACTIVITY_EXTENSIONS)

    suffix = next((e for e in ACTIVITY_EXTENSIONS if name_lower.endswith(e)), '.zip')
    db_path = current_app.config['DATABASE']
    if is_single:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    else:                                               # beside the database: a Strava export kept for Import again is moved, not copied (GBs)
        strava_export.clear_stale_uploads(db_path)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=strava_export.UPLOAD_PREFIX, dir=strava_export.export_dir(db_path))
    f.save(tmp)
    tmp.close()

    def work(job):
        if is_single:
            for item in _process_single_file(tmp.name, f.filename, rider_id):
                job.put(item)
            return
        done = None
        with zipfile.ZipFile(tmp.name) as zf:
            check_zip(zf)
            names = set(zf.namelist())
            log.info('Import started — %d files in zip, has_csv=%s', len(names), 'activities.csv' in names)
            strava = 'activities.csv' in names
            if strava:
                gen = _process_strava_export(zf, names, rider_id, segments=opt_segments, photos=opt_photos)
            else:
                gen = _process_generic_zip(zf, names, rider_id)
            for item in gen:
                if strava and '"complete": true' in item:
                    done = json.loads(item[len('data: '):])     # held back until the zip is closed and kept, so the summary can say so
                else:
                    job.put(item)
        if done is not None:
            if rider_id:
                strava_export.note_read(get_db(), rider_id)
            if opt_keep and rider_id:
                try:
                    strava_export.keep(get_db(), db_path, rider_id, tmp.name, job.state.get('total'), opt_segments, opt_photos)
                    done['kept'] = True
                except OSError as e:
                    log.error('Strava import: could not keep the export (%s)', e)
            job.put(_event(done))

    def cleanup():
        try:
            os.unlink(tmp.name)                         # gone already when the export was kept
        except FileNotFoundError:
            pass

    return _start(work, cleanup)


@bp.route('/import/strava-export/<int:rider_id>/again', methods=['POST'])
def import_again(rider_id):
    """Import a rider's kept Strava export again (services/strava_export.py), with the options ticked on the page. The file stays kept."""
    from services import strava_export
    if _current_job is not None and not _current_job.done:
        return Response('data: {"error":"An import is already running"}\n\n', mimetype='text/event-stream')
    path = strava_export.path_for(current_app.config['DATABASE'], rider_id)
    if not os.path.isfile(path) or not get_db().execute('SELECT 1 FROM StravaExport WHERE riderId=?', [rider_id]).fetchone():
        return Response('data: {"error":"That export is no longer kept"}\n\n', mimetype='text/event-stream')
    opt_segments = request.form.get('importSegments') == '1'
    opt_photos = request.form.get('importPhotos', '1') == '1'

    def work(job):
        with zipfile.ZipFile(path) as zf:
            check_zip(zf)
            names = set(zf.namelist())
            log.info('Import again of the kept Strava export for rider %s — %d files in zip', rider_id, len(names))
            for item in _process_strava_export(zf, names, rider_id, segments=opt_segments, photos=opt_photos):
                job.put(item)
        strava_export.read_again(get_db(), rider_id, job.state.get('total'), opt_segments, opt_photos)
        strava_export.note_read(get_db(), rider_id)

    return _start(work)


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
    if _current_job is not None and not _current_job.done:
        flash('An import is running: delete the export once it has finished.', 'error')
        return redirect(url_for('import_rides.index'))
    db = get_db()
    strava_export.forget(db, current_app.config['DATABASE'], rider_id)
    db.commit()
    flash('Deleted the kept Strava export. Its activities stay as they are.', 'success')
    return redirect(url_for('import_rides.index'))


def _start(work, cleanup=None):
    """Run work(job) in a background thread so a browser disconnect can't kill the import, and stream its job log. The worker appends to a log that
    never blocks; any number of SSE streams (the page that started it, or the import page reopened later) read from it."""
    job = _Job()
    global _current_job
    _current_job = job
    app = current_app._get_current_object()

    def _worker():
        with app.app_context():
            try:
                work(job)
            except zipfile.BadZipFile:
                log.error('Import failed: bad zip file')
                job.put(_event({'error': 'Not a valid zip file'}))
            except Exception as e:
                log.error('Import failed: %s\n%s', e, traceback.format_exc())
                job.put(_event({'error': str(e)}))
            finally:
                if cleanup:
                    cleanup()
                job.finish()  # always signals end

    threading.Thread(target=_worker, daemon=True).start()
    return _sse(job.stream())


@bp.route('/import/status')
def status():
    """Re-attach to the import still running in the background after the page was left, or show once how one that finished
    while nobody was watching turned out. Streams nothing when there is neither."""
    job = _current_job
    if job is None or (job.done and job.delivered):
        return _sse(iter(()))
    return _sse(job.stream())


@bp.route('/import/progress')
def progress():
    """Snapshot of the background import for the indicator every page shows: {} when there is nothing to show."""
    job = _current_job
    if job is None or (job.done and job.delivered):
        return {}
    with job.cond:
        return dict(job.state, running=not job.done)


@bp.route('/import/progress/dismiss', methods=['POST'])
def dismiss():
    job = _current_job
    if job is not None and job.done:
        job.delivered = True
    return {}


def _sse(gen):
    return Response(
        stream_with_context(gen),
        mimetype='text/event-stream',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
    )


class _Job:
    """Event log of one web import. Gunicorn runs a single worker process, so a module-level job is visible to every request."""

    def __init__(self):
        self.events = []            # (is_progress, sse_text)
        self.done = False
        self.delivered = False      # the outcome has been shown: a stream passed the end on, or the indicator was dismissed
        self.state = {}             # every field seen so far (total, done, imported, ..., complete, error), for /import/progress
        self.cond = threading.Condition()

    def put(self, item):
        with self.cond:
            self.events.append(('"done":' in item, item))
            try:
                self.state.update(json.loads(item[len('data: '):]))
            except ValueError:
                pass
            self.cond.notify_all()

    def finish(self):
        with self.cond:
            self.done = True
            self.cond.notify_all()

    def stream(self):
        i = 0
        while True:
            with self.cond:
                while i == len(self.events) and not self.done:
                    if not self.cond.wait(timeout=15):
                        break
                batch, i, done = self.events[i:], len(self.events), self.done
            if not batch and not done:
                yield ': keepalive\n\n'   # also how a vanished browser is noticed; the worker carries on regardless
                continue
            # A late joiner catching up on a big Strava export only needs the latest progress, not thousands of them.
            last_progress = max((n for n, (p, _) in enumerate(batch) if p), default=-1)
            for n, (is_progress, item) in enumerate(batch):
                if not is_progress or n == last_progress:
                    yield item
            if done:
                self.delivered = True
                return


_current_job = None


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


def _process_single_file(path, original_name, rider_id=None, bike_id=None):
    """bike_id (the phone app's choice, already checked to be the rider's) goes on the ride instead of the default bike."""
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
        _retime_file_copies(db, rider_id, act)
        if duplicates.exists_anywhere(db, act['id']):
            differs = _offer_change(db, act, original_name)
            db.commit()
            log.warning('Single file import: already exists id=%s%s', act['id'], ' (differs: waiting for review)' if differs else '')
            yield _progress(1, 1, 0, 0 if differs else 1, 0)
            yield _event({'complete': True, 'imported': 0, 'skipped': 0 if differs else 1, 'changed': 1 if differs else 0, 'errors': 0, 'activity': act_summary})
            return

        _insert(db, act, rider_id)
        if bike_id:                                     # before the segment scan, so an e-bike's efforts race for e-bike PRs from the start
            db.execute('UPDATE Activity SET bikeId=? WHERE id=?', [bike_id, act['id']])
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
                act_row = db.execute('SELECT * FROM Activity WHERE id=?', [act['id']]).fetchone()
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
        from services import auto_analyse
        auto_analyse.queue_ride(db, kept)               # this path does its own sanity and segment steps, not services/ingest.after_ride_added
        try:
            from services.mqtt import push_update
            act_row = db.execute('SELECT * FROM Activity WHERE id=?', [kept]).fetchone()
            if act_row:
                push_update(act_row)
        except Exception:
            log.warning('Home Assistant update after an import failed', exc_info=True)
        yield _progress(1, 1, 1, 0, 0)
        yield _event({'complete': True, 'imported': 0 if (dup and dup['parked'] == act['id']) else 1, 'skipped': 0, 'errors': 0,
                      'activity': dict(act_summary, id=kept), 'duplicate': dup})
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


def _process_strava_export(zf, names, rider_id=None, segments=False, photos=True):
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
        seen_key = 'strava:' + act_id
        seen_fp = reimport.fingerprint(rider_id, row, reimport.zip_fingerprint(zf, filename) if filename in names else '')
        if reimport.unchanged(db, seen_key, seen_fp):                # the same file and row, read before by the same code: nothing new in it
            unchanged += 1
            if db.execute('SELECT 1 FROM ImportChange WHERE rideId=?', [act_id]).fetchone():
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
        act['sportType'] = row.get('Activity Type', 'Ride').strip() or 'Ride'
        if not filename:
            act['source'] = 'manual'
        if read_ok:
            reimport.problem_solved(db, act_id)
        else:
            reimport.note_problem(db, act_id, rider_id, act['name'], filename, 'saved from activities.csv only: no track')
            unread.append({'id': act_id, 'name': act['name'], 'file': filename})

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
        if not already and not filename and _unpark_manual(db, act_id):
            already = True                              # a manual entry set aside behind a ride it isn't a copy of: back as its own activity
        if not already and db.execute("SELECT 1 FROM ActivityDuplicate WHERE id=? AND status IN ('parked', 'discarded')", [act_id]).fetchone():
            # set aside as a copy of another activity (or thrown away): adding it again would undo that, and a "use the other recording"
            # choice with it. Its photos and commute go on the activity kept in its place. (Read all the same, for a clock that was out above.)
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
                  'photos': n_photos, 'commutes': n_commutes, **segs, 'parked': parked, 'unread': unread, 'photos_missing': photos_missing,
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
    d = db.execute("SELECT primaryId, rowJson FROM ActivityDuplicate WHERE id=? AND status='parked'", [act_id]).fetchone()
    if not d:
        return False
    kept = db.execute('SELECT * FROM Activity WHERE id=?', [d['primaryId']]).fetchone()
    try:
        row = json.loads(d['rowJson'])
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
    imported = skipped = errors = changed = unchanged = 0
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
                _retime_file_copies(db, rider_id, act)
                if _d.exists_anywhere(db, act['id']):
                    differs = _offer_change(db, act, name)
                    reimport.remember(db, seen_key, act['id'], seen_fp)
                    db.commit()
                    log.info('Import %s: %s', 'differs from the saved ride' if differs else 'skip (duplicate)', name)
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
            errors += 1

        yield _progress(i + 1, total, imported, skipped, errors)

    log.info('Generic import done — imported=%d set aside as duplicates=%d skipped=%d (unchanged since the last import, not read: %d) '
             'files not read=%d errors=%d', imported, len(parked), skipped, unchanged, len(unread), errors)
    yield _event({'complete': True, 'imported': imported, 'skipped': skipped, 'unchanged': unchanged, 'changed': changed, 'errors': errors,
                  'parked': parked, 'unread': unread, 'noun': _noun(kinds)})


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
    saved = db.execute('SELECT * FROM Activity WHERE id=?', [act.get('id')]).fetchone()
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
           averageCadence, calories, startLat, startLng, streams,
           rawData, riderId, maxHeartrate, maxWatts, caloriesRaw, source, createdAt, updatedAt)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
    ''', [
        act.get('id'),            act.get('name'),          sport,
        sport,                    start_utc, start_local,
        act.get('distance') or 0, act.get('movingTime') or 0, act.get('elapsedTime') or 0,
        act.get('totalElevationGain') or 0, avg_speed, act.get('maxSpeed') or 0,   # true max (was the average)
        act.get('averageHeartrate'), act.get('averageWatts'),
        act.get('averageCadence'), calories,
        act.get('startLat'),      act.get('startLng'),
        act.get('streams'),       act.get('rawData') or '{}',
        rider_id, act.get('maxHeartrate'), act.get('maxWatts'), calories_raw, act.get('source'),
    ])
    if result.rowcount:
        from services.garmin import save_laps
        save_laps(db, act.get('id'), act.get('laps'))
    if result.rowcount and act.get('startLat') and act.get('startLng'):
        try:
            from services.weather import fetch_weather, save_weather
            w = fetch_weather(act['startLat'], act['startLng'],
                              start_local, act.get('streams'))
            if w:
                save_weather(db, act['id'], w)
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
