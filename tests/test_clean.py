"""Start clean: the fiction leaves, the engine stays, and nothing happens without a name."""
import shutil
import tempfile
import unittest
from pathlib import Path

from engine import clean, db


class CleanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        db.DB_PATH = self.tmp / "test.db"
        # a stand-in for the repo: the fiction's folders and a leftover, plus something that stays
        for folder in ("rounds", "world", ".claude/skills/source-demo", "engine", "tests"):
            (self.tmp / folder).mkdir(parents=True)
            (self.tmp / folder / "x.md").write_text("x", encoding="utf-8")
        (self.tmp / "handover.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_needs_a_name(self):
        with self.assertRaises(ValueError):
            clean.start_clean("  ", root=self.tmp)
        self.assertTrue((self.tmp / "rounds").exists())

    def test_the_fiction_goes_and_the_engine_stays(self):
        removed = clean.start_clean("Robin", root=self.tmp)
        self.assertEqual(sorted(Path(r).as_posix() for r in removed),
                         sorted(["rounds", "world", ".claude/skills/source-demo", "handover.json"]))
        for gone in ("rounds", "world", ".claude/skills/source-demo", "handover.json"):
            self.assertFalse((self.tmp / gone).exists(), gone)
        self.assertTrue((self.tmp / "engine" / "x.md").exists())
        self.assertTrue((self.tmp / "tests" / "x.md").exists())
        conn = db.connect()
        try:
            self.assertEqual(db.get_state(conn, "you"), "Robin")
            self.assertEqual(db.get_state(conn, "clock_mode"), "real")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM calendars").fetchone()[0], 3)
            for table in ("people", "tasks", "events", "items", "commitments", "questions", "proposals"):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM actions WHERE action = 'start-clean'").fetchone()[0], 1)
        finally:
            conn.close()
        # a second run has nothing left to remove and still rebuilds
        self.assertEqual(clean.start_clean("Robin", root=self.tmp), [])


if __name__ == "__main__":
    unittest.main()
