"""Strava's activities.csv repeats some headers; the fallback distance must come out in metres, not 1000x too big."""
import io

from routes.import_rides import _strava_csv_distance_m, _strava_csv_rows

# the start of a real export's header: Elapsed Time and Distance appear twice (summary in km, then detail in metres)
CSV = ('Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Moving Time,Elapsed Time,Distance\n'
       '20294689368,"Jul 4, 2026, 10:46:04 AM",Lanhydrock Tour,E-Bike Ride,13000,45.96,11610,13000,45959.5\n')


def test_repeated_headers_are_all_kept():
    row = _strava_csv_rows(io.StringIO(CSV))[0]
    assert row['Distance'] == '45.96' and row['Distance (2)'] == '45959.5'
    assert row['Elapsed Time'] == row['Elapsed Time (2)'] == '13000'


def test_distance_uses_the_metres_column():
    row = _strava_csv_rows(io.StringIO(CSV))[0]
    assert _strava_csv_distance_m(row) == 45959.5            # 28.6 miles, not 28,558


def test_older_export_with_only_the_km_column():
    assert _strava_csv_distance_m({'Distance': '45.96'}) == 45960.0
    assert _strava_csv_distance_m({'Distance': '1,234.5'}) == 1234500.0


def test_blank_or_zero_distance_is_none():
    assert _strava_csv_distance_m({'Distance': '', 'Distance (2)': ''}) is None
    assert _strava_csv_distance_m({'Distance': '0', 'Distance (2)': '0.0'}) is None
    assert _strava_csv_distance_m({}) is None
