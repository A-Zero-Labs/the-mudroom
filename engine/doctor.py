"""Is this machine ready for the Mudroom? Each check says what it found and, when something is
missing, what fixes it on this operating system. Read-only apart from one throwaway file that
proves the folder can be written to. The /start skill runs this first; anyone can run it as
`python mudroom.py doctor`.

Output stays plain ASCII: a Windows console on an old code page cannot print much else."""
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile

from . import ROOT
from .agents import executable

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
PORT = 8765


class Check:
    def __init__(self, name, ok, found, fix="", required=True):
        self.name, self.ok, self.found, self.fix, self.required = name, ok, found, fix, required


def python_check():
    v = sys.version_info
    found = f"Python {v.major}.{v.minor}.{v.micro} at {sys.executable}"
    # mudroom.py already refuses anything older than 3.10, so reaching here means it is fine
    return Check("Python 3.10 or newer", v >= (3, 10), found, install_python())


def install_python():
    if WINDOWS:
        return ("winget install -e --id Python.Python.3.12, then close and reopen Claude Code so it "
                "sees the new PATH. Or the installer from python.org with 'Add python.exe to PATH' ticked.")
    if MAC:
        return "brew install python@3.12, or the installer from python.org."
    return "sudo apt install python3 (Debian, Ubuntu), or your distribution's python3 package."


def sqlite_check():
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("SELECT json('{}')").fetchone()
        conn.close()
        return Check("SQLite (built into Python)", True, f"SQLite {sqlite3.sqlite_version}")
    except Exception as e:  # a stripped-down Python can lack it or its JSON functions
        return Check("SQLite (built into Python)", False, f"not usable: {e}",
                     "Install Python from python.org or your package manager; some trimmed-down "
                     "builds leave SQLite out.")


def command_check():
    """The headless sorting is allowed to run `python mudroom.py` or `python3 mudroom.py` and
    nothing else, so one of those two names has to reach a real Python. On Windows the
    Microsoft Store puts a stub called python.exe on the PATH that only opens the Store."""
    usable = []
    for name in ("python", "python3"):
        path = shutil.which(name)
        if path and not store_stub(path) and answers(path):
            usable.append(f"{name} ({path})")
    if usable:
        return Check("A 'python' or 'python3' command", True, ", ".join(usable))
    if WINDOWS:
        fix = ("Install Python with winget (see above) and reopen Claude Code. If 'python' still opens "
               "the Microsoft Store: Settings > Apps > Advanced app settings > App execution aliases, "
               "switch off python.exe and python3.exe.")
    else:
        fix = "Install Python so that python3 is on the PATH; " + install_python()
    return Check("A 'python' or 'python3' command", False,
                 "neither name reaches a working Python (the sorting runs through one of them)", fix)


def store_stub(path):
    return WINDOWS and "windowsapps" in path.lower()


def answers(path):
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
        return done.returncode == 0 and "Python 3" in (done.stdout + done.stderr)
    except (OSError, subprocess.TimeoutExpired):
        return False


def claude_check():
    path = executable()
    if path is None:
        fix = ("Install Claude Code: https://claude.com/claude-code"
               + (" (on Windows: irm https://claude.ai/install.ps1 | iex in PowerShell)" if WINDOWS else ""))
        return Check("Claude Code (the claude command)", False, "not found on the PATH", fix)
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
        version = (done.stdout or done.stderr).strip().splitlines()[0] if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired, IndexError):
        version = ""
    if not version:
        return Check("Claude Code (the claude command)", False, f"found at {path} but it did not answer",
                     "Run claude update, or reinstall Claude Code.")
    return Check("Claude Code (the claude command)", True, f"{version} at {path}",
                 "If sorting later says the model is refused, run claude update.")


def git_bash_check():
    """Claude Code on Windows runs shell commands through Git Bash, which comes with Git for
    Windows, and the sorting is only allowed to run mudroom.py through that shell. Without
    it the sorting cannot run, so it is required."""
    if not WINDOWS:
        return None
    found = shutil.which("git") or git_bash_on_disk()
    return Check("Git for Windows (Git Bash)", bool(found), found or "not found",
                 "winget install -e --id Git.Git, then reopen Claude Code.")


def git_bash_on_disk():
    for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            for sub in (("Git", "bin", "bash.exe"), ("Programs", "Git", "bin", "bash.exe")):
                path = os.path.join(base, *sub)
                if os.path.exists(path):
                    return path
    return None


def folder_check():
    try:
        with tempfile.NamedTemporaryFile(dir=ROOT, prefix=".doctor-", delete=True):
            pass
        return Check("This folder can be written to", True, str(ROOT))
    except OSError as e:
        return Check("This folder can be written to", False, f"{ROOT}: {e}",
                     "Clone the Mudroom into a folder you own, such as your Documents, not Program Files "
                     "or a synced folder that locks files.")


def port_check(port=PORT):
    for candidate in range(port, port + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidate))
                note = "" if candidate == port else f" ({port} is taken, likely an earlier Mudroom; fine)"
                return Check("A free local port", True, f"{candidate}{note}")
            except OSError:
                continue
    return Check("A free local port", False, f"{port} to {port + 9} are all taken",
                 "Close earlier Mudroom windows or servers, or start with --port and another number.",
                 required=False)


def checks():
    found = [python_check(), sqlite_check(), command_check(), claude_check(), git_bash_check(),
             folder_check(), port_check()]
    return [c for c in found if c is not None]


def report(results=None):
    """The checks as text, and whether everything required passed."""
    results = checks() if results is None else results
    lines = [f"Checking this machine ({platform.system()} {platform.release()}):"]
    for c in results:
        mark = "ok  " if c.ok else ("FIX " if c.required else "WARN")
        lines.append(f"  [{mark}] {c.name}: {c.found}")
        if not c.ok and c.fix:
            lines.append(f"         fix: {c.fix}")
    ready = all(c.ok for c in results if c.required)
    lines.append("Ready to start." if ready else "Not ready yet: fix the lines marked FIX, then run this again.")
    return "\n".join(lines), ready
