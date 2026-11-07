"""The two agents, run by the person's own Claude.

The engine never judges. When a run needs the Learning Agent and the Evaluation Agent, it
starts Claude Code in headless mode, on this repo, with the learn-evaluate skill, allowed to
run mudroom.py and to write handover.json, and nothing else: the file and search tools are
taken away, so the model reads only what the engine prints. What the model does
with that is the skill's business. What it can touch is settled here, in the allowlist,
where no prompt can argue with it. The Doorstep's button and the run command both come
through here, and so will a scheduler.
"""
import json
import os
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from . import ROOT, db, lock

PROMPT = "/learn-evaluate"   # the skill, loaded by Claude Code itself, so no file is read to find it
# an Edit rule covers every file-writing tool; python3 for a machine with no python command
ALLOWED = ("Edit(handover.json)", "Bash(python mudroom.py:*)", "Bash(python3 mudroom.py:*)")
# The demo's source, the same way: it may run the parser and the engine, and write the two
# files the parser and intake take. Demo scaffolding; it leaves with the demo.
SOURCE_PROMPT = "/source-demo"
SOURCE_ALLOWED = ("Edit(replies.json)", "Edit(handoff.json)", "Bash(python mudroom.py:*)",
                  "Bash(python3 mudroom.py:*)", "Bash(python rounds/source.py:*)",
                  "Bash(python3 rounds/source.py:*)")
DISALLOWED = ("Read", "Grep", "Glob", "WebFetch", "WebSearch", "PowerShell", "Agent", "Task")
LOG = ROOT / "run.log"           # what the judge said
SOURCE_LOG = ROOT / "source.log"   # what the source said
TIMEOUT = 900


def executable():
    """The claude command, or None. MUDROOM_CLAUDE names one explicitly, for a machine that
    keeps several; otherwise PATH, then the usual install folder."""
    named = os.environ.get("MUDROOM_CLAUDE")
    if named and Path(named).exists():
        return named
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude.cmd", "claude"):
        candidate = Path.home() / ".local" / "bin" / name
        if candidate.exists():
            return str(candidate)
    return None


def nothing_to_do(conn):
    staged = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'staged'").fetchone()[0]
    answered = conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'answered'").fetchone()[0]
    sent_back = conn.execute("SELECT COUNT(*) FROM proposals WHERE status = 'sent_back'").fetchone()[0]
    return not staged and not answered and not sent_back


def judge(timeout=TIMEOUT, owned=False):
    """Run the agents once and wait for them. Returns (ok, message), and records both.
    A run already in flight is left alone, unless owned says this call is that run, which
    is the case when intake set the lock a moment ago on the same press."""
    conn = db.connect()
    try:
        if not owned and lock.held(conn):
            return False, "A run is already in flight. Wait for it to finish."
        if nothing_to_do(conn):
            # the run ends here, with nothing for processing to clear the lock
            return finish(conn, True, "Nothing at the door and nothing to fold in.", over=True)
        claude = executable()
        if claude is None:
            return finish(conn, False, "Claude Code is not installed here, so nothing sorted what is at "
                                       "the door. Run /learn-evaluate in Claude Code, or install the "
                                       "claude command.")
        with conn:
            lock.begin(conn)
            db.set_state(conn, "last_run", json.dumps({"at": stamp(), "ok": None, "message": "in flight"}))
    finally:
        conn.close()
    failed = not headless(claude, PROMPT, ALLOWED, timeout, "The judgement")
    conn = db.connect()
    try:
        if failed:
            return finish(conn, False, explain_failure())
        if lock.held(conn):
            return finish(conn, False, "The sorting ended without handing anything to process. "
                                       "run.log has what Claude said.")
        return finish(conn, True, "Sorted. The Sorting dashboard has it.")
    finally:
        conn.close()


def headless(claude, prompt, allowed, timeout, what, log=LOG):
    """One headless run of Claude Code on this repo with a skill and an allowlist. What it
    said goes to the log named. True when it ended cleanly."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    cmd = [claude, "-p", prompt, "--output-format", "text",
           "--allowedTools", *allowed, "--disallowedTools", *DISALLOWED]
    try:
        done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        log.write_text(f"$ claude {' '.join(cmd[1:])}\n\n{done.stdout}\n{done.stderr}\nexit {done.returncode}\n",
                       encoding="utf-8")
        return done.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        log.write_text(f"{what} did not finish: {e}\n", encoding="utf-8")
        return False


def source(timeout=TIMEOUT):
    """The demo's source, run by the person's Claude: the cast answers what was sent, the
    next batch comes in through intake. The caller holds the lock. Returns (ok, message)."""
    claude = executable()
    if claude is None:
        return False, "Claude Code is not installed here, so nothing came to the door."
    conn = db.connect()
    try:
        before = conn.execute("SELECT COUNT(*) FROM actions WHERE action = 'intake'").fetchone()[0]
    finally:
        conn.close()
    ok = headless(claude, SOURCE_PROMPT, SOURCE_ALLOWED, timeout, "The source", SOURCE_LOG)
    conn = db.connect()
    try:
        after = conn.execute("SELECT COUNT(*) FROM actions WHERE action = 'intake'").fetchone()[0]
        if not ok:
            return finish(conn, False, explain_failure(SOURCE_LOG).replace("sorted what is at the door", "brought anything in")
                          .replace("The sorting failed. run.log", "The source failed. source.log"))
        if after == before:
            return finish(conn, True, "Nothing more this week to bring in.")
        return True, "Brought in."
    finally:
        conn.close()


def explain_failure(log=LOG):
    """What the log says, in one line a person can act on."""
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    if "version_too_old" in text or "claude update" in text:
        return "Claude Code is out of date, so nothing sorted what is at the door. Run claude update, then try again."
    if "not logged in" in text.lower() or "please run /login" in text.lower():
        return "Claude Code is not logged in, so nothing sorted what is at the door. Run claude and log in, then try again."
    return "The sorting failed. run.log has what Claude said."


def finish(conn, ok, message, over=False):
    """Record how the run ended. A failed run, or one with nothing to process, lets go of the
    lock here; a good run's lock is cleared by processing."""
    with conn:
        if not ok or over:
            lock.end(conn)
        db.set_state(conn, "last_run", json.dumps({"at": stamp(), "ok": ok, "message": message}))
    return ok, message


def judge_in_background(owned=False):
    threading.Thread(target=judge, kwargs={"owned": owned}, daemon=True).start()


def last_run(conn):
    raw = db.get_state(conn, "last_run")
    return json.loads(raw) if raw else None


def stamp():
    return datetime.now().isoformat(timespec="seconds")
