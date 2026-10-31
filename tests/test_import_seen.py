"""Importing the same export again doesn't read files that can't give anything new (services/reimport.ImportSeen), but reads them all again when
this version of Headwind reads files differently from the one that imported them, when the export's row or the file changed, or when the
activity is no longer saved. Throwaway DB."""
import ast
import io
import json
import os
import zipfile

import pytest
from flask import Flask

import database
from routes import import_rides
from services import parser, reimport


def gpx(day, lat0=50.4):
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
            + ''.join(f'<trkpt lat="{lat0 + i * 0.0003:.5f}" lon="-4.7"><ele>{50 + i}</ele><time>2026-07-{day:02d}T09:{i * 10 // 60:02d}:{i * 10 % 60:02d}Z</time></trkpt>'
                      for i in range(60))
            + '</trkseg></trk></gpx>')


CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename,Moving Time,Distance\n'


def row(act_id, day, name='Tour'):
    return f'{act_id},"Jul {day}, 2026, 9:00:00 AM",{name},Ride,590,1.77,activities/{act_id}.gpx,590,1770.0\n'


def strava_zip(rows, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
        for name, data in files.items():
            z.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


@pytest.fixture
def reads(monkeypatch):
    """The files the import actually opens and parses."""
    seen = []
    real = import_rides.parse_activity_file
    monkeypatch.setattr(import_rides, 'parse_activity_file', lambda name, data, **kw: seen.append(name) or real(name, data, **kw))
    return seen


def run(db, rows, files):
    z = strava_zip(rows, files)
    done = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)][-1]
    db.commit()
    return done


ROWS = [row('1', 4), row('2', 5), row('3', 6)]
FILES = {'activities/1.gpx': gpx(4), 'activities/2.gpx': gpx(5), 'activities/3.gpx': gpx(6)}


def test_the_same_export_again_reads_nothing(db, reads):
    assert run(db, ROWS, FILES)['imported'] == 3 and len(reads) == 3
    reads.clear()
    done = run(db, ROWS, FILES)
    assert reads == [] and done['unchanged'] == 3 and done['skipped'] == 3 and done['changed'] == 0


def test_differences_still_waiting_are_counted_without_reading_the_file(db, reads):
    run(db, ROWS, FILES)
    db.execute("UPDATE Activity SET distance = 99999 WHERE id='2'"); db.commit()      # what was saved differs from the export
    db.execute("DELETE FROM ImportSeen WHERE activityId='2'"); db.commit()
    assert run(db, ROWS, FILES)['changed'] == 1                                         # read, and its difference waits on the Import page
    reads.clear()
    done = run(db, ROWS, FILES)
    assert reads == [] and done['unchanged'] == 3 and done['changed'] == 1 and done['skipped'] == 2


def test_a_new_version_that_reads_files_differently_reads_them_all_again(db, reads, monkeypatch):
    run(db, ROWS, FILES)
    reads.clear()
    monkeypatch.setattr(reimport, '_reader_version', 'a later release')   # what any change to READER_MODULES' code, or the FIT library, does
    done = run(db, ROWS, FILES)
    assert len(reads) == 3 and done['unchanged'] == 0
    reads.clear()
    assert run(db, ROWS, FILES)['unchanged'] == 3 and reads == []             # and remembers it was read by that version


def test_a_changed_row_a_changed_file_or_a_deleted_activity_is_read_again(db, reads):
    run(db, ROWS, FILES)
    reads.clear()
    db.execute("DELETE FROM Activity WHERE id='3'"); db.commit()             # gone (not through the delete button: no tombstone)
    rows = [row('1', 4, name='Tour renamed on Strava'), row('2', 5), row('3', 6)]
    files = dict(FILES, **{'activities/2.gpx': gpx(5, lat0=50.5)})             # the file itself is different
    done = run(db, rows, files)
    assert sorted(reads) == ['activities/1.gpx', 'activities/2.gpx', 'activities/3.gpx'] and done['unchanged'] == 0
    reads.clear()
    assert run(db, rows, files)['unchanged'] == 3 and reads == []


def test_one_set_aside_as_a_duplicate_is_not_read_again_but_a_deleted_one_is(db, reads):
    from services import duplicates
    run(db, ROWS, FILES)
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, source, reason, status, rowJson) "
               "SELECT id, '1', riderId, 'Strava export', 'test', 'parked', '{}' FROM Activity WHERE id='2'")
    db.execute("DELETE FROM Activity WHERE id='2'"); db.commit()
    reads.clear()
    done = run(db, ROWS, FILES)
    assert reads == [] and done['unchanged'] == 3 and done['imported'] == 0          # not added and set aside again on every import
    duplicates.tombstone(db, '3', 1); db.execute("DELETE FROM Activity WHERE id='3'"); db.commit()
    run(db, ROWS, FILES)
    assert reads == ['activities/3.gpx']


def test_a_file_that_could_not_be_read_is_tried_again(db, reads, monkeypatch):
    run(db, ROWS, FILES)
    monkeypatch.setattr(reimport, '_reader_version', 'next')
    real = import_rides.parse_activity_file             # the `reads` fixture's: it notes each file read

    def flaky(name, data, **kw):
        if name == 'activities/2.gpx':
            raise ValueError('truncated')
        return real(name, data, **kw)
    monkeypatch.setattr(import_rides, 'parse_activity_file', flaky)
    run(db, ROWS, FILES)
    monkeypatch.setattr(import_rides, 'parse_activity_file', real)
    reads.clear()
    assert run(db, ROWS, FILES)['unchanged'] == 2 and reads == ['activities/2.gpx']


def test_photos_and_commutes_are_still_added_to_unchanged_activities(db, reads, monkeypatch):
    run(db, ROWS, FILES)
    added = []
    monkeypatch.setattr(import_rides, '_strava_extras', lambda db_, zf, names, row_, ride_id, *a: added.append(ride_id) or (0, 0))
    run(db, ROWS, FILES)
    assert sorted(added) == ['1', '2', '3']


def test_a_zip_of_files_again_reads_nothing(db, reads):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('a.gpx', gpx(4)); z.writestr('b.gpx', gpx(5))
    events = lambda: [json.loads(e[len('data: '):]) for e in import_rides._process_generic_zip(zipfile.ZipFile(io.BytesIO(buf.getvalue())), ['a.gpx', 'b.gpx'], 1)]
    assert events()[-1]['imported'] == 2
    db.commit()
    reads.clear()
    done = events()[-1]
    assert reads == [] and done['unchanged'] == 2


def test_reader_version_covers_the_code_the_parser_uses():
    """Every services module services/parser.py imports (and they import, and so on) is in READER_MODULES, so a change to any of them makes
    the next import read every file again."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def services_imported(mod):
        tree = ast.parse(open(os.path.join(root, *mod.split('.')) + '.py').read())
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('services'):
                out.add(node.module if node.module != 'services' else None)
                if node.module == 'services':
                    out |= {'services.' + a.name for a in node.names}
        return out - {None}

    need, todo = set(), ['services.parser']
    while todo:
        m = todo.pop()
        if m not in need:
            need.add(m)
            todo += services_imported(m)
    assert need <= set(reimport.READER_MODULES), need - set(reimport.READER_MODULES)
    assert {'services.reimport', 'routes.import_rides'} <= set(reimport.READER_MODULES)


def test_reader_version_falls_back_to_the_release_without_source(monkeypatch):
    monkeypatch.setattr(reimport, '_reader_version', None)
    with_source = reimport.reader_version()
    monkeypatch.setattr(reimport, '_reader_version', None)
    monkeypatch.setattr(reimport.inspect, 'getsource', lambda m: (_ for _ in ()).throw(OSError('frozen')))
    frozen = reimport.reader_version()
    import version
    monkeypatch.setattr(reimport, '_reader_version', None)
    monkeypatch.setattr(version, '__version__', '9.9.9')
    assert frozen != with_source and reimport.reader_version() != frozen     # the Windows build reads every file again on each release
