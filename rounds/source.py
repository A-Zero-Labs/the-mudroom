#!/usr/bin/env python3
"""The invented week: the demo's source. Its data is the batch files beside this script, and
this is its parser, the demo's own code, which leaves with the demo.

    python rounds/source.py next --week 2026-09-14 --after 01-monday-morning

prints the batch after the one named, as a handoff in the shape the Intake Engine takes, or
{"done": true} when the week has no batch left. Leave out --after for the first batch.
--replies names a JSON list the source skill wrote, the cast's answers to what the person
sent, and they go into the same batch; `cast` prints the cast file those answers follow.

A batch is one Markdown file. It opens with a title line and the slot it plays at, then one
section per item:

    # Monday morning

    day: 0
    time: 08:30

    ## email from Jordan
    subject: Update and a date
    at: 07:52

    Alex, can I get the project update before two?

The heading names the source (email, chat, transcript, capture, calendar) and the sender.
Header lines follow until the first blank line; the rest is the body as it arrived. Days
count from Monday, so day 0 is Monday and day -1 is last Sunday. Reset stamps the week.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = {"email", "chat", "transcript", "capture", "calendar"}


def stamp(start, day, time=None):
    """A day offset from Monday and an optional HH:MM, as an ISO string."""
    d = start + timedelta(days=day)
    if time is None:
        return d.isoformat()
    hours, minutes = time.split(":")
    return datetime(d.year, d.month, d.day, int(hours), int(minutes)).isoformat(timespec="minutes")


def parse(path):
    """Read one batch file. Returns (header, items)."""
    header = {"title": path.stem}
    items = []
    current = None
    in_headers = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            source, _, sender = line[3:].strip().partition(" from ")
            source = source.strip().lower()
            if source not in SOURCES:
                raise ValueError(f"{path.name}: unknown source '{source}' in heading '{line.strip()}'")
            current = {"source": source, "sender": sender.strip(), "headers": {}, "lines": []}
            items.append(current)
            in_headers = True
            continue
        if current is None:
            if line.startswith("# "):
                header["title"] = line[2:].strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                header[key.strip().lower()] = value.strip()
            continue
        if in_headers:
            if not line.strip():
                in_headers = False
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                current["headers"][key.strip().lower()] = value.strip()
                continue
            in_headers = False
        current["lines"].append(line)
    for item in items:
        item["body"] = "\n".join(item.pop("lines")).strip("\n")
    return header, items


def handoff(path, start, replies=None):
    """One batch as the handoff the Intake Engine takes, with the cast's replies in it when
    the source skill wrote any."""
    header, items = parse(path)
    day = int(header.get("day", 0))
    slot = stamp(start, day, header.get("time", "08:30"))
    batch_id = path.stem
    out = []
    for n, item in enumerate(items, 1):
        heads = item["headers"]
        received = stamp(start, int(heads.get("day", day)), heads.get("at", header.get("time", "08:30")))
        out.append({"id": f"{batch_id}-{n:02d}", "source": item["source"], "sender": item["sender"],
                    "subject": heads.get("subject"), "body": item["body"], "received_at": received,
                    "thread": heads.get("thread"), "raw": heads})
    out.extend(reply_items(replies or [], start, day, batch_id))
    return {"source": "rounds", "account": "world", "label": header["title"], "now": slot,
            "cursor": slot, "last_seen_id": batch_id, "items": out}


def replies_only(start, after, clock, replies):
    """The cast's replies on their own, once the week has no batch left. The bookmark stays
    where it was, and the clock does not move."""
    day = (date.fromisoformat(clock[:10]) - start).days if clock else 0
    # the engine's clock stands still once the week is done, so the ids take the wall clock
    prefix = f"{after or 'week'}-cast-{datetime.now():%Y%m%d%H%M%S}"
    return {"source": "rounds", "account": "world", "label": "The cast answers", "now": None,
            "cursor": clock, "last_seen_id": after, "items": reply_items(replies, start, day, prefix)}


REPLY_FIELDS = {"source", "sender", "subject", "body", "at", "day", "thread", "channel", "kind", "to"}


def reply_items(replies, start, day, prefix):
    """The cast's replies in the common shape. Each names its source, sender, body and time,
    and the sent item it answers as thread; the parser mints the ids and stamps the dates."""
    out = []
    for n, r in enumerate(replies, 1):
        if not isinstance(r, dict):
            raise ValueError(f"reply {n} is not an object")
        extra = sorted(set(r) - REPLY_FIELDS)
        if extra:
            raise ValueError(f"reply {n} carries {extra}, which the shape does not take")
        if r.get("source") not in SOURCES:
            raise ValueError(f"reply {n}: source must be one of {', '.join(sorted(SOURCES))}")
        for k in ("sender", "body", "at"):
            if not isinstance(r.get(k), str) or not r[k].strip():
                raise ValueError(f"reply {n} needs {k}")
        heads = {k: r[k] for k in ("subject", "at", "channel", "kind", "to") if r.get(k)}
        heads["cast"] = True
        out.append({"id": f"{prefix}-r{n:02d}", "source": r["source"], "sender": r["sender"].strip(),
                    "subject": r.get("subject"), "body": r["body"].strip("\n"),
                    "received_at": stamp(start, int(r.get("day", day)), r["at"]),
                    "thread": r.get("thread"), "raw": heads})
    return out


def next_file(folder, after):
    """The batch after the one named, or the first when none is named."""
    files = sorted(folder.glob("[0-9][0-9]-*.md"))   # the batches; cast.md is not one
    if after is None:
        return files[0] if files else None
    return next((f for f in files if f.stem > after), None)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rounds/source.py", description="the invented week, as a source")
    sub = parser.add_subparsers(dest="command", required=True)
    nxt = sub.add_parser("next", help="the next batch as a handoff")
    nxt.add_argument("--week", required=True, help="the week's Monday, YYYY-MM-DD")
    nxt.add_argument("--after", default=None, help="the last batch brought in; leave out for the first")
    nxt.add_argument("--dir", default=str(HERE), help="where the batch files are")
    nxt.add_argument("--replies", default=None, help="the cast's replies, a JSON list the source skill wrote")
    nxt.add_argument("--clock", default=None, help="the engine's now, for replies once the week is done")
    sub.add_parser("cast", help="print the cast, for whoever plays them")
    args = parser.parse_args(argv)
    if args.command == "cast":
        print((Path(HERE) / "cast.md").read_text(encoding="utf-8"))
        return 0
    replies = json.loads(Path(args.replies).read_text(encoding="utf-8")) if args.replies else []
    if not isinstance(replies, list):
        print(json.dumps({"error": "replies must be a JSON list"}))
        return 2
    start = date.fromisoformat(args.week)
    path = next_file(Path(args.dir), args.after)
    if path is None and replies:
        print(json.dumps(replies_only(start, args.after, args.clock, replies), ensure_ascii=False, indent=1))
        return 0
    if path is None:
        print(json.dumps({"done": True, "message": "Nothing more this week. Run 'python mudroom.py reset' to play it again."}))
        return 0
    print(json.dumps(handoff(path, start, replies), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
