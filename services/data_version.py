"""A number that goes up with every write to the tables in TABLES, kept by triggers so no write path can forget it. Something worked out from those
tables can be kept until it changes: the badges (routes/riders._compute_badges), which recount a rider's whole history and are wanted on every ride
page. A new connection sees every commit, so the number is right for each request."""

TABLES = ('Activity', 'Segment', 'SegmentEffort', 'Bike', 'SportEffort')


def ensure_schema(db):
    """Run after database.heavy_last, which rebuilds Activity and drops its triggers on the way if a start-up is cut short. Does not commit."""
    db.execute('CREATE TABLE IF NOT EXISTS DataVersion (id INTEGER PRIMARY KEY CHECK (id = 1), n INTEGER NOT NULL DEFAULT 0)')
    db.execute('INSERT OR IGNORE INTO DataVersion (id, n) VALUES (1, 0)')
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in TABLES:
        if table not in have:
            continue
        for op in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f'CREATE TRIGGER IF NOT EXISTS DataVersion_{table}_{op.lower()} AFTER {op} ON {table} '
                       'BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END')


def current(db):
    """The number now, or None when it can't be read (then nothing should be kept)."""
    try:
        row = db.execute('SELECT n FROM DataVersion WHERE id = 1').fetchone()
        return row[0] if row else None
    except Exception:
        return None
