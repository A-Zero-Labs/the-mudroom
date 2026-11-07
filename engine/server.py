"""A small local server. Every page is rendered from the database on request."""
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import json

from . import ROOT, agents, clock, db, decide, demo, lock, pages

STATIC = ROOT / "engine" / "static"
PAGES = {"/": pages.welcome, "/piping": pages.landing, "/whats-next": pages.whats_next, "/planner": pages.planner,
         "/doorstep": pages.doorstep, "/sorted": pages.checkin, "/log": pages.log}
TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
# Demo scaffolding: the Doorstep's buttons. Both go when the demo data does.
POSTS = {"/demo/next": demo.run, "/demo/judge": agents.judge_in_background, "/demo/reset": demo.start_over}
# The cards: what a person does on the Sorting dashboard. Each takes the form's fields and the engine's now.
CARDS = {"/card/approve": lambda conn, f, now: decide.approve(conn, one(f, "id"), now),
         "/card/decline": lambda conn, f, now: decide.decline(conn, one(f, "id"), now),
         "/card/send-back": lambda conn, f, now: decide.send_back(conn, one(f, "id"), one(f, "words"), now),
         "/card/done": lambda conn, f, now: decide.done(conn, one(f, "id"), now),
         "/card/ignore": lambda conn, f, now: decide.ignore(conn, one(f, "id"), now),
         "/card/answer": lambda conn, f, now: decide.answer(conn, one(f, "id"), one(f, "answer"), now),
         "/card/choose": lambda conn, f, now: decide.choose(conn, one(f, "id"), f.get("pick", []), now),
         "/card/file-all": lambda conn, f, now: decide.file_all(conn, now),
         "/card/done-all": lambda conn, f, now: decide.done_all(conn, now),
         "/question/answer": lambda conn, f, now: decide.answer_question(conn, one(f, "id"), one(f, "answer"), now),
         "/promise/close": lambda conn, f, now: decide.close_promise(conn, one(f, "id"), one(f, "how"), now)}
# The planner's tick boxes. Same door, back to the planner.
TICKS = {"/task/tick": lambda conn, f, now: decide.tick(conn, one(f, "id"), now),
         "/task/untick": lambda conn, f, now: decide.untick(conn, one(f, "id"), now)}
# The note box: a new thought goes to the door, so the page that follows is the Doorstep.
NOTES = {"/note": lambda conn, f, now: decide.leave_note(conn, one(f, "text"), now)}
# House rules: taught from a card, removed from the panel.
RULES = {"/rule/from-now-on": lambda conn, f, now: decide.from_now_on(conn, one(f, "id"), one(f, "choice"), now),
         "/rule/retire": lambda conn, f, now: decide.retire_rule(conn, one(f, "id"), now),
         "/rule/read-again": lambda conn, f, now: decide.read_again(conn, one(f, "source"), one(f, "sender"), now)}


def one(fields, key):
    return (fields.get(key) or [None])[0]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/static/"):
            self.serve_static(path)
            return
        if path == "/run-state":
            conn = db.connect()
            try:
                held = lock.held(conn) is not None
            finally:
                conn.close()
            self.respond(200, json.dumps({"held": held}).encode("utf-8"), "application/json")
            return
        if path in ("/check-in", "/how-it-works"):
            self.redirect({"/check-in": "/sorted", "/how-it-works": "/piping"}[path])   # old names
            return
        page = PAGES.get(path)
        if page is None:
            self.send_error(404, "Not in the mudroom")
            return
        conn = db.connect()
        try:
            body = page(conn, parse_qs(parsed.query))
        finally:
            conn.close()
        self.respond(200, body.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if path in CARDS:
            self.on_card(CARDS[path], "/sorted")
            return
        if path in TICKS:
            self.on_card(TICKS[path], "/planner")
            return
        if path in NOTES:
            self.on_card(NOTES[path], "/doorstep")
            return
        if path in RULES:
            self.on_card(RULES[path], "/log")
            return
        action = POSTS.get(path)
        if action is None:
            self.send_error(404, "Not in the mudroom")
            return
        action()
        self.redirect("/doorstep")

    def on_card(self, action, back):
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        conn = db.connect()
        try:
            action(conn, fields, clock.now(conn))
        except decide.Refused as why:
            self.send_error(409, str(why))
            return
        finally:
            conn.close()
        self.redirect(back)

    def redirect(self, where):
        self.send_response(303)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def serve_static(self, path):
        file = (STATIC / path[len("/static/"):]).resolve()
        if not file.is_file() or STATIC.resolve() not in file.parents:
            self.send_error(404)
            return
        self.respond(200, file.read_bytes(), TYPES.get(file.suffix, "application/octet-stream"))

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # the console is for the play, not for request lines


def serve(port=8765, open_browser=True):
    server = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"No free port between {port} and {port + 9}.")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"The Mudroom is open at {url}", flush=True)
    print("Press Ctrl+C to close it.", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nClosed.")
    finally:
        server.server_close()
