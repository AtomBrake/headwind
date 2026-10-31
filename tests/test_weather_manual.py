"""Hand-picked weather conditions, the shared analytics buckets, and a backfill that can reach rides which only kept a GPS track. Throwaway DB, no network."""
import json

import pytest
from flask import Flask

import database
from services import weather


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


def ride(db, rid='r1', lat=None, lng=None, track=True, summary=None, code=None, sport='Ride'):
    streams = json.dumps({'latlng': {'data': [[51.5, -0.12], [51.51, -0.13]]}}) if track else None
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,averageSpeed,startLat,startLng,streams,rawData,riderId,weatherSummary,weatherCode,createdAt,updatedAt)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,datetime('now'),datetime('now'))",
               [rid, 'x', sport, sport, '2020-01-05T10:00:00', '2020-01-05T10:00:00', 10000, 1800, 1800, 5.0, lat, lng, streams, '{}', summary, code])
    db.commit()


def fake(code=3):
    return lambda lat, lng, when, streams=None, sport=None: {'weatherTempC': 1.0, 'weatherWindKph': 10.0, 'weatherGustKph': 20.0, 'weatherWindDir': 200, 'weatherHumidity': 80,
                                                 'weatherRainMm': 0.0, 'weatherCode': code, 'weatherSummary': weather._WMO[code].capitalize() + ', 1°C, wind 10kph', 'weatherWindRel': 'calm'}


def test_snow_is_its_own_bucket_and_rain_excludes_it():
    assert [weather.bucket(c) for c in (0, 1, 2, 3, 45, 51, 63, 67, 71, 75, 77, 80, 82, 85, 86, 95, 99)] == \
        ['Clear', 'Clear', 'Cloudy', 'Cloudy', 'Fog', 'Rain', 'Rain', 'Rain', 'Snow', 'Snow', 'Snow', 'Rain', 'Rain', 'Snow', 'Snow', 'Storm', 'Storm']
    assert weather.bucket(None) is None


def test_origin_falls_back_to_the_first_track_point(db):
    ride(db, 'a', lat=None, lng=None)
    ride(db, 'b', lat=51.0, lng=-1.0, track=False)
    assert weather.origin(db.execute("SELECT * FROM Activity WHERE id='a'").fetchone()) == (51.5, -0.12)
    assert weather.origin(db.execute("SELECT * FROM Activity WHERE id='b'").fetchone()) == (51.0, -1.0)


def test_backfill_reaches_rides_with_only_a_track_and_fills_the_start_point(db, monkeypatch):
    monkeypatch.setattr(weather, 'fetch_weather', fake(73))
    ride(db, 'a')
    assert weather.backfill_missing(db, pause=0) == (1, 0)
    r = db.execute("SELECT weatherCode, weatherSummary, startLat FROM Activity WHERE id='a'").fetchone()
    assert r['weatherCode'] == 73 and 'snow' in r['weatherSummary'].lower() and r['startLat'] == 51.5


def test_a_virtual_ride_gets_no_weather(db, monkeypatch):
    # Zwift's Watopia sits on open sea near the Solomon Islands: its weather is never the rider's
    assert weather.fetch_weather(-11.63, 166.97, '2026-10-17T17:00:19', sport='VirtualRide') is None
    asked = []
    monkeypatch.setattr(weather, 'fetch_weather', lambda *a, **k: asked.append(a) or None)
    weather._FAILED.clear()
    ride(db, 'z', lat=-11.63, lng=166.97, sport='VirtualRide')
    assert weather.backfill_missing(db, pause=0) == (0, 0) and asked == []


def test_weather_already_on_a_virtual_ride_is_cleared_at_startup(db):
    ride(db, 'z', lat=-11.63, lng=166.97, sport='VirtualRide', summary='Overcast, 26°C, wind 17kph', code=3)
    ride(db, 'r', lat=51.5, lng=-0.12, summary='Overcast, 9°C, wind 10kph', code=3)
    db.execute("UPDATE Activity SET weatherTempC=26.4 WHERE id='z'")
    db.commit()
    database.migrate_db()
    rows = {r['id']: r for r in db.execute("SELECT id, weatherSummary, weatherTempC, weatherCode FROM Activity").fetchall()}
    assert rows['z']['weatherSummary'] is None and rows['z']['weatherTempC'] is None and rows['z']['weatherCode'] is None
    assert rows['r']['weatherSummary'] == 'Overcast, 9°C, wind 10kph'


def test_a_ride_with_no_weather_data_does_not_block_the_queue(db, monkeypatch):
    calls = []
    def f(lat, lng, when, streams=None, sport=None):
        calls.append(when)
        return None
    monkeypatch.setattr(weather, 'fetch_weather', f)
    weather._FAILED.clear()
    ride(db, 'a')
    assert weather.backfill_missing(db, limit=1, pause=0) == (0, 1)
    assert weather.backfill_missing(db, limit=1, pause=0) == (0, 0)      # already tried this run: not retried
    assert len(calls) == 1
    weather._FAILED.clear()


def test_a_chosen_condition_sticks_through_a_backfill(db, monkeypatch):
    monkeypatch.setattr(weather, 'fetch_weather', fake(3))
    ride(db, 'a', lat=51.5, lng=-0.12, summary='Overcast, 1°C, wind 10kph', code=3)
    s = weather.set_condition(db, 'a', 'Snow')
    assert s.startswith('Snow, 1°C')
    weather.save_weather(db, 'a', fake(3)(51.5, -0.12, 'x'))                  # a later refresh says overcast
    r = db.execute("SELECT weatherCode, weatherSummary, weatherSource, weatherTempC FROM Activity WHERE id='a'").fetchone()
    assert weather.bucket(r['weatherCode']) == 'Snow' and r['weatherSource'] == 'manual' and r['weatherSummary'].startswith('Snow') and r['weatherTempC'] == 1.0
    weather.set_condition(db, 'a', None)                                     # back to automatic
    weather.save_weather(db, 'a', fake(3)(51.5, -0.12, 'x'))
    assert weather.bucket(db.execute("SELECT weatherCode FROM Activity WHERE id='a'").fetchone()[0]) == 'Cloudy'


def test_choosing_a_condition_for_a_ride_with_no_weather(db):
    ride(db, 'a')
    weather.set_condition(db, 'a', 'Rain')
    r = db.execute("SELECT weatherCode, weatherSummary FROM Activity WHERE id='a'").fetchone()
    assert weather.bucket(r['weatherCode']) == 'Rain' and r['weatherSummary'] == 'Rain'


def test_fog_candidates_are_damp_still_dry_rides_nobody_has_judged(db):
    for rid, hum, wind, code in [('f1', 99, 4, 3), ('f2', 99, 30, 3), ('f3', 80, 4, 3), ('f4', 99, 4, 63), ('f5', 98, 5, 1)]:
        ride(db, rid, lat=51.5, lng=-0.12, summary='x', code=code)
        db.execute('UPDATE Activity SET weatherHumidity=?, weatherWindKph=?, weatherRainMm=0 WHERE id=?', [hum, wind, rid])
    db.commit()
    assert [c['id'] for c in weather.fog_candidates(db, 1)] == ['f1', 'f5']
    weather.set_condition(db, 'f1', 'keep')                                  # "not fog": no longer suggested, condition unchanged
    assert [c['id'] for c in weather.fog_candidates(db, 1)] == ['f5']
    assert weather.bucket(db.execute("SELECT weatherCode FROM Activity WHERE id='f1'").fetchone()[0]) == 'Cloudy'
    weather.set_condition(db, 'f5', 'Fog')
    assert weather.fog_candidates(db, 1) == [] and weather.bucket(db.execute("SELECT weatherCode FROM Activity WHERE id='f5'").fetchone()[0]) == 'Fog'


def test_a_named_storm_day_outranks_the_lookups_own_condition(db):
    from services import storms
    ride(db, 'gusty', lat=51.5, lng=-0.12, summary='Light rain, 9°C, wind 30kph', code=61)
    ride(db, 'calm', lat=51.5, lng=-0.12, summary='Clear sky, 9°C', code=0)
    ride(db, 'plain', lat=51.5, lng=-0.12, summary='Overcast', code=3)
    db.execute("UPDATE Activity SET startDateLocal='2024-01-22T10:00:00', weatherGustKph=62 WHERE id='gusty'")      # Storm Isha
    db.execute("UPDATE Activity SET startDateLocal='2024-01-22T12:00:00', weatherGustKph=9 WHERE id='calm'")
    db.execute("UPDATE Activity SET startDateLocal='2024-03-05T10:00:00', weatherGustKph=70 WHERE id='plain'")      # no storm that day
    db.commit()
    assert storms.claim_all(db, 1) == 1
    g = db.execute("SELECT weatherCode, weatherSummary, weatherSource FROM Activity WHERE id='gusty'").fetchone()
    assert weather.bucket(g['weatherCode']) == 'Storm' and g['weatherSummary'].startswith('Storm Isha, 9°C') and g['weatherSource'] == 'storm'
    assert weather.bucket(db.execute("SELECT weatherCode FROM Activity WHERE id='calm'").fetchone()[0]) == 'Clear'
    assert weather.bucket(db.execute("SELECT weatherCode FROM Activity WHERE id='plain'").fetchone()[0]) == 'Cloudy'
    weather.save_weather(db, 'gusty', fake(61)(51.5, -0.12, 'x'))            # a refresh keeps it a storm
    assert weather.bucket(db.execute("SELECT weatherCode FROM Activity WHERE id='gusty'").fetchone()[0]) == 'Storm'


def test_a_hand_picked_condition_beats_the_storm_rule(db):
    from services import storms
    ride(db, 'foggy', lat=51.5, lng=-0.12, summary='Fog, 5°C', code=45)
    db.execute("UPDATE Activity SET startDateLocal='2024-01-22T10:00:00', weatherGustKph=62 WHERE id='foggy'")
    db.commit()
    weather.set_condition(db, 'foggy', 'Fog')
    assert storms.claim_all(db, 1) == 0


def test_the_storm_table_is_sane():
    from services import storms
    assert len(storms.NAMED_STORMS) > 70 and all(a <= b for _n, a, b in storms.NAMED_STORMS)
    assert storms.storm_on('2020-02-08') == ['Ciara'] and storms.storm_on('2021-06-01') == []
