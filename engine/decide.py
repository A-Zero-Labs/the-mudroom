"""What a person does on a card: approve, decline, send back, or take a heads-up as read.

This is the only place a proposal's work turns into rows in tasks, events, commitments and
people, or into a sent reply, and it only happens after a yes on the card. Every effect
lands in the actions log, one row each, and the yes itself is logged as the person's. A
reply or a forward is not reversible once sent, so those rows say so; the rest can be undone.

Sending back is the other kind of no: the words go with the proposal, and the next run
judges the item again with them in hand. Declining needs no words and ends it.
"""
import json

from . import db, intake, lock, rules
from .process import lookup, next_id, upsert_person


class Refused(Exception):
    """A press the engine will not carry out, with the reason."""


def _clear(conn):
    """No press lands in the middle of a run: between intake and processing the tables are
    being judged, and a yes on a card would cross the judgement."""
    if lock.held(conn):
        raise Refused("A run is in flight. Try again in a minute, once the door has been judged.")


def _proposal(conn, pid, wanted=("pending",)):
    _clear(conn)
    row = conn.execute(
        "SELECT p.*, i.source, i.sender, i.subject, i.received_at, i.thread "
        "FROM proposals p JOIN items i ON i.id = p.item_id WHERE p.id = ?", (pid,)).fetchone()
    if row is None:
        raise Refused(f"No card called {pid}.")
    if row["status"] not in wanted:
        raise Refused(f"{pid} is {row['status']}, so nothing more can be done with it.")
    return row


def _you(conn):
    return (db.get_state(conn, "you", "you") or "you").lower()


def approve(conn, pid, now, by=None):
    """Carry out the work on a ready card, or file the original of a filed card. Returns the
    sentence the page shows for what happened. `by` names a house rule that said "on its
    own", in which case the yes is the rule's and the log says so."""
    p = _proposal(conn, pid) if by is None else conn.execute(
        "SELECT p.*, i.source, i.sender, i.subject, i.received_at, i.thread "
        "FROM proposals p JOIN items i ON i.id = p.item_id WHERE p.id = ?", (pid,)).fetchone()
    if p["outcome"] not in ("ready", "filed"):
        raise Refused(f"{pid} is {p['outcome']}, and only ready and filed cards take a yes.")
    done = []
    with conn:
        if p["outcome"] == "filed":
            conn.execute("UPDATE items SET status = 'filed' WHERE id = ?", (p["item_id"],))
            db.log(conn, now, "engine", "file", target=p["item_id"])
            done.append("the original filed away")
        for w in json.loads(p["work"] or "[]"):
            done.append(EFFECTS[w["kind"]](conn, p, w, now))
        conn.execute("UPDATE proposals SET status = 'approved', decided_at = ? WHERE id = ?", (now, pid))
        invite = p["source"] == "calendar" and p["outcome"] == "ready"
        sentence = ("Filed: " if p["outcome"] == "filed" else "Accepted: " if invite else "Approved: ") + "; ".join(done) + "."
        if by:
            sentence = f"On its own, under {by}: " + sentence[0].lower() + sentence[1:]
            db.log(conn, now, "rule", "approve", target=pid, detail=sentence)
        else:
            # accepting an invitation is an answer to its sender, which a real source skill sends
            db.log(conn, now, _you(conn), "accept" if invite else "approve", target=pid, detail=sentence)
    return sentence


def decline(conn, pid, now):
    """Ignore this, do nothing with it. Needs no words."""
    p = _proposal(conn, pid)
    invite = p["source"] == "calendar" and p["outcome"] == "ready"
    with conn:
        conn.execute("UPDATE proposals SET status = 'declined', decided_at = ? WHERE id = ?", (now, pid))
        sentence = (f"Declined the invitation: {p['subject']}, the diary stays as it is." if invite
                    else f"Declined: {p['subject'] or p['sender']}, nothing done.")
        db.log(conn, now, _you(conn), "decline", target=pid, detail=sentence)
    return sentence


def send_back(conn, pid, words, now):
    """Here is more, judge it again. The words stay with the proposal; the next run judges
    the item again with them in hand."""
    words = (words or "").strip()
    if not words:
        raise Refused("Sending back needs a few words on what to change.")
    p = _proposal(conn, pid)
    with conn:
        conn.execute("UPDATE proposals SET status = 'sent_back', sent_back = ?, decided_at = ? WHERE id = ?",
                     (words, now, pid))
        sentence = f"Sent back: {p['subject'] or p['sender']}, to be judged again with your words."
        db.log(conn, now, _you(conn), "send-back", target=pid, detail=sentence)
    return sentence


def done(conn, pid, now):
    """A heads-up taken as read, or a yours card you handled yourself. On a yours card the
    question closes with nothing to fold in."""
    p = _proposal(conn, pid)
    if p["outcome"] not in ("headsup", "yours"):
        raise Refused(f"{pid} is {p['outcome']}, and only a heads-up or a yours card is taken as done.")
    with conn:
        conn.execute("UPDATE proposals SET status = 'done', decided_at = ? WHERE id = ?", (now, pid))
        _close_question(conn, p)
        sentence = (f"Noted: {p['subject'] or p['sender']}." if p["outcome"] == "headsup"
                    else f"Done: {p['subject'] or p['sender']}, handled by you.")
        db.log(conn, now, _you(conn), "done", target=pid, detail=sentence)
    return sentence


def ignore(conn, pid, now):
    """Ignore this, on a yours card. The question closes with nothing to fold in, and one
    ignore teaches nothing: a rule takes more than one no."""
    p = _proposal(conn, pid)
    if p["outcome"] != "yours":
        raise Refused(f"{pid} is {p['outcome']}, and only a yours card is ignored.")
    with conn:
        conn.execute("UPDATE proposals SET status = 'declined', decided_at = ? WHERE id = ?", (now, pid))
        _close_question(conn, p)
        sentence = f"Ignored: {p['subject'] or p['sender']}, nothing done."
        db.log(conn, now, _you(conn), "ignore", target=pid, detail=sentence)
    return sentence


def answer(conn, pid, text, now):
    """The answer to the question a yours card asks. It goes on the question, and the next
    run folds it in and judges the item again with it in hand."""
    text = (text or "").strip()
    if not text:
        raise Refused("An answer needs a few words.")
    p = _proposal(conn, pid)
    if p["outcome"] != "yours" or not p["question_id"]:
        raise Refused(f"{pid} asks no question.")
    with conn:
        conn.execute(
            "UPDATE questions SET status = 'answered', answer = ?, answered_on = ? WHERE id = ? AND status = 'open'",
            (text, now, p["question_id"]))
        conn.execute("UPDATE proposals SET status = 'answered', decided_at = ? WHERE id = ?", (now, pid))
        sentence = f"Answered: {p['subject'] or p['sender']}, folded in on the next run."
        db.log(conn, now, _you(conn), "answer", target=p["question_id"], detail=sentence)
    return sentence


def close_promise(conn, cid, how, now):
    """A promise resolved by hand from the panel, whether it was kept or no longer matters.
    The door would otherwise wait for something to arrive that settles it."""
    if how != "resolved":
        raise Refused("A promise is resolved, nothing else.")
    _clear(conn)
    c = conn.execute("SELECT * FROM commitments WHERE id = ? AND status = 'open'", (cid,)).fetchone()
    if c is None:
        raise Refused(f"No open promise called {cid}.")
    with conn:
        conn.execute("UPDATE commitments SET status = 'closed', closed_by = 'you', closed_on = ? WHERE id = ?",
                     (now, cid))
        sentence = f"Resolved: {c['what']}."
        db.log(conn, now, _you(conn), "promise-resolved", target=f"commitment:{cid}", detail=sentence)
    return sentence


def answer_question(conn, qid, text, now):
    """An answer to a question that has no card of its own, from the panel. The next run folds
    it in."""
    text = (text or "").strip()
    if not text:
        raise Refused("An answer needs a few words.")
    _clear(conn)
    q = conn.execute("SELECT * FROM questions WHERE id = ? AND status = 'open'", (qid,)).fetchone()
    if q is None:
        raise Refused(f"No open question called {qid}.")
    with conn:
        conn.execute("UPDATE questions SET status = 'answered', answer = ?, answered_on = ? WHERE id = ?",
                     (text, now, qid))
        if q["item_id"]:
            conn.execute("UPDATE proposals SET status = 'answered', decided_at = ? WHERE question_id = ? AND status = 'pending'",
                         (now, qid))
        sentence = f"Answered: {q['question'][:60]}{'…' if len(q['question']) > 60 else ''}"
        db.log(conn, now, _you(conn), "answer", target=qid, detail=sentence)
    return sentence


def choose(conn, pid, picks, now):
    """The subset picked on a choose card. Each pick becomes a task, when it is yours, or a
    loop held, when someone else took it on. Nothing picked is an ignore."""
    p = _proposal(conn, pid)
    work = json.loads(p["work"] or "[]")
    if p["outcome"] != "yours" or not work or work[0]["kind"] != "choose":
        raise Refused(f"{pid} is not a card to pick from.")
    cands = work[0]["candidates"]
    try:
        chosen = sorted({int(i) for i in picks})
    except (TypeError, ValueError):
        raise Refused("A pick names a candidate by its number.")
    if any(i < 0 or i >= len(cands) for i in chosen):
        raise Refused("A pick is not on the card.")
    if not chosen:
        return ignore(conn, pid, now)
    done_ = []
    with conn:
        for i in chosen:
            c = cands[i]
            if c["owner"] == "me":
                done_.append(_task(conn, p, {"title": c["what"], "domain": "work", "due": c.get("due")}, now))
            else:
                done_.append(_commitment(conn, p, {"owner": "them", "person": c.get("person"),
                                                   "what": c["what"], "due": c.get("due")}, now))
        conn.execute("UPDATE proposals SET status = 'approved', decided_at = ? WHERE id = ?", (now, pid))
        sentence = "Picked: " + "; ".join(done_) + "."
        db.log(conn, now, _you(conn), "choose", target=pid, detail=sentence)
    return sentence


def tick(conn, tid, now):
    """A task done, from the planner. Reversible: untick puts it back."""
    return _tick(conn, tid, now, "done")


def untick(conn, tid, now):
    return _tick(conn, tid, now, "open")


def _tick(conn, tid, now, to):
    _clear(conn)
    row = conn.execute("SELECT id, title, status FROM tasks WHERE id = ?", (tid,)).fetchone()
    if row is None:
        raise Refused(f"No task called {tid}.")
    if row["status"] == to:
        raise Refused(f"{row['title']} is already {to}.")
    with conn:
        conn.execute("UPDATE tasks SET status = ?, done_at = ? WHERE id = ?",
                     (to, now if to == "done" else None, tid))
        sentence = f"{'Done' if to == 'done' else 'Back on the list'}: {row['title']}."
        db.log(conn, now, _you(conn), "tick" if to == "done" else "untick", target=f"task:{tid}", detail=sentence)
    return sentence


def leave_note(conn, text, now):
    """A new thought, typed on the Sorting dashboard. It goes to the door through intake as a note to
    self, like a capture from any source, and the next run judges it. Nothing is judged now."""
    text = (text or "").strip()
    if not text:
        raise Refused("A note needs a few words.")
    _clear(conn)
    nid = next_id(conn, "items", "note")
    intake.register(conn, {
        "source": "capture", "account": "dashboard", "label": "a note from the Sorting dashboard",
        "items": [{"id": nid, "source": "capture", "sender": db.get_state(conn, "you", "you"),
                   "body": text, "received_at": now, "raw": {"from": "dashboard"}}],
    }, run=False)
    with conn:
        db.log(conn, now, _you(conn), "note", target=nid, detail=f"Noted: {text[:60]}{'…' if len(text) > 60 else ''}")
    return nid


# ---- from now on: the big loop. One click on a card teaches the door a rule. ----

CHOICES = {
    "file": ("filed", "File mail from {sender} without asking"),
    "headsup": ("headsup", "Just show me mail from {sender}, draft nothing"),
    "skip": (None, "Never read {sender} again"),
}


def from_now_on(conn, pid, choice, now):
    """A rule taught from a card. file and headsup become a house rule on the sender, and the
    card is reshaped by it on the spot. skip marks the sender in source_senders so intake
    never reads them again, and this card is filed. Every rule records the card that taught it."""
    if choice not in CHOICES:
        raise Refused("That is not one of the choices.")
    p = _proposal(conn, pid, wanted=("pending", "approved", "declined", "done"))
    if not p["sender"] or p["sender"] == db.get_state(conn, "you", ""):
        raise Refused("A rule is about a sender, and this has none.")
    outcome, action = CHOICES[choice]
    action = action.format(sender=p["sender"])
    with conn:
        if choice == "skip":
            conn.execute(
                "INSERT OR REPLACE INTO source_senders (sender, source, disposition, person_id, taught_by, taught_on, note) "
                "VALUES (?, ?, 'skip', (SELECT person_id FROM source_senders WHERE source = ? AND sender = ?), ?, ?, ?)",
                (p["sender"], p["source"], p["source"], p["sender"], pid, now, "never read again, from the card"))
            if p["status"] == "pending":
                conn.execute("UPDATE proposals SET outcome = 'filed', work = '[]', question_id = NULL WHERE id = ?", (pid,))
                _close_question(conn, p)
            db.log(conn, now, _you(conn), "rule", target=f"sender:{p['sender']}", detail=f"From now on: {action}.")
            return action
        existing = conn.execute(
            "SELECT id FROM handling_rules WHERE status = 'active' AND scope = 'sender' AND lower(pattern) = lower(?)",
            (p["sender"],)).fetchone()
        if existing:
            conn.execute("UPDATE handling_rules SET status = 'retired', retired_on = ? WHERE id = ?", (now, existing["id"]))
        rid = next_id(conn, "handling_rules", "rule")
        conn.execute(
            "INSERT INTO handling_rules (id, scope, pattern, action, outcome, status, taught_by, taught_on, fired) "
            "VALUES (?, 'sender', ?, ?, ?, 'active', ?, ?, 0)",
            (rid, p["sender"], action, outcome, pid, now))
        if p["status"] == "pending":
            conn.execute(
                "UPDATE proposals SET outcome = ?, work = '[]', question_id = NULL, rule_id = ? WHERE id = ?",
                (outcome, rid, pid))
            _close_question(conn, p)
            rules.fired(conn, conn.execute("SELECT * FROM handling_rules WHERE id = ?", (rid,)).fetchone(), p["item_id"], now)
        db.log(conn, now, _you(conn), "rule", target=rid, detail=f"From now on: {action}.")
    return action


def retire_rule(conn, rid, now):
    row = conn.execute("SELECT * FROM handling_rules WHERE id = ? AND status = 'active'", (rid,)).fetchone()
    if row is None:
        raise Refused(f"No active rule called {rid}.")
    _clear(conn)
    with conn:
        conn.execute("UPDATE handling_rules SET status = 'retired', retired_on = ? WHERE id = ?", (now, rid))
        db.log(conn, now, _you(conn), "unrule", target=rid, detail=f"No longer: {row['action']}.")
    return row["action"]


def read_again(conn, source, sender, now):
    row = conn.execute("SELECT * FROM source_senders WHERE source = ? AND sender = ? AND disposition = 'skip'",
                       (source, sender)).fetchone()
    if row is None:
        raise Refused(f"{sender} is not skipped.")
    _clear(conn)
    with conn:
        conn.execute("UPDATE source_senders SET disposition = 'normal', taught_by = 'the panel', taught_on = ?, "
                     "note = 'read again, from the panel' WHERE source = ? AND sender = ?", (now, source, sender))
        db.log(conn, now, _you(conn), "unrule", target=f"sender:{sender}", detail=f"Read again: {sender}.")
    return sender


def _close_question(conn, p):
    if p["question_id"]:
        conn.execute("UPDATE questions SET status = 'closed' WHERE id = ? AND status = 'open'", (p["question_id"],))


def done_all(conn, now):
    """Every heads-up taken as read at once."""
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM proposals WHERE status = 'pending' AND outcome = 'headsup' ORDER BY id")]
    for pid in ids:
        done(conn, pid, now)
    return f"Noted {len(ids)}."


def file_all(conn, now):
    """Every filed card at once. The one group press: on a real mailbox most of what arrives
    is filing, and a yes per card would be worse than not having the feature."""
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM proposals WHERE status = 'pending' AND outcome = 'filed' ORDER BY id")]
    for pid in ids:
        approve(conn, pid, now)
    return f"Filed {len(ids)} away."


# ---- the effects, one per kind of work. Each returns a few words for the log sentence. ----

def _task(conn, p, w, now):
    tid = next_id(conn, "tasks", "task")
    conn.execute(
        "INSERT INTO tasks (id, title, domain, priority, due, status, notes, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        (tid, w["title"], w["domain"], w.get("priority", 2), w.get("due"), w.get("notes"), p["item_id"], now))
    db.log(conn, now, "engine", "task", target=tid, detail=json.dumps(w, ensure_ascii=False))
    return f"task added, {w['title']}"


def _event(conn, p, w, now):
    eid = next_id(conn, "events", "event")
    conn.execute(
        "INSERT INTO events (id, calendar_id, title, start, end, notes, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (eid, w["calendar"], w["title"], w["start"], w["end"], w.get("notes"), p["item_id"], now))
    db.log(conn, now, "engine", "event", target=eid, detail=json.dumps(w, ensure_ascii=False))
    return f"in the diary, {w['title']}"


def _reply(conn, p, w, now):
    """Inside the demo a reply is sent by recording it: who it went to, through which item,
    and the words. A real source skill does the sending; this row is what it works from."""
    _out(conn, lookup(conn, p["source"], p["sender"]), p["item_id"], now)
    subject = p["subject"] and (p["subject"] if p["subject"].lower().startswith("re:") else f"Re: {p['subject']}")
    sid = intake.sent(conn, p["source"], p["item_id"], p["thread"], p["sender"], subject, w["body"], now)
    db.log(conn, now, "engine", "send", target=sid, reversible=False,
           detail=json.dumps({"to": p["sender"], "source": p["source"], "body": w["body"],
                              "answers": p["item_id"]}, ensure_ascii=False))
    return f"reply sent to {p['sender']}"


def _forward(conn, p, w, now):
    name = conn.execute("SELECT name FROM people WHERE id = ?", (w["to"],)).fetchone()
    who = name["name"] if name else w["to"]
    _out(conn, w["to"], p["item_id"], now)
    subject = p["subject"] and (p["subject"] if p["subject"].lower().startswith("fwd:") else f"Fwd: {p['subject']}")
    sid = intake.sent(conn, p["source"], p["item_id"], p["thread"], who, subject, w.get("note") or "", now,
                      raw={"forwarded": p["item_id"]})
    db.log(conn, now, "engine", "forward", target=sid, reversible=False,
           detail=json.dumps({"to": w["to"], "note": w.get("note"), "forwards": p["item_id"]}, ensure_ascii=False))
    return f"passed on to {who}"


def _email(conn, p, w, now):
    """A fresh email, outside any thread: its copy sits beneath the item that asked for it."""
    name = conn.execute("SELECT name FROM people WHERE id = ?", (w["to"],)).fetchone()
    who = name["name"] if name else w["to"]
    _out(conn, w["to"], p["item_id"], now)
    sid = intake.sent(conn, "email", p["item_id"], p["thread"], who, w["subject"], w["body"], now, raw={"fresh": True})
    db.log(conn, now, "engine", "send", target=sid, reversible=False,
           detail=json.dumps({"to": w["to"], "subject": w["subject"], "body": w["body"]}, ensure_ascii=False))
    return f"email sent to {who}"


def _rule(conn, p, w, now):
    """A rule the person asked for in their own words, written where the judgement said it
    lives: skip goes in source_senders, so intake never reads the sender; the rest go in
    handling_rules, and a rule already active on the same thing is retired first."""
    if w["outcome"] == "skip":
        conn.execute(
            "INSERT OR REPLACE INTO source_senders (sender, source, disposition, person_id, taught_by, taught_on, note) "
            "VALUES (?, ?, 'skip', (SELECT person_id FROM source_senders WHERE source = ? AND sender = ?), ?, ?, ?)",
            (w["pattern"], w["source"], w["source"], w["pattern"], p["id"], now, w["action"]))
        db.log(conn, now, "engine", "rule", target=f"sender:{w['pattern']}", detail=w["action"])
        return f"from now on, {w['action']}"
    existing = conn.execute(
        "SELECT id FROM handling_rules WHERE status = 'active' AND scope = ? AND lower(pattern) = lower(?)",
        (w["scope"], w["pattern"])).fetchone()
    if existing:
        conn.execute("UPDATE handling_rules SET status = 'retired', retired_on = ? WHERE id = ?", (now, existing["id"]))
    rid = next_id(conn, "handling_rules", "rule")
    conn.execute(
        "INSERT INTO handling_rules (id, scope, pattern, action, outcome, status, taught_by, taught_on, fired) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0)",
        (rid, w["scope"], w["pattern"], w["action"], w["outcome"], p["id"], now))
    db.log(conn, now, "engine", "rule", target=rid, detail=w["action"])
    return f"from now on, {w['action']}"


TABLES = {"task": "tasks", "event": "events", "commitment": "commitments", "question": "questions"}
TITLE = {"task": "title", "event": "title", "commitment": "what", "question": "question"}


def _update(conn, p, w, now):
    kind, _, ident = w["target"].partition(":")
    table = TABLES[kind]
    before = dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (ident,)).fetchone())
    changes = dict(w["changes"])
    if kind == "commitment" and changes.get("status") == "closed":
        changes.update(closed_by=p["item_id"], closed_on=now)
    if kind == "task" and changes.get("status") == "done":
        changes["done_at"] = now
    sets = ", ".join(f"{field} = ?" for field in changes)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*changes.values(), ident))
    db.log(conn, now, "engine", "update", target=w["target"],
           detail=json.dumps({"changes": changes, "before": {f: before.get(f) for f in changes}},
                             ensure_ascii=False))
    title = before.get(TITLE[kind])
    if kind == "commitment" and changes.get("status") == "closed":
        return f"promise kept, {title}"
    if kind == "question":
        return f"the question closed, {title}"
    return f"the {kind} changed, {title}"


def _commitment(conn, p, w, now):
    cid = next_id(conn, "commitments", "commitment")
    conn.execute(
        "INSERT INTO commitments (id, owner, person_id, what, promised_on, due, status, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
        (cid, w["owner"], w["person"], w["what"], p["received_at"], w.get("due"), p["item_id"]))
    db.log(conn, now, "engine", "commitment", target=cid, detail=json.dumps(w, ensure_ascii=False))
    return f"promise noted, {w['what']}"


def _person(conn, p, w, now):
    upsert_person(conn, w)
    db.log(conn, now, "engine", "person", target=w["id"], detail=json.dumps(w, ensure_ascii=False))
    return f"noted about {w.get('name') or w['id']}"


def _out(conn, person, item_id, now):
    if person:
        conn.execute(
            "INSERT OR IGNORE INTO interactions (person_id, item_id, direction, at) VALUES (?, ?, 'out', ?)",
            (person, item_id, now))


EFFECTS = {"task": _task, "event": _event, "reply": _reply, "forward": _forward, "email": _email, "rule": _rule,
           "update": _update, "commitment": _commitment, "person": _person}
