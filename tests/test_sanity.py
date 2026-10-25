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


def ride(db, rid, dist=30000, moving=5400, elapsed=6000, avg=5.5, top=14.0, gain=300, kcal=900, sport='Ride', hr=None, hr_max=None):
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,averageSpeed,maxSpeed,totalElevationGain,calories,"
               "averageHeartrate,maxHeartrate,riderId,rawData,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'{}',datetime('now'),datetime('now'))",
               [rid, 'x', sport, sport, '2026-01-01T10:00:00', '2026-01-01T10:00:00', dist, moving, elapsed, avg, top, gain, kcal, hr, hr_max])
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


@pytest.mark.parametrize('kw', [
    dict(sport='Run', dist=42195, moving=7800, elapsed=7800, avg=5.41, top=7.5, gain=200, kcal=2800, hr=168, hr_max=185),    # a 2:10 marathon
    dict(sport='Run', dist=160000, moving=80000, elapsed=86000, avg=2.0, top=5.0, gain=6000, kcal=12000),                      # a 100-mile trail race
    dict(sport='Run', dist=1500, moving=210, elapsed=210, avg=7.1, top=9.0, gain=0),                                            # a 3:30 1500 m
    dict(sport='Walk', dist=20000, moving=4800, elapsed=4800, avg=4.17, top=6.0, gain=50),                                      # a race walk
    dict(sport='Walk', dist=3000, moving=9000, elapsed=9000, avg=0.33, top=1.5, gain=10),                                       # a stroll with the dog
    dict(sport='Hike', dist=6000, moving=14400, elapsed=20000, avg=0.42, top=3.0, gain=1600, kcal=2500),                        # a steep mountain day
    dict(sport='Swim', dist=25000, moving=28000, elapsed=29000, avg=0.9, top=0, gain=0, hr=150),                                # a long open-water swim
    dict(sport='Swim', dist=140, moving=3600, elapsed=3700, avg=0.04, top=0, gain=0),                                           # a few lengths, a long rest
    dict(sport='Ski', dist=60000, moving=14000, elapsed=25000, avg=4.3, top=35.0, gain=0, hr=120),                              # 126 km/h downhill
    dict(sport='Other', dist=0, moving=0, elapsed=0, avg=0, top=0, gain=0, kcal=0),                                             # yoga logged with nothing
])
def test_hard_but_real_activities_of_other_sports_pass(db, kw):
    ride(db, 'ok', **kw)
    assert sanity.flag(db, 'ok') is None


@pytest.mark.parametrize('kw,word', [
    (dict(sport='Run', dist=11800, moving=9, elapsed=3600, avg=1311.0, top=5.0), 'moving time of 9 s'),          # a lap timer that lost the run
    (dict(sport='Run', dist=10000, moving=1000, elapsed=1000, avg=10.0), 'not possible running'),
    (dict(sport='Walk', dist=8000, moving=1440, elapsed=1500, avg=5.6, top=30.0), 'not possible walking'),      # 20 km/h, 108 km/h top
    (dict(sport='Walk', dist=8000, moving=1440, elapsed=1500, avg=5.6, top=30.0), 'not possible on foot'),
    (dict(sport='Hike', dist=10000, moving=1500, elapsed=1600, avg=None, top=None), 'not possible walking'),    # worked out from the distance
    (dict(sport='Swim', dist=0, moving=0, elapsed=0, avg=0, top=0, gain=0), 'nothing was recorded'),
    (dict(sport='Swim', dist=2000, moving=300, elapsed=300, avg=6.7), 'not possible swimming'),
    (dict(sport='Swim', dist=400000, moving=300000, elapsed=300000, avg=1.3, gain=0), 'beyond any swim'),
    (dict(sport='Run', dist=900000, moving=200000, elapsed=200000, avg=4.5), 'beyond anything on foot'),
    (dict(sport='Run', dist=3000, gain=4000, avg=2.0), 'climb'),
    (dict(sport='VirtualRide', hr=21, hr_max=60), 'average heart rate of 21 bpm'),                       # Zwift with a strap that slipped
    (dict(sport='Yoga', dist=0, avg=0, top=0, hr=90, hr_max=250), 'top heart rate of 250 bpm'),
    (dict(sport='Paddle', dist=12000, moving=40, elapsed=4000, avg=300.0), 'moving time of 40 s'),
    (dict(sport='Row', elapsed=100 * 3600), 'hours'),
])
def test_impossible_activities_of_other_sports_are_flagged(db, kw, word):
    ride(db, 'bad', **kw)
    assert word in sanity.flag(db, 'bad')


def test_flagged_activities_of_every_sport_are_listed_and_left_out_of_the_charts(db):
    ride(db, 'walk', sport='Walk', dist=8000, moving=1440, avg=5.6, top=30.0)
    ride(db, 'blip', dist=40)
    ride(db, 'swim', sport='Swim', dist=100, moving=0, elapsed=0, avg=0, top=0, hr=12)     # too short to be a blip: only rides are
    db.execute("UPDATE Settings SET sanityAllSportsDone=0")
    res = sanity.scan_every_sport(db)
    assert sorted(f[0] for f in res['flagged']) == ['blip', 'swim', 'walk']
    assert sanity.scan_every_sport(db) == {'flagged': [], 'ran': False}         # once only
    listed = {f['id']: f for f in sanity.flagged(db, 1)}
    assert sorted(listed) == ['blip', 'swim', 'walk'] and [i for i, f in listed.items() if f['isBlip']] == ['blip']
    assert sanity.blip_ids(db, 1) == ['blip']
    assert db.execute('SELECT COUNT(*) FROM Activity WHERE ' + sanity.SANE_SQL).fetchone()[0] == 0
    sanity.dismiss(db, 'walk')
    assert db.execute('SELECT id FROM Activity WHERE ' + sanity.SANE_SQL).fetchall()[0][0] == 'walk'


def test_changing_the_sport_checks_it_against_the_new_one(db):
    from services import convert
    ride(db, 'car', dist=8000, moving=1440, avg=5.6, top=30.0)                    # 20 km/h, 108 km/h top: a ride, not a walk
    assert sanity.flag(db, 'car') is None
    convert.change_sport(db, 'ride', 'car', 'Walk')
    assert 'not possible walking' in db.execute("SELECT flagReason FROM Activity WHERE id='car'").fetchone()[0]
    convert.change_sport(db, 'workout', 'car', 'Ride')
    assert db.execute("SELECT flagReason FROM Activity WHERE id='car'").fetchone()[0] is None


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
