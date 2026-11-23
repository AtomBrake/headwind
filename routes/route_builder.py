import html as _html
import json
import logging

import requests
from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, url_for
from database import get_db, query_db
from services import planned_routes
from services import whose
from services.rider_mode import multi_rider

log = logging.getLogger(__name__)
bp = Blueprint('route_builder', __name__, url_prefix='/planner')

_ELEV_BATCH = 100


def _fetch_elevation_m(waypoints):
    if not waypoints:
        return []
    result = []
    for i in range(0, len(waypoints), _ELEV_BATCH):
        batch = waypoints[i:i + _ELEV_BATCH]
        lats = ','.join(str(w['lat']) for w in batch)
        lngs = ','.join(str(w['lng']) for w in batch)
        try:
            r = requests.get(
                'https://api.open-meteo.com/v1/elevation',
                params={'latitude': lats, 'longitude': lngs},
                timeout=10,
            )
            r.raise_for_status()
            result.extend(r.json().get('elevation', [None] * len(batch)))
        except Exception:
            result.extend([None] * len(batch))
    return result


def _build_gpx(name, waypoints, elevations):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Headwind" xmlns="http://www.topografix.com/GPX/1/1">',
        '  <rte>',
        f'    <name>{_html.escape(name)}</name>',
    ]
    for i, wp in enumerate(waypoints):
        elev = elevations[i] if i < len(elevations) and elevations[i] is not None else None
        lines.append(f'    <rtept lat="{wp["lat"]}" lon="{wp["lng"]}">')
        if elev is not None:
            lines.append(f'      <ele>{elev:.1f}</ele>')
        lines.append('    </rtept>')
    lines.append('  </rte>')
    lines.append('</gpx>')
    return '\n'.join(lines)


def _track_gpx(name, track):
    """A route that follows a line as a GPX <trk>, with the heights it came with: nothing to look up."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Headwind" xmlns="http://www.topografix.com/GPX/1/1">',
        f'  <metadata><name>{_html.escape(name)}</name></metadata>',
        '  <trk>',
        f'    <name>{_html.escape(name)}</name>',
        '    <trkseg>',
    ]
    for lat, lng, ele in track:
        lines.append(f'      <trkpt lat="{lat}" lon="{lng}">' + (f'<ele>{ele:.1f}</ele>' if ele is not None else '') + '</trkpt>')
    lines += ['    </trkseg>', '  </trk>', '</gpx>']
    return '\n'.join(lines)


def _gpx_response(name, gpx):
    safe = name.replace(' ', '_').replace('"', '')
    return Response(gpx, mimetype='application/gpx+xml', headers={'Content-Disposition': f'attachment; filename="{safe}.gpx"'})


@bp.route('/')
def index():
    center = query_db(
        'SELECT AVG(startLat) as lat, AVG(startLng) as lng FROM Activity '
        'WHERE startLat IS NOT NULL AND startLng IS NOT NULL',
        one=True,
    )
    default_lat = center['lat'] if center and center['lat'] else 54.0
    default_lng = center['lng'] if center and center['lng'] else -2.0
    return render_template('route_builder.html', default_lat=default_lat, default_lng=default_lng,
                           open_route=request.args.get('route', type=int))      # ?route=N: shown on opening (Save as route on an activity)


def _points(col):
    return f'CASE WHEN json_valid({col}) THEN json_array_length({col}) END'


@bp.route('/routes', methods=['GET'])
def list_routes():
    rows = query_db(f'''
        SELECT p.id, p.name, p.createdAt, p.source, p.sportType, p.distance, p.elevationGain, p.track IS NOT NULL AS hasTrack,
               COALESCE({_points('p.track')}, {_points('p.waypoints')}, 0) AS count, r.name AS riderName
        FROM PlannedRoute p LEFT JOIN Rider r ON r.id = p.riderId
        ORDER BY p.createdAt DESC, p.id DESC''')
    multi = multi_rider()
    return jsonify([{
        'id':        row['id'],
        'name':      row['name'],
        'createdAt': row['createdAt'],
        'source':    row['source'] or 'planner',
        'sportType': row['sportType'],
        'hasTrack':  bool(row['hasTrack']),
        'count':     row['count'],
        'distM':     row['distance'] or 0,
        'gainM':     row['elevationGain'],
        'rider':     row['riderName'] if multi else None,
    } for row in rows])


@bp.route('/routes/<int:route_id>', methods=['GET'])
def get_route(route_id):
    row = query_db('SELECT * FROM PlannedRoute WHERE id=?', [route_id], one=True)
    if not row:
        abort(404)
    return jsonify({
        'id':        row['id'],
        'name':      row['name'],
        'createdAt': row['createdAt'],
        'source':    row['source'] or 'planner',
        'sourceId':  row['sourceId'],
        'sportType': row['sportType'],
        'waypoints': json.loads(row['waypoints'] or '[]'),
        'track':     json.loads(row['track']) if row['track'] else None,
        'distM':     row['distance'] or 0,
        'gainM':     row['elevationGain'],
    })


@bp.route('/routes/<int:route_id>/waypoints', methods=['GET'])
def route_waypoints(route_id):
    """A route that follows a line as waypoints to edit (services/planned_routes.as_waypoints). Saving them makes a new route."""
    row = query_db('SELECT name, waypoints, track FROM PlannedRoute WHERE id=?', [route_id], one=True)
    if not row:
        abort(404)
    wps = planned_routes.as_waypoints(json.loads(row['track'])) if row['track'] else json.loads(row['waypoints'] or '[]')
    return jsonify({'name': row['name'], 'waypoints': wps})


@bp.route('/routes', methods=['POST'])
def save_route():
    data = request.get_json(force=True)
    waypoints = data.get('waypoints') or []
    if len(waypoints) < 2:
        return jsonify({'error': 'Need at least 2 waypoints'}), 400
    try:
        waypoints = [{'lat': float(w['lat']), 'lng': float(w['lng'])} for w in waypoints]
    except (TypeError, ValueError, KeyError):
        return jsonify({'error': 'Waypoints need a lat and lng'}), 400
    db = get_db()
    route_id, _ = planned_routes.save(db, whose.rider_id(), data.get('name'), waypoints=waypoints)
    db.commit()
    row = query_db('SELECT name, distance FROM PlannedRoute WHERE id=?', [route_id], one=True)
    return jsonify({'id': route_id, 'name': row['name'], 'distM': row['distance'], 'count': len(waypoints)}), 201


@bp.route('/routes/import', methods=['POST'])
def import_gpx():
    """GPX files (one route each) saved as routes, source 'gpx'. [{file, status, id, name}], status: saved, exists (the same name and points
    are here already), empty (no points) or unreadable."""
    db = get_db()
    rider_id = whose.rider_id()
    out = []
    for f in request.files.getlist('files'):
        res = {'file': f.filename}
        try:
            got = planned_routes.from_gpx(f.read(), f.filename)
        except Exception as e:
            log.info('Route import: %s could not be read (%s)', f.filename, e)
            out.append({**res, 'status': 'unreadable'})
            continue
        if not got:
            out.append({**res, 'status': 'empty'})
            continue
        route_id, new = planned_routes.save(db, rider_id, got['name'], track=got['track'], source='gpx', sport=got['sportType'])
        out.append({**res, 'status': 'saved' if new else 'exists', 'id': route_id, 'name': got['name']})
    db.commit()
    return jsonify(out)


@bp.route('/routes/from-activity/<rid>', methods=['POST'])
def from_activity(rid):
    """Save as route on an activity's page: a route from its own points, the activity's rider's (yours, whose.rider_id, for a friend's activity),
    then the Routes page showing it (routes/saved_routes.py)."""
    db = get_db()
    act = db.execute('SELECT riderId, sportType FROM Activity WHERE id=?', [rid]).fetchone()
    if not act:
        abort(404)
    from services import sports
    if sports.is_virtual(act['sportType']):
        abort(400)                                      # a game world, not a place
    rider_id = act['riderId']
    if rider_id is None or db.execute('SELECT 1 FROM Friend WHERE riderId=?', [rider_id]).fetchone():
        rider_id = whose.rider_id()
    got = planned_routes.from_activity(db, rid, rider_id)
    if not got:
        abort(400)                                      # no GPS track
    db.commit()
    return redirect(url_for('saved_routes.index', route=got[0]))


@bp.route('/routes/<int:route_id>', methods=['DELETE'])
def delete_route(route_id):
    db = get_db()
    db.execute('DELETE FROM PlannedRoute WHERE id=?', [route_id])
    db.commit()
    return '', 204


@bp.route('/export', methods=['POST'])
def export_current():
    data = request.get_json(force=True)
    name = (data.get('name') or 'Route').strip()[:100]
    waypoints = data.get('waypoints') or []
    if len(waypoints) < 2:
        return jsonify({'error': 'Need at least 2 waypoints'}), 400
    elevations = _fetch_elevation_m(waypoints)
    return _gpx_response(name, _build_gpx(name, waypoints, elevations))


@bp.route('/routes/<int:route_id>/export.gpx')
def export_saved(route_id):
    row = query_db('SELECT name, waypoints, track FROM PlannedRoute WHERE id=?', [route_id], one=True)
    if not row:
        abort(404)
    if row['track']:
        return _gpx_response(row['name'], _track_gpx(row['name'], json.loads(row['track'])))
    waypoints = json.loads(row['waypoints'] or '[]')
    elevations = _fetch_elevation_m(waypoints)
    return _gpx_response(row['name'], _build_gpx(row['name'], waypoints, elevations))
