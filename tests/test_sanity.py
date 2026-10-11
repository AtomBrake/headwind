"""Junk-ride safety rails (flag, never delete; the rider can dismiss) and the on-foot parsing fixes. Throwaway DB."""
import pytest
from flask import Flask

import database
from services import sanity
from services.parser import _gain_smoothed, parse_gpx


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider(name,isDefault) VALUES ('Rob',1)")
        d.commit()
        yield d


def ride(db, rid, dist=30000, moving=5400, elapsed=6000, avg=5.5, top=14.0, gain=300, kcal=900, sport='Ride'):
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,averageSpeed,maxSpeed,totalElevationGain,calories,riderId,rawData,createdAt,updatedAt)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,'{}',datetime('now'),datetime('now'))",
               [rid, 'x', sport, sport, '2026-01-01T10:00:00', '2026-01-01T10:00:00', dist, moving, elapsed, avg, top, gain, kcal])
    db.commit()


def test_a_normal_hard_ride_is_not_flagged(db):
    ride(db, 'ok', dist=160000, moving=21000, elapsed=25000, avg=7.6, top=22, gain=2800, kcal=4800)    # a 100-mile day
    assert sanity.flag(db, 'ok') is None


@pytest.mark.parametrize('kw,word', [
    (dict(avg=1133.0), 'not possible'),                 # 2,535 mph
    (dict(top=60.0), 'glitch'),
    (dict(dist=40), 'only 40 m'),
    (dict(dist=20000, moving=3, elapsed=3, avg=0.2), 'moving time'),
    (dict(dist=3000, moving=9000, avg=0.3), 'barely moved'),
    (dict(gain=12000), 'climb'),
    (dict(dist=5000, gain=3000), 'climb'),
    (dict(elapsed=80 * 3600), 'hours'),
    (dict(kcal=30000), 'kcal'),
])
def test_impossible_rides_are_flagged_with_a_reason(db, kw, word):
    ride(db, 'bad', **kw)
    assert word in sanity.flag(db, 'bad')


def test_dismissing_is_permanent_and_charts_see_the_ride_again(db):
    ride(db, 'bad', avg=1133.0)
    sanity.flag(db, 'bad'); db.commit()
    assert [f['id'] for f in sanity.flagged(db, 1)] == ['bad']
    assert db.execute('SELECT COUNT(*) FROM Activity WHERE ' + sanity.SANE_SQL).fetchone()[0] == 0
    sanity.dismiss(db, 'bad'); db.commit()
    assert sanity.flagged(db, 1) == [] and sanity.flag(db, 'bad') is None          # never flagged again
    assert db.execute('SELECT COUNT(*) FROM Activity WHERE ' + sanity.SANE_SQL).fetchone()[0] == 1


def test_scan_all_flags_old_data_but_leaves_dismissed_alone(db):
    ride(db, 'a', avg=1133.0); ride(db, 'b', avg=900.0); ride(db, 'c')
    sanity.dismiss(db, 'b'); db.commit()
    assert sanity.scan_all(db) == 1
    assert [f['id'] for f in sanity.flagged(db, 1)] == ['a']


def test_only_bike_rides_are_judged(db):
    ride(db, 'v', avg=1133.0, sport='Walk')
    assert sanity.flag(db, 'v') is None


def test_gps_altitude_noise_is_not_counted_as_climbing():
    flat_noisy = [100 + (1.5 if i % 2 else -1.5) for i in range(200)]
    assert _gain_smoothed(flat_noisy) < 3
    hill = [100 + i * 0.5 for i in range(100)] + [150 - i * 0.5 for i in range(100)]
    assert 45 < _gain_smoothed(hill) < 52


def gpx(points):
    pts = ''.join('<trkpt lat="%.6f" lon="-0.12"><ele>10</ele><time>2026-01-01T10:%02d:%02dZ</time></trkpt>' % (lat, t // 60, t % 60) for t, lat in points)
    return ('<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><type>walking</type><trkseg>%s</trkseg></trk></gpx>' % pts).encode()


def test_a_slow_walk_with_repeating_gps_fixes_still_counts_as_moving():
    # 1.2 m/s walk (about 2.7 mph) where the phone repeats each position for two seconds before jumping
    pts = [(t, 51.5 + (t // 2) * 2.4 / 111320) for t in range(0, 600)]
    asphalt = parse_gpx(gpx(pts))
    on_foot = parse_gpx(gpx(pts), stopped_speed=0.5)
    assert on_foot['movingTime'] > 550
    assert on_foot['movingTime'] > asphalt['movingTime']
