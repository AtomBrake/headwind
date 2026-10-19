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

log = logging.getLogger(__name__)

bp = Blueprint('import_rides', __name__)


@bp.route('/import')
def index():
    from database import query_db
    from services import reimport, strava_gear
    from services.rider_mode import owner_rider_id
    riders = query_db('SELECT id, name FROM Rider ORDER BY isDefault DESC, name ASC')
    return render_template('import.html', riders=riders, changes=reimport.pending(get_db()), strava_pending=strava_gear.pending(get_db(), owner_rider_id()))


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
    try:
        rider_id = int(request.form.get('riderId') or 0) or None
    except ValueError:
        rider_id = None
    if rider_id is None:
        default = _qdb('SELECT id FROM Rider WHERE isDefault=1 LIMIT 1', one=True)
        rider_id = default['id'] if default else None

    opt_segments = request.form.get('importSegments') == '1'         # a Strava export's segments.csv: off unless asked for
    opt_photos = request.form.get('importPhotos', '1') == '1'        # its photos: on unless turned off

    name_lower = f.filename.lower()
    is_single = name_lower.endswith(ACTIVITY_EXTENSIONS)

    suffix = next((e for e in ACTIVITY_EXTENSIONS if name_lower.endswith(e)), '.zip')
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.save(tmp)
    tmp.close()

    # Run processing in a background thread so browser disconnect can't kill the import. The worker appends to a job log that never
    # blocks; any number of SSE streams (the uploading page, or the import page reopened later) read from it.
    job = _Job()
    global _current_job
    _current_job = job
    app = current_app._get_current_object()

    def _worker():
        with app.app_context():
            try:
                if is_single:
                    for item in _process_single_file(tmp.name, f.filename, rider_id):
                        job.put(item)
                else:
                    with zipfile.ZipFile(tmp.name) as zf:
                        check_zip(zf)
                        names = set(zf.namelist())
                        log.info('Import started — %d files in zip, has_csv=%s',
                                    len(names), 'activities.csv' in names)
                        if 'activities.csv' in names:
                            gen = _process_strava_export(zf, names, rider_id, segments=opt_segments, photos=opt_photos)
                        else:
                            gen = _process_generic_zip(zf, names, rider_id)
                        for item in gen:
                            job.put(item)
            except zipfile.BadZipFile:
                log.error('Import failed: bad zip file')
                job.put(_event({'error': 'Not a valid zip file'}))
            except Exception as e:
                log.error('Import failed: %s\n%s', e, traceback.format_exc())
                job.put(_event({'error': str(e)}))
            finally:
                os.unlink(tmp.name)
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
    imported = skipped = errors = changed = 0
    n_photos = n_commutes = 0
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

        act = {}
        filename = row.get('Filename', '').strip()
        if filename and filename in names:
            try:
                data = safe_zip_read(zf, filename)
                if filename.endswith('.gz'):
                    data = safe_gunzip(data)
                act = parse_activity_file(filename, data) or {}
            except Exception as e:
                log.warning('Strava import: could not read %s (%s); using activities.csv only', filename, e)

        act['id'] = act_id
        act['name'] = row.get('Activity Name', 'Imported Activity').strip() or 'Imported Activity'
        act['sportType'] = row.get('Activity Type', 'Ride').strip() or 'Ride'

        def csv_num(key):
            v = row.get(key, '').strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None

        start_dt = _parse_strava_date(row.get('Activity Date', ''))
        if start_dt:                                    # activities.csv gives the start in UTC
            start_dt = start_dt.replace(tzinfo=timezone.utc)
            if act.get('streams'):                      # cropped on Strava: the file is the whole recording, activities.csv the window kept
                from services.parser import crop
                act = crop(act, start_dt, csv_num('Elapsed Time (2)') or csv_num('Elapsed Time'), _strava_csv_distance_m(row))
            act['startDateLocal'] = start_dt.isoformat()
        cropped = act.get('cropped', False)              # kept on the act: accepting it on the Import page takes Strava's 0 m climb as a figure

        # Strava's own distance and moving time win over the file's: they carry the rider's crops and "correct distance" on Strava, its moving
        # time from the track, and a ski day's distance without the lifts. The file's are what the device wrote (a speed sensor gone wrong,
        # auto-pause off). The track itself is kept as the file has it.
        strava_moving, strava_dist = csv_num('Moving Time'), _strava_csv_distance_m(row)
        if strava_moving:
            act['movingTime'] = int(strava_moving)
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
        if act.get('averageHeartrate') is None:
            act['averageHeartrate'] = csv_num('Average Heart Rate')
        if act.get('averageWatts') is None:
            act['averageWatts'] = csv_num('Average Watts')
        if act.get('calories') is None:
            act['calories'] = csv_num('Calories')

        if already:
            try:
                differs = _offer_change(db, act, 'Strava export')
                db.commit()
            except Exception as e:
                log.error('Re-import compare failed for %s: %s', act_id, e)
                differs = False
            changed += bool(differs)
            skipped += not differs
            try:                                        # an export imported before these were read: add them to the saved ride
                p, c = _strava_extras(db, zf, names, row, act_id, photos, captions)
                db.commit()
                n_photos, n_commutes = n_photos + p, n_commutes + c
            except Exception as e:
                log.error('Strava import: photos / commute for %s failed: %s', act_id, e)
                db.rollback()
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
            db.commit()
            imported += 1
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
        try:                                            # rides of the Strava bikes already matched go on their bike; the rest wait for /gear/strava
            bikes = {'bikes_filled': strava_gear.apply_matched(db, rider_id), 'bikes_to_match': strava_gear.pending(db, rider_id),
                     'bikes_url': f'/gear/strava?rider={rider_id}'}
            db.commit()
        except Exception as e:
            log.error('Strava import: could not put rides on their bikes (%s)', e)
            db.rollback()
    log.info('Strava import done — imported=%d skipped=%d changed=%d errors=%d photos=%d commutes=%d bikes=%s',
                imported, skipped, changed, errors, n_photos, n_commutes, bikes)
    yield _event({'complete': True, 'imported': imported, 'skipped': skipped, 'changed': changed, 'errors': errors, **bikes,
                  'photos': n_photos, 'commutes': n_commutes, **segs})


def _process_generic_zip(zf, names, rider_id=None):
    activity_files = [
        n for n in names
        if n.lower().endswith(ACTIVITY_EXTENSIONS)
    ]
    total = len(activity_files)
    yield _event({'total': total, 'source': 'files'})

    db = get_db()
    imported = skipped = errors = changed = 0

    for i, name in enumerate(activity_files):
        try:
            data = safe_zip_read(zf, name)
            if name.lower().endswith('.gz'):
                data = safe_gunzip(data)
            act = parse_activity_file(name, data)
            if act and act.get('startDateLocal'):
                from services import duplicates as _d
                if _d.exists_anywhere(db, act['id']):
                    differs = _offer_change(db, act, name)
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
                    after_ride_added(db, (dup or {}).get('kept', act.get('id')))
                    db.commit()
                    imported += 1
            else:
                log.warning('Import skip (no parseable activity): %s', name)
                skipped += 1
        except Exception as e:
            log.error('Import error for %s: %s\n%s', name, e, traceback.format_exc())
            errors += 1

        yield _progress(i + 1, total, imported, skipped, errors)

    log.info('Generic import done — imported=%d skipped=%d errors=%d',
                imported, skipped, errors)
    yield _event({'complete': True, 'imported': imported, 'skipped': skipped, 'changed': changed, 'errors': errors})


def _split_start(act):
    """(startDate, startDateLocal) for the Activity row. A GPX/FIT time with a timezone (a phone recording is UTC 'Z') is stored as
    the UTC instant plus the home-timezone local time, like Garmin rides; a naive time is local already and stays as is."""
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
    return utc.strftime('%Y-%m-%dT%H:%M:%S'), utc.astimezone(tz.zone()).strftime('%Y-%m-%dT%H:%M:%S')


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
    if not calories and rider_id and sport in ('Ride', 'VirtualRide', 'EBikeRide'):
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
           rawData, riderId, maxHeartrate, maxWatts, caloriesRaw, createdAt, updatedAt)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
    ''', [
        act.get('id'),            act.get('name'),          sport,
        sport,                    start_utc, start_local,
        act.get('distance') or 0, act.get('movingTime') or 0, act.get('elapsedTime') or 0,
        act.get('totalElevationGain') or 0, avg_speed, act.get('maxSpeed') or 0,   # true max (was the average)
        act.get('averageHeartrate'), act.get('averageWatts'),
        act.get('averageCadence'), calories,
        act.get('startLat'),      act.get('startLng'),
        act.get('streams'),       '{}',
        rider_id, act.get('maxHeartrate'), act.get('maxWatts'), calories_raw,
    ])
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
