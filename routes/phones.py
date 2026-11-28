"""Pair a phone with this instance: create a device token, show it once as a QR code (and text), list / revoke paired phones. Also the
live tracking links the phones and Watches have started (services/live_share.py), running and recent, each running one with Stop: for a
link sent by mistake when the phone isn't to hand."""

from flask import Blueprint, jsonify, render_template, request
from urllib.parse import quote

from database import get_db
from services import device_auth, external_url, live_share, qr

bp = Blueprint('phones', __name__, url_prefix='/phones')


@bp.route('/')
def index():
    # Only an https address is any use: the apps refuse plain http, even on the home network
    address = external_url.describe()
    return render_template('phones.html', devices=device_auth.devices(), server_url=address['https'], other_url=address['url'],
                           stale_days=device_auth.STALE_DAYS, shares=live_share.listing(get_db()),
                           after_end_min=live_share.AFTER_END_S // 60)


@bp.route('/create', methods=['POST'])
def create():
    d = request.get_json() or {}
    url = external_url.https()                          # Settings → Outside address is the one place it's set
    if not url:
        return jsonify({'error': "The app only talks to an https:// address (it refuses plain http, even on your home network). "
                                 "Set the address you reach Headwind on from outside the house under Settings → Outside address first."}), 400
    token, did = device_auth.create(d.get('name') or 'Phone')
    link = f"headwind://pair?u={quote(url, safe='')}&t={token}"
    return jsonify({'id': did, 'token': token, 'server_url': url, 'link': link, 'qr': qr.data_url(link)})


@bp.route('/<int:device_id>/revoke', methods=['POST'])
def revoke(device_id):
    device_auth.revoke(device_id)
    return jsonify({'ok': True})


@bp.route('/revoke-stale', methods=['POST'])
def revoke_stale():
    """Every token not used for device_auth.STALE_DAYS, flagged on the page."""
    return jsonify({'ok': True, 'revoked': device_auth.revoke_stale()})


@bp.route('/live/<int:share_id>/stop', methods=['POST'])
def stop_live(share_id):
    """Stop a live tracking link: it ends at once, as when the phone stops it."""
    db = get_db()
    row = db.execute('SELECT riderId FROM LiveShare WHERE id=?', [share_id]).fetchone()
    if not row:
        return jsonify({'error': 'No such link.'}), 404
    return jsonify({'ok': True, 'stopped': live_share.stop(db, row['riderId'], share_id=share_id)})
