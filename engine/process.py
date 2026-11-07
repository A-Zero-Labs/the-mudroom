"""Processing: the only way judgement enters the database.

The model writes one file, handover.json, and this is the one piece of code that reads it.
It checks the file against what actually arrived and against the closed lists in the engine,
then writes everything it accepts in a single transaction: a proposal per item carrying its
work, the question a yours item raises, one decision log row per decision, the interactions the
items show, and the items marked judged. If one part is wrong, none of it is written, the
file stays where it is, and every problem is reported. The learn-evaluate skill carries the
contract this enforces. Tasks, events and commitments are written later, when a card is approved.
"""
import json
from datetime import date
from pathlib import Path

from . import CLASSES, KINDS, OUTCOMES, ROOT, clock, db, lock, rules

HANDOVER = ROOT / "handover.json"
KEYS = ("consumed", "people", "senders", "seen", "items")
DOMAINS = ("work", "family", "personal")
SOURCES = ("email", "chat", "transcript", "capture", "calendar")
DISPOSITIONS = ("skip", "watch", "normal")
OWNERS = ("me", "them")
READY = ("task", "event", "reply", "forward", "email", "update", "commitment", "person", "rule")
SCOPES = ("sender", "domain", "subject")
RULE_OUTCOMES = ("skip", "filed", "headsup", "ready", "yours", "auto")
# auto: the one way the door acts without a yes. A matching item is judged as usual, and if the
# judgement makes it ready, processing approves the card itself, logged as the rule's doing.
# No rule ships with auto; a person asks for it in words, and says yes to the rule once.
YOURS = ("question", "choose")
PERSON_FIELDS = ("name", "pronouns", "domain", "role", "trait")
SUBJECT_KINDS = ("person", "sender", "task", "event", "commitment", "item")
TABLES = {"task": "tasks", "event": "events", "commitment": "commitments", "question": "questions"}
CHANGES = {"task": ("title", "due", "priority", "status", "notes"),
           "event": ("title", "start", "end", "notes"),
           "commitment": ("status", "due", "what"),
           "question": ("status",)}   # closed: the item settled it without an answer to fold in
STATUSES = {"task": ("open", "done"), "commitment": ("open", "closed"), "question": ("closed",)}
FIELDS = {  # what each kind of work may carry besides its kind
    "task": ("title", "domain", "priority", "due", "notes"),
    "event": ("title", "calendar", "start", "end", "minutes", "notes"),
    "reply": ("body", "by"),
    "forward": ("to", "note"),
    "email": ("to", "subject", "body"),
    "rule": ("scope", "pattern", "outcome", "action", "source"),
    "update": ("target", "changes"),
    "commitment": ("owner", "person", "what", "due"),
    "person": ("id",) + PERSON_FIELDS,
    "question": ("subject", "question"),
    "choose": ("summary", "candidates"),
}


class Refused(Exception):
    """The file was not accepted. Nothing was written."""

    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def process(conn, data, now):
    """Check a handover against the database and write it. Returns the count per outcome,
    or raises Refused carrying every problem found, with nothing written."""
    plan = Checker(conn, data).run()
    return write(conn, plan, now)


class Checker:
    """Reads the file against the database and builds the plan to write."""

    def __init__(self, conn, data):
        self.conn = conn
        self.data = data
        self.problems = []
        self.start = clock.this_week(conn)
        self.onward = date.today() if clock.real(conn) else None   # a weekday means the coming one
        self.people = {r["id"] for r in conn.execute("SELECT id FROM people")}
        self.new_people = set()
        self.calendars = tuple(r["id"] for r in conn.execute("SELECT id FROM calendars ORDER BY id"))

    def bad(self, where, what):
        self.problems.append(f"{where}: {what}")

    def run(self):
        d = self.data
        if not isinstance(d, dict):
            raise Refused(["file: must be a JSON object with the five keys"])
        extra = sorted(set(d) - set(KEYS))
        missing = [k for k in KEYS if k not in d]
        if extra:
            self.bad("file", f"unknown key(s) {extra}")
        if missing:
            self.bad("file", f"missing key(s) {missing}")
        for k in KEYS:
            if k in d and not isinstance(d[k], list):
                self.bad("file", f"{k} must be a list")
        if self.problems:
            raise Refused(self.problems)
        consumed = self.consumed(d["consumed"])
        plan = {"consumed": consumed, "people": self.people_entries(d["people"]),
                "senders": self.senders(d["senders"]), "items": []}
        reopened = self.seen(d["seen"], d["items"], consumed)
        for entry in d["items"]:
            item = self.item(entry, reopened)
            if item:
                plan["items"].append(item)
        if self.problems:
            raise Refused(self.problems)
        return plan

    # ---- the four small sections ----

    def consumed(self, ids):
        out = []
        for q in ids:
            row = self.conn.execute("SELECT status FROM questions WHERE id = ?", (str(q),)).fetchone()
            if row is None:
                self.bad("consumed", f"{q!r} is not a question")
            elif row["status"] != "answered":
                self.bad("consumed", f"{q} is {row['status']}, not answered")
            elif q in out:
                self.bad("consumed", f"{q} is listed twice")
            else:
                out.append(q)
        return out

    def taught_by(self, where, e):
        if e.get("from") is not None and e["from"] not in self.data["consumed"]:
            self.bad(where, f"from {e['from']!r} is not a consumed question")

    def people_entries(self, entries):
        out = []
        for n, e in enumerate(entries):
            where = f"people[{n}]"
            if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"]:
                self.bad(where, "needs an id")
                continue
            extra = sorted(set(e) - set(("id", "from") + PERSON_FIELDS))
            if extra:
                self.bad(where, f"unknown field(s) {extra}")
            self.taught_by(where, e)
            if e["id"] not in self.people:
                if not (e.get("name") and e.get("domain")):
                    self.bad(where, f"new person {e['id']} needs a name and a domain")
                self.new_people.add(e["id"])
            if e.get("domain") is not None and e["domain"] not in DOMAINS:
                self.bad(where, f"domain must be one of {', '.join(DOMAINS)}")
            out.append(e)
        return out

    def senders(self, entries):
        out = []
        for n, e in enumerate(entries):
            where = f"senders[{n}]"
            if not isinstance(e, dict):
                self.bad(where, "must be an object")
                continue
            extra = sorted(set(e) - {"sender", "source", "disposition", "person", "note", "from"})
            if extra:
                self.bad(where, f"unknown field(s) {extra}")
            if not e.get("sender") or not e.get("source"):
                self.bad(where, "needs sender and source")
            if e.get("source") not in SOURCES:
                self.bad(where, f"source must be one of {', '.join(SOURCES)}")
            if e.get("disposition") not in DISPOSITIONS:
                self.bad(where, f"disposition must be one of {', '.join(DISPOSITIONS)}")
            if e.get("person") is not None and not self.known_person(e["person"]):
                self.bad(where, f"person {e['person']!r} is not a person the engine knows")
            self.taught_by(where, e)
            out.append(e)
        return out

    def seen(self, seen, items, consumed):
        """Every staged item must be seen and have an entry, and so must every item whose card
        was sent back. Nothing else may be, except an item whose question was answered this
        run: that one is judged again."""
        staged = {r["id"] for r in self.conn.execute("SELECT id FROM items WHERE status = 'staged'")}
        back = {r["item_id"] for r in self.conn.execute(
            "SELECT item_id FROM proposals WHERE status = 'sent_back'")}
        reopened = set()
        if consumed:
            marks = ",".join("?" * len(consumed))
            reopened = {r["item_id"] for r in self.conn.execute(
                f"SELECT item_id FROM questions WHERE id IN ({marks}) AND item_id IS NOT NULL", consumed)}
        seen_ids = [str(s) for s in seen]
        if len(set(seen_ids)) != len(seen_ids):
            self.bad("seen", "an id is listed twice")
        seen_set = set(seen_ids)
        for i in sorted(staged - seen_set):
            self.bad("seen", f"{i} is at the door and not in seen")
        for i in sorted(back - seen_set):
            self.bad("seen", f"{i} was sent back and is not in seen")
        for i in sorted(seen_set - staged - back - reopened):
            self.bad("seen", f"{i} was neither staged nor re-opened by an answer, nor sent back")
        entry_ids = [e.get("id") if isinstance(e, dict) else None for e in items]
        if len(set(entry_ids)) != len(entry_ids):
            self.bad("items", "an item has two entries")
        for i in sorted(seen_set - set(entry_ids)):
            self.bad("seen", f"{i} has no entry in items")
        for i in entry_ids:
            if i not in seen_set:
                self.bad("items", f"{i!r} is not in seen")
        return reopened

    # ---- one item ----

    def item(self, entry, reopened):
        if not isinstance(entry, dict):
            self.bad("items", "an entry is not an object")
            return None
        where = entry.get("id") or "an entry without id"
        extra = sorted(set(entry) - {"id", "class", "outcome", "reason", "work"})
        if extra:
            self.bad(where, f"unknown field(s) {extra}")
        if entry.get("class") not in CLASSES:
            self.bad(where, f"class {entry.get('class')!r} is not in the engine's list")
        outcome = entry.get("outcome")
        if outcome not in OUTCOMES:
            self.bad(where, f"outcome {outcome!r} is not one of {', '.join(OUTCOMES)}")
            outcome = None
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            self.bad(where, "needs a reason, in plain words")
        work = entry.get("work")
        if not isinstance(work, list):
            self.bad(where, "work must be a list")
            work = []
        planned = [w for w in (self.work(where, n, w) for n, w in enumerate(work)) if w]
        kinds = [w["kind"] for w in planned]
        rule = rules.match(self.conn, entry.get("id")) if entry.get("id") else None
        if rule and rule["outcome"] in ("ready", "yours") and outcome and outcome != rule["outcome"]:
            # auto asks nothing of the judgement: it only says what happens once the card is ready
            self.bad(where, f"house rule {rule['id']} says {rule['outcome']}: {rule['action']}")
        if outcome == "ready":
            if not kinds:
                self.bad(where, "ready carries at least one piece of work")
            for k in kinds:
                if k not in READY:
                    self.bad(where, f"ready cannot carry {k}")
        elif outcome == "yours":
            if len(kinds) != 1 or kinds[0] not in YOURS:
                self.bad(where, "yours carries exactly one question or choose")
        elif outcome in ("headsup", "filed") and kinds:
            self.bad(where, f"{outcome} carries no work")
        return {"id": entry.get("id"), "class": entry.get("class"), "outcome": outcome,
                "reason": entry.get("reason"), "work": planned, "reopened": entry.get("id") in reopened,
                "rule": rule}

    def work(self, where, n, w):
        loc = f"{where} work[{n}]"
        if not isinstance(w, dict):
            self.bad(loc, "must be an object")
            return None
        kind = w.get("kind")
        if kind not in KINDS:
            self.bad(loc, f"kind {kind!r} is not in the engine's list")
            return None
        extra = sorted(set(w) - set(FIELDS[kind]) - {"kind"})
        if extra:
            note = " (the engine mints ids)" if "id" in extra else ""
            self.bad(loc, f"{kind} cannot carry {extra}{note}")
        out = {"kind": kind}
        getattr(self, "kind_" + kind)(loc, w, out)
        return out

    # ---- helpers ----

    def text(self, where, w, field):
        v = w.get(field)
        if not isinstance(v, str) or not v.strip():
            self.bad(where, f"needs {field}, as text")
            return None
        return v.strip()

    def choice(self, where, w, field, options):
        v = w.get(field)
        if v not in options:
            self.bad(where, f"{field} must be one of {', '.join(options)}")
            return None
        return v

    def when(self, where, value, field, need_time=False):
        if value is None:
            return None
        try:
            return clock.resolve(value, self.start, need_time=need_time, onward=self.onward)
        except ValueError as e:
            self.bad(where, f"{field}: {e}")
            return None

    def known_person(self, pid):
        return pid in self.people or pid in self.new_people

    def exists(self, table, ident):
        return self.conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (ident,)).fetchone() is not None

    # ---- the kinds of work ----

    def kind_task(self, loc, w, out):
        out["title"] = self.text(loc, w, "title")
        out["domain"] = self.choice(loc, w, "domain", DOMAINS)
        out["priority"] = w.get("priority", 2)
        if out["priority"] not in (1, 2, 3):
            self.bad(loc, "priority is 1, 2 or 3")
        out["due"] = self.when(loc, w.get("due"), "due")
        out["notes"] = w.get("notes")

    def kind_event(self, loc, w, out):
        out["title"] = self.text(loc, w, "title")
        out["calendar"] = self.choice(loc, w, "calendar", self.calendars)
        if w.get("start") is None:
            self.bad(loc, "needs a start, with a time")
        out["start"] = self.when(loc, w.get("start"), "start", need_time=True)
        if w.get("end") is not None and w.get("minutes") is not None:
            self.bad(loc, "give end or minutes, one of the two")
        if w.get("end") is not None:
            out["end"] = self.when(loc, w["end"], "end", need_time=True)
        else:
            minutes = w.get("minutes", 60)
            if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
                self.bad(loc, "minutes must be a whole number above zero")
                minutes = 60
            out["end"] = clock.add_minutes(out["start"], minutes) if out["start"] else None
        out["notes"] = w.get("notes")

    def kind_reply(self, loc, w, out):
        out["body"] = self.text(loc, w, "body")
        out["by"] = self.when(loc, w.get("by"), "by")

    def kind_forward(self, loc, w, out):
        out["to"] = w.get("to")
        if not self.known_person(out["to"]):
            self.bad(loc, f"to {out['to']!r} is not a person the engine knows")
        out["note"] = w.get("note")

    def kind_rule(self, loc, w, out):
        """Where a rule lives is the first thing it settles: skip means the sender is never
        read at all, and needs the source; anything else arrives and is handled a set way."""
        out["scope"] = self.choice(loc, w, "scope", SCOPES)
        out["pattern"] = self.text(loc, w, "pattern")
        out["outcome"] = self.choice(loc, w, "outcome", RULE_OUTCOMES)
        out["action"] = self.text(loc, w, "action")
        out["source"] = w.get("source")
        if out["outcome"] == "skip":
            if out["scope"] != "sender":
                self.bad(loc, "skip is only for a sender: a domain or a subject still has to be read to match")
            if out["source"] not in SOURCES:
                self.bad(loc, f"skip needs the source the sender writes on, one of {', '.join(SOURCES)}")

    def kind_email(self, loc, w, out):
        out["to"] = w.get("to")
        if not self.known_person(out["to"]):
            self.bad(loc, f"to {out['to']!r} is not a person the engine knows")
        out["subject"] = self.text(loc, w, "subject")
        out["body"] = self.text(loc, w, "body")

    def kind_update(self, loc, w, out):
        target = str(w.get("target") or "")
        kind, sep, ident = target.partition(":")
        if not sep or kind not in CHANGES or not ident:
            self.bad(loc, f"target {target!r} must be task:id, event:id, commitment:id or question:id")
            return
        if not self.exists(TABLES[kind], ident):
            self.bad(loc, f"target {target!r} does not exist")
        changes = w.get("changes")
        if not isinstance(changes, dict) or not changes:
            self.bad(loc, "changes must name at least one field")
            return
        out["target"] = target
        out["changes"] = {}
        for field, value in changes.items():
            if field not in CHANGES[kind]:
                self.bad(loc, f"a {kind} does not allow changing {field!r}")
                continue
            if field in ("due", "start", "end"):
                value = self.when(loc, value, field, need_time=(kind == "event"))
            elif field == "priority" and value not in (1, 2, 3):
                self.bad(loc, "priority is 1, 2 or 3")
            elif field == "status" and value not in STATUSES[kind]:
                self.bad(loc, f"a {kind} status is one of {', '.join(STATUSES[kind])}")
            elif field in ("title", "what", "notes") and not isinstance(value, str):
                self.bad(loc, f"{field} must be text")
            out["changes"][field] = value

    def kind_commitment(self, loc, w, out):
        out["owner"] = self.choice(loc, w, "owner", OWNERS)
        out["person"] = w.get("person")
        if not self.known_person(out["person"]):
            self.bad(loc, f"person {out['person']!r} is not a person the engine knows")
        out["what"] = self.text(loc, w, "what")
        out["due"] = self.when(loc, w.get("due"), "due")

    def kind_person(self, loc, w, out):
        pid = w.get("id")
        if not isinstance(pid, str) or not pid:
            self.bad(loc, "needs the person's id")
            return
        out["id"] = pid
        if pid not in self.people and not (w.get("name") and w.get("domain")):
            self.bad(loc, f"new person {pid} needs a name and a domain")
        if w.get("domain") is not None and w["domain"] not in DOMAINS:
            self.bad(loc, f"domain must be one of {', '.join(DOMAINS)}")
        for f in PERSON_FIELDS:
            if f in w:
                out[f] = w[f]

    def kind_question(self, loc, w, out):
        out["subject"] = str(w.get("subject") or "")
        out["question"] = self.text(loc, w, "question")
        self.subject_known(loc, out["subject"])
        settled = self.conn.execute(
            "SELECT answer FROM questions WHERE subject = ? AND status IN ('answered', 'consumed') "
            "ORDER BY answered_on DESC LIMIT 1", (out["subject"],)).fetchone()
        if settled:
            self.bad(loc, f"{out['subject']} was already answered: {settled['answer']!r}. Use the answer.")
        standing = self.conn.execute(
            "SELECT id FROM questions WHERE subject = ? AND status = 'open'", (out["subject"],)).fetchone()
        out["existing"] = standing["id"] if standing else None

    def subject_known(self, loc, subject):
        kind, sep, ident = subject.partition(":")
        if not sep or kind not in SUBJECT_KINDS or not ident:
            self.bad(loc, f"subject {subject!r} must be kind:id, with kind one of {', '.join(SUBJECT_KINDS)}")
            return
        if kind == "person":
            ok = self.known_person(ident)
        elif kind == "sender":
            ok = self.conn.execute("SELECT 1 FROM items WHERE sender = ? LIMIT 1", (ident,)).fetchone() is not None
        elif kind == "item":
            ok = self.exists("items", ident)
        else:
            ok = self.exists(TABLES[kind], ident)
        if not ok:
            self.bad(loc, f"subject {subject!r} names a {kind} the engine does not know")

    def kind_choose(self, loc, w, out):
        out["summary"] = self.text(loc, w, "summary")
        cands = w.get("candidates")
        if not isinstance(cands, list) or not cands:
            self.bad(loc, "needs at least one candidate")
            return
        out["candidates"] = []
        for n, c in enumerate(cands):
            where = f"{loc} candidates[{n}]"
            if not isinstance(c, dict):
                self.bad(where, "must be an object")
                continue
            extra = sorted(set(c) - {"what", "owner", "person", "due"})
            if extra:
                self.bad(where, f"cannot carry {extra}")
            cand = {"what": self.text(where, c, "what"), "owner": self.choice(where, c, "owner", OWNERS),
                    "person": c.get("person"), "due": self.when(where, c.get("due"), "due")}
            if cand["person"] is not None and not self.known_person(cand["person"]):
                self.bad(where, f"person {cand['person']!r} is not a person the engine knows")
            out["candidates"].append(cand)


# ---- writing ----

def write(conn, plan, now):
    """Write an accepted plan in one transaction. Returns the count per outcome."""
    counts = {o: 0 for o in OUTCOMES}
    you = db.get_state(conn, "you", "")
    with conn:
        for q in plan["consumed"]:
            conn.execute("UPDATE questions SET status = 'consumed' WHERE id = ?", (q,))
        for p in plan["people"]:
            upsert_person(conn, p)
        for s in plan["senders"]:
            conn.execute(
                "INSERT OR REPLACE INTO source_senders "
                "(sender, source, disposition, person_id, taught_by, taught_on, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (s["sender"], s["source"], s["disposition"], s.get("person"),
                 s.get("from") or "learn", now, s.get("note")))
        for it in plan["items"]:
            conn.execute(
                "UPDATE proposals SET status = 'superseded', decided_at = ? "
                "WHERE item_id = ? AND status IN ('pending', 'sent_back', 'answered')",
                (now, it["id"]))
            outcome, rule = it["outcome"], it.get("rule")
            if rule:
                rules.fired(conn, rule, it["id"], now)
                if rule["outcome"] in rules.ENFORCED:
                    outcome = rule["outcome"]   # the work is dropped: filed and headsup carry none
            question_id = None
            work = []
            for w in (it["work"] if outcome == it["outcome"] else []):
                w = dict(w)
                if w["kind"] == "question":
                    question_id = w.pop("existing", None) or new_question(conn, it["id"], w, now)
                work.append(w)
            pid = next_id(conn, "proposals", "proposal")
            conn.execute(
                "INSERT INTO proposals (id, item_id, class, outcome, reason, work, question_id, rule_id, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (pid, it["id"], it["class"], outcome, it["reason"],
                 json.dumps(work, ensure_ascii=False), question_id, rule["id"] if rule else None, now))
            conn.execute(
                "INSERT INTO decision_log (at, actor, item_id, decision, reason) VALUES (?, ?, ?, ?, ?)",
                (now, "evaluate", it["id"], outcome, it["reason"]))
            record_interactions(conn, it["id"], you, now)
            conn.execute("UPDATE items SET status = 'judged' WHERE id = ?", (it["id"],))
            counts[outcome] += 1
            if rule and rule["outcome"] == "auto" and outcome == "ready":
                from . import decide
                decide.approve(conn, pid, now, by=rule["id"])
        db.log(conn, now, "engine", "process", target=f"{len(plan['items'])} items",
               detail=json.dumps(counts))
        lock.end(conn)
    return counts


def upsert_person(conn, p):
    fields = {f: p[f] for f in PERSON_FIELDS if f in p}
    if conn.execute("SELECT 1 FROM people WHERE id = ?", (p["id"],)).fetchone():
        if fields:
            sets = ", ".join(f"{f} = ?" for f in fields)
            conn.execute(f"UPDATE people SET {sets} WHERE id = ?", (*fields.values(), p["id"]))
    else:
        conn.execute(
            "INSERT INTO people (id, name, pronouns, domain, role, trait) VALUES (?, ?, ?, ?, ?, ?)",
            (p["id"], fields.get("name"), fields.get("pronouns"), fields.get("domain"),
             fields.get("role"), fields.get("trait")))


def new_question(conn, item_id, w, now):
    qid = next_id(conn, "questions", "question")
    conn.execute(
        "INSERT INTO questions (id, item_id, subject, question, asked_on, status) VALUES (?, ?, ?, ?, ?, 'open')",
        (qid, item_id, w["subject"], w["question"], now))
    return qid


def next_id(conn, table, prefix):
    """The engine mints every id it writes: proposal-14, question-4."""
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE id LIKE ?", (f"{prefix}-%",)).fetchone()[0] + 1
    while conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (f"{prefix}-{n}",)).fetchone():
        n += 1
    return f"{prefix}-{n}"


def record_interactions(conn, item_id, you, now):
    """Who was in touch through this item: in from its sender, out when you wrote it."""
    item = conn.execute("SELECT source, sender, received_at, raw FROM items WHERE id = ?", (item_id,)).fetchone()
    heads = json.loads(item["raw"] or "{}")
    if you and item["sender"] == you:
        person, direction = person_for(conn, item["source"], heads.get("to"), now), "out"
    else:
        person, direction = person_for(conn, item["source"], item["sender"], now), "in"
    if person:
        conn.execute(
            "INSERT OR IGNORE INTO interactions (person_id, item_id, direction, at) VALUES (?, ?, ?, ?)",
            (person, item_id, direction, item["received_at"]))


def lookup(conn, source, name):
    """The person a sender resolves to, writing nothing. source_senders is the map across
    sources, one row per source and handle, and its tie wins. With no row, a name that fits
    exactly one person is that person. A name that fits two people resolves to nobody."""
    if not name:
        return None
    row = conn.execute("SELECT person_id FROM source_senders WHERE source = ? AND sender = ?",
                       (source, name)).fetchone()
    if row:
        return row["person_id"]
    matches = conn.execute("SELECT id FROM people WHERE lower(name) = lower(?)", (name,)).fetchall()
    return matches[0]["id"] if len(matches) == 1 else None


def person_for(conn, source, name, now):
    """lookup, and when the match came from the name alone, the tie is written back, recorded
    as taught by a match, so the next run resolves the sender without matching."""
    pid = lookup(conn, source, name)
    if pid and not conn.execute("SELECT 1 FROM source_senders WHERE source = ? AND sender = ?",
                                (source, name)).fetchone():
        conn.execute(
            "INSERT INTO source_senders (sender, source, disposition, person_id, taught_by, taught_on, note) "
            "VALUES (?, ?, 'normal', ?, 'match', ?, 'the name fits one person')", (name, source, pid, now))
    return pid


# ---- the command ----

def run(path=None):
    """Take the handover file into the database. Returns the exit code."""
    path = Path(path) if path else HANDOVER
    if not path.exists():
        print(f"No handover file at {path}.")
        return 1
    try:
        data = load(path)
    except ValueError as e:
        print(f"{path.name} is not valid JSON: {e}")
        return 1
    conn = db.connect()
    try:
        now = clock.now(conn)
        try:
            counts = process(conn, data, now)
        except Refused as r:
            aside = path.with_name("handover.refused.json")
            path.replace(aside)
            n = len(r.problems)
            print(f"Refused, nothing written. {n} problem{'s' if n != 1 else ''} in {path.name}, "
                  f"moved aside as {aside.name}:")
            for p in r.problems:
                print(f"  {p}")
            return 1
        print(summary(conn, counts))
    finally:
        conn.close()
    path.unlink()
    return 0


def summary(conn, counts):
    n = sum(counts.values())
    lines = [f"Judged {n} item{'s' if n != 1 else ''}: {counts['ready']} ready for you, "
             f"{counts['yours']} for your input, {counts['headsup']} heads-up, {counts['filed']} filed away."]
    loops = conn.execute("SELECT COUNT(*) FROM commitments WHERE status = 'open'").fetchone()[0]
    waiting = conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'open'").fetchone()[0]
    lines.append(f"Loops held: {loops}. Questions waiting: {waiting}.")
    left = conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'answered'").fetchone()[0]
    if left:
        lines.append(f"{left} answered question{'s' if left != 1 else ''} not folded in this run, still queued.")
    return "\n".join(lines)
