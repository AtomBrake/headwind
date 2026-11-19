"""Home Assistant sensors in mi, ft and mph keep their unit (their ids say it, and dashboards read them), but say they're a distance or a speed,
so HA can show them in metric units from each entity's settings. No broker."""
import json

from services import live, mqtt


def _config(uid, unit):
    return json.loads(mqtt._discovery(uid, uid, 'mdi:bike', unit)[2])


def test_distances_climbs_and_speeds_have_a_device_class_and_keep_their_unit():
    for uid, unit, cls in (('total_distance_mi', 'mi', 'distance'), ('total_elevation_ft', 'ft', 'distance'),
                           ('last_ride_avg_speed_mph', 'mph', 'speed'), ('week_swim_distance_m', 'm', 'distance')):
        c = _config(uid, unit)
        assert (c['unit_of_measurement'], c['device_class']) == (unit, cls), uid
    assert 'device_class' not in _config('total_calories', 'kcal') and 'device_class' not in _config('last_ride_name', None)


def test_every_imperial_sensor_is_covered():
    for uid, _, _, unit in mqtt.SENSORS + live.SENSORS:
        if unit in ('mi', 'ft', 'mph'):
            assert _config(uid, unit).get('device_class'), uid
