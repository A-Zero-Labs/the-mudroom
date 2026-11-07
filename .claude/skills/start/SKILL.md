---
name: start
description: Start the Mudroom. Starts the local server in the background and opens the front door in the browser. Use when the user says start, open the mudroom, run it, or has just cloned the repository and wants to see it.
---

# Start

You check the machine, start the Mudroom's server and open it in the browser. Nothing else:
no reset, no sorting. If the person has never run it, the server sets the invented week up
on its own before it opens.

## First, check the machine

Someone trying the Mudroom for the first time may not have Python yet, or may have one that
the Windows Store is hiding. Find out before starting anything, and help them get it right.

1. On Windows, also check for Git: `git --version`. Claude Code runs its commands through
   Git Bash, which comes with Git for Windows, and the sorting cannot run without it. If
   Python is missing too, offer both installs together, so one restart covers them.
2. Find a working Python. Try `python --version`, then `python3 --version`, and on Windows
   also `py -3 --version`. A version of 3.12 or newer counts. A message about the Microsoft
   Store, or no version at all, does not: that is the Store's stand-in, not Python.
3. With one found, run `<that command> mudroom.py doctor`. It checks Python, SQLite, a
   `python` or `python3` command the sorting can use, Claude Code, that the folder can be
   written to, and a free port. It prints `Ready to start.` or lines marked `FIX`, each with
   the fix for this operating system. `WARN` lines are worth a mention and do not block.
4. All ready: go on to the run, without reporting the checks one by one.
5. Something to fix, or no Python at all: say in plain words what is missing and why the
   Mudroom needs it, then offer to do it for them. Install only after they say yes, one
   thing at a time, and show the command before running it:
   - Windows, Python: `winget install -e --id Python.Python.3.12`.
   - Windows, Git for Windows: `winget install -e --id Git.Git`. Required, not optional.
   - Windows, `python` opens the Microsoft Store even with Python installed: they switch it
     off themselves under Settings > Apps > Advanced app settings > App execution aliases
     (python.exe and python3.exe). Walk them through it; it is not a command.
   - Mac: `brew install python@3.12` if Homebrew is there; otherwise the installer from
     python.org, which they run themselves.
   - Linux: `sudo apt install python3` or the distribution's own package, where that gives
     3.12 or newer; they type the password themselves. An older system needs a newer
     Python from python.org.
   - Claude Code too old: `claude update`.
   If winget or brew is missing, or an install fails, give the python.org link
   (https://www.python.org/downloads/) and say to tick "Add python.exe to PATH" on Windows.
6. After installing Python or Git on Windows, this Claude Code session still has the old
   PATH. Say so: close Claude Code, open it again in this folder, and say `/start` once more.
   Do not carry on with a Python found by its full path; the sorting needs the plain command.
7. Never install anything without a yes, never change system settings yourself, and never
   touch the engine to get round a missing piece.

## The run

1. Start the server in the background, so this conversation stays free:
   `python mudroom.py serve`, or `python3 mudroom.py serve` where that is the command. Use the
   shell's background mode; the command runs until the
   browser tab is closed and the process is stopped. It prints the address it is open at,
   `http://127.0.0.1:8765/` unless that port was taken, in which case the next free one.
2. Read the address from what it printed and say it in one line. The server opens a browser
   tab on that address itself; if no tab appeared, give the address to open by hand.
3. Say what to do next, in one line: the front door explains the two things you can do, and
   "Play the demo" takes you to the Doorstep, where the week begins.

## If it does not start

- `python` not found: the check above should have caught it; go back to it.
- A port error or an address that is not 8765: say which address it is on; a server from an
  earlier session may still be holding 8765, which is fine.
- Anything else: show the last lines it printed and stop. Do not try to fix the engine.

## Never

- Never reset the week from here. `python mudroom.py reset` is the person's call, and the
  Doorstep has a button for it.
- Never run the sorting from here. The Doorstep's button does that.
