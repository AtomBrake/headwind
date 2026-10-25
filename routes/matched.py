"""The activity page's "Same route" card (services/matched.py), drawn after the page so the page doesn't wait for it."""
from flask import Blueprint, abort, render_template

from database import get_db
from services import matched

bp = Blueprint('matched', __name__)


@bp.route('/rides/<rid>/matched')
def card(rid):
    db = get_db()
    if not db.execute('SELECT 1 FROM Activity WHERE id=?', [rid]).fetchone():
        abort(404)
    return render_template('_matched.html', m=matched.compare(db, rid))
