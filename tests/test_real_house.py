"""A house on real time, after start-clean: the clock is the real one, a run that finds nothing
holds nothing up, a bookmark never falls back to nothing, and an approved message is kept for
the person to send, since nothing here reaches a real account yet. Runs against the
throwaway database, set up as the demo and then switched the way start-clean switches it."""
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import helpers
from engine import agents, clock, db, decide, demo, intake, lock, pages, process, seed, show, status

GOOD = json.loads((helpers.HERE / "handover" / "good.json").read_text(encoding="utf-8"))


class RealHouseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)
        process.process(self.conn, copy.deepcopy(GOOD), db.get_state(self.conn, "clock"))
        # start-clean ran nine days ago: the stored clock and week are that moment's
        then = datetime.now() - timedelta(days=9)
        with self.conn:
            db.set_state(self.conn, "clock_mode", "real")
            db.set_state(self.conn, "clock", then.isoformat(timespec="minutes"))
            db.set_state(self.conn, "week_start", clock.week_start(then.date()).isoformat())

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pending(self, item_id):
        return self.conn.execute("SELECT id FROM proposals WHERE item_id = ? AND status = 'pending'",
                                 (item_id,)).fetchone()["id"]

    # ---- the clock ----

    def test_the_clock_is_the_real_one_not_the_moment_of_start_clean(self):
        self.assertEqual(clock.now(self.conn)[:13], datetime.now().isoformat()[:13])
        self.assertEqual(clock.this_week(self.conn), clock.week_start())
        mark = intake.bookmark(self.conn, "gmail", "me@example.org")
        self.assertEqual((mark["clock"], mark["week_start"]),
                         (clock.now(self.conn), clock.week_start().isoformat()))

    def test_the_judge_reads_the_live_clock_from_state(self):
        state = {r["key"]: r["value"] for r in show.rows(self.conn, "state")}
        self.assertEqual(state["clock"], clock.now(self.conn))
        self.assertEqual(state["week_start"], clock.week_start().isoformat())

    def test_a_weekday_in_a_judgement_means_the_coming_one(self):
        checker = process.Checker(self.conn, {})
        self.assertEqual(checker.start, clock.week_start())
        for day in clock.DAYS:
            meant = clock.as_date(checker.when("items[0]", day, "due"))
            self.assertTrue(date.today() <= meant < date.today() + timedelta(days=7), (day, meant))
        self.assertEqual(clock.resolve("Thursday", date(2026, 11, 2), onward=date(2026, 11, 7)), "2026-11-12")
        self.assertEqual(clock.resolve("Thursday", date(2026, 11, 2)), "2026-11-05", "the demo keeps its week")

    def test_status_names_the_house_and_its_week(self):
        text = status.report()
        self.assertIn(f"Alex's Mudroom, week of Monday {clock.long_date(clock.week_start())}", text)

    # ---- the bookmark and the run ----

    def test_a_fetch_with_nothing_new_keeps_the_bookmark_and_holds_nothing_up(self):
        with self.conn:
            lock.end(self.conn)
        first = {"source": "gmail", "account": "me@example.org", "cursor": "2026-11-05T09:00",
                 "last_seen_id": "gmail-1", "items": [
                     {"id": "gmail-1", "source": "email", "sender": "sam@example.org", "subject": "Lunch",
                      "body": "Thursday?", "received_at": "2026-11-05T09:00"}]}
        intake.register(self.conn, first)
        self.assertTrue(lock.held(self.conn), "something to judge starts a run")
        with self.conn:
            lock.end(self.conn)   # as processing would
        intake.register(self.conn, {"source": "gmail", "account": "me@example.org",
                                    "cursor": None, "last_seen_id": None, "items": []})
        mark = intake.bookmark(self.conn, "gmail", "me@example.org")
        self.assertEqual((mark["cursor"], mark["last_seen_id"]), ("2026-11-05T09:00", "gmail-1"))
        self.assertIsNone(lock.held(self.conn), "nothing new starts no run")
        self.assertIn("nothing to judge", intake.summary(
            {"staged": 0, "skipped": 0, "updated": 0, "label": None, "now": clock.now(self.conn)}))
        decide._clear(self.conn)   # a press on a card is not refused

    def test_a_fetch_of_only_skipped_senders_holds_nothing_up(self):
        with self.conn:
            lock.end(self.conn)
            self.conn.execute("INSERT INTO source_senders (sender, source, disposition) "
                              "VALUES ('news@example.org', 'email', 'skip')")
        intake.register(self.conn, {"source": "gmail", "account": "me@example.org", "cursor": "2026-11-05T10:00",
                                    "items": [{"id": "gmail-2", "source": "email", "sender": "news@example.org",
                                               "subject": "Weekly", "received_at": "2026-11-05T10:00"}]})
        self.assertIsNone(lock.held(self.conn))

    def test_the_judge_lets_go_when_there_is_nothing_to_judge(self):
        with self.conn:
            self.conn.execute("UPDATE items SET status = 'judged' WHERE status = 'staged'")
            lock.begin(self.conn)   # a run that began, as the Doorstep's button begins one
        ok, message = agents.judge(owned=True)
        self.assertTrue(ok)
        self.assertIn("Nothing at the door", message)
        self.assertIsNone(lock.held(self.conn))

    def test_run_after_start_clean_judges_and_never_calls_the_demo_source(self):
        with mock.patch.object(demo, "present", lambda: False), \
                mock.patch.object(agents, "judge", lambda **kw: (True, "judged")), \
                mock.patch.object(agents, "source", side_effect=AssertionError("the demo's source is gone")):
            self.assertEqual(demo.run(wait=True), (True, "judged"))

    def test_source_skills_are_the_persons_own(self):
        skills = self.tmp / ".claude" / "skills"
        for name in ("source-demo", "source-gmail", "source-slack", "learn-evaluate"):
            (skills / name).mkdir(parents=True)
            (skills / name / "SKILL.md").write_text("---\n---\n", encoding="utf-8")
        self.assertEqual(intake.source_skills(self.tmp), ["source-gmail", "source-slack"])

    # ---- a real house keeps the demo out ----

    def test_the_demo_stays_out_even_when_its_files_come_back(self):
        if not (demo.ROUNDS / "source.py").exists():
            self.skipTest("the demo has left this checkout already")
        self.assertFalse(demo.present())

    def test_reset_refuses_to_replace_a_real_house(self):
        with self.assertRaises(SystemExit) as refused:
            seed.reset()
        self.assertIn("This house is yours", str(refused.exception))
        self.assertTrue(db.real_house(), "nothing was rebuilt")

    def test_start_clean_warns_before_emptying_a_real_house(self):
        import argparse
        import contextlib
        import mudroom
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            mudroom.cmd_start_clean(argparse.Namespace(you="Alex", yes=False))
        self.assertIn("This house is already Alex's", said.getvalue())
        self.assertIn("would empty it", said.getvalue())

    # ---- what a yes does ----

    def test_an_approved_reply_is_kept_for_the_person_to_send(self):
        said = decide.approve(self.conn, self.pending("01-test-morning-01"), clock.now(self.conn))
        self.assertIn("reply to Jordan kept for you to send", said)
        self.assertNotIn("sent to", said)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM actions WHERE action = 'send'").fetchone()[0], 0)
        kept = self.conn.execute("SELECT * FROM actions WHERE action = 'to-send'").fetchone()
        self.assertEqual(kept["reversible"], 1)
        copy_ = self.conn.execute("SELECT * FROM items WHERE status = 'sent'").fetchone()
        self.assertTrue(json.loads(copy_["raw"])["unsent"])
        self.assertIn("Your reply, not sent", pages.sent_card(copy_, date.today(), pages.Who(self.conn)))

    def test_a_press_is_stamped_with_the_real_time(self):
        nid = decide.leave_note(self.conn, "call the plumber", clock.now(self.conn))
        stamped = self.conn.execute("SELECT received_at FROM items WHERE id = ?", (nid,)).fetchone()[0]
        self.assertEqual(stamped[:10], date.today().isoformat())


class PagesTest(unittest.TestCase):
    class Who:
        def tag(self, *args):
            return "Sam"

    def test_a_passed_on_message_draws_on_the_doorstep(self):
        item = {"id": "sent-1", "source": "email", "received_at": "2026-11-02T10:00", "subject": "Fwd: Order",
                "body": "", "raw": json.dumps({"to": "Sam", "forwarded": "01-x"})}
        html = pages.sent_card(item, date(2026, 11, 2), self.Who())
        self.assertIn("Passed on", html)
        self.assertIn("No note.", html)

    def test_a_fresh_email_shows_its_subject(self):
        item = {"id": "sent-2", "source": "email", "received_at": "2026-11-02T10:00", "subject": "Opening date",
                "body": "Hello", "raw": json.dumps({"to": "Sam", "fresh": True})}
        self.assertIn("<h3>Opening date</h3>", pages.sent_card(item, date(2026, 11, 2), self.Who()))

    def test_a_date_beyond_this_week_says_which_day(self):
        today = datetime.now().replace(second=0, microsecond=0)
        self.assertEqual(pages.moment(today), f"{clock.DAYS[today.weekday()][:3]} {today:%H:%M}")
        old = today - timedelta(days=30)
        self.assertEqual(pages.moment(old), f"{clock.short_date(old.date())} {old:%H:%M}")


class Utf8Test(unittest.TestCase):
    def test_output_is_utf8_whatever_the_machines_code_page(self):
        import mudroom
        saved = sys.stdout, sys.stderr, sys.stdin
        raw = io.BytesIO()
        sys.stdout = io.TextIOWrapper(raw, encoding="cp1252")   # what Windows gives a pipe
        sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        sys.stdin = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        try:
            mudroom.speak_utf8()
            print("Party \U0001f389 at Zoë's")
            sys.stdout.flush()
            self.assertEqual(raw.getvalue().decode("utf-8").strip(), "Party \U0001f389 at Zoë's")
        finally:
            sys.stdout, sys.stderr, sys.stdin = saved


if __name__ == "__main__":
    unittest.main()
