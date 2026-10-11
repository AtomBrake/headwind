"""Alcohol and recovery: how the morning after a drinking day compares with the morning after a dry day, from the Garmin sleep and heart-rate data
already in Headwind. Correlation, not proof (a late night out also means a short night), so the page says so."""
from datetime import date, timedelta

MIN_DRINK_DAYS = 5          # fewer than this and the comparison is noise
HEAVY_UNITS = 2.0           # a "drinking day" is 2+ units; a lighter day is left out of both groups
METRICS = [('restingHR', 'Resting heart rate (next morning)', 'bpm', 0, False),
           ('hrv', 'Heart-rate variability (next morning)', 'ms', 0, True),
           ('sleepHours', 'Sleep that night', 'h', 1, True)]      # (column, label, unit, decimals, higher is better)


def recovery_comparison(db, rider_id):
    """None if there is nothing logged yet, else {'drink_days', 'dry_days', 'rows': [{label, unit, drink, dry, diff, better_when_higher, n_drink, n_dry}], 'enough'}."""
    units = {r['logDate']: r['u'] for r in db.execute(
        "SELECT logDate, COALESCE(SUM(alcoholUnits), 0) u FROM FoodLog WHERE riderId=? GROUP BY logDate", [rider_id])}
    logged_food = {r[0] for r in db.execute("SELECT DISTINCT logDate FROM FoodLog WHERE riderId=? AND calories > 0", [rider_id])}
    if not any(u > 0 for u in units.values()):
        return None
    garmin = {r['date']: r for r in db.execute('SELECT date, restingHR, hrv, sleepHours FROM GarminDaily')}
    drink, dry = [], []
    for day in logged_food:                 # a day only counts as dry if food was logged that day (an unlogged day is unknown, not dry)
        try:
            nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        except ValueError:
            continue
        g = garmin.get(nxt)
        if not g:
            continue
        u = units.get(day, 0)
        if u >= HEAVY_UNITS:
            drink.append(g)
        elif u == 0:
            dry.append(g)
    rows = []
    for col, label, unit, dec, higher in METRICS:
        a = [g[col] for g in drink if g[col] is not None]
        b = [g[col] for g in dry if g[col] is not None]
        if not a or not b:
            continue
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        rows.append({'label': label, 'unit': unit, 'drink': round(ma, dec) if dec else round(ma), 'dry': round(mb, dec) if dec else round(mb),
                     'diff': round(ma - mb, dec) if dec else round(ma - mb), 'better_when_higher': higher, 'n_drink': len(a), 'n_dry': len(b)})
    return {'drink_days': len(drink), 'dry_days': len(dry), 'rows': rows, 'enough': len(drink) >= MIN_DRINK_DAYS and bool(rows)}
