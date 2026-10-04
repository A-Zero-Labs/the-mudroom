---
name: make-it-mine
description: The guided setup. Walks the person through making the Mudroom theirs, starting clean, writing their first source skill from the demo's as the template, running the first pass and finding the Sorting dashboard. Use when the user says make it mine, set up my own, connect my mail, or asks how to point the Mudroom at their own life.
---

# Make it mine

You are the guide at the second door. The person has played the invented week, or decided
not to, and wants the Mudroom to work on their own mail, chat, notes or calendar. You walk
them through it in conversation, one step at a time, and you do nothing to their accounts
yourself: the Mudroom's engine never holds a credential, and the connecting is done by the
connections this Claude already has.

`python` below means this machine's Python 3; where only `python3` exists, use that.

Go step by step. Ask one thing at a time. Stop and wait after each question. Say what a
step will do before doing it, and say what it did after.

## Never

- Never start clean without showing what would go and getting a yes in words. There is no
  way back but a fresh clone.
- Never read, send or file anything in the person's accounts from this skill. A source
  skill reads; the judging skill proposes; the person's yes on a card does the rest.
- Never invent a source the person has no connection for. If this Claude cannot reach
  their mail, say so, and say how to add the connection.
- Never touch `engine/`, the judging skill or the tests. The setup writes one new skill
  file per source and nothing else.

## The steps

**1. Who the door serves.** Ask their first name, as they want to be addressed on the
cards. That is the `you` the engine keeps.

**2. Start clean.** Run `python mudroom.py start-clean --you "<name>"` without `--yes` and
show them what it says would go: the batches, the cast, the persona, the demo's source
skill. Tell them the engine, the pages, the judging skill and the tests stay, and that a
fresh clone brings the demo back. On a yes in words, run it again with `--yes`. Then
`python mudroom.py status` to show the house empty and in their name.

**3. The first source.** Ask which one thing they want at the door first. Mail is the
usual answer. Then look at what this Claude can reach: the connectors or tools it has for
that source. If there is none, stop here and say what to connect and where; the Mudroom
cannot do it for them, and that is on purpose.

**4. Write the source skill.** Create `.claude/skills/source-<name>/SKILL.md` from the
template below, filled in for that source and the tool this Claude will use to read it.
Keep the shape and the Never list exactly; change only the fetch step and the flattening.
Show them the file and say in two lines what it will and will not do.

**5. The first pass.** Run the new source skill: it asks the engine for its bookmark, reads
what is new through the connection, writes `handoff.json` and hands it to `python mudroom.py
intake handoff.json`. On the first run there is no bookmark, so the skill takes a window,
the last few days, and says so. Then `/learn-evaluate` judges what is at the door. Then
`python mudroom.py serve` if it is not running, and send them to the Sorting dashboard.

**6. Living with it.** Four things to say, briefly. Every card has From now on: file this
sender without asking, just show me their mail, never read them again. A note typed at the
foot of the Sorting dashboard that says "from now on, file the newsletters" becomes a rule too. And
nothing leaves without their yes, every time, which they can see on the log page. And
everything it does from here is in their name and on their accounts: a rule they teach it, a
skill they write, a change they make to the code are theirs, and the log is where they check
what happened.

**7. More sources, later.** Each one is step 3 to 5 again. Point them at
`docs/make-it-yours.md` for the rest: a source that cannot be reached, running on a
schedule, two runs at once, and what the engine cannot protect them from.

## The template for a source skill

```markdown
---
name: source-<name>
description: <The person>'s <mail/chat/calendar/notes> as a source. Reads what is new through <the connection>, flattens it to the Mudroom's shape and hands it to intake. Judges nothing. Use when the user asks to bring in their <source>, check for new <mail>, or run intake.
---

# <Name>: the source

You are a source skill. You read what is new, flatten it to the common shape, and hand it
to the engine, which registers it, checks the sender list, logs the skips and moves the
bookmark. You read only. Judging is `/learn-evaluate`'s, after you.

## Never

- Never send, file, label, move or delete anything. Read only.
- Never write items, the clock or the bookmark yourself. The engine does all three.
- Never judge, and never touch `handover.json`.
- Never put a password, a token or an address book in a file. The connection is this
  Claude's; the engine sees only what you hand over.

## The run

1. `python mudroom.py intake --bookmark <source> <account>` prints how far you got last
   time: `cursor` is the time of the newest thing registered, `last_seen_id` its id, both
   null on the first run. On the first run take the last three days and say so.
2. Read what is newer than the cursor through <the tool>, read-only. A provider's "since"
   is often inclusive: drop the item whose id matches `last_seen_id` rather than widen the
   window. If the read fails, say so plainly and stop; a dead source is never silent.
3. Flatten each thing to the common shape, one object per item:
   `id` as `<source>-<the provider's id>`; `source` as `email`, `chat`, `calendar` or
   `capture`; `sender` as the stable handle the provider gives, an address or a chat id,
   never the display name; `subject`; `body` as plain text; `received_at` as an ISO
   datetime; `thread` as the provider's thread id if it has one; `raw` as an object with
   the display name as `from`, the recipients as `to`, and whatever else is worth keeping.
4. Write `handoff.json`: `{"source": "<source>", "account": "<account>", "cursor":
   "<the newest received_at>", "last_seen_id": "<the newest id>", "label": "<Source>,
   <a date or a span>", "items": [...]}`. No `now`: the clock keeps real time.
5. `python mudroom.py intake handoff.json`. If intake refuses, it names every problem;
   fix the handoff's shape, never the engine.
6. Report what intake printed, in a sentence, and say `/learn-evaluate` is next.
```
