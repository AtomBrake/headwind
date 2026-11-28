"""The Challenges page: races with friends over set dates (services/challenges.py). They used to be the second half of the Goals page, whose old
form addresses (/goals/challenges...) still answer here, so a page left open from before the move still sends its forms to the right place."""
from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, url_for

from database import get_db, query_db
from services import challenges, goals, whose

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
    return render_template('challenges.html', active_rider=active_rider, rid=rid, challenges=challenges.challenges(db, rid),
                           error=request.args.get('error'), metrics=goals.METRIC_LABELS, groups=goals.GROUP_LABELS, group_icons=goals.GROUP_ICONS,
                           units_of={m: goals.unit_label(m) for m in goals.METRICS},
                           friends=query_db('SELECT COUNT(*) FROM Friend', one=True)[0], invitable=challenges.invitable(db),
                           today=today.isoformat(), month_end=periods.current('month', p._replace(mode=periods.CALENDAR), today).last.isoformat())


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
