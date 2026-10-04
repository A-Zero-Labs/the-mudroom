---
name: source-demo
description: The demo's source. Plays the cast's answers to what the person sent, brings the invented week's next batch to the Mudroom's door through the same intake a real source uses, and judges nothing. Use when the user asks to bring the next batch in, play the next intake, or start the next part of the day.
---

# The demo's source

You are a source skill. A source fetches what is new, flattens it to the common shape, and
hands it to the engine, which registers it, checks the sender list, logs the skips and moves
the bookmark. The invented week is your data, in `rounds/`, and `rounds/source.py` is your
parser. Judging is `/learn-evaluate`'s, after you. `python` below means this machine's Python 3; where only `python3` exists, use that.

The invented week has a cast, and a real mailbox answers back. So before you bring the
next batch in, you play the cast: you read what the person sent since the last batch and
write what each of those people would send back, as themselves. Those answers arrive in
the same batch as the scripted items.

## Never

- Never open a file, search the repo, or read the database yourself. Two commands print
  everything: `python mudroom.py show` and `python rounds/source.py`. Nothing else is
  needed, and nothing else is allowed.
- Never write items, the clock or the bookmark yourself. The engine does all three from the
  handoff.
- Never judge, and never touch `handover.json`. That is the other skill's.
- Never skip a batch, reorder the week or change what a batch says. The week is data.
- Never bring in more than one batch in a run. One batch, then the judge; the engine refuses
  a second, and the week is played a batch at a time on purpose.
- Never write as the person, and never let the cast settle the week early or contradict
  what the cast file says the week holds.

## The run

1. `python mudroom.py intake --bookmark rounds world` prints how far this source got:
   `last_seen_id` is the last batch brought in, null on a fresh week; `checked_at` is when;
   `week_start` is the week's Monday; `clock` is the engine's now.
2. `python rounds/source.py next --week <week_start> --after <last_seen_id>` prints the
   next batch as a handoff, so you know its slot and what it brings. Leave `--after` out
   when `last_seen_id` is null. `"done": true` means the week has no batch left.
3. `python mudroom.py show items status=sent` prints what the person sent through the
   mudroom: replies, forwards and emails, each with `thread` naming the item it answered and
   `received_at` saying when. `python mudroom.py show actions action=accept` prints the
   invitations they accepted, and `show actions action=decline` those declined, `at` saying
   when. Anything with a time after `checked_at` is new since the last batch. If nothing is
   new, skip to step 6.
4. `python rounds/source.py cast` prints the cast: who each person is, how they write, what
   the week holds, and how they take what the person sends. Read it as a script.
5. For each new thing, decide whether its recipient answers, and write the answer in that
   person's voice, at a plausible time between `checked_at` and the coming batch's slot. Put
   them in `replies.json` as a list, each entry in the shape the parser takes:

   ```json
   [{"source": "email", "sender": "Jordan", "subject": "Re: Update and a date",
     "at": "13:40", "thread": "sent-1",
     "body": "Fine. Send me the range by Tuesday evening then.\n\nJordan"}]
   ```

   `source` is the source the person used, `sender` the cast member's name as the batch
   files write it, `thread` the id of the sent item being answered, `at` the time. A chat
   carries `channel` as the original did. The sent items you already have hold everything
   you need. Nobody answers a thank-you, and a newsletter, a notice or a service desk never
   answers.
6. `python rounds/source.py next --week <week_start> --after <last_seen_id> --replies replies.json > handoff.json`
   writes the batch with the cast's answers in it. Leave `--replies` out when nothing was
   new. When the week is done and there are replies, the parser hands over the replies on
   their own; when it is done and there are none, say so, and that `python mudroom.py
   reset` plays the week again.
7. `python mudroom.py intake handoff.json` registers it. If intake refuses, it names every
   problem; that means the parser and the engine disagree, which is a bug to report, never
   something to patch in the file.
8. Report what intake printed, in a sentence, and which of the cast answered, and say
   `/learn-evaluate` is next.
