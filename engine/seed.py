"""Reset: rebuild the database from world/seed.json, stamped to this week."""
import json
from datetime import datetime, timedelta

from . import WORLD, clock, db


def reset(today=None, path=None):
    """Restore the seed, stamp the dates, rewind the clock. Returns the week's Monday. The
    tests pass their own seed; the demo's is world/seed.json."""
    path = path or WORLD / "seed.json"
    if db.real_house():
        raise SystemExit("This house is yours: start-clean made it so, and reset would replace it "
                         "with the invented week. To play the demo, download or clone the Mudroom "
                         "afresh, into another folder.")
    if not path.exists():
        raise SystemExit("The invented week has left this house: start-clean removed it. "
                         "To play the demo again, download or clone the Mudroom afresh, into another folder.")
    data = json.loads(path.read_text(encoding="utf-8"))
    start = clock.week_start(today)
    conn = db.rebuild()
    with conn:
        conn.executemany(
            "INSERT INTO calendars (id, name, colour, note) VALUES (:id, :name, :colour, :note)",
            [{"note": None, **c} for c in data["calendars"]],
        )
        conn.executemany(
            "INSERT INTO people (id, name, pronouns, domain, role, trait) "
            "VALUES (:id, :name, :pronouns, :domain, :role, :trait)",
            [{"pronouns": None, "role": None, "trait": None, **p} for p in data["people"]],
        )
        for e in data["events"]:
            repeats = "days" in e
            for day in e["days"] if repeats else [e["day"]]:
                start_at = clock.stamp(start, day, e["time"])
                end_at = (clock.as_datetime(start_at) + timedelta(minutes=e.get("minutes", 60)))
                conn.execute(
                    "INSERT INTO events (id, calendar_id, title, start, end, notes, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'seed', ?)",
                    (f"{e['id']}-{day}" if repeats else e["id"], e["calendar"], e["title"],
                     start_at, end_at.isoformat(timespec="minutes"), e.get("notes"),
                     clock.stamp(start, -7)),
                )
        for t in data["tasks"]:
            conn.execute(
                "INSERT INTO tasks (id, title, domain, priority, due, notes, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'seed', ?)",
                (t["id"], t["title"], t["domain"], t.get("priority", 2),
                 clock.stamp(start, t["due_day"]) if "due_day" in t else None,
                 t.get("notes"), clock.stamp(start, t.get("created_day", -7))),
            )
        for c in data["commitments"]:
            conn.execute(
                "INSERT INTO commitments (id, owner, person_id, what, promised_on, due, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'seed')",
                (c["id"], c["owner"], c.get("person"), c["what"],
                 clock.stamp(start, c["promised_day"]),
                 clock.stamp(start, c["due_day"]) if "due_day" in c else None),
            )
        for q in data["questions"]:
            conn.execute(
                "INSERT INTO questions (id, subject, question, asked_on) VALUES (?, ?, ?, ?)",
                (q["id"], q["subject"], q["question"], clock.stamp(start, q["asked_day"])),
            )
        opening = clock.stamp(start, 0, "08:00")
        db.set_state(conn, "you", data.get("you", "Alex"))
        db.set_state(conn, "week_start", start.isoformat())
        db.set_state(conn, "clock", opening)
        db.set_state(conn, "clock_mode", "demo")
        db.set_state(conn, "reset_at", datetime.now().isoformat(timespec="seconds"))
        db.log(conn, opening, "engine", "reset", detail=f"week of {start.isoformat()}")
    conn.close()
    return start
