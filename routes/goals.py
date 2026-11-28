"""The Goals page: the rider's weekly, monthly and yearly goals (services/goals.py). Challenges with friends are routes/challenges.py."""
from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, url_for

from database import get_db, query_db
from services import goals, whose

bp = Blueprint('goals', __name__)


def _back(rider_id, error=None):
    args = [('rider', rider_id)] if rider_id and not query_db('SELECT isDefault FROM Rider WHERE id=?', [rider_id], one=True)['isDefault'] else []
    if error:
        args.append(('error', error))
    return redirect(url_for('goals.index') + ('?' + urlencode(args) if args else ''))


def _rider_id():
    """The rider a form is for (its hidden `rider`) when whose.viewable allows it, or the request's own."""
    view = whose.viewable(request.form.get('rider'))
    return view.id if view else whose.rider_id()


@bp.route('/goals')
def index():
    from routes.dashboard import _riders
    from services import favourites, periods, tz
    _, active_rider, rid = _riders(request.args)
    db = get_db()
    today, p = tz.today(), periods.for_request()
    every = {k: goals.ROLLING_PERIOD_LABELS.get(k, f'every {k}') if p.mode == periods.ROLLING else f'every {k}' for k in goals.PERIODS}
    return render_template('goals.html', active_rider=active_rider, rid=rid, goals=goals.goals(db, rid, today, p),
                           error=request.args.get('error'), metrics=goals.METRIC_LABELS, periods=goals.PERIODS, every=every,
                           sport_choices=favourites.choices(db, rid, every_group=True) if rid else [], units_of={m: goals.unit_label(m) for m in goals.METRICS})


@bp.route('/goals/add', methods=['POST'])
def add_goal():
    rid = _rider_id()
    every = request.form.get('every') or ('sports' not in request.form and request.form.get('sport') == 'all')
    sport = None if every else request.form.getlist('sports') or request.form.get('sport') or []     # sport: one group, as the form had it
    err = goals.add_goal(get_db(), rid, request.form.get('metric'), request.form.get('period'), sport, request.form.get('target'))
    return _back(rid, err)


@bp.route('/goals/<int:gid>/delete', methods=['POST'])
def delete_goal(gid):
    rid = _rider_id()
    goals.delete_goal(get_db(), rid, gid)
    return _back(rid)

