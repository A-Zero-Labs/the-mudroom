"""show is how the agents read: any table, a filter, decoded JSON columns, and nothing written."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from engine import db, process, show

GOOD = json.loads((helpers.HERE / "handover" / "good.json").read_text(encoding="utf-8"))


class ShowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)
        self.now = db.get_state(self.conn, "clock")

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_door_is_items_with_status_staged(self):
        at_the_door = show.rows(self.conn, "items", {"status": "staged"})
        self.assertEqual([i["id"] for i in at_the_door], [f"01-test-morning-0{n}" for n in (1, 2, 3, 4)])
        self.assertEqual(at_the_door[1]["headers"]["channel"], "#project")   # raw comes out decoded
        self.assertNotIn("raw", at_the_door[1])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM source_senders").fetchone()[0], 0)

    def test_filters_and_counts(self):
        self.assertEqual(show.rows(self.conn, "items", {"id": "01-test-morning-03"})[0]["sender"], "The Daily Digest")
        self.assertEqual(show.rows(self.conn, "questions", {"status": "answered"}), [])
        self.assertEqual(show.counts(self.conn)["people"], 8)
        with self.assertRaises(KeyError):
            show.rows(self.conn, "items", {"colour": "red"})
        with self.assertRaises(KeyError):
            show.rows(self.conn, "nothing")

    def test_judged_items_leave_the_door_and_work_reads_as_a_list(self):
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.assertEqual(show.rows(self.conn, "items", {"status": "staged"}), [])
        proposal = show.rows(self.conn, "proposals", {"item_id": "01-test-morning-02"})[0]
        self.assertEqual([w["kind"] for w in proposal["work"]], ["update", "event"])


if __name__ == "__main__":
    unittest.main()
