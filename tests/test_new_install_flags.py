"""A new database starts with every once-only start-up repair done (database._REPAIR_FLAGS), so the second start doesn't run them all against
the first import. A database with activities and no Settings row (an old install) still gets repaired."""
import pathlib
import re
import sqlite3

from flask import Flask

import database


def _migrate(path):
    app = Flask('t')
    app.config['DATABASE'] = path
    with app.app_context():
        database.migrate_db()
        database.migrate_db()                           # the second start


def test_a_new_database_has_every_repair_done(tmp_path):
    path = str(tmp_path / 'new.db')
    _migrate(path)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    s = db.execute('SELECT * FROM Settings WHERE id=1').fetchone()
    assert all(s[f] == 1 for f in database._REPAIR_FLAGS)
    assert s['garminHistoryDone'] == 0 and s['garminWeightsDone'] == 0            # downloads, not repairs
    assert db.execute("SELECT COUNT(*) FROM TaskLog WHERE task LIKE 'startup:%'").fetchone()[0] == 0


def test_an_old_database_without_settings_is_still_repaired(tmp_path):
    path = str(tmp_path / 'old.db')
    _migrate(path)
    db = sqlite3.connect(path)
    db.execute('DELETE FROM Settings')                  # rides saved before any Settings row was
    db.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance) VALUES ('1', 'Ride', 'Ride', '2020-06-01T08:00:00', 10000)")
    db.commit()
    _migrate(path)
    assert db.execute('SELECT COUNT(*) FROM Settings').fetchone()[0] == 0          # no flags set for it: the repairs wait for the row, as before


def test_every_repair_flag_is_in_the_list():
    root = pathlib.Path(database.__file__).parent
    read = set()
    for f in [root / 'database.py', *(root / 'services').glob('*.py'), *(root / 'routes').glob('*.py')]:
        for sel in re.findall(r'SELECT ([\w, ]*Done[\w, ]*) FROM Settings', f.read_text(encoding='utf-8')):
            read |= {c.strip() for c in sel.split(',') if c.strip().endswith('Done')}
    assert read - {'garminHistoryDone', 'garminWeightsDone'} == set(database._REPAIR_FLAGS)
