"""The Routes page: every saved route (PlannedRoute, services/planned_routes.py) drawn together on one map, each line opening the route, and
listed in a table to sort and filter, with routes brought in from GPX files, a Strava export or Garmin Connect's courses. Each route has a page
of its own (/routes/<id>): its map and profile, renaming, its sport, and the activities that followed it (services/route_library.py). A route
from an activity is made on the activity's page (Save as route, routes/route_builder.from_activity), which opens the route's page. Routes
aren't edited here: the planner (routes/route_builder.py) is hidden until it works.

The route's own data (its points, GPX export, delete) and the GPX import are the planner's endpoints under /planner/routes."""
import logging
import zipfile

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for
from database import get_db, query_db
from services import jobs, planned_routes, route_library, sports
from services import whose
from services.rider_mode import multi_rider

log = logging.getLogger(__name__)
bp = Blueprint('saved_routes', __name__, url_prefix='/routes')

GARMIN_JOB = 'garmin_courses'
SOURCE_LABELS = {'planner': 'Drawn in the planner', 'gpx': 'GPX file', 'activity': 'Activity', 'strava': 'Strava', 'garmin': 'Garmin'}


def _garmin_on():
    from services.garmin import connected
    return connected(query_db('SELECT garminEmail, garminPassword FROM Settings WHERE id=1', one=True))


def _kept_exports():
    """The Strava exports kept for Import again (services/strava_export.py) whose routes can be read without uploading the file again."""
    from services import strava_export
    return strava_export.kept(get_db(), current_app.config['DATABASE'])


@bp.route('/')
def index():
    show = request.args.get('route', type=int)
    if show is not None:                                  # the old address of one route: its own page now
        return redirect(url_for('saved_routes.route', route_id=show))
    rows = query_db('''
        SELECT p.id, p.name, p.createdAt, COALESCE(p.source, 'planner') AS source, p.sourceId, p.sportType, p.distance, p.elevationGain,
               r.name AS riderName, a.id AS activityId
        FROM PlannedRoute p
        LEFT JOIN Rider r ON r.id = p.riderId
        LEFT JOIN Activity a ON p.source = 'activity' AND a.id = p.sourceId
        ORDER BY p.createdAt DESC, p.id DESC''')
    last = jobs.last(get_db(), GARMIN_JOB)
    used = sorted({r['sportType'] for r in rows if r['sportType']}, key=lambda s: sports.label(s).lower())
    return render_template('routes.html', routes=rows, multi=multi_rider(), source_labels=SOURCE_LABELS,
                           sports=[(s, sports.label(s)) for s in sports.SPORTS], garmin_on=_garmin_on(), kept=_kept_exports(),
                           garmin_job=last['id'] if last and last['state'] in ('queued', 'running') else None,
                           used_sports=[(s, sports.label(s)) for s in used],
                           used_sources=[(k, SOURCE_LABELS.get(k, k)) for k in SOURCE_LABELS if any(r['source'] == k for r in rows)],
                           page=_centre())


def _centre():
    """Where a map with nothing on it yet starts: the middle of the rider's activities, else Britain."""
    c = query_db('SELECT AVG(startLat) AS lat, AVG(startLng) AS lng FROM Activity WHERE startLat IS NOT NULL AND startLng IS NOT NULL', one=True)
    return {'lat': (c['lat'] if c and c['lat'] else 54.0), 'lng': (c['lng'] if c and c['lng'] else -2.0)}


@bp.route('/lines')
def lines():
    """{lines: {id: [[lat, lng], ...]}}: every route's line for the overview map, simplified (route_library.map_line)."""
    return jsonify(lines=route_library.map_lines(get_db()))


@bp.route('/<int:route_id>')
def route(route_id):
    """One route's page: its map and profile (the points come from /planner/routes/<id>), name, sport, GPX and delete, and the activities that
    followed it, fetched after the page (activities)."""
    r = query_db('''
        SELECT p.id, p.name, p.createdAt, COALESCE(p.source, 'planner') AS source, p.sourceId, p.sportType, p.distance, p.elevationGain,
               p.riderId, r.name AS riderName, a.id AS activityId, a.name AS activityName
        FROM PlannedRoute p
        LEFT JOIN Rider r ON r.id = p.riderId
        LEFT JOIN Activity a ON p.source = 'activity' AND a.id = p.sourceId
        WHERE p.id = ?''', [route_id], one=True)
    if not r:
        abort(404)
    return render_template('route.html', r=r, multi=multi_rider(), source_labels=SOURCE_LABELS,
                           sports=[(s, sports.label(s)) for s in sports.SPORTS], page=dict(_centre(), id=route_id))


@bp.route('/<int:route_id>/activities')
def activities(route_id):
    """The route page's "Done before" card (services/route_library.summary), as HTML to put in place: a short note when nothing has followed it."""
    db = get_db()
    if not db.execute('SELECT 1 FROM PlannedRoute WHERE id=?', [route_id]).fetchone():
        abort(404)
    return render_template('_route_activities.html', m=route_library.summary(db, route_id, whose.rider_id()))


@bp.route('/<int:route_id>/segments')
def segments(route_id):
    """The route page's "Segments on this route" card (services/route_library.segments_on), as HTML to put in place: nothing when there are none.
    The segments' shapes are in its data-shapes, for the map."""
    db = get_db()
    if not db.execute('SELECT 1 FROM PlannedRoute WHERE id=?', [route_id]).fetchone():
        abort(404)
    segs = route_library.segments_on(db, route_id, whose.rider_id())
    return render_template('_route_segments.html', segs=segs) if segs else ''


@bp.route('/<int:route_id>', methods=['POST'])
def update(route_id):
    """Rename a route ({name}) or change its sport ({sportType}, '' for none). Answers {name, sportType} as saved."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    if not db.execute('SELECT 1 FROM PlannedRoute WHERE id=?', [route_id]).fetchone():
        return jsonify(error='No such route'), 404
    if 'name' in data and planned_routes.rename(db, route_id, data['name']) is None:
        return jsonify(error='A route needs a name'), 400
    if 'sportType' in data and not planned_routes.set_sport(db, route_id, data['sportType']):
        return jsonify(error='Not a sport Headwind knows'), 400
    db.commit()
    row = db.execute('SELECT name, sportType FROM PlannedRoute WHERE id=?', [route_id]).fetchone()
    return jsonify(name=row['name'], sportType=row['sportType'])


@bp.route('/import/strava', methods=['POST'])
def import_strava():
    """The routes you made on Strava, from a Strava export: the one kept from an earlier import (form rider: whose), or a zip uploaded now
    (form zipfile), of which only routes.csv and routes/ are read. {routes_created, routes_existing, routes_unread}."""
    from services.limits import check_zip
    db = get_db()
    rider = request.form.get('rider', type=int)
    try:
        if rider is not None:
            from services import strava_export
            if not any(k['riderId'] == rider for k in _kept_exports()):
                return jsonify(error='That export is no longer kept'), 404
            zf = zipfile.ZipFile(strava_export.path_for(current_app.config['DATABASE'], rider))
        else:
            f = request.files.get('zipfile')
            if not f or not f.filename:
                return jsonify(error='Choose your Strava export, the .zip Strava emailed you'), 400
            zf = zipfile.ZipFile(f.stream)
            rider = whose.rider_id()
        with zf:
            check_zip(zf)
            names = set(zf.namelist())
            if 'routes.csv' not in names:
                return jsonify(error="That zip isn't a Strava export with routes in it: it has no routes.csv"), 400
            res = planned_routes.import_strava(db, zf, names, rider)
    except zipfile.BadZipFile:
        return jsonify(error='Not a zip file'), 400
    db.commit()
    log.info('Routes page: Strava routes created=%d already here=%d not read=%d',
             res['routes_created'], res['routes_existing'], res['routes_unread'])
    return jsonify(res)


@bp.route('/import/garmin/courses')
def garmin_courses():
    """The Garmin Connect courses to choose from (services/planned_routes.garmin_course_list), with each one's sport as the page shows it:
    {courses: [{id, name, sport, sportLabel, distM, gainM, created, here}]}. One call to Garmin, while the page waits."""
    from services.garmin import SignInNeeded, _client
    if not _garmin_on():
        return jsonify(error='Connect Garmin in Settings first'), 400
    try:
        courses = planned_routes.garmin_course_list(get_db(), _client(), whose.rider_id())
    except SignInNeeded as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        log.warning('Garmin courses: the list could not be read (%s)', e)
        return jsonify(error=f'Could not reach Garmin: {e}'), 502
    for c in courses:
        c['sportLabel'] = sports.label(c['sport']) if c['sport'] else None
    return jsonify(courses=courses)


@bp.route('/import/garmin', methods=['POST'])
def import_garmin():
    """Bring in the Garmin Connect courses chosen on the page ({ids}), in the background (services/jobs.py): each is a download.
    {job}: the one already running, if any."""
    if not _garmin_on():
        return jsonify(error='Connect Garmin in Settings first'), 400
    ids = (request.get_json(silent=True) or {}).get('ids')
    if not isinstance(ids, list) or not ids or not all(isinstance(i, (str, int)) and not isinstance(i, bool) for i in ids):
        return jsonify(error='Choose the courses to bring in'), 400
    db = get_db()
    job = jobs.enqueue(db, GARMIN_JOB, {'rider': whose.rider_id(), 'ids': [str(i) for i in ids]})
    if job is None:
        running = jobs.last(db, GARMIN_JOB)
        job = running['id'] if running else None
    return jsonify(job=job)


@bp.route('/import/garmin/<int:job_id>')
def garmin_status(job_id):
    """{state, progress: {done, total, result?}, error} for the page to poll."""
    job = jobs.get(get_db(), job_id)
    if not job or job['kind'] != GARMIN_JOB:
        return jsonify(error='No such import'), 404
    return jsonify(state=job['state'], progress=job['progress'] or {}, error=job['error'])


@jobs.handler(GARMIN_JOB)
def _garmin_job(job):
    from services.garmin import _client
    db = get_db()
    try:
        api = _client()
    except Exception as e:
        raise RuntimeError(f'Could not reach Garmin: {e}') from e
    res = planned_routes.import_garmin(db, api, job['args']['rider'], ids=job['args'].get('ids'),
                                       progress=lambda done, total: jobs.progress(db, job['id'], done=done, total=total))
    jobs.progress(db, job['id'], result=res)
    log.info('Garmin courses: %d of %d new, %d already here, %d not read', res['created'], res['total'], res['existing'], res['unread'])
