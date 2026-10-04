"""The engine test for processing: its own tiny batch and its own judgements, run against a
throwaway database built from the schema and the cast. Nothing here judges the demo's week.

    python -m unittest discover -s tests
"""
import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import helpers
from engine import clock, db, lock, process

HERE = Path(__file__).resolve().parent
GOOD = json.loads((HERE / "handover" / "good.json").read_text(encoding="utf-8"))
AFTER = json.loads((HERE / "handover" / "after-answer.json").read_text(encoding="utf-8"))
START = helpers.START


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)
        self.now = db.get_state(self.conn, "clock")

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def count(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def answer_first_question(self):
        with self.conn:
            self.conn.execute(
                "UPDATE questions SET status = 'answered', answer = 'No.', answered_on = ? WHERE id = 'question-1'",
                (self.now,))

    def refused(self, mutate, expect):
        data = copy.deepcopy(GOOD)
        mutate(data)
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, data, self.now)
        self.assertIn(expect, "\n".join(caught.exception.problems))
        self.assertEqual(self.count("SELECT COUNT(*) FROM proposals"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM items WHERE status = 'staged'"), 4)

    def test_good_file_is_written(self):
        counts = process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.assertEqual(counts, {"ready": 2, "yours": 1, "headsup": 0, "filed": 1})
        self.assertEqual(self.count("SELECT COUNT(*) FROM items WHERE status = 'judged'"), 4)
        self.assertEqual(self.count("SELECT COUNT(*) FROM proposals WHERE status = 'pending'"), 4)
        self.assertEqual(self.count("SELECT COUNT(*) FROM decision_log WHERE actor = 'evaluate'"), 4)
        q = self.conn.execute("SELECT * FROM questions WHERE id = 'question-1'").fetchone()
        self.assertEqual((q["item_id"], q["subject"], q["status"]),
                         ("01-test-morning-04", "sender:Casey (recruiter)", "open"))
        p = self.conn.execute("SELECT * FROM proposals WHERE item_id = '01-test-morning-04'").fetchone()
        self.assertEqual(p["question_id"], "question-1")
        # the work is stored with its dates resolved against the engine's week
        work = json.loads(self.conn.execute(
            "SELECT work FROM proposals WHERE item_id = '01-test-morning-02'").fetchone()["work"])
        self.assertEqual((work[1]["start"], work[1]["end"]), ("2026-09-15T09:30", "2026-09-15T09:45"))
        # nothing acts on its own: the commitment the update would close is still open
        self.assertEqual(self.count(
            "SELECT COUNT(*) FROM commitments WHERE id = 'chris-test-results' AND status = 'open'"), 1)
        # Jordan and Chris wrote in
        self.assertEqual(self.count("SELECT COUNT(*) FROM interactions WHERE direction = 'in'"), 2)
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'process'"), 1)

    def test_answer_reopens_its_item(self):
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.answer_first_question()
        counts = process.process(self.conn, copy.deepcopy(AFTER), self.now)
        self.assertEqual(counts["filed"], 1)
        self.assertEqual(self.count(
            "SELECT COUNT(*) FROM proposals WHERE item_id = '01-test-morning-04' AND status = 'superseded'"), 1)
        self.assertEqual(self.count(
            "SELECT COUNT(*) FROM proposals WHERE item_id = '01-test-morning-04' AND status = 'pending'"), 1)
        self.assertEqual(self.count("SELECT COUNT(*) FROM questions WHERE id = 'question-1' AND status = 'consumed'"), 1)
        self.assertEqual(self.count("SELECT COUNT(*) FROM decision_log WHERE item_id = '01-test-morning-04'"), 2)

    def test_answered_subject_is_not_asked_again(self):
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.answer_first_question()
        data = copy.deepcopy(AFTER)
        data["items"][0]["outcome"] = "yours"
        data["items"][0]["work"] = [{"kind": "question", "subject": "sender:Casey (recruiter)", "question": "Again?"}]
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, data, self.now)
        self.assertIn("already answered", "\n".join(caught.exception.problems))

    def test_refusals(self):
        cases = [
            (lambda d: d.update({"rules": []}), "unknown key"),
            (lambda d: d.pop("seen"), "missing key"),
            (lambda d: d["seen"].remove("01-test-morning-03"), "at the door and not in seen"),
            (lambda d: d["seen"].append("nothing-here"), "neither staged nor re-opened"),
            (lambda d: d["items"].pop(), "has no entry in items"),
            (lambda d: d["items"][0].update({"class": "spam"}), "not in the engine's list"),
            (lambda d: d["items"][0].update({"outcome": "maybe"}), "outcome 'maybe'"),
            (lambda d: d["items"][0]["work"][0].update({"kind": "telegram"}), "kind 'telegram'"),
            (lambda d: d["items"][2].update({"work": [{"kind": "task", "title": "x", "domain": "work"}]}),
             "filed carries no work"),
            (lambda d: d["items"][0].update({"work": []}), "ready carries at least one"),
            (lambda d: d["items"][3]["work"].append(
                {"kind": "question", "subject": "item:01-test-morning-04", "question": "and?"}), "exactly one"),
            (lambda d: d["items"][1]["work"][0].update({"target": "commitment:nope"}), "does not exist"),
            (lambda d: d["items"][1]["work"][0].update({"changes": {"owner": "them"}}), "does not allow changing"),
            (lambda d: d["items"][0]["work"][1].update({"person": "nobody"}), "not a person the engine knows"),
            (lambda d: d["items"][3]["work"][0].update({"subject": "casey"}), "must be kind:id"),
            (lambda d: d["items"][3]["work"][0].update({"subject": "person:casey"}), "does not know"),
            (lambda d: d["consumed"].append("one-to-one-moved"), "not answered"),
            (lambda d: d["items"][0]["work"][1].update({"id": "commitment-9"}), "the engine mints ids"),
            (lambda d: d["items"][0]["work"][1].update({"due": "Someday"}), "is not a date"),
            (lambda d: d["items"][1]["work"][1].update({"start": "Tuesday"}), "needs a time"),
        ]
        for mutate, expect in cases:
            with self.subTest(expect=expect):
                self.refused(mutate, expect)

    def test_sender_ties(self):
        # a name that fits one person is tied and the tie is recorded as a match
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        ties = {(r["source"], r["sender"]): (r["person_id"], r["taught_by"])
                for r in self.conn.execute("SELECT * FROM source_senders")}
        self.assertEqual(ties, {("email", "Jordan"): ("jordan", "match"), ("chat", "Chris"): ("chris", "match")})

    def test_ambiguous_name_is_left_untied_and_a_tie_wins(self):
        with self.conn:
            self.conn.execute("INSERT INTO people (id, name, domain) VALUES ('jordan-2', 'Jordan', 'family')")
            self.conn.execute(
                "INSERT INTO source_senders (sender, source, disposition, person_id, taught_by) "
                "VALUES ('Chris', 'chat', 'normal', 'morgan', 'test')")
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.assertEqual(self.count("SELECT COUNT(*) FROM source_senders WHERE sender = 'Jordan'"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM interactions WHERE person_id LIKE 'jordan%'"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM interactions WHERE person_id = 'morgan'"), 1)

    def test_a_refused_file_is_moved_aside(self):
        bad = self.tmp / "handover.json"
        data = copy.deepcopy(GOOD)
        data["items"][0]["outcome"] = "maybe"
        bad.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(process.run(bad), 1)
        self.assertFalse(bad.exists())
        self.assertTrue((self.tmp / "handover.refused.json").exists())
        self.assertEqual(self.count("SELECT COUNT(*) FROM proposals"), 0)

    def test_run_lock(self):
        # intake set it, processing clears it, and a lock from a run that died is ignored
        self.assertIsNotNone(lock.held(self.conn))
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.assertIsNone(lock.held(self.conn))
        with self.conn:
            lock.begin(self.conn)
            stale = (datetime.now() - timedelta(minutes=lock.STALE_MINUTES + 1)).isoformat(timespec="seconds")
            self.conn.execute("UPDATE run_lock SET started_at = ?", (stale,))
        self.assertIsNone(lock.held(self.conn))

    def test_dates(self):
        self.assertEqual(clock.resolve("Wednesday 09:00", START), "2026-09-16T09:00")
        self.assertEqual(clock.resolve("wednesday", START), "2026-09-16")
        self.assertEqual(clock.resolve("2026-09-16T09:00", START), "2026-09-16T09:00")
        self.assertEqual(clock.resolve("2026-09-30", START), "2026-09-30")
        with self.assertRaises(ValueError):
            clock.resolve("Funday", START)
        with self.assertRaises(ValueError):
            clock.resolve("Wednesday", START, need_time=True)


if __name__ == "__main__":
    unittest.main()
