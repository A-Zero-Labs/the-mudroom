"""The Doorstep's buttons bring the invented week in through intake and start it again."""
import shutil
import tempfile
import unittest
from pathlib import Path

from engine import db, demo, lock, seed


@unittest.skipUnless(demo.present(), "the invented week has left; nothing to walk")
class DemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        db.DB_PATH = self.tmp / "test.db"
        seed.reset()

    def tearDown(self):
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def count(self, sql):
        conn = db.connect()
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()

    def test_a_press_during_a_run_is_refused(self):
        demo.next_round()          # intake set the lock, as a press does
        self.assertIs(demo.run(), False)
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'intake'"), 1)

    def test_next_round_walks_the_week_and_start_over_clears_it(self):
        conn = db.connect()
        first = demo.upcoming(conn)
        conn.close()
        self.assertEqual(first.stem, "01-monday-morning")
        self.assertEqual(demo.title(first), "Monday morning")
        self.assertIn("bakery", demo.story(first))   # the story rides in the batch
        conn = db.connect()
        self.assertIn("Crumb", demo.intro(conn))
        self.assertFalse(demo.anything_to_answer(conn))
        conn.close()
        result = demo.next_round()
        self.assertEqual(result["staged"], 8)
        self.assertEqual(self.count("SELECT COUNT(*) FROM items WHERE status = 'staged'"), 8)
        # every batch in rounds/ comes in once, then the week is done
        n = 1
        while True:
            conn = db.connect()
            with conn:
                lock.end(conn)   # as processing would, one batch per run
            conn.close()
            if demo.next_round() is None:
                break
            n += 1
        self.assertEqual(n, len(list(demo.ROUNDS.glob("[0-9][0-9]-*.md"))))   # the batches, not cast.md
        conn = db.connect()
        self.assertIsNone(demo.upcoming(conn))
        conn.close()
        demo.start_over()
        self.assertEqual(self.count("SELECT COUNT(*) FROM items"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM source_state"), 0)
        self.assertEqual(db.get_state(db.connect(), "clock")[11:], "08:00")


if __name__ == "__main__":
    unittest.main()
