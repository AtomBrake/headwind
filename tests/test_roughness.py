"""Road roughness aggregation: speed-normalised readings averaged into ~20 m cells, pocket data left out by default. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from services import roughness, sensors


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


def sidecar(cid, mount, rough, speed=8.0, n=60, lat0=51.5, lng0=-0.12, start=1_790_000_000_000):
    rows = [[start + i * 1000, rough, 1.0, 0.1, 3.0, 1013.0, lat0 + i * 8.0 / 111_320.0, lng0, speed, 50.0] for i in range(n)]
    return {'client_id': cid, 'fields': sensors.FIELDS[:10], 'rows': rows, 'mount': mount, 'device': 'Pixel 10', 'sensors_only': True}


def test_readings_are_scaled_to_the_reference_speed():
    assert roughness.norm(1.0, 8.0) == pytest.approx(1.0)
    assert roughness.norm(1.0, 16.0) == pytest.approx(0.7071, abs=1e-3)      # twice as fast: eased down by the square root
    assert roughness.norm(1.0, 1.0) is None                     # crawling: mostly the rider
    assert roughness.norm(None, 8.0) is None


def test_cells_average_rides_over_the_same_road(db):
    sensors.store(db, 1, sidecar('a', 'bars', 1.0))
    sensors.store(db, 1, sidecar('b', 'bars', 3.0, start=1_790_100_000_000))
    db.commit()
    cs = roughness.cells(db, 1)
    assert cs and all(c['rides'] == 2 for c in cs)
    assert all(abs(c['r'] - 2.0) < 0.01 for c in cs)            # the two rides average to 2.0 everywhere


def test_pocket_rides_are_excluded_unless_asked_for(db):
    sensors.store(db, 1, sidecar('p', 'pocket', 2.0))
    db.commit()
    assert roughness.cells(db, 1) == []
    assert roughness.cells(db, 1, include_pocket=True)


def test_a_cell_needs_a_few_seconds_of_data(db):
    sensors.store(db, 1, sidecar('s', 'bars', 1.0, n=sensors.MIN_ROWS))
    db.commit()
    assert all(c['n'] >= roughness.MIN_SAMPLES for c in roughness.cells(db, 1))


def test_summary_gives_percentile_breaks_and_the_worst_spots(db):
    sensors.store(db, 1, sidecar('s', 'bars', 1.0))
    db.commit()
    s = roughness.summary(roughness.cells(db, 1))
    assert s['cells'] > 0 and len(s['breaks']) == 4 and s['worst']
    assert roughness.summary([]) == {'cells': 0, 'km': 0, 'breaks': [], 'worst': []}


def test_the_ride_track_is_thinned(db):
    pts = roughness.track(sidecar('t', 'bars', 1.0, n=2000)['rows'], max_points=300)
    assert len(pts) == 300 and len(pts[0]) == 3


def test_steep_climbs_are_not_counted_as_road():
    from services import roughness
    rows = []
    for i in range(60):
        press = 1000 - i * 0.12                   # about 1 m up every second at 5 m/s = a very steep climb
        rows.append([i * 1000, 6.0, 9.0, 1.0, 0, press, 54.8 + i * 4e-5, -1.7, 5.0, 100, None])
    assert roughness.rows_with_position(rows) == [] or len(roughness.rows_with_position(rows)) < 15
    flat = [[i * 1000, 6.0, 9.0, 1.0, 0, 1000.0, 54.8 + i * 4e-5, -1.7, 5.0, 100, None] for i in range(60)]
    assert len(roughness.rows_with_position(flat)) == 60


def test_speed_scaling_is_gentle():
    from services import roughness
    assert roughness.norm(2.0, 8.0) == 2.0
    assert abs(roughness.norm(2.0, 2.0 * 8.0 / 8.0 * 4) - 2.0 * (8.0 / 8.0) ** 0.5 * (8.0 / 8.0)) < 5     # sanity: no blow-up
    assert roughness.norm(2.0, 4.0) < 2.0 * 2        # linear scaling would double it; square root gives 1.41x
