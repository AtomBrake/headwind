"""Deleting an activity settles the copies set aside behind it (services/duplicates.settle_parked): behind another live recording of the same ride,
back as their own when only Garmin's record was deleted, discarded with a delete the rider made. And the run-once repair for copies an older delete
left behind an id that's gone. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from services import duplicates, garmin_changes, photos, workouts


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'A', 1)")
        photos.ensure_schema(d)
        garmin_changes.ensure_schema(d)
        d.commit()
        yield d


def _row(aid, name, day='2026-02-10', hour=9, dist=12000.0, secs=3600, sport='Ride', hr=None):
    start = f'{day}T{hour:02d}:00:00'
    return {'id': aid, 'name': name, 'type': sport, 'sportType': sport, 'riderId': 1, 'startDate': start + 'Z', 'startDateLocal': start,
            'distance': dist, 'movingTime': secs, 'elapsedTime': secs, 'averageSpeed': dist / secs, 'averageHeartrate': hr, 'rawData': '{}'}


def _add(db, aid, name, **kw):
    r = _row(aid, name, **kw)
    db.execute(f"INSERT INTO Activity ({','.join(r)}) VALUES ({','.join('?' * len(r))})", list(r.values()))


def _set_aside(db, aid, primary, name='Copy', **kw):
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, source, reason, status, rowJson) VALUES (?,?,1,'Phone or file','r','parked',?)",
               [aid, primary, json.dumps(_row(aid, name, **kw))])


def _dups(db):
    return {r['id']: (r['primaryId'], r['status']) for r in db.execute("SELECT id, primaryId, status FROM ActivityDuplicate WHERE status<>'deleted'")}


def _live(db):
    return sorted(r[0] for r in db.execute('SELECT id FROM Activity'))


def test_a_delete_of_your_own_moves_a_copy_behind_its_twin_and_discards_the_rest(db):
    _add(db, 'garmin_1', 'Box Hill loop')
    _add(db, 'garmin_2', 'Box Hill loop', dist=12100.0)                  # Garmin's double upload of it, kept apart on purpose
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('garmin_2', 'garmin_1', 1, 'kept_both', '{}')")
    _set_aside(db, '111', 'garmin_1', 'Strava copy')                      # the same ride as garmin_2 too
    _set_aside(db, '222', 'garmin_1', 'Phone copy', day='2026-02-11')     # the same ride as nothing still here
    db.execute("INSERT INTO ActivityPhoto (activityId, filename, sourceKey) VALUES ('garmin_1', 'act_1.jpg', 'strava:media/1.jpg')")
    db.commit()
    assert duplicates.delete_activity(db, 'garmin_1')
    assert _live(db) == ['garmin_2']
    assert _dups(db) == {'111': ('garmin_2', 'parked'), '222': ('garmin_1', 'discarded'), 'garmin_2': ('', 'kept_both')}
    assert db.execute("SELECT rowJson FROM ActivityDuplicate WHERE id='222'").fetchone()[0] == '{}'
    assert db.execute('SELECT COUNT(*) FROM ActivityPhoto').fetchone()[0] == 0          # yours, deleted with it
    assert duplicates.is_deleted(db, 'garmin_1')


def test_deleted_in_garmin_brings_a_copy_back_as_its_own_with_the_photos(db):
    _add(db, 'garmin_1', 'Box Hill loop')
    _set_aside(db, '222', 'garmin_1', 'Phone copy')
    db.execute("INSERT INTO ActivityPhoto (activityId, filename, sourceKey) VALUES ('garmin_1', 'act_1.jpg', 'strava:media/1.jpg')")
    db.execute("INSERT INTO GarminChange (rideId, garminId, riderId, rideName, kind) VALUES ('garmin_1', '1', 1, 'Box Hill loop', 'deleted')")
    db.commit()
    assert garmin_changes.resolve(db, 'garmin_1', 'delete') == 'deleted'
    assert _live(db) == ['222'] and _dups(db) == {}
    assert db.execute("SELECT name FROM Activity WHERE id='222'").fetchone()[0] == 'Phone copy'
    assert db.execute('SELECT activityId FROM ActivityPhoto').fetchone()[0] == '222'
    assert duplicates.is_deleted(db, 'garmin_1')                               # Garmin's own record stays deleted


def test_deleting_a_walk_settles_its_copies_too(db):
    _add(db, 'garmin_1', 'Walk', sport='Walk')
    _set_aside(db, '222', 'garmin_1', 'Phone walk', sport='Walk')
    db.commit()
    assert workouts.delete(db, 'garmin_1', 1)
    assert _dups(db) == {'222': ('garmin_1', 'discarded')}


def test_copies_left_behind_a_deleted_activity_move_behind_their_twin_once(db):
    _add(db, '999', 'Box Hill loop (Strava)')                              # the same session, still here
    _set_aside(db, 'garmin_1', 'gone_1', 'Box Hill loop')                  # left behind by an older delete
    _set_aside(db, 'garmin_3', 'gone_3', 'Lonely', day='2026-02-12')       # nothing still here is that ride
    _set_aside(db, 'garmin_4', '999', 'Fine', dist=12050.0)                # behind a live activity already: left alone
    db.execute("UPDATE Settings SET strandedParkedFixDone=0")
    db.commit()
    res = duplicates.repair_stranded_parked(db)
    assert res == {'ran': True, 'moved': [('garmin_1', '999')], 'unmatched': [('garmin_3', 'Lonely', 'gone_3')]}
    assert _dups(db) == {'garmin_1': ('999', 'parked'), 'garmin_3': ('gone_3', 'parked'), 'garmin_4': ('999', 'parked')}
    assert [d['id'] for d in duplicates.parked_for(db, '999')] == ['garmin_1', 'garmin_4']
    assert duplicates.repair_stranded_parked(db)['ran'] is False
