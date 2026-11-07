#!/usr/bin/env python3
"""The Mudroom: reads your mail, messages and notes once and sorts them into four piles.

  python mudroom.py reset     rebuild the week from the seed, stamped to this week
  python mudroom.py serve     open the dashboards in your browser
  python mudroom.py intake    register what a source skill fetched; the demo's is /source-demo
  python mudroom.py process   take handover.json into the database
  python mudroom.py learn-evaluate   run the two agents on what is at the door, through your Claude
  python mudroom.py run       the whole pass on demand: the next batch in, judged, processed
  python mudroom.py status    where the play stands
  python mudroom.py show      what the agents read: the tables, their rows, or one table filtered
  python mudroom.py doctor    is this machine ready: Python, SQLite, Claude Code, the folder, a port
"""
import argparse
import json
import sys

if sys.version_info < (3, 10):
    sys.exit("The Mudroom needs Python 3.10 or newer.")

from engine import agents, clock, db, demo, doctor, intake, process, server, show, status  # noqa: E402


def cmd_reset(args):
    start = demo.start_over()
    print(f"The house is in order. Week of Monday {clock.long_date(start)}, clock at Monday 08:00.")
    print("Run 'python mudroom.py serve' to open the dashboards.")


def cmd_start_clean(args):
    from engine import clean
    going = clean.what_goes()
    print("Start clean rebuilds the house empty, in your name, and removes the invented week:")
    for p in going:
        print(f"  {p.relative_to(clean.ROOT)}")
    if not going:
        print("  (nothing left to remove)")
    print("The engine, the pages, the judging skill and the tests stay.")
    if not args.yes:
        print("Run it again with --yes to go ahead. There is no way back but a fresh clone.")
        return
    removed = clean.start_clean(args.you)
    print(f"Done. The house is {args.you}'s now; {len(removed)} things removed.")
    print("Next: docs/make-it-yours.md, Writing a source skill.")


def cmd_intake(args):
    if not db.exists():
        print("Nothing set up yet. Run 'python mudroom.py reset' first.")
        return
    if args.bookmark:
        conn = db.connect()
        try:
            print(json.dumps(intake.bookmark(conn, args.bookmark[0], args.bookmark[1]), indent=1))
        finally:
            conn.close()
        return
    if not args.file:
        print("Intake registers what a source skill fetched: python mudroom.py intake <file>, or - for stdin.")
        print("The demo's source is the skill source-demo, which brings the week's next batch.")
        return
    sys.exit(intake.run(args.file))


def cmd_process(args):
    if not db.exists():
        print("Nothing set up yet. Run 'python mudroom.py reset' first.")
        return
    sys.exit(process.run(args.path))


def cmd_learn_evaluate(args):
    if not db.exists():
        print("Nothing set up yet. Run 'python mudroom.py reset' first.")
        return
    ok, message = agents.judge()
    print(message)
    sys.exit(0 if ok else 1)


def cmd_run(args):
    if not db.exists():
        print("Nothing set up yet. Run 'python mudroom.py reset' first.")
        return
    result = demo.run(wait=True)
    if result is False:
        print("A run is already in flight. Wait for it to finish.")
        sys.exit(1)
    ok, message = result
    print(message)
    sys.exit(0 if ok else 1)


def cmd_serve(args):
    if not db.exists():
        print("No week set up yet, so resetting first.")
        cmd_reset(args)
    server.serve(port=args.port, open_browser=not args.no_browser)


def cmd_show(args):
    """Read-only. No table named: every table with its row count. Tables named: their rows, one
    JSON row per line under a heading. One table with column=value filters: the rows that match."""
    if not db.exists():
        print("Nothing set up yet. Run 'python mudroom.py reset' first.")
        return
    tokens = args.tables
    filters = dict(t.split("=", 1) for t in tokens if "=" in t)
    wanted = [t for t in tokens if "=" not in t]
    conn = db.connect()
    try:
        if not wanted:
            for name, n in show.counts(conn).items():
                print(f"{n:>6}  {name}")
            return
        if filters and len(wanted) != 1:
            print("A filter goes with one table: show items status=staged")
            return
        for table in wanted:
            try:
                rows = show.rows(conn, table, filters)
            except KeyError as e:
                print(e.args[0])
                continue
            print(f"== {table} ({len(rows)}) ==")
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
    finally:
        conn.close()


def cmd_doctor(args):
    text, ready = doctor.report()
    print(text)
    sys.exit(0 if ready else 1)


def cmd_status(args):
    if not db.exists():
        print("Nothing set up yet. Run 'python mudroom.py reset' first.")
        return
    print(status.report())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mudroom", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset", help="rebuild the week from the seed").set_defaults(run=cmd_reset)
    clean_parser = sub.add_parser("start-clean", help="remove the invented week and make the house yours")
    clean_parser.add_argument("--you", required=True, help="your name, as the door should know you")
    clean_parser.add_argument("--yes", action="store_true", help="go ahead; without it, only says what would go")
    clean_parser.set_defaults(run=cmd_start_clean)
    serve_parser = sub.add_parser("serve", help="open the dashboards")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    serve_parser.set_defaults(run=cmd_serve)
    intake_parser = sub.add_parser("intake", help="register what a source skill fetched")
    intake_parser.add_argument("file", nargs="?", default=None, help="the handoff, or - for stdin")
    intake_parser.add_argument("--bookmark", nargs=2, metavar=("SOURCE", "ACCOUNT"),
                               help="how far a source got last time")
    intake_parser.set_defaults(run=cmd_intake)
    process_parser = sub.add_parser("process", help="take the handover file into the database")
    process_parser.add_argument("path", nargs="?", default=None, help="the file, handover.json by default")
    process_parser.set_defaults(run=cmd_process)
    sub.add_parser("learn-evaluate", help="run the two agents through your Claude").set_defaults(run=cmd_learn_evaluate)
    sub.add_parser("run", help="the whole pass on demand").set_defaults(run=cmd_run)
    show_parser = sub.add_parser("show", help="read-only: the tables, the rows of the tables named, or one table filtered")
    show_parser.add_argument("tables", nargs="*")
    show_parser.set_defaults(run=cmd_show)
    sub.add_parser("status", help="where the play stands").set_defaults(run=cmd_status)
    sub.add_parser("doctor", help="check this machine is ready to run the Mudroom").set_defaults(run=cmd_doctor)
    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
