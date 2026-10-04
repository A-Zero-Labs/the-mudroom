"""The run lock: one run at a time between intake and processing.

A run begins when intake registers what is new and ends when processing has written the
judgement. Between the two, anything that would write from a page defers, so an approval
cannot land in the middle of a half-finished run. The lock keeps wall-clock time, since the
engine's own clock stands still during a run. A lock older than STALE_MINUTES belongs to a
run that died, and it is ignored, so a dead run can never wedge the pages.
"""
from datetime import datetime, timedelta
from uuid import uuid4

STALE_MINUTES = 10


def begin(conn):
    """Mark a run in flight. Replaces any lock already there, and the run has brought nothing
    in yet."""
    conn.execute("DELETE FROM run_lock")
    conn.execute("INSERT INTO run_lock (token, started_at) VALUES (?, ?)",
                 (uuid4().hex, datetime.now().isoformat(timespec="seconds")))
    conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('run_intakes', '0')")


def end(conn):
    conn.execute("DELETE FROM run_lock")
    conn.execute("DELETE FROM state WHERE key = 'run_intakes'")


def intakes(conn):
    """How many batches the run in flight has brought in. One is the most a run may."""
    row = conn.execute("SELECT value FROM state WHERE key = 'run_intakes'").fetchone()
    return int(row[0]) if row else 0


def held(conn):
    """When the run in flight began, or None. A stale lock counts as none."""
    row = conn.execute("SELECT started_at FROM run_lock").fetchone()
    if row is None:
        return None
    started = datetime.fromisoformat(row[0])
    if datetime.now() - started > timedelta(minutes=STALE_MINUTES):
        return None
    return started
