"""The Intake Engine: registers what a source fetched, checks the sender list, keeps the bookmark.

A source is a skill that pulls what is new through a connection the person's own Claude
holds, flattens it to the common shape, and hands it here. This is the one door into items,
for the demo's invented week and for a real mailbox alike:

    python mudroom.py intake --bookmark <source> <account>   how far that source got last time
    python mudroom.py intake <file>                          register what it fetched, - for stdin

The handoff is one JSON object: source, account, the new cursor and last_seen_id, an optional
now for the demo's clock, an optional label, and items in the common shape. Every item is
registered, and one that is already known is updated in place. An item from a sender marked
skip is marked skipped without being read, and the decision log says so. Only once everything is in
does the bookmark move, so nothing is lost if intake fails halfway. docs/make-it-yours.md,
Writing a source skill, says what a source does before it gets here.
"""
import json
import sys
from pathlib import Path

from . import clock, db, lock

SOURCES = ("email", "chat", "transcript", "capture", "calendar")
ITEM_FIELDS = ("id", "source", "sender", "subject", "body", "received_at", "thread", "raw")


class Refused(Exception):
    """The handoff was not accepted. Nothing was written."""

    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


def bookmark(conn, source, account):
    """How far a source got last time, plus the week and the clock a demo source needs."""
    out = {"source": source, "account": account, "cursor": None, "last_seen_id": None, "checked_at": None}
    row = conn.execute(
        "SELECT cursor, last_seen_id, checked_at FROM source_state WHERE source = ? AND account = ?",
        (source, account)).fetchone()
    if row:
        out.update(dict(row))
    out["week_start"] = db.get_state(conn, "week_start")
    out["clock"] = db.get_state(conn, "clock")
    return out


def check(handoff):
    problems = []
    if not isinstance(handoff, dict):
        return ["the handoff must be a JSON object"]
    for k in ("source", "account"):
        if not isinstance(handoff.get(k), str) or not handoff[k]:
            problems.append(f"needs {k}")
    for k in ("now", "cursor", "last_seen_id", "label"):
        if handoff.get(k) is not None and not isinstance(handoff[k], str):
            problems.append(f"{k} must be text")
    items = handoff.get("items")
    if not isinstance(items, list):
        problems.append("items must be a list")
        items = []
    for n, it in enumerate(items):
        where = f"items[{n}]"
        if not isinstance(it, dict):
            problems.append(f"{where}: must be an object")
            continue
        extra = sorted(set(it) - set(ITEM_FIELDS))
        if extra:
            problems.append(f"{where}: unknown field(s) {extra}")
        if not isinstance(it.get("id"), str) or not it["id"]:
            problems.append(f"{where}: needs an id")
        if it.get("source") not in SOURCES:
            problems.append(f"{where}: source must be one of {', '.join(SOURCES)}")
        if not it.get("received_at"):
            problems.append(f"{where}: needs received_at")
        if it.get("raw") is not None and not isinstance(it["raw"], dict):
            problems.append(f"{where}: raw must be an object")
    ids = [it.get("id") for it in items if isinstance(it, dict)]
    if len(set(ids)) != len(ids):
        problems.append("an item id appears twice")
    return problems


def sent(conn, source, item_id, thread, to, subject, body, now, raw=None):
    """The copy of what you sent through the mudroom, recorded in items beside what came in,
    so the Doorstep reads as the inbox it stands for. Status sent: it is not at the door,
    because the judgement that drafted it already proposed everything it implies, and a
    reply you send from elsewhere still arrives through its source like any other item."""
    from .process import next_id
    sid = next_id(conn, "items", "sent")
    heads = {"to": to, "at": now[11:16], **(raw or {})}
    conn.execute(
        "INSERT INTO items (id, source, sender, subject, body, received_at, staged_at, thread, raw, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'sent')",
        (sid, source, db.get_state(conn, "you", "you"), subject, body, now, now,
         thread or item_id, json.dumps(heads, ensure_ascii=False)))
    return sid


def register(conn, handoff, run=True):
    """Register a source's handoff in one transaction. Returns the counts. A source's fetch
    starts a run, held until processing; a note dropped at the door does not, it waits for
    the next run like anything else there."""
    problems = check(handoff)
    if problems:
        raise Refused(problems)
    counts = {"staged": 0, "skipped": 0, "updated": 0}
    with conn:
        if handoff.get("now") and db.get_state(conn, "clock_mode", "demo") == "demo":
            db.set_state(conn, "clock", handoff["now"])
        now = clock.now(conn)
        if run:
            # One batch per run: what is at the door is judged before more comes in, so a
            # source that fetched twice in one run is stopped here, not in its prompt.
            if lock.held(conn) and lock.intakes(conn) >= 1:
                raise Refused(["one batch per run: what is at the door is judged before more comes in"])
            if not lock.held(conn):
                lock.begin(conn)
            db.set_state(conn, "run_intakes", lock.intakes(conn) + 1)
        for it in handoff["items"]:
            raw = json.dumps(it.get("raw") or {}, ensure_ascii=False)
            if conn.execute("SELECT 1 FROM items WHERE id = ?", (it["id"],)).fetchone():
                conn.execute(
                    "UPDATE items SET sender = ?, subject = ?, body = ?, received_at = ?, thread = ?, raw = ? "
                    "WHERE id = ?",
                    (it.get("sender"), it.get("subject"), it.get("body"), it["received_at"],
                     it.get("thread"), raw, it["id"]))
                counts["updated"] += 1
                continue
            skip = conn.execute(
                "SELECT 1 FROM source_senders WHERE source = ? AND sender = ? AND disposition = 'skip'",
                (it["source"], it.get("sender"))).fetchone() is not None
            conn.execute(
                "INSERT INTO items (id, source, sender, subject, body, received_at, staged_at, thread, raw, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (it["id"], it["source"], it.get("sender"), it.get("subject"), it.get("body"),
                 it["received_at"], now, it.get("thread"), raw, "skipped" if skip else "staged"))
            if skip:
                conn.execute(
                    "INSERT INTO decision_log (at, actor, item_id, decision, reason) "
                    "VALUES (?, 'intake', ?, 'skipped', 'sender marked skip in source_senders')",
                    (now, it["id"]))
                counts["skipped"] += 1
            else:
                counts["staged"] += 1
        conn.execute(
            "INSERT OR REPLACE INTO source_state (source, account, cursor, last_seen_id, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (handoff["source"], handoff["account"], handoff.get("cursor"), handoff.get("last_seen_id"), now))
        db.log(conn, now, "engine", "intake", target=f"{handoff['source']}:{handoff['account']}",
               detail=json.dumps({"label": handoff.get("label"), **counts}))
    counts["now"] = now
    counts["label"] = handoff.get("label")
    return counts


def summary(result):
    n, s, u = result["staged"], result["skipped"], result["updated"]
    parts = [f"{n} item{'s' if n != 1 else ''} at the door"]
    if s:
        parts.append(f"{s} skipped")
    if u:
        parts.append(f"{u} already known")
    head = result["label"] or "Intake"
    when = clock.clock_label(clock.as_datetime(result["now"]))
    return (f"{head}: {', '.join(parts)}. Clock: {when}.\n"
            "Not judged yet. Open the Doorstep to read what came in, or run learn-evaluate.")


def run(path):
    """The command. Returns the exit code."""
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        handoff = json.loads(text)
    except (OSError, ValueError) as e:
        print(f"Could not read the handoff: {e}")
        return 1
    conn = db.connect()
    try:
        try:
            result = register(conn, handoff)
        except Refused as r:
            n = len(r.problems)
            print(f"Refused, nothing registered. {n} problem{'s' if n != 1 else ''}:")
            for p in r.problems:
                print(f"  {p}")
            return 1
        print(summary(result))
    finally:
        conn.close()
    return 0
