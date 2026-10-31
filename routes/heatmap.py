
import json
import logging
from flask import Blueprint, Response, abort, render_template, request
from database import get_db, query_db
from services import map_tiles, sports, tracks as _tracks, zwift
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
    sport_types = query_db(                    # virtual rides have their own Zwift switch
        f"SELECT DISTINCT a.sportType {_WITH_LINE} AND a.sportType IS NOT NULL AND NOT {sports.virtual_sql('a.sportType')} ORDER BY a.sportType"
    )
    has_virtual = query_db(f"SELECT 1 {_WITH_LINE} AND {sports.virtual_sql('a.sportType')} LIMIT 1", one=True) is not None
    return render_template('heatmap.html',
                           min_date=bounds['min_d'] or '',
                           max_date=bounds['max_d'] or '',
                           sport_types=sport_types,
                           has_virtual=has_virtual,
                           zwift_worlds={w['slug']: zwift.for_page(w) for w in zwift.WORLDS},
                           zwift_credit=zwift.CREDIT,
                           people=[dict(p) for p in _people()])


@bp.route('/heatmap/tile/<int:z>/<int:x>/<int:y>')
def tile_proxy(z, x, y):
    """One map tile for the HD export's canvas, same-origin (services/map_tiles.py has the layers and each provider's terms)."""
    tile = map_tiles.fetch(get_db(), request.args.get('layer', 'dark'), z, x, y)
    if tile is None:
        abort(502)
    return Response(tile[0], mimetype=tile[1], headers={'Cache-Control': 'private, max-age=86400'})


@bp.route('/heatmap/zwift/<slug>.png')
def zwift_map(slug):
    """A Zwift world's map, for the heatmap and a virtual ride's page, and for the HD export's canvas (which can't read Zwift's CDN: no CORS).
    Only the fixed list in services/zwift, so unlike tile_proxy it stays on in demo mode."""
    png = zwift.map_image(slug)
    if png is None:
        abort(404 if slug not in zwift.BY_SLUG else 502)
    return Response(png, mimetype='image/png', headers={'Cache-Control': 'public, max-age=604800'})


@bp.route('/heatmap/data')
def data():
    from_date = request.args.get('from', '')
    to_date   = request.args.get('to', '')
    sport     = request.args.get('sport', '').strip()
    who       = request.args.get('who', '').strip()
    virtual   = request.args.get('virtual', 'out')    # Zwift and other virtual rides: 'out' (the default: no patch of ocean), 'in' or 'only'

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
    if virtual == 'only':
        where += f" AND {sports.virtual_sql('a.sportType')}"
    elif virtual != 'in':
        where += f" AND NOT {sports.virtual_sql('a.sportType')}"
    who_sql, who_params = _who_sql(who)
    where += who_sql
    params.extend(who_params)

    _tracks.fill(get_db())                     # anything new since start-up
    rows = query_db(f"SELECT a.riderId, {col}, a.sportType, t.minLat, t.maxLat, t.minLng, t.maxLng "
                    f"FROM Ride a JOIN ActivityTrack t ON t.activityId = a.id {where}", params)
    worlds = []                                # the Zwift world each virtual ride is in, so the page can draw its map; null for the rest
    for r in rows:
        w = zwift.world_of(*r[3:7]) if sports.is_virtual(r[2]) else None
        worlds.append(w['slug'] if w else None)
    # Each line is stored as JSON already: joined as they are, rather than parsed and written out again. `riders` is whose each track is.
    return Response('{"count":%d,"tracks":[%s],"riders":%s,"worlds":%s}' % (
                        len(rows), ','.join(r[1] for r in rows), json.dumps([r[0] for r in rows]), json.dumps(worlds)),
                    mimetype='application/json')
