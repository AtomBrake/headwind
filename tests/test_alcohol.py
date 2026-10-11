"""Alcohol units: the weekly summary the Nutrition page's ring and the Home Assistant sensors use. Throwaway DB."""
import pytest
from flask import Flask

import database


@pytest.fixture
def ctx(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider(name,isDefault) VALUES ('Rob',1)")
        d.commit()
        yield d


def drink(d, day, units):
    d.execute("INSERT INTO FoodLog (riderId, logDate, foodName, calories, alcoholUnits, mealType, source) VALUES (1, ?, 'drink', 150, ?, 'dinner', 'drink')", [day, units])
    d.commit()


def test_the_week_total_covers_seven_days_ending_on_the_day(ctx):
    from routes.nutrition import _alcohol_summary
    drink(ctx, '2026-10-11', 2.6); drink(ctx, '2026-10-11', 2.3); drink(ctx, '2026-10-09', 3.0); drink(ctx, '2026-10-05', 4.0); drink(ctx, '2026-10-04', 9.0)   # the 4th is 7 days back: outside
    s = _alcohol_summary(1, '2026-10-11', 14)
    assert s == {'today': 4.9, 'week': 11.9, 'goal': 14, 'days': 3}


def test_no_drinks_is_zero_not_an_error(ctx):
    from routes.nutrition import _alcohol_summary
    assert _alcohol_summary(1, '2026-10-11', 14)['week'] == 0
    assert _alcohol_summary(1, 'not-a-date', 14)['week'] == 0


def test_units_maths():
    assert round(568 * 4.5 / 1000, 1) == 2.6        # a pint of 4.5% beer
    assert round(175 * 13 / 1000, 1) == 2.3         # a medium glass of 13% wine
    assert 25 * 40 / 1000 == 1.0                    # a single measure of spirit


def test_recovery_compares_drinking_days_with_dry_days_the_next_morning(ctx):
    from services import alcohol
    for i in range(1, 8):                                   # seven drinking days (3 units) and seven dry days, food logged on all
        for day, units in ((f'2026-09-{i:02d}', 3.0), (f'2026-09-{i + 10:02d}', 0)):
            ctx.execute("INSERT INTO FoodLog (riderId, logDate, foodName, calories, alcoholUnits, mealType) VALUES (1, ?, 'x', 500, ?, 'dinner')", [day, units or None])
    ctx.execute('INSERT OR IGNORE INTO GarminDaily (date) VALUES (?)', ['2026-09-01'])
    for i in range(1, 8):
        ctx.execute('INSERT OR REPLACE INTO GarminDaily (date, restingHR, sleepHours) VALUES (?, 60, 6.5)', [f'2026-09-{i + 1:02d}'])         # morning after a drinking day
        ctx.execute('INSERT OR REPLACE INTO GarminDaily (date, restingHR, sleepHours) VALUES (?, 52, 7.5)', [f'2026-09-{i + 11:02d}'])        # morning after a dry day
    ctx.commit()
    r = alcohol.recovery_comparison(ctx, 1)
    assert r['enough'] and r['drink_days'] == 7 and r['dry_days'] == 7
    hr = next(x for x in r['rows'] if x['unit'] == 'bpm')
    assert (hr['drink'], hr['dry'], hr['diff']) == (60, 52, 8)


def test_recovery_needs_logged_drinks_and_enough_of_them(ctx):
    from services import alcohol
    assert alcohol.recovery_comparison(ctx, 1) is None
    drink(ctx, '2026-09-01', 3.0)
    r = alcohol.recovery_comparison(ctx, 1)
    assert r is not None and not r['enough']
