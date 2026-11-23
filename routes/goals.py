"""The Goals page: the rider's weekly, monthly and yearly goals, and their challenges with friends (services/goals.py)."""
from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, url_for

from database import get_db, query_db
from services import goals, whose

bp = Blueprint('goals', __name__)


def _back(rider_id, error=None, anchor=''):
    args = [('rider', rider_id)] if rider_id and not query_db('SELECT isDefault FROM Rider WHERE id=?', [rider_id], one=True)['isDefault'] else []
    if error:
        args.append(('error', error))
    return redirect(url_for('goals.index') + ('?' + urlencode(args) if args else '') + anchor)


def _rider_id():
    """The rider a form is for (its hidden `rider`) when whose.viewable allows it, or the request's own."""
    view = whose.viewable(request.form.get('rider'))
    return view.id if view else whose.rider_id()


@bp.route('/goals')
def index():
    from routes.dashboard import _riders
    from services import periods, tz
    _, active_rider, rid = _riders(request.args)
    db = get_db()
    today, p = tz.today(), periods.for_request()
    every = {k: goals.ROLLING_PERIOD_LABELS.get(k, f'every {k}') if p.mode == periods.ROLLING else f'every {k}' for k in goals.PERIODS}
    return render_template('goals.html', active_rider=active_rider, rid=rid, goals=goals.goals(db, rid, today, p), challenges=goals.challenges(db, rid),
                           error=request.args.get('error'), metrics=goals.METRIC_LABELS, periods=goals.PERIODS, every=every, groups=goals.GROUP_LABELS,
                           group_icons=goals.GROUP_ICONS, units_of={m: goals.unit_label(m) for m in goals.METRICS},
                           friends=query_db('SELECT COUNT(*) FROM Friend', one=True)[0], invitable=goals.invitable(db),
                           today=today.isoformat(), month_end=periods.current('month', p._replace(mode=periods.CALENDAR), today).last.isoformat())


@bp.route('/goals/add', methods=['POST'])
def add_goal():
    rid = _rider_id()
    err = goals.add_goal(get_db(), rid, request.form.get('metric'), request.form.get('period'), request.form.get('sport') or 'all',
                         request.form.get('target'))
    return _back(rid, err)


@bp.route('/goals/<int:gid>/delete', methods=['POST'])
def delete_goal(gid):
    rid = _rider_id()
    goals.delete_goal(get_db(), rid, gid)
    return _back(rid)


@bp.route('/goals/challenges', methods=['POST'])
def start_challenge():
    rid = _rider_id()
    err = goals.start_challenge(get_db(), rid, request.form)
    return _back(rid, err, '#challenges')


@bp.route('/goals/challenges/<int:cid>/<action>', methods=['POST'])
def challenge_action(cid, action):
    rid = _rider_id()
    if action in ('join', 'leave'):
        goals.set_joined(get_db(), cid, action == 'join')
    elif action == 'delete':
        goals.delete_challenge(get_db(), cid)
    return _back(rid, None, '#challenges')
