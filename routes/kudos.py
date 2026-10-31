import logging
from flask import Blueprint, jsonify, request
from database import get_db, query_db
from services.ai import analyse_ride

log = logging.getLogger(__name__)

bp = Blueprint('kudos', __name__)


@bp.route('/rides/<rid>/kudos', methods=['POST'])
def kudos(rid):
    activity = query_db('SELECT * FROM Activity WHERE id=?', [rid], one=True)
    if not activity:
        return jsonify({'error': 'Not found'}), 404
    from services import friend_rides
    if friend_rides.friend_of(get_db(), rid):
        return jsonify({'error': friend_rides.REFUSED}), 403
    from services.sports import is_ride
    if not is_ride(activity['sportType']):
        return jsonify({'error': 'AI coaching is only available for ride activities'}), 400
    try:
        from services.ai import PERSONALITIES
        data = request.get_json(silent=True) or {}
        personality_key = data.get('personality') or 'default'
        if personality_key not in PERSONALITIES:
            personality_key = 'default'

        db = get_db()
        db.execute('UPDATE Settings SET coachPersonality=? WHERE id=1', [personality_key])
        text = analyse_ride(db, activity, personality_key=personality_key)
        return jsonify({'kudos': text})
    except Exception as e:
        log.exception('AI analysis failed')
        return jsonify({'error': str(e)}), 500


@bp.route('/rides/<rid>/kudos/status')
def kudos_status(rid):
    """For a ride page showing 'Analysing…': whether the analysis of a new ride (services/auto_analyse.py) is still on its way, and the text once it's there."""
    from services import auto_analyse
    row = query_db('SELECT aiKudos FROM Activity WHERE id=?', [rid], one=True)
    return jsonify({'pending': auto_analyse.is_pending(rid), 'kudos': (row['aiKudos'] if row else None) or None})
