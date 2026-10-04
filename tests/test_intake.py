"""The Intake Engine registers a handoff, checks the sender list, keeps the bookmark."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from engine import db, intake, lock, show


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)
        self.handoff = helpers.SOURCE.handoff(helpers.BATCH, helpers.START)

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def count(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def test_registered_with_bookmark_clock_and_lock(self):
        self.assertEqual(self.count("SELECT COUNT(*) FROM items WHERE status = 'staged'"), 4)
        self.assertEqual(db.get_state(self.conn, "clock"), "2026-09-15T09:15")
        mark = intake.bookmark(self.conn, "rounds", "world")
        self.assertEqual((mark["last_seen_id"], mark["cursor"], mark["week_start"]),
                         ("01-test-morning", "2026-09-15T09:15", "2026-09-14"))
        self.assertIsNotNone(lock.held(self.conn))
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'intake'"), 1)

    def test_known_items_update_in_place(self):
        again = copy.deepcopy(self.handoff)
        again["items"][0]["subject"] = "Steering pack, corrected"
        with self.conn:
            lock.end(self.conn)   # a re-fetch is a new run; one run brings one batch
        result = intake.register(self.conn, again)
        self.assertEqual((result["staged"], result["updated"]), (0, 4))
        self.assertEqual(self.count("SELECT COUNT(*) FROM items"), 4)
        self.assertEqual(self.conn.execute(
            "SELECT subject FROM items WHERE id = '01-test-morning-01'").fetchone()[0], "Steering pack, corrected")

    def test_skipped_sender_is_marked_and_logged_without_being_read(self):
        with self.conn:
            self.conn.execute("DELETE FROM items")
            self.conn.execute(
                "INSERT INTO source_senders (sender, source, disposition, taught_by) "
                "VALUES ('The Daily Digest', 'email', 'skip', 'test')")
            lock.end(self.conn)   # a fresh run
        result = intake.register(self.conn, copy.deepcopy(self.handoff))
        self.assertEqual((result["staged"], result["skipped"]), (3, 1))
        self.assertEqual(self.conn.execute(
            "SELECT status FROM items WHERE id = '01-test-morning-03'").fetchone()[0], "skipped")
        self.assertEqual(self.count(
            "SELECT COUNT(*) FROM decision_log WHERE actor = 'intake' AND decision = 'skipped'"), 1)
        self.assertEqual(len(show.rows(self.conn, "items", {"status": "staged"})), 3)

    def test_bad_handoff_is_refused_whole(self):
        bad = copy.deepcopy(self.handoff)
        bad["items"][1]["source"] = "pigeon"
        del bad["account"]
        with self.conn:
            self.conn.execute("DELETE FROM items")
        with self.assertRaises(intake.Refused) as caught:
            intake.register(self.conn, bad)
        problems = "\n".join(caught.exception.problems)
        self.assertIn("needs account", problems)
        self.assertIn("source must be one of", problems)
        self.assertEqual(self.count("SELECT COUNT(*) FROM items"), 0)

    def test_the_parser_walks_the_week(self):
        folder = helpers.HERE / "rounds"
        self.assertEqual(helpers.SOURCE.next_file(folder, None).stem, "01-test-morning")
        self.assertIsNone(helpers.SOURCE.next_file(folder, "01-test-morning"))
        self.assertEqual(self.handoff["label"], "Test morning")
        self.assertEqual(self.handoff["items"][1]["raw"]["channel"], "#project")


    def test_the_cast_replies_ride_in_the_batch(self):
        replies = [{"source": "email", "sender": "Jordan", "subject": "Re: Update", "at": "13:40",
                    "thread": "sent-1", "body": "Fine.\n\nJordan"},
                   {"source": "chat", "sender": "Chris", "channel": "#project", "at": "13:50", "body": "on it"}]
        h = helpers.SOURCE.handoff(helpers.BATCH, helpers.START, replies)
        tail = h["items"][-2:]
        self.assertEqual([t["id"] for t in tail], ["01-test-morning-r01", "01-test-morning-r02"])
        self.assertEqual((tail[0]["thread"], tail[0]["received_at"], tail[0]["raw"]["cast"]),
                         ("sent-1", "2026-09-15T13:40", True))
        self.assertEqual(tail[1]["raw"]["channel"], "#project")
        with self.assertRaises(ValueError):
            helpers.SOURCE.handoff(helpers.BATCH, helpers.START, [{"source": "email", "sender": "Jordan"}])
        with self.assertRaises(ValueError):
            helpers.SOURCE.handoff(helpers.BATCH, helpers.START, [dict(replies[0], id="mine")])
        # once the week is done the replies come on their own, and the bookmark stays put
        alone = helpers.SOURCE.replies_only(helpers.START, "03-monday-afternoon", "2026-09-14T16:30", replies)
        self.assertEqual((alone["label"], alone["last_seen_id"], alone["now"]),
                         ("The cast answers", "03-monday-afternoon", None))
        self.assertRegex(alone["items"][0]["id"], r"^03-monday-afternoon-cast-\d{14}-r01$")
        self.assertEqual(alone["items"][0]["received_at"], "2026-09-14T13:40")


    def test_one_batch_per_run(self):
        second = copy.deepcopy(self.handoff)
        for it in second["items"]:
            it["id"] = it["id"].replace("01-test-morning", "02-test-noon")
        with self.assertRaises(intake.Refused) as caught:
            intake.register(self.conn, second)
        self.assertIn("one batch per run", "\n".join(caught.exception.problems))
        self.assertEqual(self.count("SELECT COUNT(*) FROM items"), 4)
        with self.conn:
            lock.end(self.conn)
        intake.register(self.conn, second)   # the next run may
        self.assertEqual(self.count("SELECT COUNT(*) FROM items"), 8)


if __name__ == "__main__":
    unittest.main()
