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


def _is_number(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


def test_every_number_is_graphed_and_text_is_not():
    """Home Assistant draws a line graph (and keeps long-term statistics) for a sensor with a state_class; one without draws a bar of
    values, as Activities This Week and Badges Earned did. Missing readings are NO_VALUE, which HA takes as no value, not text."""
    stats = {'rides': 3, 'dist': 50000, 'elev': 800, 'secs': 7200, 'cals': 900, 'last_name': 'Morning Ride', 'last_date': '2026-11-21',
             'last_dist': 20000, 'last_elev': 100, 'last_time': 3600, 'last_speed': 5.5, 'all_n': 7, 'week_n': 2, 'any_name': 'Run',
             'any_sport': 'Run', 'any_date': '2026-11-22', 'badges_earned': 4, 'badges_total': 20}
    garmin = {'bodyBattery': 60, 'restingHR': 50, 'hrv': 40, 'sleepHours': 7.5, 'sleepScore': 80, 'steps': 9000, 'stressScore': 25}
    live_c = {'state': 'riding', 'sport': 'Ride', 'speed_mph': 15.2, 'distance_mi': 3.1, 'elapsed': '0:12:00', 'elevation_ft': 120,
              'roughness': None, 'lean': 4.0, 'pressure': 1012.0, 'battery': 80}
    for sensors, states in ((mqtt.SENSORS, mqtt._state_values(stats)), (mqtt.SENSORS, mqtt._state_values({})),
                            (mqtt.GARMIN_SENSORS, mqtt._garmin_state_values(garmin)), (mqtt.GARMIN_SENSORS, mqtt._garmin_state_values({})),
                            (live.SENSORS, live.states_for(live_c))):
        for uid, _, _, unit in sensors:
            value, graphed = states[uid], 'state_class' in _config(uid, unit)
            assert value != 'unknown' or not graphed, uid
            assert graphed == (_is_number(value) or value == mqtt.NO_VALUE), (uid, value)


def test_counts_have_units():
    units = {uid: unit for uid, _, _, unit in mqtt.SENSORS + mqtt.GARMIN_SENSORS}
    assert (units['total_rides'], units['week_activities'], units['badges_earned'], units['garmin_steps']) == ('rides', 'activities', 'badges', 'steps')
