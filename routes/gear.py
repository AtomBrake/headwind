"""Gear: bikes, the parts on them, a service log, and which bike rode which ride; and kit, the gear that isn't a bike (shoes first). See services/gear.py
and services/kit.py for the rules and docs/GEAR.md for the tour."""
import json
import logging
import os

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, send_from_directory, url_for

from database import get_db, query_db
from services import gear, kit
from services.gear_catalog import CATALOG, GROUPS
from services.rider_mode import multi_rider, owner_rider_id

log = logging.getLogger(__name__)
bp = Blueprint('gear', __name__)


def _units():
    r = query_db('SELECT units FROM Settings WHERE id=1', one=True)
    return (r['units'] if r and r['units'] else 'imperial')


def _rider_id():
    """The rider whose gear we are looking at: the owner, or ?rider=N / form rider in a multi-rider install."""
    want = request.values.get('rider', type=int)
    if want and multi_rider() and query_db('SELECT 1 FROM Rider WHERE id=?', [want], one=True):
        return want
    return owner_rider_id()


def _bike_or_404(bike_id):
    b = gear.get_bike(get_db(), bike_id)
    if not b:
        abort(404)
    return b


def _disp_dist(meters, units):
    """metres -> a tidy number in the user's units for form fields."""
    if meters is None:
        return ''
    return round(meters / 1000 / 10) * 10 if units == 'metric' and meters >= 10000 else (round(meters / 1000, 1) if units == 'metric' else round(meters / gear.MI))


def _catalog_for_ui(units):
    out = []
    for c in CATALOG:
        out.append(dict(c, check=_disp_dist(c['check_m'], units) if c['check_m'] else '', replace=_disp_dist(c['replace_m'], units) if c['replace_m'] else ''))
    return out


def _back(default):
    """Where a form says to go next (a list it was sent from), if it's a path on this site; otherwise the default."""
    back = request.form.get('back') or ''
    return back if back.startswith('/') and not back.startswith('//') else default


def _flash_redirect(url, error=None):
    from urllib.parse import quote
    if error:
        url += ('&' if '?' in url else '?') + 'error=' + quote(str(error))
    return redirect(url)


# ---------- overview ----------
@bp.route('/')
def index():
    db = get_db()
    rid = _rider_id()
    units = _units()
    bikes = []
    for b in gear.list_bikes(db, rid, include_archived=request.args.get('archived') == '1'):
        st = gear.bike_stats(db, b['id'])
        bikes.append({'bike': b, 'stats': st, 'odometer': gear.odometer(db, b), 'health': gear.bike_health(db, b['id'])})
    default = query_db('SELECT defaultBikeId FROM Rider WHERE id=?', [rid], one=True)
    from services import strava_gear
    strava = {'pending': strava_gear.pending(db, rid), 'any': bool(query_db('SELECT 1 FROM StravaBike WHERE riderId=?', [rid], one=True))}
    used = kit.all_stats(db, rid)
    items = [{'kit': k, 'stats': used.get(k['id'], {}), 'status': kit.status(db, k, used.get(k['id'], {}).get('distance', 0)), 'defaults': kit.defaults_of(db, k['id']),
              'icon': kit.KIND_ICONS.get(k['kind'], '')}
             for k in kit.list_kit(db, rid, include_retired=request.args.get('retired') == '1')]
    return render_template('gear.html', bikes=bikes, kit_items=items, no_gear=_no_gear(db, rid), kit_due=kit.due_items(db, rid), show_retired=request.args.get('retired') == '1',
                           has_retired=bool(query_db('SELECT 1 FROM Kit WHERE riderId=? AND retiredOn IS NOT NULL', [rid], one=True)), strava=strava, default_id=default['defaultBikeId'] if default else None, due=gear.due_items(db, rid), span=gear.ride_span(db, rid), rid=rid,
                           riders=query_db('SELECT id, name FROM Rider ORDER BY isDefault DESC, name') if multi_rider() else [], error=request.args.get('error'), units=units,
                           show_archived=request.args.get('archived') == '1', has_archived=bool(query_db('SELECT 1 FROM Bike WHERE riderId=? AND archived=1', [rid], one=True)))


def _no_gear(db, rid):
    """The Gear page's note on activities with no gear: {'href': the Activities page filtered to them, 'n', 'types': [(sport, n, href)]},
    each type linking to that sport alone. Rides count once there's a bike, the rest once there's kit for their sport (gear.no_gear_kind,
    gear.kit_sports); None for nothing."""
    from urllib.parse import urlencode
    from werkzeug.datastructures import MultiDict
    from services.sport_filter import SportFilter
    which = gear.no_gear_kind(db, rid)
    counts = gear.no_gear_counts(db, rid, which) if which else []
    if not counts:
        return None
    names = [s for s, _ in SportFilter(db, rid, MultiDict()).sports]
    href = lambda skip=(): url_for('dashboard.activities_page') + '?' + urlencode([('gear', which), ('rider', rid)] + [('skip', x) for x in skip])
    return {'href': href(), 'n': sum(n for _, n in counts), 'types': [(s, n, href([x for x in names if x != s])) for s, n in counts]}


@bp.route('/photo/<name>')
def photo(name):
    if not gear.valid_photo_name(name):
        abort(404)
    return send_from_directory(gear.photo_dir(current_app.config['DATABASE']), name, max_age=3600)


# ---------- bikes ----------
@bp.route('/bike/new')
@bp.route('/bike/<int:bike_id>/edit')
def bike_form(bike_id=None):
    b = _bike_or_404(bike_id) if bike_id else None
    units = _units()
    return render_template('gear_bike_form.html', bike=b, kinds=gear.BIKE_KINDS, units=units, rid=(b['riderId'] if b else _rider_id()), error=request.args.get('error'),
                           start_disp=_disp_dist(b['startMeters'], units) if b and b['startMeters'] else '')


@bp.route('/bike/save', methods=['POST'])
def bike_save():
    db = get_db()
    f = request.form
    units = _units()
    bike_id = f.get('id', type=int)
    try:
        start = gear.to_meters(f['start'], units) if f.get('start') not in (None, '') else 0
        fields = dict(name=f.get('name'), kind=f.get('kind'), brand=f.get('brand'), model=f.get('model'), year=f.get('year'), boughtOn=f.get('boughtOn'), startMeters=start, notes=f.get('notes'))
        if bike_id:
            b = _bike_or_404(bike_id)
            gear.update_bike(db, bike_id, **fields)
        else:
            bike_id = gear.create_bike(db, f.get('rider', type=int) or _rider_id(), f.get('name'), f.get('kind') or 'road', f.get('brand'), f.get('model'), f.get('year'), f.get('boughtOn') or None, start, f.get('notes'))
        upload = request.files.get('photo')
        if upload and upload.filename and os.environ.get('HEADWIND_DEMO') != '1':        # the public demo never writes uploaded files
            gear.save_photo(db, bike_id, upload.read(gear.MAX_PHOTO_BYTES + 1), current_app.config['DATABASE'])
        db.commit()
    except (ValueError, TypeError) as e:
        db.rollback()
        return _flash_redirect(url_for('gear.bike_form', bike_id=f.get('id', type=int)) if f.get('id') else url_for('gear.bike_form'), e)
    return redirect(url_for('gear.bike', bike_id=bike_id))


@bp.route('/bike/<int:bike_id>')
def bike(bike_id):
    db = get_db()
    b = _bike_or_404(bike_id)
    units = _units()
    st = gear.bike_stats(db, bike_id)
    from services.gear_catalog import BY_KIND
    def _group(p):
        return (BY_KIND.get(p['kind']) or BY_KIND['custom'])['group']
    parts = sorted(({'part': p, 'status': gear.part_status(db, p), 'group': _group(p), 'label': (BY_KIND.get(p['kind']) or BY_KIND['custom'])['label']} for p in gear.part_rows(db, bike_id)),
                   key=lambda x: (GROUPS.index(x['group']) if x['group'] in GROUPS else 99, x['part']['kind'], x['part']['installedOn']))
    retired = [{'part': p, 'status': gear.part_status(db, p)} for p in gear.part_rows(db, bike_id, include_retired=True) if p['retiredOn']]
    recent = db.execute('SELECT id, name, sportType, startDateLocal, distance, movingTime, averageSpeed, totalElevationGain FROM Activity WHERE bikeId=? ORDER BY startDateLocal DESC LIMIT 8', [bike_id]).fetchall()
    default = query_db('SELECT defaultBikeId FROM Rider WHERE id=?', [b['riderId']], one=True)
    from services.strava_gear import strava_name
    return render_template('gear_bike.html', bike=b, strava_name=strava_name(db, bike_id), stats=st, odometer=gear.odometer(db, b), parts=parts, retired=retired, log=gear.service_log(db, bike_id), recent=recent, units=units,
                           catalog=_catalog_for_ui(units), groups=GROUPS, actions=gear.ACTIONS, is_default=bool(default and default['defaultBikeId'] == bike_id), today=gear.today().isoformat(),
                           by_year=json.dumps(st['by_year']), error=request.args.get('error'), kinds=dict(gear.BIKE_KINDS))


@bp.route('/strava')
def strava_page():
    """Match the bikes a Strava export named to the rider's bikes (services/strava_gear.py)."""
    from services import strava_gear
    db = get_db()
    rid = _rider_id()
    rows = strava_gear.overview(db, rid)
    return render_template('gear_strava.html', rows=rows, bikes=gear.list_bikes(db, rid, include_archived=True), kinds=gear.BIKE_KINDS, rid=rid,
                           riders=query_db('SELECT id, name FROM Rider ORDER BY isDefault DESC, name') if multi_rider() else [], error=request.args.get('error'),
                           elsewhere=sum(r['elsewhere'] for r in rows), done=request.args.get('done'))


@bp.route('/strava', methods=['POST'])
def strava_save():
    from services import strava_gear
    db = get_db()
    f = request.form
    rid = _rider_id()
    names = f.getlist('name')
    choices = {n: {'match': f.get(f'match_{i}'), 'kind': f.get(f'kind_{i}'), 'retired': bool(f.get(f'retired_{i}'))} for i, n in enumerate(names)}
    try:
        res = strava_gear.save(db, rid, choices, replace=bool(f.get('replace')))
        db.commit()
    except ValueError as e:
        db.rollback()
        return _flash_redirect(url_for('gear.strava_page', rider=rid), e)
    try:
        from services.mqtt import push_update
        push_update(background=True)
    except Exception:
        log.warning('Home Assistant update after matching Strava bikes failed', exc_info=True)
    n, m = len(res['created']), res['moved']
    done = (f"Added {n} bike{'s' if n != 1 else ''}; " if n else '') + (f"{m:,} rides put on their Strava bikes." if m != 1 else "1 ride put on its Strava bike.")
    return redirect(url_for('gear.strava_page', rider=rid, done=done))


@bp.route('/bike/<int:bike_id>/default', methods=['POST'])
def bike_default(bike_id):
    db = get_db()
    b = _bike_or_404(bike_id)
    try:
        gear.set_default(db, b['riderId'], bike_id)
        db.commit()
    except ValueError as e:
        return _flash_redirect(url_for('gear.bike', bike_id=bike_id), e)
    return redirect(request.referrer or url_for('gear.bike', bike_id=bike_id))


@bp.route('/default', methods=['POST'])
def set_default():
    db = get_db()
    rid = request.form.get('rider', type=int) or _rider_id()
    bid = request.form.get('bike', type=int)
    try:
        gear.set_default(db, rid, bid)
        db.commit()
    except ValueError as e:
        return _flash_redirect(url_for('gear.index'), e)
    return redirect(request.referrer or url_for('gear.index'))


@bp.route('/bike/<int:bike_id>/archive', methods=['POST'])
def bike_archive(bike_id):
    db = get_db()
    _bike_or_404(bike_id)
    gear.archive_bike(db, bike_id, request.form.get('undo') != '1')
    db.commit()
    return redirect(url_for('gear.index'))


@bp.route('/bike/<int:bike_id>/delete', methods=['POST'])
def bike_delete(bike_id):
    db = get_db()
    b = _bike_or_404(bike_id)
    gear.remove_photo(db, bike_id, current_app.config['DATABASE'])
    gear.delete_bike(db, bike_id)
    db.commit()
    return redirect(url_for('gear.index', rider=b['riderId']))


@bp.route('/bike/<int:bike_id>/photo', methods=['POST'])
def bike_photo(bike_id):
    db = get_db()
    _bike_or_404(bike_id)
    if os.environ.get('HEADWIND_DEMO') == '1':
        return _flash_redirect(url_for('gear.bike', bike_id=bike_id), 'Picture uploads are switched off in the demo.')
    try:
        if request.form.get('remove'):
            gear.remove_photo(db, bike_id, current_app.config['DATABASE'])
        else:
            up = request.files.get('photo')
            if not up or not up.filename:
                raise ValueError('choose a picture first')
            gear.save_photo(db, bike_id, up.read(gear.MAX_PHOTO_BYTES + 1), current_app.config['DATABASE'])
        db.commit()
    except ValueError as e:
        return _flash_redirect(url_for('gear.bike', bike_id=bike_id), e)
    return redirect(url_for('gear.bike', bike_id=bike_id))


# ---------- parts and service ----------
def _meters_field(name, units):
    v = request.form.get(name)
    return gear.to_meters(v, units) if v not in (None, '') else None


@bp.route('/bike/<int:bike_id>/part', methods=['POST'])
def part_add(bike_id):
    db = get_db()
    _bike_or_404(bike_id)
    units = _units()
    f = request.form
    try:
        pid = gear.add_part(db, bike_id, f.get('kind'), f.get('name'), f.get('installedOn') or None, _meters_field('initial', units) or 0, _meters_field('checkEvery', units), _meters_field('replaceEvery', units),
                            f.get('checkDays') or None, f.get('replaceDays') or None, f.get('notify') == '1', f.get('cost') or None, f.get('notes'))
        db.commit()
        gear.evaluate_alerts(db)
        db.commit()
    except (ValueError, TypeError) as e:
        db.rollback()
        return _flash_redirect(url_for('gear.bike', bike_id=bike_id), e)
    return redirect(url_for('gear.bike', bike_id=bike_id) + '#parts')


@bp.route('/part/<int:part_id>/edit', methods=['POST'])
def part_edit(part_id):
    db = get_db()
    p = db.execute('SELECT * FROM Part WHERE id=?', [part_id]).fetchone()
    if not p:
        abort(404)
    units = _units()
    f = request.form
    try:
        gear.update_part(db, part_id, name=f.get('name'), installedOn=f.get('installedOn') or p['installedOn'], initialMeters=_meters_field('initial', units) or 0,
                         checkEveryM=_meters_field('checkEvery', units), replaceEveryM=_meters_field('replaceEvery', units), checkEveryDays=f.get('checkDays') or None,
                         replaceEveryDays=f.get('replaceDays') or None, notify=f.get('notify') == '1', notes=f.get('notes'))
        db.commit()
    except (ValueError, TypeError) as e:
        db.rollback()
        return _flash_redirect(url_for('gear.bike', bike_id=p['bikeId']), e)
    return redirect(url_for('gear.bike', bike_id=p['bikeId']) + '#parts')


@bp.route('/bike/<int:bike_id>/service', methods=['POST'])
def service_add(bike_id):
    db = get_db()
    _bike_or_404(bike_id)
    f = request.form
    try:
        new_part = False if f.get('fit_new') == '0' else {'name': f.get('new_name') or None, 'cost': f.get('cost') or None}
        gear.log_service(db, bike_id, f.get('action'), f.get('date') or None, f.get('part', type=int) or None, f.get('cost') or None, f.get('notes'), new_part)
        db.commit()
        gear.evaluate_alerts(db)
        db.commit()
    except (ValueError, TypeError) as e:
        db.rollback()
        return _flash_redirect(url_for('gear.bike', bike_id=bike_id), e)
    return redirect(url_for('gear.bike', bike_id=bike_id) + '#log')


@bp.route('/log/<int:log_id>/delete', methods=['POST'])
def log_delete(log_id):
    db = get_db()
    row = db.execute('SELECT bikeId FROM ServiceLog WHERE id=?', [log_id]).fetchone()
    if not row:
        abort(404)
    gear.delete_log(db, log_id)
    db.commit()
    return redirect(url_for('gear.bike', bike_id=row['bikeId']) + '#log')


# ---------- kit: shoes and the other gear that isn't a bike (services/kit.py) ----------
def _kit_or_404(kit_id):
    k = kit.get(get_db(), kit_id)
    if not k:
        abort(404)
    return k


def _sport_choices(db, rider_id, have=()):
    """The sports a default can be set for: the rider's own non-ride sports, most done first, then the usual ones, then any already picked."""
    from services.sports import is_ride
    seen, out = set(), []
    rows = db.execute('SELECT sportType, COUNT(*) n FROM Activity WHERE riderId=? GROUP BY sportType ORDER BY n DESC', [rider_id]).fetchall()
    for s in [r['sportType'] for r in rows if not is_ride(r['sportType'])] + kit.DEFAULT_SPORTS + list(have):
        key = kit.sport_key(s)
        if s and key and key not in seen:
            seen.add(key)
            out.append((key, s))
    return out


@bp.route('/kit/new')
@bp.route('/kit/<int:kit_id>/edit')
def kit_form(kit_id=None):
    db = get_db()
    k = _kit_or_404(kit_id) if kit_id else None
    units = _units()
    rid = k['riderId'] if k else _rider_id()
    have = kit.defaults_of(db, kit_id) if k else []
    taken = {s: kid for s, kid in kit.defaults(db, rid).items() if kid != kit_id}
    names = {x['id']: x['name'] for x in kit.list_kit(db, rid, include_retired=True)}
    return render_template('gear_kit_form.html', kit=k, kinds=kit.KINDS, units=units, rid=rid, error=request.args.get('error'),
                           kind=(k['kind'] if k else request.args.get('kind') or 'shoes'), sports=_sport_choices(db, rid, have), have=set(have),
                           taken={s: names.get(kid, '') for s, kid in taken.items()},
                           start_disp=_disp_dist(k['startMeters'], units) if k and k['startMeters'] else '',
                           replace_disp=(_disp_dist(k['replaceAtM'], units) if k['replaceAtM'] else '') if k else _disp_dist(kit.REPLACE_DEFAULT_M['shoes'], units))


@bp.route('/kit/save', methods=['POST'])
def kit_save():
    db = get_db()
    f = request.form
    units = _units()
    kit_id = f.get('id', type=int)
    try:
        start = gear.to_meters(f['start'], units) if f.get('start') not in (None, '') else 0
        replace = gear.to_meters(f['replace'], units) if f.get('replace') not in (None, '') else 0      # blank: never
        fields = dict(name=f.get('name'), kind=f.get('kind'), brand=f.get('brand'), model=f.get('model'), boughtOn=f.get('boughtOn'),
                      startMeters=start, replaceAtM=replace, notes=f.get('notes'))
        if kit_id:
            _kit_or_404(kit_id)
            kit.update(db, kit_id, **fields)
        else:
            kit_id = kit.create(db, f.get('rider', type=int) or _rider_id(), f.get('name'), f.get('kind') or 'shoes', f.get('brand'), f.get('model'),
                                f.get('boughtOn') or None, start, replace, f.get('notes'))
        if not kit.get(db, kit_id)['retiredOn']:
            kit.set_defaults(db, kit_id, f.getlist('sport'))
        kit.evaluate_alerts_for(db, kit_id)
        db.commit()
    except (ValueError, TypeError) as e:
        db.rollback()
        return _flash_redirect(url_for('gear.kit_form', kit_id=f.get('id', type=int)) if f.get('id') else url_for('gear.kit_form'), e)
    return redirect(url_for('gear.kit_page', kit_id=kit_id))


@bp.route('/kit/<int:kit_id>')
def kit_page(kit_id):
    db = get_db()
    k = _kit_or_404(kit_id)
    recent = db.execute('SELECT id, name, sportType, startDateLocal, distance, movingTime, averageSpeed, totalElevationGain FROM Activity WHERE kitId=? ORDER BY startDateLocal DESC LIMIT 12',
                        [kit_id]).fetchall()
    from services.strava_gear import strava_kit_name
    return render_template('gear_kit.html', kit=k, stats=kit.stats(db, kit_id), status=kit.status(db, k), recent=recent, defaults=kit.defaults_of(db, kit_id),
                           kind_label=kit.kind_label(k['kind']), icon=kit.KIND_ICONS.get(k['kind'], ''), strava_name=strava_kit_name(db, kit_id),
                           error=request.args.get('error'))


@bp.route('/kit/<int:kit_id>/retire', methods=['POST'])
def kit_retire(kit_id):
    db = get_db()
    _kit_or_404(kit_id)
    kit.retire(db, kit_id, request.form.get('undo') != '1')
    db.commit()
    return redirect(url_for('gear.kit_page', kit_id=kit_id))


@bp.route('/kit/<int:kit_id>/delete', methods=['POST'])
def kit_delete(kit_id):
    db = get_db()
    k = _kit_or_404(kit_id)
    kit.delete(db, kit_id)
    db.commit()
    return redirect(url_for('gear.index', rider=k['riderId']))


@bp.route('/activity/<rid>/kit', methods=['POST'])
def activity_kit(rid):
    db = get_db()
    back = _back(url_for('rides.detail', rid=rid))
    try:
        kit.set_activity_kit(db, rid, request.form.get('kit', type=int))
        db.commit()
    except ValueError as e:
        db.rollback()
        return _flash_redirect(back, e)
    return redirect(back)


# ---------- which bike on which ride ----------
@bp.route('/ride/<rid>/bike', methods=['POST'])
def ride_bike(rid):
    db = get_db()
    bike_id = request.form.get('bike', type=int)
    back = _back(url_for('rides.detail', rid=rid))
    try:
        _set_bike(db, rid, bike_id)
    except ValueError as e:
        db.rollback()
        return _flash_redirect(back, e)
    return redirect(back)


def _set_bike(db, rid, bike_id):
    """Put one ride on a bike (or none) and commit, then see whether that brought a part due."""
    gear.set_ride_bike(db, rid, bike_id)
    db.commit()
    a = db.execute('SELECT riderId FROM Activity WHERE id=?', [rid]).fetchone()
    if bike_id and a:
        gear.evaluate_alerts(db, rider_id=a['riderId'])
        db.commit()


@bp.route('/assign')
def assign_page():
    db = get_db()
    rid = _rider_id()
    bikes = gear.list_bikes(db, rid, include_archived=True)     # retired last: old rides may have been on them
    return render_template('gear_assign.html', bikes=bikes, bike_names=[b['name'] + (' (retired)' if b['archived'] else '') for b in bikes], span=gear.ride_span(db, rid), rid=rid, today=gear.today().isoformat(), preselect=request.args.get('bike', type=int),
                           riders=query_db('SELECT id, name FROM Rider ORDER BY isDefault DESC, name') if multi_rider() else [])


@bp.route('/api/calendar')
def api_calendar():
    rid = _rider_id()
    try:
        year, month = int(request.args['year']), int(request.args['month'])
        if not (1900 <= year <= 2100 and 1 <= month <= 12):
            raise ValueError
    except (KeyError, ValueError):
        return jsonify({'error': 'year and month are required'}), 400
    return jsonify({'days': gear.calendar_month(get_db(), rid, year, month)})


@bp.route('/api/day-rides')
def api_day_rides():
    """The rides on the days picked on the calendar (?dates=YYYY-MM-DD,...), so each can get its own bike: [{id, name, sport, when, distance,
    bike, bike_name}], at most gear.DAY_RIDES_MAX, and how many there are in all."""
    try:
        dates = [d for d in (request.args.get('dates') or '').split(',') if d]
        rides, total = gear.day_rides(get_db(), _rider_id(), dates)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'rides': rides, 'total': total})


@bp.route('/api/ride-bike', methods=['POST'])
def api_ride_bike():
    """JSON {ride: id, bike: id|null}: one ride's bike, from the calendar's list of a day's rides."""
    db = get_db()
    b = request.get_json(silent=True) or {}
    a = db.execute('SELECT a.id FROM Ride a WHERE a.id=? AND a.riderId=?', [str(b.get('ride') or ''), _rider_id()]).fetchone()
    if not a:
        return jsonify({'error': 'ride not found'}), 404
    try:
        _set_bike(db, a['id'], int(b['bike']) if b.get('bike') else None)
    except (ValueError, TypeError) as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True})


@bp.route('/api/assign', methods=['POST'])
def api_assign():
    """JSON: {bike: id|null, dates: [...], from: 'YYYY-MM-DD'|null, to: ...|null, only_unassigned: bool, dry_run: bool}. dry_run just counts."""
    db = get_db()
    b = request.get_json(silent=True) or {}
    rid = _rider_id()
    try:
        res = gear.assign_rides(db, rid, b.get('bike'), b.get('dates') or None, b.get('from') or None, b.get('to') or None, bool(b.get('only_unassigned', True)), bool(b.get('dry_run')))
        if not b.get('dry_run'):
            db.commit()
            if b.get('bike'):
                gear.evaluate_alerts(db, rider_id=rid)
                db.commit()
    except (ValueError, TypeError) as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify(res)
