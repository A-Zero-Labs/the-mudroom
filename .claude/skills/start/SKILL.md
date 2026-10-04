---
name: start
description: Start the Mudroom. Starts the local server in the background and opens the front door in the browser. Use when the user says start, open the mudroom, run it, or has just cloned the repository and wants to see it.
---

# Start

You start the Mudroom's server and open it in the browser. Nothing else: no reset, no
sorting, no questions. If the person has never run it, the server sets the invented week up
on its own before it opens.

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

- `python` not found: try `python3`. If neither is found, say that Python 3.10 or newer is
  needed, and where to get it.
- A port error or an address that is not 8765: say which address it is on; a server from an
  earlier session may still be holding 8765, which is fine.
- Anything else: show the last lines it printed and stop. Do not try to fix the engine.

## Never

- Never reset the week from here. `python mudroom.py reset` is the person's call, and the
  Doorstep has a button for it.
- Never run the sorting from here. The Doorstep's button does that.
