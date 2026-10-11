"""What FoodLog.sugar means: TOTAL sugars, never free/added sugar. Open Food Facts' added-sugars field is unreliable (it can exceed the total), so it is ignored."""
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


OFF = {'code': '111', 'product_name': 'Crunch bar', 'brands': 'Acme', 'nutriments': {'energy-kcal_100g': 480, 'sugars_100g': 23.0, 'added-sugars_100g': 43.11, 'carbohydrates_100g': 60}}


def test_the_food_database_value_used_is_total_sugars_not_added_sugars():
    from routes.nutrition import _off_product_to_dict
    p = _off_product_to_dict(OFF)
    assert p['_sugars_per_100g'] == 23.0                    # the label's total, not the (impossible) 43.11 "added"
    assert not any('added' in k for k in p)                 # added sugars are not carried anywhere


def test_a_logged_foods_sugar_is_worked_out_from_total_sugars(ctx):
    from routes.nutrition import _saved_sugar
    ctx.execute("INSERT INTO FoodCache (key, barcode, name, searchText, kcal100g, sugars100g) VALUES ('111', '111', 'Crunch bar', 'crunch bar', 480, 23.0)")
    ctx.commit()
    assert _saved_sugar('111', 'Crunch bar', 50, 240) == 11.5       # 50 g of a food with 23 g total sugars per 100 g


def test_the_sugar_reference_defaults_to_fifty_and_says_it_is_total(ctx):
    from routes.nutrition import _get_goals
    g = _get_goals()
    assert g['sugar'] == 50 and g['sugar_basis'] == 'total'


def test_a_reference_the_user_already_set_is_kept(ctx):
    from routes.nutrition import _get_goals
    ctx.execute('UPDATE Settings SET nutritionSugarGoal=35 WHERE id=1'); ctx.commit()
    assert _get_goals()['sugar'] == 35
