"""An activity with no sport: counted as a ride for totals, segments and gear (services/sports.is_ride), but nothing calls it one, since nothing
says it was. Its name reads "Activity" (sports.label), and on the Data page its records stay in the Ride row they always counted towards."""
from services import sports, workouts
from tests.test_sport_records import app  # noqa: F401  (a fixture)


def test_no_sport_reads_activity_but_still_counts_as_a_ride():
    for nothing in (None, ''):
        assert sports.label(nothing) == 'Activity'
        assert sports.is_ride(nothing) and sports.kind(nothing) == 'ride' and sports.stat_group(nothing or 'Ride') == 'ride'
    assert [sports.label(s) for s in ('Ride', 'VirtualRide', 'Walk')] == ['Ride', 'Indoor ride', 'Walk']     # a sport still reads as itself
    assert workouts.label({'name': None, 'sport': None, 'startDateLocal': '2026-11-24T07:30:00'}) == 'Morning activity'
    assert workouts.label({'name': None, 'sport': 'Ride', 'startDateLocal': '2026-11-24T18:30:00'}) == 'Evening ride'


def test_the_data_pages_records_keep_a_no_sport_activity_with_the_rides(app):  # noqa: F811
    from routes.data import _sport_records
    row = lambda aid, sport, dist: {'id': aid, 'name': None, 'sportType': sport, 'startDateLocal': '2026-11-20T08:00:00', 'distance': dist,
                                    'movingTime': 3600, 'totalElevationGain': 100, 'mps': dist / 3600}
    with app.test_request_context():
        recs = _sport_records([row('r1', 'Ride', 20000), row('n1', None, 30000), row('w1', 'Walk', 4000)])['all']
    assert [e['sport'] for e in recs] == ['Ride', 'Walk']                    # not a row of its own called "Activity"
    assert recs[0]['dist']['id'] == 'n1' and recs[0]['dist']['name'] == 'Ride'
