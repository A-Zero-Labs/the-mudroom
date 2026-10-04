"""Start clean: the invented week leaves, and a working engine with no fiction in it stays.

The database is rebuilt from the schema with only what the engine needs to run: the three
calendars, your name, a clock that keeps real time. The folders that held the week go: the
batches and the cast, the persona and the seed, and the demo's source skill. The engine, the
pages, the judging skill and the tests stay. From here, what comes to the door comes from a
source skill of your own; docs/make-it-yours.md says how to write one.

This is the one command that deletes files, so it says what it will remove and does
nothing without a yes.
"""
import shutil
from datetime import datetime

from . import ROOT, clock, db

CALENDARS = [("work", "Work", "#4f7cf0"), ("family", "Family", "#3aa76d"), ("personal", "Personal", "#d9822b")]
FICTION = ("rounds", "world", ".claude/skills/source-demo")
LEFTOVERS = ("handover.json", "handover.refused.json", "handoff.json", "replies.json", "run.log", "source.log",
             "world/mudroom.db")


def what_goes(root=ROOT):
    """The paths start-clean would remove, those that exist."""
    paths = [root / p for p in FICTION] + [root / p for p in LEFTOVERS]
    return [p for p in paths if p.exists()]


def start_clean(you, root=ROOT, today=None):
    """Rebuild the house empty, in your name, and remove the fiction. Returns what was removed."""
    you = (you or "").strip()
    if not you:
        raise ValueError("Start clean needs your name: it is the 'you' the door serves.")
    removed = []
    for path in what_goes(root):
        if not path.exists():
            continue   # inside a folder already removed, such as world/mudroom.db
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path.relative_to(root)))
    now = datetime.now()
    start = clock.week_start(today or now.date())
    conn = db.rebuild()
    with conn:
        conn.executemany("INSERT INTO calendars (id, name, colour, note) VALUES (?, ?, ?, NULL)", CALENDARS)
        db.set_state(conn, "you", you)
        db.set_state(conn, "week_start", start.isoformat())
        db.set_state(conn, "clock", now.isoformat(timespec="minutes"))
        db.set_state(conn, "clock_mode", "real")
        db.set_state(conn, "reset_at", now.isoformat(timespec="seconds"))
        db.log(conn, now.isoformat(timespec="minutes"), "engine", "start-clean",
               detail=f"the house is {you}'s now; removed {', '.join(removed) or 'nothing'}")
    conn.close()
    return removed
