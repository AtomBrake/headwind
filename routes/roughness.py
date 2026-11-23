"""Road roughness map: where the phone's shake readings say the roads are rough. See services/roughness.py."""
from flask import Blueprint, jsonify, render_template, request

from database import get_db, query_db
from services import roughness, whose

bp = Blueprint('roughness', __name__)


@bp.route('/roughness')
def index():
    r = whose.rider()
    n = query_db('SELECT COUNT(*) AS n FROM ActivitySensor WHERE riderId=?', [r['id']], one=True)['n'] if r else 0
    return render_template('roughness.html', recordings=n)


@bp.route('/roughness/data')
def data():
    r = whose.rider()
    if not r:
        return jsonify({'cells': [], 'summary': roughness.summary([])})
    since = (request.args.get('since') or '')[:10] or None
    cs = roughness.cells(get_db(), r['id'], since=since, include_pocket=request.args.get('pocket') == '1')
    return jsonify({'cells': cs, 'summary': roughness.summary(cs)})
