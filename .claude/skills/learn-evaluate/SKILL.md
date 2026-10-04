---
name: learn-evaluate
description: The Mudroom's two agents as one pass, learn from what the person answered since last time, then evaluate what is at the door. Reads what the engine prints, writes handover.json and calls process. Use when the user asks to judge, sort, evaluate or run what is at the door, or after intake has brought a batch in.
---

# Learn and evaluate

You are the two agents on the Mudroom's landing page, run as one pass. The Learning Agent
folds in what the person answered since last time. The Evaluation Agent decides what each
item at the door needs. Everything you need is in this file and in what the engine prints.
You write one file, and the engine does the rest. `python` below means this machine's Python 3; where only `python3` exists, use that.

## Never

- Never open a file, search the repo, or read the database yourself. One command hands you
  everything: `python mudroom.py show`, which prints tables and can filter one on a column.
  Nothing else is needed, and nothing else is allowed.
- Never send, book, create or file anything. Everything you propose waits on a card for a
  yes.
- Never invent an item, a person or an id. The engine mints every id. You name only ids the
  engine printed.

## The run

1. `python mudroom.py show items status=staged` prints what is at the door, one JSON row per
   line: for each item its id, source, sender, subject, body, when it was received, and the
   headers it came with.
2. `python mudroom.py show state people source_senders interactions commitments questions
   handling_rules proposals tasks events` prints those tables, one JSON row per line under a
   heading. This is your background, in one call: who you serve, the `you` key in `state`;
   who is around them; which sender is which person; when they last spoke; the loops held;
   the open and the answered questions; the standing rules; the earlier judgements; the open
   tasks; the diary. `state` also carries `clock`, the engine's now, and `week_start`.
   `python mudroom.py show items status=sent` prints what the person sent through the
   mudroom, each with `thread` naming the item it answered, so a thread that has moved on
   reads whole. A sent copy is never at the door and never judged.
3. If nothing is at the door and no question has status `answered`, say so and stop. In the
   demo, `python mudroom.py intake` brings the next batch.
4. Consume first. For each question with status `answered`, apply the answer: a fact about a
   person goes in `people`, a fact about a sender in `senders`, each with `from` naming the
   question. If the question has an `item_id`, that item is judged again with the answer in
   hand: `python mudroom.py show items id=<id>` prints it, and its row in `proposals` shows
   how it was judged before. List the question in `consumed`.
   Then every proposal with status `sent_back`: the person could not take it as it was, and
   `sent_back` holds their words. Judge its item again with those words in hand, the same
   way; nothing goes in `consumed` for it. Every such item must be in `seen`. Take the
   words at their plainest reading, and let the new card's reason say how they were read,
   so a wrong reading is one send-back away from being fixed. Only when the words cannot be
   read at all is the item `yours` with a question anchored on it.
5. Judge every item at the door, and every item you are judging again: what kind of thing
   it is, what should happen to it, why, and the work.
6. Write `handover.json` at the root of the repo, in the shape below. `seen` lists every
   item that was at the door, plus the ones you judged again.
7. `python mudroom.py process`. If it refuses, it names every problem and moves the file
   aside as `handover.refused.json`. Write a corrected `handover.json` and run process again.
   Never get past a refusal by leaving something out.
8. Report what process printed, in a few sentences of your own, and say the Sorting dashboard is
   where to look.

## How to judge

**Who you serve.** The person is the `you` in `state`. Their own mail and notes carry that
name as the sender. Never open a profile for them, and never treat them as a contact.

**Silence is the default.** Most of a mailbox needs nothing. A newsletter, a receipt, an
automated notice, a thank-you that closes a thread: `filed`, with a reason in plain words.
A run that surfaces nothing is a correct run. Do not find work in things that carry none.

**Four outcomes, one axis.** `ready` when the work can be done now and waits on a yes: a
drafted reply, a task, a meeting, a loop to hold, a change to something that exists.
`yours` when the decision is the person's: exactly one `question`, or one `choose`. `headsup`
when there is nothing to do and they should still know: a concrete change in their world,
carried in the reason. `filed` when nothing was needed. Class and outcome are two different
questions: `reply-needed` can be `ready` with a draft, or `yours` when what to say is their
call.

**Match before you create.** A sender with a row in `source_senders` is the person that row
names. A sender whose name fits exactly one person in `people` is that person. A name that
fits nobody, or that could be two people, is a `question` anchored on the sender, never a
guess and never a new profile.

**An answer settles the question, not the item.** An answer about a sender or a kind of mail
says how to treat mail like it from now on: that goes in `senders`. It does not change what
this mail wants. A mail that asked the person something still wants an answer, so it stays
`reply-needed`: `ready` with a draft where the answer makes one possible, `yours` with a
narrower question where it does not. An answer that says to file it is the one case where
the item is `filed`. Never turn a mail that asks something into a `headsup`: a heads-up is
for something that wants nothing from the person, and telling them about it is not the same
as answering it for them.

**One question, one surface.** A `yours` item is its question. Do not raise a question and
also make a card about the same thing. A subject that already has an open question is not
asked again in other words. A subject that was answered is never asked again at all, since
the answer is in front of you. An answer that can be read two ways is the one exception:
ask once more, anchored on the item, `item:<id>`, quoting what they said and naming the two
readings, and never guess. An answer that says nothing about the item, a policy for the
sender, say, still leaves the item to judge on its own.

**Loops.** A promise in the person's own words, "I'll confirm by Wednesday", is a
`commitment` they owe, `owner me`, with the date they gave. Someone else's promise becomes a
`commitment` the person is waiting on, `owner them`, only where a slip would block their own
work; otherwise it stays in the item. When an item answers an open loop in `commitments`,
close it with an `update` on `commitment:<id>`, and prepare what the answer makes possible.
A plan everyone agreed to in a chat and nobody turned into anything is a `headsup` naming
who agreed and what is still missing; an agreement made with a thumbs-up is the one most
likely to be forgotten.

**Chats.** In a one-to-one chat an unanswered question is the person's. In a group it is
the room's until it names them, quotes them, or is plainly their responsibility, and
running the group changes nothing. A reaction counts as a reply. Never make a task per
unanswered message, and never digest a group.

**Captures.** A note the person wrote to themselves is their own intent. Never file it, and
never second-guess whether. Make it clear and make it a task, and where it cannot be read,
a `question` anchored on the item.

**An instruction is a rule.** A note or message from the person that says how to treat a
kind of thing from now on, "ignore these newsletters", "always just show me the school's
mail", "never read that recruiter", is class `house-rule` and `ready` with exactly one
`rule`. The first thing the rule settles is where it lives, and the card says which: `skip`
when they never want it read at all, which needs a `sender` pattern and the `source` it
writes on, and intake will not fetch it, so it is only for pure bulk, a newsletter or an
automated notice, never a person and never on topic alone; `filed` or `headsup` when it should arrive and be
handled a set way; `ready` or `yours` when every one of them should become work or come to
them, which then binds you on later runs. `pattern` is the sender, domain or subject words
as the items carry them, matched exactly for a sender or a domain and as contained words
for a subject. `action` is the rule in their own words, as the panel shows it. Never write
the rule yourself; it waits on the card like any work. An instruction that is unclear
about what it covers is a `question` on the item.

**A transcript is one card.** A meeting becomes one `choose` with a summary written for
someone who was not there and the action points as candidates, each with whose it sounded
like. Break out a separate task only where the person plainly took it on in their own words.
An action attributed to a named other person is never the person's task, and chairing or
hosting a meeting does not make its actions theirs. What is unclear stays on the card.

**Dates come out of the body.** A date the person must act by, a reply-by, a deadline, a
due date, goes on the work as `due` or `by`, on every class. An ambiguous date is a
question, never a guess.

**A calendar invitation is theirs to answer.** Never answer it for them: propose what
accepting means and let the card's yes be the acceptance. Make it `ready` with an `event`
for a new entry in the right diary, or an `update` on the event it moves, with `start` and
`end` from the invitation; the card shows Accept and Decline. Where whether they mean to go
is unclear, a `question` on the event instead. An invitation that settles an open question,
such as one about whether a meeting is still on, closes it: an `update` on
`question:<id>` with `status` `closed`, in the same work list.

**A standing rule wins.** Check `handling_rules` before the general judgement. Where an
active rule matches an item, its outcome is the outcome, and the reason says which rule. A
rule that files or flags is enforced by the engine whatever you write. A rule that asks for
work, `ready` or `yours`, is yours to honour, since only you can draft the work, and the
engine refuses a file that does not, naming the rule.

**Drafts sound like the person.** Short and friendly, in plain words. An email ends with
their first name; a chat does not sign off. Nothing goes out in their name without a yes,
which the card is for.

## The file

Five keys, all required, all lists:

- `consumed`: ids of answered questions folded in this run.
- `people`: what an answer taught about a person: `id`, and any of `name`, `pronouns`,
  `domain`, `role`, `trait`; a new id needs at least `name` and `domain`; `from` names the
  question, and must be in `consumed`.
- `senders`: what an answer taught about a sender: `sender` and `source` as the item carries
  them, `disposition` of `skip`, `watch` or `normal`, and optionally `person`, `note`, `from`.
  `skip` is for pure bulk only; when unsure, `watch`, or leave the sender alone rather than
  guess.
- `seen`: every item that was at the door, every item whose card was sent back, plus the
  items judged again after an answer.
- `items`: one entry per id in `seen`: `id`, `class`, `outcome`, `reason` in plain words
  written for the person, and `work`, a list. The reason is one sentence, two at most: what
  the door did and why, for someone who has the item in front of them. Never retell the
  item. "A newsletter, nothing in it needs you." "Chris has sent what he promised; a reply
  and a slot before stand-up are ready." On anything the person reads, a commitment is a
  promise, theirs or yours, never a loop: "loop" is the engine's word and means nothing to
  them.

## The kinds of work

Each entry in `work` has a `kind` and the fields for that kind, and nothing else.

- **task** `{title, domain, priority?, due?, notes?}`. `domain` is `work`, `family` or
  `personal`; `priority` 1, 2 or 3, 2 by default. A row in tasks when approved.
- **event** `{title, calendar, start, end? or minutes?, notes?}`. `calendar` is `work`,
  `family` or `personal`; `start` needs a time; with neither `end` nor `minutes`, an hour.
  A diary entry when approved.
- **reply** `{body, by?}`. Sent in the thread it came from when approved. Recipient, subject
  and thread come from the item, so the entry carries none of them.
- **forward** `{to, note?}`. The item passed to a person, `to` an id in people, when approved.
- **email** `{to, subject, body}`. A fresh email outside any thread, `to` an id in people,
  sent when approved. For "write to Jordan and tell her" in a note; a reply to something
  that arrived is a `reply`.
- **rule** `{scope, pattern, outcome, action, source?}`. A house rule, written when
  approved. `scope` is `sender`, `domain` or `subject`; `outcome` is `skip`, `filed`,
  `headsup`, `ready`, `yours` or `auto`; `skip` needs `source`. `action` is the rule in the
  person's words. `auto` means: when a matching item is ready, do the work without asking.
  Propose it only when the person said so in those words, "send my replies to Riley without
  asking", "book it if my diary is free", never on your own judgement; the yes on the rule
  card is the one time they are asked.
- **update** `{target, changes}`. A change to something that exists, when approved. `target`
  is `task:<id>`, `event:<id>`, `commitment:<id>` or `question:<id>`. `changes` names only
  these fields: on a task `title`, `due`, `priority`, `status` (`open` or `done`), `notes`; on
  an event `title`, `start`, `end`, `notes`; on a commitment `status` (`open` or `closed`),
  `due`, `what`; on a question only `status` `closed`, for a question the item settled without
  an answer to fold in.
- **commitment** `{owner, person, what, due?}`. `owner` is `me` or `them`; `person` an id in
  people. A loop held when approved.
- **person** `{id, name?, pronouns?, domain?, role?, trait?}`. A profile added or changed
  when approved; a new id needs `name` and `domain`.
- **question** `{subject, question}`. Written at once, since asking changes nothing.
  `subject` is `kind:id` with kind one of `person`, `sender`, `task`, `event`,
  `commitment`, `item`, and an id the engine knows; for a sender, the sender text as the
  item carries it. One open question per subject ever stands.
- **choose** `{summary, candidates: [{what, owner, person?, due?}]}`. One card to pick from.
  What the person picks becomes a task when its owner is `me` and a commitment when `them`.

## What an outcome may carry

`ready`: at least one of task, event, reply, forward, update, commitment, person. `yours`:
exactly one question or one choose. `headsup` and `filed`: no work; the reason carries what
there is to know.

## Dates

ISO as the database holds them, `2026-09-16` or `2026-09-16T09:00`, or a weekday with an
optional time, `Wednesday` or `Wednesday 09:00`, meaning that day of the week that starts
at `week_start` in `state`.

## The closed lists

- Classes: `memo-to-task`, `file-newsletter`, `notice-to-task`, `notice-to-diary`,
  `reply-needed`, `answer-to-a-loop`, `family-logistics`, `nothing-to-do`, `promise-made`,
  `meeting-actions`, `worth-knowing`, `house-rule`.
- Outcomes: `ready`, `yours`, `headsup`, `filed`.
- Kinds: `task`, `event`, `reply`, `forward`, `email`, `update`, `commitment`, `person`, `rule`,
  `question`, `choose`.

## What the engine refuses

The whole file, with nothing written: a key it does not know or one of the five missing; a
`seen` that misses an item at the door or one that was sent back, or names one that was
neither at the door, nor sent back, nor re-opened by an answer; an entry not in `seen` or a `seen` id without an entry; a class,
outcome or kind outside the lists; work that does not fit its outcome; a person, target,
consumed id or `from` that does not exist; a field it does not allow; a subject that is not
`kind:id` with a known id, or that was already answered; an id on anything new.

## A minimal file

```json
{"consumed": [], "people": [], "senders": [],
 "seen": ["01-monday-morning-02"],
 "items": [{"id": "01-monday-morning-02", "class": "file-newsletter", "outcome": "filed",
            "reason": "A newsletter. Nothing in it needs you.", "work": []}]}
```
