"""The live tracking link's page, for anyone the rider sent it to, signed in or not (services/live_share.py has the rest): GET /live/<token>
draws the map and figures, and its script (static/js/live.js) asks /live/<token>/data every few seconds for what's new. An unknown, revoked
or expired token gets the same "This link has ended" page, with the same status, so a guess can't tell whether a token ever existed."""
import time

from flask import Blueprint, jsonify, make_response, render_template, request

from database import get_db
from services import live_share
from services.demo import RateLimiter

bp = Blueprint('live_share', __name__)

POLL_S = 10                 # how often the page asks for what's new
# Per address, in each web process: a page polling every POLL_S makes 6 a minute, so this is a dozen people behind one address.
_limiter = RateLimiter(limit=90, window=60)


def _limited():
    wait = _limiter.check(request.remote_addr or '?')     # the client's address (services/trusted_proxy.py has read a proxy's)
    if not wait:
        return None
    resp = jsonify(error='Too many requests: slow down a little.') if request.path.endswith('/data') else \
        make_response(render_template('live.html', ended=False, busy=True), 429)
    resp.status_code = 429
    resp.headers['Retry-After'] = str(wait)
    return _private(resp)


def _private(resp):
    """Never kept by a cache or a search engine."""
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


def _ended():
    return _private(make_response(render_template('live.html', ended=True, after_end_min=live_share.AFTER_END_S // 60), 404))


@bp.route('/live/<token>')
def page(token):
    busy = _limited()
    if busy:
        return busy
    db = get_db()
    share = live_share.lookup(db, token)
    if not share:
        return _ended()
    v = live_share.view(db, share)
    return _private(make_response(render_template('live.html', ended=False, v=v, poll_s=POLL_S, after_end_min=live_share.AFTER_END_S // 60)))


@bp.route('/live/<token>/data')
def data(token):
    busy = _limited()
    if busy:
        return busy
    db = get_db()
    share = live_share.lookup(db, token)
    if not share:
        return _private(make_response(jsonify(ended=True), 404))
    return _private(jsonify(live_share.view(db, share, since=request.args.get('since'), now=time.time())))
