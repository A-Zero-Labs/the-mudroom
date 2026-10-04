"""The Mudroom's engine: the deterministic part. Standard library and SQLite only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "world"
DB_PATH = ROOT / "mudroom.db"

# What can happen to something, as stored and as shown. Nothing in the Mudroom ever
# reaches outside it without a person saying so.
OUTCOMES = {
    "ready": "Ready for you",      # the work is done, waiting on your yes
    "yours": "Needs your input",   # no answer given, the decision is yours
    "headsup": "Heads-up",         # nothing to do, and you should still know
    "filed": "Filed away",         # nothing was needed, recorded with the reason
}

# What kind of thing an item is, as a closed list. A judgement naming anything else is
# refused.
CLASSES = (
    "memo-to-task",
    "file-newsletter",
    "notice-to-task",
    "notice-to-diary",
    "reply-needed",
    "answer-to-a-loop",
    "family-logistics",
    "nothing-to-do",
    "promise-made",       # a promise spotted in what someone wrote, in either direction
    "meeting-actions",    # what a transcript turned up, gathered onto one card
    "worth-knowing",      # nothing to do, and still worth a heads-up
    "house-rule",         # the person saying how to treat a kind of thing from now on
)

# What a judgement can propose, as a closed list. The learn-evaluate skill says what each
# one carries and what it becomes.
KINDS = (
    "task", "event", "reply", "forward", "email", "update", "commitment", "person",
    "rule", "question", "choose",
)
