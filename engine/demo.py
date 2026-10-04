"""Demo scaffolding: what the Doorstep's two buttons do.

Bring the next batch of the invented week in, through the same intake a source skill uses,
and start the week again from the seed. This module, the Doorstep and rounds/ leave together
when the demo data does.
"""
import importlib.util

import json
import threading

from . import ROOT, agents, clock, db, intake, lock, seed

ROUNDS = ROOT / "rounds"


def present():
    """Whether the invented week is still here. After start-clean it is not, and every
    button of the demo's goes quiet."""
    return (ROUNDS / "source.py").exists()


def _source():
    spec = importlib.util.spec_from_file_location("demo_source", ROUNDS / "source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source = _source() if present() else None


def upcoming(conn):
    """The next batch file, or None when the week is done or the demo has left."""
    if source is None:
        return None
    mark = intake.bookmark(conn, "rounds", "world")
    return source.next_file(ROUNDS, mark["last_seen_id"])


def title(path):
    return source.parse(path)[0]["title"]


def last_batch(conn):
    """The batch brought in last, or None."""
    if source is None:
        return None
    mark = intake.bookmark(conn, "rounds", "world")
    if not mark["last_seen_id"]:
        return None
    path = ROUNDS / f"{mark['last_seen_id']}.md"
    return path if path.exists() else None


def story(path):
    """The batch's story, one paragraph from its header: what has happened in Alex's life,
    in plain words, for the bar on the Doorstep."""
    return source.parse(path)[0].get("story", "")


def intro(conn):
    """Who you are, from the first batch's header, for the bar before anything has arrived."""
    first = source.next_file(ROUNDS, None) if source else None
    return source.parse(first)[0].get("intro", "") if first else ""


def anything_to_answer(conn):
    """Whether the person sent anything since the last batch: if not, the cast has nothing
    to say and the batch can come in through the parser without a Claude run."""
    mark = intake.bookmark(conn, "rounds", "world")
    since = mark["checked_at"] or ""
    sent = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'sent' AND received_at > ?", (since,)).fetchone()[0]
    answered = conn.execute(
        "SELECT COUNT(*) FROM actions WHERE action IN ('accept', 'decline') AND at > ?", (since,)).fetchone()[0]
    return bool(sent or answered)


def slot(conn, path):
    """When the batch plays, on the engine's clock: 'Monday 08:30'."""
    header = source.parse(path)[0]
    start = clock.as_date(db.get_state(conn, "week_start"))
    return clock.clock_label(clock.as_datetime(
        source.stamp(start, int(header.get("day", 0)), header.get("time", "08:30"))))


def next_round():
    """Bring the next batch in. Returns intake's counts, or None when the week is done."""
    conn = db.connect()
    try:
        path = upcoming(conn)
        if path is None:
            return None
        start = clock.as_date(db.get_state(conn, "week_start"))
        return intake.register(conn, source.handoff(path, start))
    finally:
        conn.close()


def run(wait=False):
    """The whole pass on demand: the source skill plays the cast and brings the next batch
    in, then the agents judge, then processing, which the judging skill calls. Returns
    (ok, message) when wait is set, True when started in the background, and False when a
    run is already in flight, in which case nothing is started. Without a Claude, the
    batch still comes in through the parser, so the Doorstep has something to show."""
    conn = db.connect()
    try:
        if lock.held(conn):
            return False
        if agents.executable() is None:
            next_round()
            return agents.judge(owned=True)
        with conn:
            lock.begin(conn)
            db.set_state(conn, "last_run", json.dumps({"at": agents.stamp(), "ok": None, "message": "in flight"}))
    finally:
        conn.close()
    if wait:
        return whole_pass()
    threading.Thread(target=whole_pass, daemon=True).start()
    return True


def whole_pass():
    conn = db.connect()
    try:
        answer = anything_to_answer(conn)
        phase(conn, "the people are writing back" if answer else "bringing the post in")
    finally:
        conn.close()
    if answer:
        ok, message = agents.source()
        if not ok:
            return ok, message
    else:
        next_round()   # nothing for the cast to answer: the parser alone, no Claude run
    conn = db.connect()
    try:
        lock.begin(conn)   # intake set it; a source that brought nothing did not, and the judge owns it now
        phase(conn, "sorting what came in")
        conn.commit()
    finally:
        conn.close()
    return agents.judge(owned=True)


def phase(conn, what):
    """What the run is doing right now, for the bar while it works."""
    db.set_state(conn, "last_run", json.dumps({"at": agents.stamp(), "ok": None, "message": what}))


def start_over():
    """A clean sheet: the seed restored, the clock rewound, any file a run left behind gone.
    Returns the week's Monday."""
    for name in ("handover.json", "handover.refused.json", "handoff.json", "replies.json"):
        leftover = ROOT / name
        if leftover.exists():
            leftover.unlink()
    return seed.reset()
