"""The agents are run by the person's Claude; without one, nothing judges and nothing wedges."""
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from engine import agents, db, lock


class AgentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_without_claude_nothing_is_judged_and_the_lock_clears(self):
        keep = agents.executable
        agents.executable = lambda: None
        try:
            ok, message = agents.judge(owned=True)
        finally:
            agents.executable = keep
        self.assertFalse(ok)
        self.assertIn("Claude Code is not installed", message)
        self.assertIsNone(lock.held(self.conn))
        self.assertIs(agents.last_run(self.conn)["ok"], False)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM items WHERE status = 'staged'").fetchone()[0], 4)

    def test_a_run_in_flight_is_not_started_twice(self):
        # intake set the lock; a press that does not own it is refused and changes nothing
        ok, message = agents.judge()
        self.assertFalse(ok)
        self.assertIn("already in flight", message)
        self.assertIsNone(agents.last_run(self.conn))
        self.assertIsNotNone(lock.held(self.conn))

    def test_nothing_to_do_needs_no_claude(self):
        with self.conn:
            self.conn.execute("UPDATE items SET status = 'judged'")
            lock.end(self.conn)
        ok, message = agents.judge()
        self.assertTrue(ok)
        self.assertIn("Nothing at the door", message)


if __name__ == "__main__":
    unittest.main()
