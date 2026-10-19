"""A file's own sport (services/parser._map_sport, services/sports.from_type): FIT sports and sub-sports, GPX and TCX types. Anything not a ride
used to come in as a ride when a file was uploaded on its own; the pairs below are what a real Strava export's files say, and what
activities.csv calls the same activities."""
import pytest

from services import parser, sports
from services.garmin import garmin_sport


@pytest.mark.parametrize('sport, sub, want', [
    # FIT: sport, sub_sport -> what Strava called it
    ('cycling', 'generic', 'Ride'), ('cycling', 'mountain', 'Ride'), ('cycling', 'road', 'Ride'), ('cycling', None, 'Ride'),
    ('cycling', 'virtual_activity', 'VirtualRide'), ('cycling', 'indoor_cycling', 'VirtualRide'),
    ('cycling', 'e_bike_fitness', 'EBikeRide'), ('cycling', 'e_bike_mountain', 'EBikeRide'), ('e_biking', None, 'EBikeRide'),
    ('walking', 'generic', 'Walk'), ('walking', None, 'Walk'), ('running', 'generic', 'Run'), ('running', 'trail', 'Run'), ('hiking', 'generic', 'Hike'),
    ('swimming', 'lap_swimming', 'Swim'), ('swimming', 'open_water', 'Swim'),
    ('alpine_skiing', 'generic', 'Ski'), ('cross_country_skiing', 'generic', 'Ski'),
    ('stand_up_paddleboarding', 'generic', 'Paddle'), ('kayaking', 'generic', 'Paddle'),
    ('windsurfing', 'generic', 'Surf'), ('kitesurfing', 'generic', 'Surf'), ('surfing', 'generic', 'Surf'),
    ('training', 'yoga', 'Other'), ('training', 'strength_training', 'Other'), ('training', 'cardio_training', 'Other'),
    ('tennis', 'generic', 'Other'), ('snowshoeing', 'generic', 'Other'), (62, 'generic', 'Other'), (64, 85, 'Other'),
    # GPX <type>
    ('cycling', None, 'Ride'), ('mountain_biking', None, 'Ride'), ('EMountainBikeRide', None, 'EBikeRide'), ('ebikeride', None, 'EBikeRide'),
    ('running', None, 'Run'), ('trail_running', None, 'Run'), ('walking', None, 'Walk'), ('hiking', None, 'Hike'),
    ('StandUpPaddling', None, 'Paddle'), ('Canoeing', None, 'Paddle'), ('1', None, 'Ride'), ('9', None, 'Run'),
    # TCX Sport
    ('Biking', None, 'Ride'), ('Running', None, 'Run'), ('Other', None, 'Other'),
    # the phone apps' GPX types, and Headwind's own names
    ('ebike', None, 'EBikeRide'), ('vride', None, 'VirtualRide'), ('EBikeRide', None, 'EBikeRide'), ('VirtualRide', None, 'VirtualRide'),
    ('Paddle', None, 'Paddle'), ('Golf', None, 'Golf'),
])
def test_a_files_sport(sport, sub, want):
    assert parser._map_sport(sport, sub) == want


def test_every_sport_maps_to_itself_and_nothing_unknown_is_a_ride():
    assert all(parser._map_sport(s) == s for s in sports.SPORTS)
    assert parser._map_sport('motorcycling') == 'Other' and parser._map_sport('something new') == 'Other'


def test_garmin_and_files_share_the_rules():
    for k in ('mountain_biking', 'e_bike_mountain', 'indoor_cycling', 'lap_swimming', 'resort_skiing', 'stand_up_paddleboarding', 'yoga'):
        assert garmin_sport(k) == sports.from_type(k)


def test_a_gpx_named_as_a_strava_e_mtb_ride_or_paddle_comes_in_as_one():
    def gpx(kind):
        pts = ''.join(f'<trkpt lat="{50.4 + i * 0.0003:.5f}" lon="-4.7"><time>2026-07-04T09:{i // 6:02d}:{i % 6 * 10:02d}Z</time></trkpt>' for i in range(30))
        return (f'<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><type>{kind}</type>'
                f'<trkseg>{pts}</trkseg></trk></gpx>').encode()
    assert parser.parse_gpx(gpx('EMountainBikeRide'))['sportType'] == 'EBikeRide'
    assert parser.parse_gpx(gpx('StandUpPaddling'))['sportType'] == 'Paddle'
    no_type = gpx('x').replace(b'<type>x</type>', b'')
    assert parser.parse_gpx(no_type)['sportType'] == 'Ride'                    # no sport named at all: a ride, as before
