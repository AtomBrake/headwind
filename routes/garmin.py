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
    Step 1 of signing in to Garmin, used by both the Settings page and the setup wizard. The password is used for this sign-in only and never
    saved: Garmin's tokens are kept in TOKEN_DIR, renew themselves, and every sync uses them. The email is saved once Garmin accepts the
    sign-in, and a new sign-in's tokens replace the old ones only then, so a typo never breaks a working one. When Garmin challenges with MFA,
    returns a token the caller must pass to /garmin/connect/mfa along with the code within 5 minutes.
    """
    d = request.get_json(silent=True) or {}
    email = (d.get('email') or '').strip()
    password = d.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    try:
        from services.garmin import start_login
        result = start_login(email, password)
    except Exception as e:
        log.warning('Garmin sign-in failed', exc_info=True)
        return jsonify({'error': str(e)}), 400   # nothing changed: the saved sign-in stays in place

    if result.get('ok'):
        _signed_in_as(email)
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
    except Exception as e:
        log.warning('Garmin MFA failed', exc_info=True)
        return jsonify({'error': str(e)}), 400
    _signed_in_as(result.pop('email'))
    return jsonify(result)


def _signed_in_as(email):
    """After Garmin accepted a sign-in (its tokens are saved): remember the account, and drop an older install's saved password and any
    "sign in again" flag."""
    db = get_db()
    prev = db.execute('SELECT garminEmail FROM Settings WHERE id=1').fetchone()
    db.execute('''
        INSERT INTO Settings (id, garminEmail) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET garminEmail=excluded.garminEmail, garminPassword=NULL, garminSignInNeeded=NULL
    ''', [email])
    if prev and prev['garminEmail'] and prev['garminEmail'].lower() != email.lower():
        # a different account has its own history: ask the first-run question again
        db.execute('''UPDATE Settings SET garminHistoryFrom=NULL, garminHistoryCursor=NULL, garminHistoryDone=0, garminWeightsDone=0, garminWeightsStatus=NULL,
                      garminHistoryStatus=NULL, garminHistoryRetryAt=NULL WHERE id=1''')
    db.commit()


@bp.route('/garmin/disconnect', methods=['POST'])
def disconnect():
    """Sign out of Garmin here: delete the saved tokens (and an older install's password). The email stays, to sign in again with. Syncs stop
    until then; what was synced stays. It doesn't revoke the tokens at Garmin: deleting them is what stops Headwind using them."""
    from services.garmin import forget_tokens
    forget_tokens()
    db = get_db()
    db.execute('UPDATE Settings SET garminPassword=NULL, garminSignInNeeded=NULL WHERE id=1')
    db.commit()
    return jsonify({'ok': True})


def _garmin_on():
    from services.garmin import connected
    return connected(query_db('SELECT garminEmail, garminPassword FROM Settings WHERE id=1', one=True))


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
    if not _garmin_on():
        return jsonify({'error': 'Garmin is not connected'}), 400

    try:
        from services.garmin import sync_garmin
        from services.mqtt import push_update
        days = sync_garmin(days=14)
        push_update()
        return jsonify({'synced': days})
    except Exception as e:
        log.exception('Garmin health sync from the page failed')
        return jsonify({'error': str(e)}), 500


@bp.route('/garmin/sync-activities')
def sync_activities():
    s = query_db('SELECT garminSyncMode FROM Settings WHERE id=1', one=True)
    if not _garmin_on():
        return jsonify({'error': 'Garmin is not connected'}), 400
    if s['garminSyncMode'] != 'full':
        return jsonify({'error': 'Garmin activity sync is not enabled'}), 403

    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    if not rider:
        return jsonify({'error': 'No default rider found'}), 400

    def generate():
        try:
            from services.garmin import sync_garmin_activities
            for status in sync_garmin_activities(rider['id']):
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
    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    if not _garmin_on() or not rider:
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
                try:
                    res = sport_fix.scan(db, _client(), rider_id)
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


_changes_lock = threading.Lock()


@bp.route('/garmin/changes/check', methods=['POST'])
def changes_check():
    """Look for activities deleted or changed in Garmin now, rather than at the daily sweep (services/garmin_changes.run), in the background.
    ?whole=1 (Settings' Full re-sync): all of the history at once (garmin_changes.full). Its progress and result are in TaskLog, shown on the
    Import page and the Tasks page."""
    from flask import current_app, redirect, url_for
    rider = query_db('SELECT id FROM Rider WHERE isDefault=1', one=True)
    whole = request.args.get('whole') == '1'
    if _garmin_on() and rider and _changes_lock.acquire(blocking=False):     # already running: the page shows that one
        threading.Thread(target=_bg_changes_check, args=(current_app._get_current_object(), rider['id'], whole), daemon=True).start()
    return redirect(url_for('import_rides.index') + '#garmin-changes')


def _bg_changes_check(app, rider_id, whole=False):
    from services import garmin_changes, tasks
    from services.garmin import _client
    try:
        with app.app_context():
            db = get_db()
            with tasks.run(db, garmin_changes.TASK, 'Garmin full re-sync' if whole else 'Garmin changes check') as t:
                check = garmin_changes.full if whole else garmin_changes.run
                t.result = garmin_changes.describe(check(db, _client(), rider_id))
    except Exception as e:                              # already logged as failed by tasks.run
        log.warning('Garmin changes check failed: %s', e)
    finally:
        _changes_lock.release()


@bp.route('/garmin/changes/<path:ride_id>/<choice>', methods=['POST'])
def changes_resolve(ride_id, choice):
    """Settle activities changed in Garmin (services/garmin_changes.resolve). ride_id 'deleted' or 'edited' settles every one of that kind.
    Back to the activity's page when it came from there (and still exists), else the Import page."""
    from flask import flash, redirect, url_for
    from services import garmin_changes
    from services.ingest import after_ride_removed
    db = get_db()
    pending = garmin_changes.pending(db)
    ids = [c['rideId'] for c in pending if c['kind'] == ride_id] if ride_id in ('deleted', 'edited') else [ride_id]
    try:
        done = [garmin_changes.resolve(db, i, choice) for i in ids]
    except ValueError as e:
        db.rollback()
        flash(str(e), 'error')
        return redirect(url_for('import_rides.index') + '#garmin-changes')
    db.commit()
    deleted, changed = done.count('deleted'), done.count('changed')
    if deleted or changed:
        after_ride_removed()                            # the Home Assistant totals drop what was deleted or became another sport
    n = len(ids)
    flash(f"Deleted {deleted} activit{'ies' if deleted != 1 else 'y'}." if choice == 'delete' else
          f"Took Garmin's name or sport for {changed} activit{'ies' if changed != 1 else 'y'}." if choice == 'garmin' else
          f"Kept {n} activit{'ies' if n != 1 else 'y'} as {'they are' if n != 1 else 'it is'} here.", 'success')
    if request.form.get('back') == 'ride' and not deleted:
        return redirect(url_for('rides.detail', rid=ride_id))
    return redirect(url_for('import_rides.index') + '#garmin-changes')
