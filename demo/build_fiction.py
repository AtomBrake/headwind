"""The made-up life around the demo's activities (demo/generate_demo_db.py): bikes, parts and shoes, a food diary, weight, water, steps, sleep and
recovery, goals, a challenge with a friend, planned routes and the AI coach's notes. All invented; nothing comes from a real database."""
import json
import math
import os
import secrets
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo('Europe/London')

# (kcal, protein, carbs, fat, fibre) per 100 g, typical serving g. Plausible, not lab-exact: this is a made-up diary.
FOODS = {
    'Porridge oats': (370, 11, 60, 8, 9, 50), 'Semi-skimmed milk': (47, 3.5, 4.9, 1.7, 0, 150), 'Banana': (89, 1.1, 23, 0.3, 2.6, 110), 'Scrambled eggs (2 eggs)': (150, 10, 1.5, 11, 0, 130),
    'Wholemeal toast (2 slices)': (230, 9, 41, 3, 6, 70), 'Butter': (717, 0.6, 0.6, 81, 0, 10), 'Greek yoghurt': (97, 9, 4, 5, 0, 200), 'Granola': (450, 9, 62, 17, 7, 40),
    'Mixed berries': (45, 0.9, 10, 0.3, 4, 80), 'Bacon sandwich': (255, 14, 26, 11, 2, 190), 'Corn flakes': (375, 7, 84, 1, 3, 40), 'Peanut butter on toast': (290, 11, 30, 14, 5, 90),
    'Chicken salad wrap': (190, 13, 20, 6, 2, 230), 'Ham and cheese sandwich': (260, 14, 28, 10, 2, 190), 'Salt and vinegar crisps': (520, 6, 50, 33, 4, 30), 'Tomato soup': (45, 1, 7, 1.5, 1, 300),
    'Crusty bread roll': (270, 9, 52, 2, 3, 70), 'Jacket potato': (95, 2.5, 21, 0.2, 2.5, 280), 'Tuna and sweetcorn': (130, 15, 8, 4, 1, 120), 'Side salad': (20, 1, 3, 0.3, 1.5, 100),
    'Pasta (cooked)': (150, 5.5, 30, 1, 2, 220), 'Tomato and basil sauce': (50, 1.5, 8, 1.5, 1.5, 150), 'Chicken curry': (140, 11, 7, 7, 1.5, 300), 'Basmati rice (cooked)': (135, 3, 29, 0.4, 0.5, 200),
    'Spaghetti bolognese': (130, 7.5, 14, 4.5, 1.5, 400), 'Grilled salmon fillet': (205, 22, 0, 13, 0, 140), 'New potatoes': (75, 1.8, 16, 0.3, 1.8, 200), 'Steamed broccoli': (34, 2.8, 4, 0.4, 2.6, 120),
    'Chilli con carne': (115, 8, 11, 4.5, 3, 350), 'Margherita pizza (2 slices)': (250, 11, 30, 9, 2, 220), 'Fish and chips': (200, 9, 22, 8, 2, 450), 'Roast chicken dinner': (135, 12, 11, 5, 2, 500),
    'Egg fried noodles stir fry': (150, 6, 22, 4, 2, 380), 'Lentil dahl': (105, 6, 14, 3, 4, 300), 'Apple': (52, 0.3, 14, 0.2, 2.4, 150), 'Protein bar': (370, 33, 33, 12, 5, 55), 'Flapjack': (440, 6, 58, 21, 4, 70),
    'Latte': (45, 3, 4, 2, 0, 300), 'Chocolate bar': (520, 7, 58, 29, 2, 45), 'Mixed nuts': (610, 20, 12, 52, 7, 30), 'Rice cakes with peanut butter': (330, 12, 40, 13, 4, 60),
    'Recovery shake': (95, 16, 7, 1, 0, 400), 'Digestive biscuits (2)': (480, 7, 66, 21, 3, 30), 'Cheddar cheese': (410, 25, 0.1, 34, 0, 30), 'Energy gel': (260, 0, 64, 0, 0, 40),
    'Malt loaf slice': (285, 7, 60, 1.5, 5, 35), 'Hummus and carrot sticks': (120, 4, 9, 7, 4, 120), 'Cheese on toast': (310, 15, 27, 15, 3, 120), 'Beans on toast': (130, 6, 22, 2, 6, 280),
    'Wensleydale and fruit cake': (380, 9, 50, 16, 2, 110), 'Bara brith slice': (300, 5, 60, 3, 3, 70), 'Kendal mint cake': (390, 0, 98, 0, 0, 40), 'Bakewell tart slice': (420, 5, 55, 20, 2, 80),
}
BREAKFASTS = [['Porridge oats', 'Semi-skimmed milk', 'Banana'], ['Scrambled eggs (2 eggs)', 'Wholemeal toast (2 slices)', 'Butter'], ['Greek yoghurt', 'Granola', 'Mixed berries'],
              ['Bacon sandwich', 'Latte'], ['Corn flakes', 'Semi-skimmed milk', 'Banana'], ['Peanut butter on toast', 'Banana']]
LUNCHES = [['Chicken salad wrap', 'Apple', 'Salt and vinegar crisps'], ['Ham and cheese sandwich', 'Salt and vinegar crisps', 'Apple'], ['Tomato soup', 'Crusty bread roll', 'Cheddar cheese'],
           ['Jacket potato', 'Tuna and sweetcorn', 'Side salad'], ['Pasta (cooked)', 'Tomato and basil sauce', 'Cheddar cheese'], ['Beans on toast', 'Apple'], ['Cheese on toast', 'Side salad']]
DINNERS = [['Chicken curry', 'Basmati rice (cooked)'], ['Spaghetti bolognese', 'Side salad'], ['Grilled salmon fillet', 'New potatoes', 'Steamed broccoli'], ['Chilli con carne', 'Basmati rice (cooked)'],
           ['Margherita pizza (2 slices)', 'Side salad'], ['Egg fried noodles stir fry'], ['Lentil dahl', 'Basmati rice (cooked)'], ['Roast chicken dinner']]
SNACKS = ['Protein bar', 'Flapjack', 'Latte', 'Chocolate bar', 'Mixed nuts', 'Rice cakes with peanut butter', 'Digestive biscuits (2)', 'Hummus and carrot sticks', 'Malt loaf slice', 'Banana', 'Apple']
FUEL = ['Energy gel', 'Flapjack', 'Malt loaf slice', 'Banana', 'Protein bar']
LOCAL_TREATS = {'peak': 'Bakewell tart slice', 'lakes': 'Kendal mint cake', 'snowdonia': 'Bara brith slice', 'dales': 'Wensleydale and fruit cake'}


def food_row(rng, name, scale=1.0):
    kcal, p, c, f, fi, serv = FOODS[name]
    g = serv * scale * rng.uniform(0.85, 1.15)
    k = g / 100.0
    return dict(foodName=name, calories=round(kcal * k), protein=round(p * k, 1), carbs=round(c * k, 1), fat=round(f * k, 1), fibre=round(fi * k, 1), servingG=round(g))


# ------------------------------------------------------------------ gear
def bike_photo(path, base, accent, fat=False):
    from PIL import Image, ImageDraw, ImageFilter
    W, H = 1400, 875
    im = Image.new('RGB', (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(base[i] * (1 - t) + base[i] * 0.45 * t) for i in range(3)))
    d.ellipse([200, 690, 1200, 760], fill=(0, 0, 0))
    im = im.filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(im)

    def wheel(cx, cy, r):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(235, 235, 235) if not fat else (40, 40, 40), width=14 if not fat else 34)
        d.ellipse([cx - r + 24, cy - r + 24, cx + r - 24, cy + r - 24], outline=(120, 120, 130), width=3)
        for k in range(16):
            ang = k * math.pi / 8
            d.line([(cx, cy), (cx + (r - 18) * math.cos(ang), cy + (r - 18) * math.sin(ang))], fill=(160, 160, 170), width=2)
        d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=(200, 200, 205))
    wheel(430, 640, 235)
    wheel(980, 640, 235)
    bb, seat, head, w = (640, 640), (560, 330), (900, 340), 22
    d.line([(430, 640), bb, seat, (430, 640)], fill=accent, width=w, joint='curve')
    d.line([bb, head, seat], fill=accent, width=w, joint='curve')
    d.line([head, (980, 640)], fill=(60, 60, 70), width=w - 4)
    d.line([seat, (545, 255)], fill=(30, 30, 35), width=14)
    d.rounded_rectangle([490, 235, 640, 262], 12, fill=(25, 25, 28))
    d.line([head, (930, 270), (985, 285)], fill=(30, 30, 35), width=14)
    d.ellipse([580, 580, 700, 700], outline=(210, 210, 215), width=10)
    im.save(path, 'JPEG', quality=88)


def make_gear(db, db_path, rider, end_day, rng):
    """Four bikes with parts and a service log, two pairs of shoes as the defaults for runs and for walks and hikes. {kind: bike id}."""
    from services import gear, kit
    MI = gear.MI
    ago = lambda days: (end_day - timedelta(days=days)).isoformat()
    road = gear.create_bike(db, rider, 'Roadie', 'road', 'Canyon', 'Endurace CF 7', 2022, ago(900), 0, 'The long-day bike.')
    grav = gear.create_bike(db, rider, 'Gravel', 'gravel', 'Ribble', 'Gravel AL', 2021, ago(1100), 1800 * MI, 'Bridleways and forest roads.')
    mtb = gear.create_bike(db, rider, 'Trail bike', 'mtb', 'Whyte', 'T-140', 2020, ago(1500), 900 * MI, 'Trail centres.')
    ebike = gear.create_bike(db, rider, 'E-bike', 'ebike', 'Orbea', 'Rise H30', 2023, ago(640), 0, 'For the big days in the hills.')
    gear.set_default(db, rider, road)
    for bid, base, acc in ((road, (22, 70, 105), (252, 76, 2)), (grav, (45, 85, 62), (250, 190, 40)), (mtb, (70, 50, 40), (40, 200, 120)),
                           (ebike, (60, 66, 90), (110, 170, 240))):
        fd, tmp = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        bike_photo(tmp, base, acc, fat=bid == mtb)
        with open(tmp, 'rb') as fh:
            gear.save_photo(db, bid, fh.read(), db_path)
        os.remove(tmp)
    P = gear.add_part
    P(db, road, 'chain', 'Shimano 105 chain', ago(75), 0, 450 * MI, 2500 * MI)
    P(db, road, 'cassette', 'Shimano 105 11-34', ago(520), 0, 5000 * MI, 8000 * MI)
    P(db, road, 'tyre_front', 'Continental GP5000 30mm', ago(150), 0, 1000 * MI, 4000 * MI)
    P(db, road, 'tyre_rear', 'Continental GP5000 30mm', ago(150), 0, 1000 * MI, 2500 * MI)
    P(db, road, 'brake_pads', 'Shimano L05A resin', ago(210), 0, 900 * MI, 2500 * MI)
    P(db, road, 'bar_tape', 'Lizard Skins DSP', ago(610), 0, None, 4000 * MI, None, 540)
    P(db, grav, 'chain', 'SRAM Rival chain', ago(180), 0, 1000 * MI, 2500 * MI)
    P(db, grav, 'tyre_rear', 'WTB Riddler 45mm', ago(330), 0, 1000 * MI, 2500 * MI)
    P(db, grav, 'sealant', 'Orange Seal', ago(215), 0, None, None, None, 120)
    P(db, mtb, 'chain', 'SRAM NX chain', ago(260), 0, 600 * MI, 1500 * MI)
    P(db, mtb, 'brake_pads', 'Shimano sintered pads', ago(120), 0, 400 * MI, 900 * MI)
    P(db, ebike, 'chain', 'KMC e11 chain', ago(200), 0, 800 * MI, 2000 * MI)
    chain = db.execute("SELECT id FROM Part WHERE bikeId=? AND kind='chain'", [road]).fetchone()[0]
    gear.log_service(db, road, 'cleaned', ago(9), None, None, 'Full strip and degrease')
    gear.log_service(db, road, 'inspected', ago(50), chain, None, 'Chain checker: 0.25%')
    gear.log_service(db, grav, 'serviced', ago(80), None, 45, 'Hubs and headset re-greased')
    mchain = db.execute("SELECT id FROM Part WHERE bikeId=? AND kind='chain'", [mtb]).fetchone()[0]
    gear.log_service(db, mtb, 'replaced', ago(260), mchain, 32.99, 'Worn at 0.75% after a wet winter', new_part={'name': 'SRAM NX chain'})
    kit.create(db, rider, 'Trail shoes', 'shoes', 'Inov-8', 'Trailfly', ago(400), 120000, None, 'Grip for wet rock.', ['Run'])
    kit.create(db, rider, 'Walking boots', 'shoes', 'Scarpa', 'Terra GTX', ago(800), 60000, 0, None, ['Walk', 'Hike'])
    kit.create(db, rider, 'Paddle board', 'board', 'Red Paddle Co', 'Ride 10\'6"', ago(700), 0, 0, None, ['Paddle'])
    return {'road': road, 'gravel': grav, 'mtb': mtb, 'ebike': ebike}


# ------------------------------------------------------------------ food, body, recovery
def make_nutrition(db, rider, end_day, rng, days=240):
    """A food diary, water, weigh-ins, steps and Garmin-style recovery days for the last `days` days, eating more on the active ones."""
    db.execute("""UPDATE Settings SET nutritionCalGoal=2300, nutritionProteinGoal=130, nutritionCarbGoal=280, nutritionFatGoal=70, nutritionWaterGoalMl=2500,
                  nutritionWeightUnit='kg', heightCm=178, sex='male', birthYear=1987, stepGoal=10000, goalWeightKg=71, goalAuto=0 WHERE id=1""")
    mins, area_of = {}, {}
    for r in db.execute("SELECT substr(startDateLocal,1,10) d, SUM(movingTime)/60 m FROM Activity WHERE riderId=? GROUP BY 1", [rider]):
        mins[r['d']] = r['m'] or 0
    w0, w1 = 75.8, 71.9
    for i in range(days, -1, -1):
        d = end_day - timedelta(days=i)
        ds, dow = d.isoformat(), d.weekday()
        active = mins.get(ds, 0)
        progress = (days - i) / days
        w = w0 - (w0 - w1) * progress + rng.gauss(0, 0.22) + (0.4 if active == 0 and dow == 6 else 0)
        if rng.random() > 0.05 or i == 0:
            meals = [('breakfast', rng.choice(BREAKFASTS)), ('lunch', rng.choice(LUNCHES))]
            if rng.random() > 0.08 or i == 0:
                dinner = ['Fish and chips'] if dow == 4 and rng.random() < 0.5 else ['Roast chicken dinner'] if dow == 6 else rng.choice(DINNERS)
                meals.append(('dinner', dinner))
            for meal, names in meals:
                for nm in names:
                    _food(db, rider, ds, meal, food_row(rng, nm))
            for nm in rng.sample(SNACKS, rng.choice([1, 2, 2, 3])):
                _food(db, rider, ds, 'snacks', food_row(rng, nm, 0.9))
            if active > 45:
                for nm in rng.sample(FUEL, 2 if active > 120 else 1):
                    _food(db, rider, ds, 'snacks', food_row(rng, nm))
                if active > 90:
                    _food(db, rider, ds, 'snacks', food_row(rng, 'Recovery shake'))
                if active > 150 and rng.random() < 0.5:
                    _food(db, rider, ds, 'snacks', food_row(rng, rng.choice(list(LOCAL_TREATS.values()))))
            for _ in range(rng.randint(4, 8)):
                db.execute('INSERT INTO HydrationLog (riderId, logDate, ml) VALUES (?,?,?)', [rider, ds, rng.choice([250, 330, 500, 500, 750])])
        if rng.random() < 0.8:
            db.execute('INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (?,?,?,?)', [rider, ds, round(w, 1), 'scale'])
        steps = max(1800, int(rng.gauss(7800, 2100)) + (int(active * 95) if active else 0) + (2500 if dow >= 5 else 0))
        resting = round(50 - 3 * progress + rng.gauss(0, 1.5) + (2 if active > 180 else 0))
        sleep = max(4.9, min(9.3, rng.gauss(7.3, 0.75)))
        body = max(12, min(99, int(rng.gauss(74, 14) - (12 if active > 150 else 0))))
        hrs, bbs = [], []
        base_ms = int(datetime(d.year, d.month, d.day, tzinfo=LONDON).timestamp() * 1000)
        for q in range(0, 96, 2):
            t = base_ms + q * 15 * 60000
            hour = q / 4
            hrs.append([t, int(resting + (9 if 7 <= hour <= 22 else 0) + rng.gauss(0, 4) + (40 if active and 9 <= hour <= 11 else 0))])
            bbs.append([t, max(5, min(100, int(body + 20 - 1.6 * max(0, hour - 6) if hour > 6 else 30 + hour * 7)))])
        db.execute('''INSERT INTO GarminDaily (date, restingHR, hrv, hrvBalanced, sleepHours, sleepScore, bodyBattery, steps, stressScore, hrStream,
                      bodyBatteryStream, totalCalories, activeCalories) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   [ds, resting, round(rng.gauss(68, 9)), 1, round(sleep, 1), int(max(35, min(97, sleep * 11 + rng.gauss(0, 7)))), body, steps,
                    int(max(10, min(80, rng.gauss(30, 10)))), json.dumps(hrs), json.dumps(bbs), round(2200 + steps * 0.04 + active * 8.5),
                    round(steps * 0.04 + active * 8.5)])
    for nm, meal in (('Porridge bowl', BREAKFASTS[0]), ('Big day out', ['Chilli con carne', 'Basmati rice (cooked)', 'Recovery shake']), ('Lazy lunch', LUNCHES[1])):
        mid = db.execute('INSERT INTO SavedMeal (name) VALUES (?)', [nm]).lastrowid
        for item in meal:
            f = food_row(rng, item)
            db.execute('INSERT INTO SavedMealItem (mealId, foodName, calories, protein, carbs, fat, servingG, fibre) VALUES (?,?,?,?,?,?,?,?)',
                       [mid, item, f['calories'], f['protein'], f['carbs'], f['fat'], f['servingG'], f['fibre']])
    from services import food_cache                    # the demo can't reach Open Food Facts: search finds these instead
    food_cache.store([{'name': nm, 'brand': '', 'kcal_per_100g': v[0], 'protein_per_100g': v[1], 'carbs_per_100g': v[2], 'fat_per_100g': v[3],
                       'fibre_per_100g': v[4], 'serving_g': v[5]} for nm, v in FOODS.items()])
    for item in ('Protein bar', 'Flapjack', 'Greek yoghurt', 'Banana', 'Latte'):
        f = food_row(rng, item)
        db.execute('INSERT INTO FoodFavourite (riderId, foodName, calories, protein, carbs, fat, servingG) VALUES (?,?,?,?,?,?,?)',
                   [rider, item, f['calories'], f['protein'], f['carbs'], f['fat'], f['servingG']])


def _food(db, rider, ds, meal, r):
    db.execute('INSERT INTO FoodLog (riderId, logDate, foodName, calories, protein, carbs, fat, fibre, servingG, quantity, mealType, source) '
               'VALUES (?,?,?,?,?,?,?,?,?,1,?,?)', [rider, ds, r['foodName'], r['calories'], r['protein'], r['carbs'], r['fat'], r['fibre'], r['servingG'], meal, 'manual'])


# ------------------------------------------------------------------ goals, routes, the coach
def make_goals(db, rider):
    from services import goals
    for metric, period, sport, target in (('count', 'week', ['all'], '4'), ('distance', 'month', ['group:ride'], '400'), ('climb', 'year', ['all'], '100000'),
                                          ('distance', 'month', ['group:foot'], '60')):
        err = goals.add_goal(db, rider, metric, period, None if sport == ['all'] else sport, target)
        if err:
            print(f'  goal {metric}/{period}: {err}')


def make_challenge(db, rider, friend_id, end_day):
    """A month of climbing against the friend, this month, and last month's distance, which the friend won or lost."""
    first = end_day.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    for name, metric, sport, a, b in (('Climb-off', 'climb', 'all', first, nxt - timedelta(days=1)),
                                      ('Distance duel', 'distance', 'ride', prev, first - timedelta(days=1))):
        cid = db.execute('''INSERT INTO Challenge (uid, riderId, name, metric, sport, startDate, endDate, target, mine, joined)
                            VALUES (?,?,?,?,?,?,?,NULL,1,1)''', [secrets.token_hex(8), rider, name, metric, sport, a.isoformat(), b.isoformat()]).lastrowid
        db.execute('INSERT INTO ChallengeMember (challengeId, friendId) VALUES (?,?)', [cid, friend_id])


def make_planned_routes(db, rider, lib, rng):
    """A few routes from the library saved as planned ones, as if drawn in the planner, and a few never ridden yet."""
    from services import planned_routes
    picked = 0
    for (area, kind), routes in sorted(lib.items()):
        if kind not in ('road', 'gravel', 'hike', 'run') or not routes:
            continue
        for r in rng.sample(routes, min(2, len(routes))):
            track = planned_routes.clean([list(p) for p in r['coords'][::2]])
            sport = {'road': 'Ride', 'gravel': 'GravelRide', 'hike': 'Hike', 'run': 'Run'}[kind]
            planned_routes.save(db, rider, r['name'], track=track, waypoints=planned_routes.as_waypoints(track), source='planner', sport=sport)
            picked += 1
    return picked


COACH = {
    'climb': ['Strong climbing today: {gain} m at an average of {hr} bpm. You paced the long drags well and saved something for the top.',
              '{gain} m of climbing in {hours}. Your heart rate stayed under control on the steep bits, which is the sign of good pacing.'],
    'long': ['A big day: {km} km. Fuelling looks right, as your pace held steady through the second half.',
             '{km} km and {hours} on the move. Keep a recovery day in the next two days; your legs will thank you.'],
    'easy': ['Nice easy one at {hr} bpm: exactly the zone 2 work that builds the base.', 'Gentle {km} km. Easy days like this make the hard ones possible.'],
    'foot': ['{km} km on foot with {gain} m of ascent. Steady effort, with a sensible pace on the descents.',
             'Good time on your feet: {hours}. The climbing will pay off on the bike, too.'],
    'water': ['A calm {km} km on the water. Paddling gives the legs a day off while the rest of you works.'],
}


def make_coach_notes(db, rider, rng, share=0.35):
    """What the AI coach would have said about about a third of the activities, written beforehand (live AI stays off in the demo)."""
    n = 0
    for a in db.execute('SELECT id, sportType, distance, movingTime, totalElevationGain, averageHeartrate, startDateLocal FROM Activity WHERE riderId=?', [rider]).fetchall():
        if rng.random() > share or not a['distance']:
            continue
        km, gain = a['distance'] / 1000, a['totalElevationGain'] or 0
        st = a['sportType']
        kind = ('water' if st == 'Paddle' else 'foot' if st in ('Run', 'Walk', 'Hike') else 'climb' if gain > km * 15 else 'long' if km > 70 else 'easy')
        h, m = divmod(int((a['movingTime'] or 0) / 60), 60)
        text = rng.choice(COACH[kind]).format(gain=round(gain), hr=round(a['averageHeartrate'] or 130), km=round(km, 1), hours=f'{h} h {m:02d} min' if h else f'{m} min')
        db.execute('UPDATE Activity SET aiKudos=?, aiKudosAt=? WHERE id=?', [text, a['startDateLocal'], a['id']])
        n += 1
    return n


def make_extras(db, rider, lib, end_day, rng, out_db, friend_id=None):
    make_goals(db, rider)
    if friend_id:
        make_challenge(db, rider, friend_id, end_day)
    n_routes = make_planned_routes(db, rider, lib, rng)
    n_notes = make_coach_notes(db, rider, rng)
    db.commit()
    print(f'extras: 4 goals, {n_routes} planned routes, {n_notes} coach notes' + (', 2 challenges' if friend_id else ''))
