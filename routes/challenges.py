"""The Challenges page: races with friends over set dates (services/challenges.py). They used to be the second half of the Goals page, whose old
form addresses (/goals/challenges...) still answer here, so a page left open from before the move still sends its forms to the right place.
A segment race (services/segment_race.py) has a page of its own too, /challenges/<id>: the map of its segments, the overall table and a board
for each segment. ?segment=<id> on the Challenges page opens the form for a race on that segment (the segment page's Race this segment)."""
from urllib.parse import urlencode

from flask import Blueprint, abort, redirect, render_template, request, url_for

from database import get_db, query_db
from services import challenges, goals, segment_race, sports, whose

bp = Blueprint('challenges', __name__)


def _back(rider_id, error=None):
    args = [('rider', rider_id)] if rider_id and not query_db('SELECT isDefault FROM Rider WHERE id=?', [rider_id], one=True)['isDefault'] else []
    if error:
        args.append(('error', error))
    return redirect(url_for('challenges.index') + ('?' + urlencode(args) if args else ''))


def _rider_id():
    """The rider a form is for (its hidden `rider`) when whose.viewable allows it, or the request's own."""
    view = whose.viewable(request.form.get('rider'))
    return view.id if view else whose.rider_id()


@bp.route('/challenges')
def index():
    from routes.dashboard import _riders
    from services import periods, tz
    _, active_rider, rid = _riders(request.args)
    db = get_db()
    today, p = tz.today(), periods.for_request()
    pickable = segment_race.pickable(db, rid)
    pick = request.args.get('segment', type=int)
    pick = next((s for s in pickable if s['id'] == pick), None)
    return render_template('challenges.html', active_rider=active_rider, rid=rid, challenges=challenges.challenges(db, rid, today=today),
                           pickable=pickable, pick=pick, seg_classes=sports.CLASS_LABELS, class_icons=sports.CLASS_ICONS,
                           class_family=segment_race.CLASS_FAMILY, max_segments=segment_race.MAX_SEGMENTS,
                           pick_missing=request.args.get('segment') is not None and pick is None,
                           error=request.args.get('error'), metrics=goals.METRIC_LABELS, groups=goals.GROUP_LABELS, group_icons=goals.GROUP_ICONS,
                           units_of={m: goals.unit_label(m) for m in goals.METRICS},
                           friends=query_db('SELECT COUNT(*) FROM Friend', one=True)[0], invitable=challenges.invitable(db),
                           today=today.isoformat(), month_end=periods.current('month', p._replace(mode=periods.CALENDAR), today).last.isoformat())


@bp.route('/challenges/<int:cid>')
def race(cid):
    """A segment race's page. The "new" marks are against the boards as this rider last saw them (ChallengeSeen), which become these once the
    page is made."""
    from routes.dashboard import _riders
    from services import tz
    _, active_rider, rid = _riders(request.args)
    db = get_db()
    c = next((c for c in challenges.challenges(db, rid, today=tz.today()) if c['id'] == cid), None)
    if c is None:
        abort(404)
    if c['metric'] != challenges.SEGMENTS:
        return redirect(url_for('challenges.index', **({'rider': rid} if request.args.get('rider') else {})))
    new = segment_race.mark_new(db, cid, rid, c['race'])
    page = render_template('challenge_race.html', active_rider=active_rider, rid=rid, c=c, new=new, on_foot=c['segClass'] == 'foot',
                           map_data=[{'n': s['position'], 'name': s['name'], 'start': s['start'], 'end': s['end'], 'shape': s['shape']}
                                     for s in c['race']['segments']])
    segment_race.seen(db, cid, rid, c['race'])
    return page


@bp.route('/challenges', methods=['POST'])
def start():
    rid = _rider_id()
    return _back(rid, challenges.start_challenge(get_db(), rid, request.form))


@bp.route('/challenges/<int:cid>/<action>', methods=['POST'])
def act(cid, action):
    rid = _rider_id()
    if action in ('join', 'leave'):
        challenges.set_joined(get_db(), cid, action == 'join')
    elif action == 'delete':
        challenges.delete_challenge(get_db(), cid)
    return _back(rid)


# The addresses on the Goals page: 308 keeps the method and the form, so the browser posts it again to the new one
@bp.route('/goals/challenges', methods=['POST'])
def moved_start():
    return redirect(url_for('challenges.start'), 308)


@bp.route('/goals/challenges/<int:cid>/<action>', methods=['POST'])
def moved_action(cid, action):
    return redirect(url_for('challenges.act', cid=cid, action=action), 308)
