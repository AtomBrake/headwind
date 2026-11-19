"""Pair a phone with this instance: create a device token, show it once as a QR code (and text), list / revoke paired phones."""
import os

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from urllib.parse import quote

from services import device_auth, external_url, qr

bp = Blueprint('phones', __name__, url_prefix='/phones')


@bp.route('/')
def index():
    # Only an https address is any use: the apps refuse plain http, even on the home network
    address = external_url.describe()
    return render_template('phones.html', devices=device_auth.devices(), server_url=address['https'], other_url=address['url'],
                           stale_days=device_auth.STALE_DAYS)


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


# ── the Android app itself (sideloading; served behind the normal login) ─────────────────────────────
def _apk_path():
    """HEADWIND_APK, or headwind.apk beside the database (with an optional version.txt next to it)."""
    data_dir = os.path.dirname(os.path.abspath(current_app.config['DATABASE'].replace('sqlite:///', '')))
    return os.environ.get('HEADWIND_APK') or os.path.join(data_dir, 'headwind.apk')


@bp.route('/app')
def app_page():
    apk = _apk_path()
    info = ''
    try:
        info = open(os.path.join(os.path.dirname(apk), 'version.txt')).read().strip()
    except OSError:
        pass
    available = os.path.exists(apk)
    return render_template('phones_app.html', available=available, info=info, apk_path=apk,
                           size_mb=round(os.path.getsize(apk) / 1048576, 1) if available else None)


@bp.route('/app.apk')
def app_apk():
    apk = _apk_path()
    if not os.path.exists(apk):
        return jsonify({'error': 'no APK has been built yet'}), 404
    return send_file(apk, mimetype='application/vnd.android.package-archive', as_attachment=True, download_name='headwind.apk')
