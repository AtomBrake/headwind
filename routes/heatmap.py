
import json
import logging
from flask import Blueprint, Response, abort, render_template, request
from database import get_db, query_db
from services import map_tiles, sports, tracks as _tracks, zwift
from services import whose

log = logging.getLogger(__name__)

bp = Blueprint('heatmap', __name__)

# The lines drawn are worked out once per activity (services/tracks.py: simplified to within SIMPLIFY_M for the live map, SIMPLIFY_HD_M for the HD export), not from
# every activity's streams on each request. Every sport with a track: rides, runs, walks, hikes, swims and the rest.
_WITH_LINE = 'FROM Activity a JOIN ActivityTrack t ON t.activityId = a.id WHERE t.line IS NOT NULL'


def _people():
    """Whose lines the heatmap can show: the request's own rider (whose.rider_id: the owner, today) first, then this instance's other riders,
    then friends (their activities came in by friend sync, routes/friends.py), each but the first only once they have a line to draw."""
    return query_db(f'''
        SELECT r.id, r.name, r.isDefault, f.id IS NOT NULL AS isFriend
        FROM Rider r LEFT JOIN Friend f ON f.riderId = r.id
        WHERE r.id = ? OR EXISTS (SELECT 1 {_WITH_LINE} AND a.riderId = r.id)
        ORDER BY isFriend, r.isDefault DESC, r.name COLLATE NOCASE
    ''', [whose.rider_id()])


def _who_sql(who):
    """?who= as SQL on Activity a: '' (the default) the request's own rider's activities, 'all' everyone's together, or one rider's id."""
    if who == 'all':
        return '', []
    if who.isdigit():
        return ' AND a.riderId = ?', [int(who)]
    own = whose.rider_id()
    return (' AND a.riderId = ?', [own]) if own is not None else ('', [])


@bp.route('/heatmap')
def index():
    _tracks.fill(get_db())                     # anything new since start-up
    bounds = query_db(
        f"SELECT MIN(date(a.startDateLocal)) as min_d, MAX(date(a.startDateLocal)) as max_d {_WITH_LINE}",
        one=True
    )
    sport_types = query_db(                    # virtual rides and runs have their own Zwift switch
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


def _cut(rows):
    """The HD export's rows with each rider's privacy zones cut out (services/privacy_zones.py): an image is made to be shown. A line that
    goes into a zone is broken there, and each piece outside goes out as a row of its own, the same activity's. A line nowhere near a zone
    isn't read."""
    from services import privacy_zones
    zones = privacy_zones.hiders(get_db())
    if not zones:
        return rows
    out = []
    for r in rows:
        h = zones.get(r[0])
        if not h or not h.near_box(*r[3:7]):
            out.append(r)
            continue
        for piece in h.pieces(json.loads(r[1])):
            out.append((r[0], json.dumps(piece, separators=(',', ':')), *r[2:]))
    return out


@bp.route('/heatmap/data')
def data():
    from_date = request.args.get('from', '')
    to_date   = request.args.get('to', '')
    sport     = request.args.get('sport', '').strip()
    who       = request.args.get('who', '').strip()
    virtual   = request.args.get('virtual', 'out')    # Zwift and other virtual rides and runs: 'out' (the default: no patch of ocean), 'in' or 'only'

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
    rows = query_db(f"SELECT a.riderId, {col}, a.sportType, t.minLat, t.maxLat, t.minLng, t.maxLng, a.id, a.name, a.startDateLocal, a.distance "
                    f"FROM Activity a JOIN ActivityTrack t ON t.activityId = a.id {where}", params)
    if hd:
        rows = _cut(rows)
    worlds = []                                # the Zwift world each virtual activity is in, so the page can draw its map; null for the rest
    for r in rows:
        w = zwift.world_of(*r[3:7]) if sports.is_virtual(r[2]) else None
        worlds.append(w['slug'] if w else None)
    # Each line is stored as JSON already: joined as they are, rather than parsed and written out again. `riders` is whose each track is;
    # `ids`, `names`, `dates`, `sports` and `distances` (metres) are what a click on a track shows and opens, in the same order.
    return Response('{"count":%d,"tracks":[%s],"riders":%s,"worlds":%s,"ids":%s,"names":%s,"dates":%s,"sports":%s,"distances":%s}' % (
                        len(rows), ','.join(r[1] for r in rows), json.dumps([r[0] for r in rows]), json.dumps(worlds),
                        json.dumps([r[7] for r in rows]),
                        json.dumps([r[8] or sports.label(r[2]) for r in rows]),
                        json.dumps([r[9] for r in rows]),
                        json.dumps([sports.label(r[2]) for r in rows]),
                        json.dumps([round(r[10]) if r[10] is not None else None for r in rows])),
                    mimetype='application/json')
