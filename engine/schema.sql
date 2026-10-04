-- The Mudroom: the shape of the database.
-- SQLite is the source of truth while the demo runs. Reset rebuilds it from world/seed.json.

CREATE TABLE state (            -- week_start, clock, clock_mode (demo | real), you, reset_at
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE run_lock (         -- the run in flight: set at intake, cleared by processing, ignored
                                -- once it is older than ten minutes. See engine/lock.py.
  token      TEXT PRIMARY KEY,
  started_at TEXT NOT NULL      -- wall-clock time, since the engine's clock stands still in a run
);

CREATE TABLE people (
  id       TEXT PRIMARY KEY,    -- 'jordan'
  name     TEXT NOT NULL,
  pronouns TEXT,
  domain   TEXT NOT NULL,       -- work | family | personal
  role     TEXT,
  trait    TEXT                 -- how they write, in one line
);

CREATE TABLE calendars (
  id     TEXT PRIMARY KEY,      -- work | family | personal
  name   TEXT NOT NULL,
  colour TEXT NOT NULL,
  note   TEXT
);

CREATE TABLE events (
  id          TEXT PRIMARY KEY,
  calendar_id TEXT NOT NULL REFERENCES calendars(id),
  title       TEXT NOT NULL,
  start       TEXT NOT NULL,    -- ISO datetime, stamped at reset
  end         TEXT NOT NULL,
  notes       TEXT,
  source      TEXT NOT NULL DEFAULT 'seed',   -- seed, or the item that produced it
  created_at  TEXT
);

CREATE TABLE tasks (
  id         TEXT PRIMARY KEY,
  title      TEXT NOT NULL,
  domain     TEXT NOT NULL,     -- work | family | personal
  priority   INTEGER NOT NULL DEFAULT 2,     -- 1 high, 2 normal, 3 low
  due        TEXT,              -- ISO date
  status     TEXT NOT NULL DEFAULT 'open',   -- open | done
  notes      TEXT,
  source     TEXT NOT NULL DEFAULT 'seed',
  created_at TEXT,
  done_at    TEXT
);

CREATE TABLE commitments (      -- promises in both directions: the loops the mudroom holds
  id          TEXT PRIMARY KEY,
  owner       TEXT NOT NULL,    -- me (Alex promised) | them (someone promised Alex)
  person_id   TEXT REFERENCES people(id),
  what        TEXT NOT NULL,
  promised_on TEXT,
  due         TEXT,
  status      TEXT NOT NULL DEFAULT 'open',  -- open | closed
  source      TEXT,             -- the item where the promise was made
  closed_by   TEXT,             -- the item or action that closed it
  closed_on   TEXT
);

CREATE TABLE questions (        -- one open question per subject
  id          TEXT PRIMARY KEY, -- question-4
  item_id     TEXT REFERENCES items(id),  -- the item it is the surface of, if any
  subject     TEXT NOT NULL,    -- kind:id, such as person:taylor or sender:Casey (recruiter)
  question    TEXT NOT NULL,
  asked_on    TEXT,
  status      TEXT NOT NULL DEFAULT 'open',  -- open | answered | consumed
                                             --   | closed (done or set aside, nothing to fold in)
  answer      TEXT,
  answered_on TEXT
);

CREATE TABLE source_state (     -- the bookmark per source: how far the last fetch got
  source       TEXT NOT NULL,   -- as items.source, or rounds for the demo's invented week
  account      TEXT NOT NULL,   -- you@example.com, or world for the demo
  cursor       TEXT,            -- how far the fetch got: a received_at, or the slot in the demo
  last_seen_id TEXT,            -- its id in items, or the batch in the demo
  checked_at   TEXT,            -- when intake last looked, whether or not anything was new
  PRIMARY KEY (source, account)
);

CREATE TABLE items (            -- what came to the door, in one shape whatever the source
  id          TEXT PRIMARY KEY,
  source      TEXT NOT NULL,    -- email | chat | transcript | capture | calendar
  sender      TEXT,
  subject     TEXT,
  body        TEXT,
  received_at TEXT,
  staged_at   TEXT NOT NULL,    -- when intake registered it, on the engine's clock
  thread      TEXT,
  raw         TEXT,             -- the message as it arrived, JSON
  status      TEXT NOT NULL DEFAULT 'staged'  -- staged | skipped | judged | filed (after a yes)
                                              --   | sent (your reply or forward, kept by the engine)
);

CREATE TABLE proposals (        -- the judgement on an item, and the work that came with it
  id          TEXT PRIMARY KEY, -- proposal-14
  item_id     TEXT NOT NULL REFERENCES items(id),
  class       TEXT NOT NULL,    -- what kind of thing the item is, from CLASSES in the engine
  outcome     TEXT NOT NULL,    -- ready | yours | headsup | filed
  reason      TEXT NOT NULL,    -- why, in plain words, as the card shows it
  work        TEXT NOT NULL,    -- JSON: the list of work, each entry with its kind, as
                                --   the learn-evaluate skill defines it, dates resolved
  question_id TEXT REFERENCES questions(id),  -- for a yours card, the question that is its surface
  rule_id     TEXT REFERENCES handling_rules(id),  -- the house rule that shaped it, if one did
  status      TEXT NOT NULL DEFAULT 'pending', -- pending | approved | declined | done
                                              --   | sent_back | answered (judged again on the next run)
                                              --   | superseded (judged again, and was)
  sent_back   TEXT,             -- what you said when you sent it back, in your words
  created_at  TEXT,
  decided_at  TEXT
);

CREATE TABLE actions (          -- the log: one row per effect, by the engine or by you
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  at         TEXT NOT NULL,
  actor      TEXT NOT NULL,     -- alex | mudroom | engine
  action     TEXT NOT NULL,     -- approve | decline | done | tick | file | reset | ...
  target     TEXT,
  reversible INTEGER NOT NULL DEFAULT 1,
  detail     TEXT
);

CREATE TABLE decision_log (     -- why each thing was handled that way, skips included
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  at       TEXT NOT NULL,
  actor    TEXT NOT NULL,       -- whose decision: intake | learn | evaluate | process
  item_id  TEXT NOT NULL REFERENCES items(id),  -- skips included: intake registers
                                                --   everything before it marks anything
  decision TEXT NOT NULL,       -- skipped | ready | yours | headsup | filed
  reason   TEXT NOT NULL        -- in plain words
);

CREATE TABLE interactions (     -- who was in touch, which way round, through which item
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id TEXT NOT NULL REFERENCES people(id),
  item_id   TEXT NOT NULL REFERENCES items(id),
  direction TEXT NOT NULL,      -- in (they contacted you) | out (you contacted them)
  at        TEXT NOT NULL,
  UNIQUE (person_id, item_id, direction)   -- the same email fetched twice makes one row
);

CREATE TABLE source_senders (   -- what is known about a sender, checked at intake
  sender      TEXT NOT NULL,    -- the address or handle, as the source gives it
  source      TEXT NOT NULL,    -- email | chat | transcript | capture | calendar
  disposition TEXT NOT NULL DEFAULT 'normal',  -- skip | watch | normal
  person_id   TEXT REFERENCES people(id),      -- who this is, once known
  taught_by   TEXT,             -- the proposal, answer or action that made the row
  taught_on   TEXT,
  note        TEXT,
  PRIMARY KEY (source, sender)
);

CREATE TABLE handling_rules (   -- what you told it to do from now on. Retiring keeps the row.
  id           TEXT PRIMARY KEY,   -- rule-3
  scope        TEXT NOT NULL,      -- sender | domain | subject
  pattern      TEXT NOT NULL,      -- admin@school.example, school.example, or words in a subject
  action       TEXT NOT NULL,      -- what you asked for, in plain words: make a task
  outcome      TEXT NOT NULL,      -- what a match becomes: ready | yours | headsup | filed
  status       TEXT NOT NULL DEFAULT 'active',  -- active | retired
  taught_by    TEXT,               -- the proposal, answer or action that made the rule
  taught_on    TEXT,
  retired_on   TEXT,
  last_applied TEXT,
  fired        INTEGER NOT NULL DEFAULT 0
);
