"""Where the play stands, for the console."""
from . import clock, db, lock


def count(conn, table, status):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE status = ?", (status,)).fetchone()[0]


def report():
    conn = db.connect()
    start = clock.this_week(conn)
    now = clock.as_datetime(clock.now(conn))
    you = db.get_state(conn, "you", "")
    house = f"{you}'s Mudroom" if you else "The Mudroom"
    if not clock.real(conn):
        house = f"The demo: {house}"
    slots = [r[0] for r in conn.execute("SELECT DISTINCT staged_at FROM items ORDER BY staged_at")]
    if not slots:
        door = "Nothing has come to the door yet."
    else:
        last = clock.slot_label(clock.as_datetime(slots[-1]))
        door = f"Intakes so far: {len(slots)}, the last one {last}."
    waiting = count(conn, "items", "staged")
    if waiting:
        door += f" At the door: {waiting} items waiting to be judged."
    lines = [
        f"{house}, week of Monday {clock.long_date(start)}",
        f"Clock: {clock.clock_label(now)}. {door}",
        f"Open tasks: {count(conn, 'tasks', 'open')}   "
        f"Promises open: {count(conn, 'commitments', 'open')}   "
        f"Questions waiting: {count(conn, 'questions', 'open')}",
    ]
    held = lock.held(conn)
    if held:
        lines.append(f"A run is in flight since {held:%H:%M}, not yet processed.")
    pending = {r["outcome"]: r["n"] for r in conn.execute(
        "SELECT outcome, COUNT(*) AS n FROM proposals WHERE status = 'pending' GROUP BY outcome")}
    if pending:
        lines.append(f"Ready for you: {pending.get('ready', 0)}   "
                     f"Needs your input: {pending.get('yours', 0)}   "
                     f"Heads-up: {pending.get('headsup', 0)}   Filed away: {pending.get('filed', 0)}")
    conn.close()
    return "\n".join(lines)
