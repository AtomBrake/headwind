import json
import logging
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context
from database import get_db, query_db

bp = Blueprint('garmin', __name__)
log = logging.getLogger(__name__)


@bp.route('/garmin/connect', methods=['POST'])
def connect():
    """
    Step 1 of first-time Garmin auth, used by both the Settings page and the setup
    wizard. Attempts the login first and saves the email/password into Settings only once
    Garmin accepts them (or asks for an MFA code), so a typo never replaces working credentials. On success, tokens
    are cached in .garmin_tokens/ and every future sync just works with no further
    prompting. When Garmin challenges with MFA, returns a token the caller must pass
    to /garmin/connect/mfa along with the code within 5 minutes.
    """
    d = request.get_json(silent=True) or {}
    email = (d.get('email') or '').strip()
    password = d.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    db = get_db()
    prev = db.execute('SELECT garminEmail FROM Settings WHERE id=1').fetchone()
    try:
        from services.garmin import start_login, TOKEN_DIR
        if prev and prev['garminEmail'] and prev['garminEmail'].lower() != email.lower():
            # switching accounts: the cached tokens belong to the old one and would silently be reused
            import shutil
            shutil.rmtree(TOKEN_DIR, ignore_errors=True)
        result = start_login(email, password)
    except Exception as e:
        log.warning('Garmin sign-in failed', exc_info=True)
        return jsonify({'error': str(e)}), 400   # nothing saved: the previous working credentials stay in place

    # Reached only once Garmin accepted the password (or is waiting on an MFA code)
    db.execute('''
        INSERT INTO Settings (id, garminEmail, garminPassword) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET garminEmail=excluded.garminEmail, garminPassword=excluded.garminPassword
    ''', [email, password])
    if prev and prev['garminEmail'] and prev['garminEmail'].lower() != email.lower():
        # a different account has its own history: ask the first-run question again
        db.execute('''UPDATE Settings SET garminHistoryFrom=NULL, garminHistoryCursor=NULL, garminHistoryDone=0, garminWeightsDone=0, garminWeightsStatus=NULL,
                      garminHistoryStatus=NULL, garminHistoryRetryAt=NULL WHERE id=1''')
    db.commit()
    return jsonify(result)


@bp.route('/garmin/connect/mfa', methods=['POST'])
def connect_mfa():
    """Step 2: completes a login /garmin/connect paused on {'needs_mfa': True}."""
    d = request.get_json(silent=True) or {}
    token = (d.get('token') or '').strip()
    code = (d.get('code') or '').strip()
    if not token or not code:
        return jsonify({'error': 'Missing code'}), 400

    try:
        from services.garmin import complete_mfa
        result = complete_mfa(token, code)
        return jsonify(result)
    except Exception as e:
        log.warning('Garmin MFA failed', exc_info=True)
        return jsonify({'error': str(e)}), 400


def _history_state():
    s = query_db('SELECT garminHistoryFrom, garminHistoryDone, garminHistoryStatus FROM Settings WHERE id=1', one=True)
    return {'from': s['garminHistoryFrom'] if s else None, 'done': bool(s and s['garminHistoryDone']),
            'status': s['garminHistoryStatus'] if s else None}


@bp.route('/garmin/history', methods=['GET'])
def history_status():
    return jsonify(_history_state())


@bp.route('/garmin/history', methods=['POST'])
def history():
    """The first-run question: how much past health data to pull from Garmin. 'all' (the default), 'none', or a
    number of days. Asking again later (e.g. for more years) carries on from where the backfill got to."""
    d = request.get_json(silent=True) or {}
    from services.garmin import history_from, HISTORY_WAKE
    try:
        frm = history_from(d.get('range') or 'all')
    except (TypeError, ValueError):
        return jsonify({'error': "range must be 'all', 'none' or a number of days"}), 400
    db = get_db()
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.execute('UPDATE Settings SET garminHistoryFrom=?, garminHistoryDone=0, garminHistoryRetryAt=NULL, garminHistoryStatus=?, '
               'garminWeightsDone=0, garminWeightsRetryAt=NULL WHERE id=1',      # a new range: fetch the weigh-ins for it too
               [frm, 'Only recent days will be synced.' if frm == 'none' else 'Starting to fetch health history…'])
    db.commit()
    HISTORY_WAKE.set()
    return jsonify(_history_state())


@bp.route('/garmin/sync', methods=['POST'])
def sync():
    s = query_db('SELECT garminEmail, garminPassword FROM Settings WHERE id=1', one=True)
    if not s or not s['garminEmail'] or not s['garminPassword']:
        return jsonify({'error': 'Garmin credentials not configured'}), 400

    try:
        from services.garmin import sync_garmin
        from services.mqtt import push_update
        days = sync_garmin(s['garminEmail'], s['garminPassword'], days=14)
        push_update()
        return jsonify({'synced': days})
    except Exception as e:
        log.exception('Garmin health sync from the page failed')
        return jsonify({'error': str(e)}), 500


@bp.route('/garmin/sync-activities')
def sync_activities():
    s = query_db('SELECT garminEmail, garminPassword, garminSyncMode FROM Settings WHERE id=1', one=True)
    if not s or not s['garminEmail'] or not s['garminPassword']:
        return jsonify({'error': 'Garmin credentials not configured'}), 400
    if s['garminSyncMode'] != 'full':
        return jsonify({'error': 'Garmin activity sync is not enabled'}), 403

    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    if not rider:
        return jsonify({'error': 'No default rider found'}), 400

    def generate():
        try:
            from services.garmin import sync_garmin_activities
            for status in sync_garmin_activities(s['garminEmail'], s['garminPassword'], rider['id']):
                yield f"data: {json.dumps(status)}\n\n"
        except Exception as e:
            log.exception('Garmin activity sync from the page failed')
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
    )


@bp.route('/garmin/sports')
def sports_page():
    """Review what an older Garmin sync saved with the wrong sport (see services/sport_fix.py)."""
    from flask import render_template
    from services import sport_fix, tasks
    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    return render_template('garmin_sports.html', fixes=sport_fix.pending(get_db(), rider['id']) if rider else [], msg=request.args.get('msg', ''),
                           check=tasks.last(get_db(), sport_fix.TASK))


_sports_lock = threading.Lock()


@bp.route('/garmin/sports/check', methods=['POST'])
def sports_check():
    """Start the check in the background: paging through Garmin can take minutes, and it must not stop when the browser leaves the page.
    Its progress and result are in TaskLog, shown here and on the Tasks page."""
    from flask import current_app, redirect, url_for
    s = query_db('SELECT garminEmail, garminPassword FROM Settings WHERE id=1', one=True)
    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    if not s or not s['garminEmail'] or not s['garminPassword'] or not rider:
        return redirect(url_for('garmin.sports_page', msg='Connect Garmin in Settings first.'))
    if _sports_lock.acquire(blocking=False):            # already running: the page shows that one
        threading.Thread(target=_bg_sports_check, args=(current_app._get_current_object(), rider['id']), daemon=True).start()
    return redirect(url_for('garmin.sports_page'))


def _bg_sports_check(app, rider_id):
    from services import sport_fix, tasks
    from services.garmin import _client
    try:
        with app.app_context():
            db = get_db()
            with tasks.run(db, sport_fix.TASK, 'Activity type check') as t:
                s = db.execute('SELECT garminEmail, garminPassword FROM Settings WHERE id=1').fetchone()
                try:
                    res = sport_fix.scan(db, _client(s['garminEmail'], s['garminPassword']), rider_id)
                except Exception as e:
                    raise RuntimeError(f'Could not reach Garmin: {e}') from e
                missing = res['checked'] - res['found']
                t.result = (f"Checked {res['found']} of your {res['checked']} Garmin rides: {res['proposed']} "
                            f"{'has' if res['proposed'] == 1 else 'have'} the wrong sport.") + \
                           (f' {missing} are no longer on Garmin and were left alone.' if missing else '')
    except Exception as e:                              # already logged as failed by tasks.run
        log.warning('Activity type check failed: %s', e)
    finally:
        _sports_lock.release()


@bp.route('/garmin/sports/apply', methods=['POST'])
def sports_apply():
    from flask import redirect, url_for
    from services import sport_fix
    from services.ingest import after_ride_removed
    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    if not rider:
        return redirect(url_for('garmin.sports_page'))
    res = sport_fix.apply(get_db(), rider['id'], request.form.getlist('ride'))
    after_ride_removed()                                   # the Home Assistant ride totals drop the activities that moved out
    try:
        from services.mqtt import push_update_nutrition
        push_update_nutrition()
    except Exception:
        log.warning('Home Assistant nutrition update after the activity type fix failed', exc_info=True)
    msg = f"Changed {res['changed']}." + (f" {res['failed']} could not be changed (see below)." if res['failed'] else '') + \
          (f" Left {res['kept']} as {'it is' if res['kept'] == 1 else 'they are'}." if res['kept'] else '')
    return redirect(url_for('garmin.sports_page', msg=msg))
