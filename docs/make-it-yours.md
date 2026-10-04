# Make it yours

Turning the Mudroom from a demo into a system that runs on your own life.

This is a working list. It collects everything a real setup has to deal with that the
demo does not, and it grows as we find them. Entries are not in order of importance, and
some are decisions rather than tasks. When a section is settled enough to hand to a
stranger, it moves into the README or a page of its own.

Each entry says what the situation is, why it matters, and what the options are. Where a
call has not been made, it says so. One thing to hold throughout: once the Mudroom runs on
your accounts, what it does is in your name, and a rule, a source skill or a change to the
code is yours. The section "What the engine cannot protect you from" says where the limits
are.

---

## The scheduler

**Situation.** The Mudroom has no scheduler. `python mudroom.py run` does the whole pass
once, by hand or from a button: intake, then the two agents through your own Claude Code in
headless mode, then processing. `engine/agents.py` is the call, with an allowlist that lets
the model read, write `handover.json` and run `mudroom.py`, and nothing else. The piping
page says intake runs on a schedule or on demand, and only the second half is true today.

**Why it matters.** A door that only sorts when you remember to run it is a
tool you have to remember to use, which is the problem it was meant to solve. Letting it
act on its own later, see below, depends on the thing running often enough to build a record.

**Options.**

Claude Code's own scheduling, which runs a prompt on a cron expression. This suits the
Mudroom well, because the judging step needs a Claude anyway, so one scheduled run can
fetch, evaluate and process in a single pass.

Cowork routines, if the user works there. Same shape, different host.

Ordinary `cron` on macOS or Linux, or Task Scheduler on Windows, calling `mudroom.py`.
This works for the deterministic half. The judging step still needs a Claude, so either
the scheduled command invokes one headlessly or the schedule only stages, leaving the
judgement for whenever you next open a session.

**Open.** How often. Once a morning is the obvious start, though a busy mailbox may want
several runs a day at different times, each doing a different job. Also open: whether a
scheduled run should judge, or only stage and leave judging until a person is present.

---

## Your Claude runs the agents

**Situation.** The engine never judges. When a run reaches the two agents, `engine/agents.py`
starts Claude Code in headless mode on the repo, with one prompt, follow the learn-evaluate
skill, and an allowlist: read anything, edit `handover.json`, run `mudroom.py`, nothing else.
The Doorstep's button, `python mudroom.py run` and `python mudroom.py learn-evaluate` all go
through it. What Claude said each time is kept in `run.log`.

**Why it matters.** This is the seam made mechanical. However the model is talked to, by the
skill or by text that arrived in the mail it is judging, it cannot reach past the allowlist,
and the allowlist is set by the engine, where no prompt can argue with it.

**What a machine needs.** A `claude` command on the path that is current: an old one refuses
the model and the Doorstep says so. `claude update` fixes that. A machine that keeps several
copies can name one in `MUDROOM_CLAUDE`. Each run spends tokens on the person's own plan, a
few minutes of work for a batch of ten.

**Open.** Whether the allowlist should also deny the network, and whether a run should be
refused while a person has the repo open in an interactive session.

---

## Two runs at once

**Situation.** A scheduled run and a manual run can overlap. So can a scheduled run and
a click on a card. Nothing stops them.

**Why it matters.** Both write to the same SQLite file. A half-finished intake plus an
approval landing in the middle of it can leave the database in a state neither of them
intended.

**How it works.** Built 2026-09-20. A single-row lock, set when intake registers what is
new and cleared when processing has written the judgement, in `engine/lock.py`. A page that
writes defers while the lock is fresh, and a lock older than ten minutes belongs to a run
that died and is ignored, so a crashed run cannot wedge the system.

**Open.** Nothing. The Doorstep's buttons and the run command refuse while a run is in
flight, and approve will do the same when it arrives.

---

## Connecting your own sources

**Situation.** The demo registers one source, an invented week. Nothing else is wired.

**Why it matters.** This is the step everything else waits on.

**How it works.** A source is a skill your Claude runs. It asks the engine how far it got
last time, `python mudroom.py intake --bookmark <source> <account>`, pulls what is newer
through a connection your Claude already holds, flattens it to the common shape, and hands
it over, `python mudroom.py intake <file>`. The engine holds no credentials and opens no
connections. The demo's own source, `/source-demo`, is the worked example, with the
invented week's parser in `rounds/source.py`. The guided way: open Claude Code in this
folder and say `/make-it-mine`. It asks your name, starts clean, writes your first source
skill from a template and runs the first pass, one step at a time.

Before the first real source, the invented week has to go, and `/make-it-mine` does that as
its second step. By hand it is `python mudroom.py start-clean --you "Your name"`: it says
what would go and removes it only with `--yes`, the folders `rounds/` and `world/` and the
demo's source skill, then rebuilds the database empty, in your name, with the clock on real
time. The engine, the pages, the judging skill and the tests stay. `reset` refuses from then
on, since there is no week to restore; a fresh clone brings the demo back. Fiction left in a
real system is confusing at best, and worse once the door acts on its own.
One rule for what a source writes: the sender of an item is the stable handle the source
gives, an email address, a chat id, and the display name goes in the raw copy. The
identity map, `source_senders`, keys on that handle, so one person's address on one source
and id on another both point at the same row in `people`, as do a work address and a
personal one, or two ids on the same chat app.

**Open.** Nothing on the shape; it is settled as a file in the agreed shape. What remains is
the first source to write up in full.

---

## Writing a source skill

**Situation.** The demo has one source, the invented week, brought to the door by `python
mudroom.py intake`. A real source is a skill your Claude runs, one per source, that pulls what
is new through a connection your Claude already holds and hands it to the engine. The
`learn-evaluate` skill stays exactly as it is: a source skill fetches and flattens, and judges
nothing. The repo ships one source skill, the demo's, and no real one, because it ships no
accounts.

**What a source skill does**, in the shape that has held up on a real mailbox:

1. Asks the engine how far it got last time: the bookmark in `source_state` for this source
   and account, a cursor and the id of the newest item registered. Pull only what is newer.
   A provider's "since" is often inclusive, so drop the item whose id matches the bookmark
   rather than widening the window.
2. Pulls read-only, through the connection your Claude holds. The engine never sees a
   credential. If the pull fails, tell the engine, so that it can raise a question saying
   the source needs attention and clear it on the next good pull. A dead source is never
   silent.
3. Flattens each item to the common shape: an id built from the source and the provider's
   id, the source, the sender as the stable handle the provider gives, the subject, the
   body, when it was received, the thread, and the rest as the raw copy, display name
   included.
4. Hands the items to the engine, `python mudroom.py intake <file>`, which registers them
   all, updates the ones it already knows, marks the ones from a sender on the skip list
   without reading them, logs each skip, and only then moves the bookmark.
5. Stops. Judging is the `learn-evaluate` skill's. Sending is nobody's.

A task app is two sources in one: its inbox, whose items are the person's own captures and
arrive like any other item, and what was completed since the bookmark, which the engine
reconciles against the tasks it created before anything is judged.

**Open.** A failed pull. The handoff has no way to say the source could not be reached, so
the question that should tell the person to re-authorise is not raised yet.

---

## The Doorstep stays

**Situation.** The Doorstep shows what arrived, in the order it arrived, each thing still
looking like what it is, and beneath each thing what you sent back through the Mudroom. It
was built as a window onto the invented week.

**Why it matters.** With your own sources it is the one place that shows every source
together, mail beside chat beside notes, with your replies under what they answered. Your
mail app shows only mail. Whether that is worth a page of its own is your call once you have
lived with it; it costs nothing to keep.

**How it works.** The demo's buttons on it go quiet once the invented week has left; the
judge button stays, for when something waits at the door.

---




## The sender list starts empty

**Situation.** `source_senders` has no rows on a fresh setup, so nothing is recognised as
bulk.

**Why it matters.** The first few runs on a real mailbox will be loud. Everything gets a
full read and a judgement, including every newsletter.

**Options.** Seed it from the provider where one offers a hint, such as a promotions
category. Or accept a noisy first week and let it learn, which is honest and slower. Or
let the user paste a list of senders to ignore on day one.

**Open.** All of it. Worth noting that the discipline matters more than the speed: never
classify a sender on topic alone, prefer keeping when unsure, and leave a sender
unclassified rather than guess, so uncertainty costs attention instead of losing mail.

Worth knowing for a real mailbox: a good first pass is more than the sender
list. A watched or known sender is always kept. One family of notifications is force-kept
ahead of the skip list, because a share request needs a decision. Subject prefixes that mark
an auto-reply or a read receipt are skipped, as is an empty note to self, and every skip is
logged with the check that fired, so a wrong skip is findable and reversible. The Mudroom's
first pass is the sender list alone. The rest are small deterministic checks that belong in
the staging step once a real source is wired, never in the judgement.

---

## Keeping up with people

**Situation.** The Mudroom knows who the people around you are and when you were last in
touch with each of them, and nothing more. It holds no dated facts about a person, a
birthday, an anniversary, a milestone, and it has no notion of how close someone is to you.

**Why it matters.** Much of keeping up with people is quiet
timekeeping: a birthday is next week, you have not spoken to an old friend since March, a
colleague you rely on has gone silent. The tables to notice this from are already there.

**How it could work.** Two additions, both small. A table of dated facts about a person,
each with what it is, when it recurs, and how far ahead it should surface, so a birthday
becomes a card in good time and never a calendar event. And a note on each person
of how close they are to you, family and close friends, people you work with, people you
know, people you have lost touch with, that sets how long a silence may last before the
mudroom mentions it. That is yours to set: the mudroom asks once and does not guess it from
how often someone writes.
A reminder should open into something to do, a message drafted in your voice or a call
proposed, so it is a card like any other.

**Open.** Whether this ships in the system or stays a personalisation. Either way it is
built on people and interactions as they are, so nothing in the core has to change first.

---

## Locking a source to read-only

**Situation.** Every source the Mudroom reads can also be written to, if the connection you give
it allows writing. Nothing in the design makes any source read-only by default.

**Why it matters.** You may well want one that is. Reading what someone asked you in a chat is
useful; answering in your name, in a medium where people expect a reply within minutes, is a
different proposition. The same argument applies to anything where the tone matters more than
the content, or where a mistake is seen instantly by other people.

**How to do it properly.** Put the lock where the model cannot reach it. An instruction in a
prompt asking it not to send is not a lock, because a prompt can be argued with, including by
text that arrived in the material it was asked to judge. One way that works is
a launcher script holding an allowlist: the commands that read pass, everything else exits
with an error before it reaches the tool at all. It is an allowlist rather than a denylist, so
a verb added by a future release of that tool is refused by default instead of quietly
permitted.

**Open.** Whether the Mudroom should ship a worked example of one locked source, so the pattern
is visible, or only describe it here.

---

## Effects on real accounts

**Situation.** In the demo, an approved effect lands in the Mudroom's own tables. A task
appears in its planner, a reply is marked sent. Nothing leaves the file.

**Why it matters.** On your own life you will want some of those effects to be real: a
task actually created, an event actually added, a reply actually sent.

**How it works.** The outward half is a closed map of effect writers, and one function is
the only thing allowed to call them. The demo's writers write to its own tables. Real ones
call out through your Claude's connections. Swapping them is the mirror of swapping a
source.

**Open.** Which effects to make real first. The safe order is create a task, then add an
event, then anything that sends. Sending is the one that never comes to happen
without asking, however clean the record, because a sent message cannot be unsent.

Also open: checking that an effect can run before its card shows a button. A sound way is
to attach to every prepared action a block naming the tool, the type and what the executor
needs, and to refuse at processing anything the executor could not carry out, such as a
forward with no message id or an event with no times, so an approve never fails behind a
dead button. The demo has no such check, because every effect lands in its own tables. Once
effects are real, each writer should declare what it needs, which account sends, which
message is filed, which calendar is written, and processing should check it before the card is
written.

---

## What the engine cannot protect you from

**Situation.** The engine constrains the handover file. It checks it, clamps it, and refuses
it when it overreaches.

**Why it matters.** It cannot constrain an agent that has been talked into editing a file
or running a command directly, because that agent owns the repo, holds a shell, and in the
same session holds the connections to your accounts. Text arriving in your inbox is written
by strangers, and the judging step reads it.

**Options.** Keep the judging session's connector permissions read-only, with a deny list
naming every command that writes on anything connected. Put the outward effects in a separate step
with its own permissions. Check the engine's own files against known hashes so a quiet edit
shows up. The headless run in `engine/agents.py` already does the first of these for the
judging step: its allowlist is read, edit `handover.json`, run `mudroom.py`.

**Open.** How much of this the repo should ship by default versus explain and leave to the
user.

---

## Your own views

**Situation.** Seven pages ship: the front door, the Doorstep, the Sorting dashboard, the
Planning dashboard, the log, the piping and What's next. They are rendered as plain HTML
from SQLite on every request.

**Why it matters.** They are examples. Most people will want something else.

**How it works.** Each page is a function that queries the database and returns a string.
There is no framework and no build step, so changing one is ordinary Python and ordinary
CSS. Adding a page is a function plus a line in the routing table.

**Open.** Nothing. This one is ready to hand over.

---

## Keeping your data

**Situation.** Everything lives in one SQLite file, which is not in version control.

**Why it matters.** Months of accumulated judgement, rules and history sit in that file.
Losing it means starting over.

**Options.** Dump the data to text and commit it, so the durable
state is diffable and the working database is rebuilt from it each run. That also solves
running the same system on more than one machine. The Mudroom does not do this, and for a
single machine with a backup it may not need to.

**Open.** Whether to adopt the dump-and-rebuild cycle, and if so whether it belongs in the
demo or only in a real setup.

---

## Degrees of independence

**Situation.** As shipped, the Mudroom never acts on its own. Every effect that reaches
outside it waits for a person to approve it, every time. The one way past that is a house
rule with the outcome `auto`, described at the end of this file, which no rule carries until
you ask for it in words and say yes to it once. Setting something aside needs no approval,
because nothing leaves the system when it happens.

**Why it matters.** This is deliberate, and it is the first thing to understand about what
you downloaded. A stranger pointing an agent at their own mail should not have to trust it
before they have watched it work. Independence is the part that goes wrong most expensively
and the part that is hardest to unwind once it has been granted.

**What it would take to add.** The engine already records everything the decision needs: one
row per effect in `actions` with a flag saying whether it can be undone, and the kind of
work on every proposal. Granting more means answering three things. How many
clean approvals count as evidence. Whether a kind of work is eligible at all. And who is
allowed to grant it.

Sensible answers: a number the owner picks rather than one written into the code, only
reversible effects unless the owner explicitly authorises otherwise, and the owner's own
say-so each time, written down with the date and the reasoning. Anything that sends a
message is capped below the top permanently, whatever its record, because a sent message
cannot be unsent.

**Open.** Whether to add a step that is earned by a record of clean approvals, beside the
rule a person asks for in words.

---

## Rules that do work

**Situation.** A rule in the demo sets an outcome for anything that matches it: file it,
heads-up, ready, yours. It says nothing about what to prepare. A rule could carry the
work itself: forward anything matching to a named person with a cover note, or make a task
in a given place with a field pulled out of the message, such as a pickup code. It could
also match on topic, by the model's judgement, where the demo matches on a sender, a domain
or a subject.

**Why it matters.** Most of what a person teaches the door has that shape: every
time this arrives, do this with it. An outcome alone covers filing and heads-ups. The rest
needs the work.

**How it would work.** A rule gains a work template, the same shape as an entry in the
handover file's work list, with placeholders the engine fills from the item. Processing prepares
that work when the rule fires, and the card says which rule shaped it. Topic as a scope
means the judgement decides the match and the engine records it, since a topic cannot be
matched by string.

**Open.** Whether this comes with the house rules in the demo or only in a real setup.

---

## What it may do on its own, later

**Situation.** The demo waits for a yes on everything with an effect, and on some things
without one. It proposes a person's profile rather than writing it, proposes closing a loop
when the answer lands rather than closing it, surfaces a calendar invitation rather than
answering it, and files nothing until asked.

**Why it matters.** Each of those is a place where a person who has watched the door work
for a while will want to let it act on its own.

**How it would work.** Each is a setting a person grants deliberately, one at a time: write
and merge profiles when the match is certain, close a loop when the answer is unambiguous,
answer an invitation the calendar already holds, file what was judged filed. The engine
already has what a grant needs: the actions log as the record, and the reversible flag
on every effect.

**Open.** The order to offer them in. Filing first, since it is the loudest and the most
reversible. Sending never.

---

## Still to capture

Things we know are coming and have not written up yet.

- What a person should do in their first week, in order, rather than as a list of topics.
- A persona of your own: who the mudroom serves, what they protect, how they write. The
  demo runs without one, on the owner's name in the state table and a plain default voice
  in the judge skill. A future option, either a row the person fills in at setup and the
  agents read like any other table, or the skill edited to say it.
- What to do when a judgement is repeatedly wrong about the same kind of thing.
- Whether to keep the demo installed alongside a real setup, and how they stay separate.


## Filing on a real mailbox

The demo files by marking the item; a real source has a mailbox to move mail in. Two things
worth building in from the start. Select what still
needs filing from the decision log on every run, not from the batch that judged it, so a failed
move is picked up next time instead of sitting in the inbox for good. And never file mail
whose card is still open: a card the person has not answered owns its mail, while a card
they declined does file, since they decided nothing was needed.


## A rule that acts on its own

A house rule can carry the outcome `auto`. A matching item is sorted as usual, and if the
judgement makes it ready, the engine approves the card itself, at processing, and logs the
yes as the rule's: "On its own, under rule-7: reply sent to Riley". The card never waits.

No rule ships with `auto`, and no menu on a card offers it. You ask for it in words, in the
note box or in chat, "send the two-line replies to Riley on your own", the judgement
proposes the rule, and you say yes to it once. Removing the rule on the log page ends it
the same minute. The log shows every yes a rule gave, under its own name, so you can see
what it did before you give it more.
