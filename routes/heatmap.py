
import json
import logging
import requests as _requests
from flask import Blueprint, Response, abort, render_template, request
from database import get_db, query_db
from services import tracks as _tracks
from services.rider_mode import owner_rider_id

log = logging.getLogger(__name__)

bp = Blueprint('heatmap', __name__)

# The lines drawn are worked out once per activity (services/tracks.py: SAMPLE points for the live map, SAMPLE_HD for the HD export), not from
# every ride's streams on each request.
_WITH_LINE = 'FROM Ride a JOIN ActivityTrack t ON t.activityId = a.id WHERE t.line IS NOT NULL'


def _people():
    """Whose lines the heatmap can show: the owner first, then this instance's other riders, then friends (their rides came in by friend
    sync, routes/friends.py), each only once they have a line to draw."""
    return query_db(f'''
        SELECT r.id, r.name, r.isDefault, f.id IS NOT NULL AS isFriend
        FROM Rider r LEFT JOIN Friend f ON f.riderId = r.id
        WHERE r.isDefault = 1 OR EXISTS (SELECT 1 {_WITH_LINE} AND a.riderId = r.id)
        ORDER BY isFriend, r.isDefault DESC, r.name COLLATE NOCASE
    ''')


def _who_sql(who):
    """?who= as SQL on Ride a: '' (the default) the owner's rides, 'all' everyone's together, or one rider's id."""
    if who == 'all':
        return '', []
    if who.isdigit():
        return ' AND a.riderId = ?', [int(who)]
    owner = owner_rider_id()
    return (' AND a.riderId = ?', [owner]) if owner is not None else ('', [])


@bp.route('/heatmap')
def index():
    _tracks.fill(get_db())                     # anything new since start-up
    bounds = query_db(
        f"SELECT MIN(date(a.startDateLocal)) as min_d, MAX(date(a.startDateLocal)) as max_d {_WITH_LINE}",
        one=True
    )
    sport_types = query_db(
        f'SELECT DISTINCT a.sportType {_WITH_LINE} AND a.sportType IS NOT NULL ORDER BY a.sportType'
    )
    return render_template('heatmap.html',
                           min_date=bounds['min_d'] or '',
                           max_date=bounds['max_d'] or '',
                           sport_types=sport_types,
                           people=[dict(p) for p in _people()])


_ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/'
# layer name -> (Esri service path, native max zoom or None). CARTO's basemaps needed an API key from 2026, so dark/light are now
# Esri's keyless gray canvases (each is a base + a transparent place-name overlay, exported as two layers).
_TILE_LAYERS = {
    'satellite': ('World_Imagery', None),
    'labels':    ('Reference/World_Boundaries_and_Places', None),
    'dark':      ('Canvas/World_Dark_Gray_Base', 16),
    'dark_ref':  ('Canvas/World_Dark_Gray_Reference', 16),
    'light':     ('Canvas/World_Light_Gray_Base', 16),
    'light_ref': ('Canvas/World_Light_Gray_Reference', 16),
}


@bp.route('/heatmap/tile/<int:z>/<int:x>/<int:y>')
def tile_proxy(z, x, y):
    """Proxy map tiles for HD canvas export (bypasses CORS)."""
    path, native = _TILE_LAYERS.get(request.args.get('layer', 'dark'), _TILE_LAYERS['dark'])
    try:
        if native and z > native:
            # Past the layer's native zoom: take the parent tile and enlarge the right quarter/sixteenth of it — what Leaflet
            # does on screen — instead of Esri's "map data not available" placeholder.
            import io
            from PIL import Image
            dz = z - native
            r = _requests.get(f'{_ESRI}{path}/MapServer/tile/{native}/{y >> dz}/{x >> dz}', timeout=8,
                              headers={'User-Agent': 'Headwind/1.0 (self-hosted bike app)'})
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert('RGBA')
                size = img.width >> dz
                left, top = (x & ((1 << dz) - 1)) * size, (y & ((1 << dz) - 1)) * size
                out = io.BytesIO()
                img.crop((left, top, left + size, top + size)).resize((256, 256), Image.LANCZOS).save(out, 'PNG')
                return Response(out.getvalue(), mimetype='image/png', headers={
                    'Cache-Control': 'public, max-age=86400', 'Access-Control-Allow-Origin': '*'})
        else:
            r = _requests.get(f'{_ESRI}{path}/MapServer/tile/{z}/{y}/{x}', timeout=8,
                              headers={'User-Agent': 'Headwind/1.0 (self-hosted bike app)'})
            if r.status_code == 200:
                return Response(r.content, mimetype=r.headers.get('Content-Type', 'image/png'), headers={
                    'Cache-Control': 'public, max-age=86400', 'Access-Control-Allow-Origin': '*'})
    except Exception:
        log.debug('Satellite tile fetch failed', exc_info=True)
    abort(502)


@bp.route('/heatmap/data')
def data():
    from_date = request.args.get('from', '')
    to_date   = request.args.get('to', '')
    sport     = request.args.get('sport', '').strip()
    who       = request.args.get('who', '').strip()

    hd = request.args.get('hd') == '1'
    col = 't.lineHd' if hd else 't.line'
    where = f"WHERE {col} IS NOT NULL"
    params = []
    if from_date and to_date:
        where += " AND date(a.startDateLocal) BETWEEN ? AND ?"
        params.extend([from_date, to_date])
    elif from_date:
        where += " AND date(a.startDateLocal) >= ?"
        params.append(from_date)
    elif to_date:
        where += " AND date(a.startDateLocal) <= ?"
        params.append(to_date)
    if sport:
        where += " AND lower(a.sportType) LIKE ?"
        params.append(f'%{sport.lower()}%')
    who_sql, who_params = _who_sql(who)
    where += who_sql
    params.extend(who_params)

    _tracks.fill(get_db())                     # anything new since start-up
    rows = query_db(f"SELECT a.riderId, {col} FROM Ride a JOIN ActivityTrack t ON t.activityId = a.id {where}", params)
    # Each line is stored as JSON already: joined as they are, rather than parsed and written out again. `riders` is whose each track is.
    return Response('{"count":%d,"tracks":[%s],"riders":%s}' % (len(rows), ','.join(r[1] for r in rows), json.dumps([r[0] for r in rows])),
                    mimetype='application/json')
