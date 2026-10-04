"""The engine test for house rules: the same judgement applied without a rule and with one,
a rule that files or flags overriding the outcome and logging that it fired, a rule that asks
for work refusing a file that ignores it, and the rules taught and removed from the pages."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from engine import db, decide, lock, pages, process, rules

HERE = Path(__file__).resolve().parent
GOOD = json.loads((HERE / "handover" / "good.json").read_text(encoding="utf-8"))


def teach(conn, sender, outcome, now, action=None):
    conn.execute(
        "INSERT INTO handling_rules (id, scope, pattern, action, outcome, status, taught_by, taught_on, fired) "
        "VALUES (?, 'sender', ?, ?, ?, 'active', 'the test', ?, 0)",
        (f"rule-{sender.lower()}", sender, action or f"{outcome} for {sender}", outcome, now))
    conn.commit()


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)
        self.now = db.get_state(self.conn, "clock")

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def one(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()

    def test_the_same_file_without_and_with_a_rule(self):
        counts = process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.assertEqual(counts["ready"], 2)
        before = self.one("SELECT outcome, work, rule_id FROM proposals WHERE item_id = '01-test-morning-01'")
        self.assertEqual((before["outcome"], before["rule_id"]), ("ready", None))
        # the same batch again, with Jordan's mail flagged from now on
        self.conn.close()
        self.conn = helpers.stage(self.tmp)
        teach(self.conn, "Jordan", "headsup", self.now, "Tell me about Jordan, nothing more")
        counts = process.process(self.conn, copy.deepcopy(GOOD), self.now)
        self.assertEqual((counts["ready"], counts["headsup"]), (1, 1))
        after = self.one("SELECT outcome, work, rule_id FROM proposals WHERE item_id = '01-test-morning-01'")
        self.assertEqual((after["outcome"], after["work"], after["rule_id"]), ("headsup", "[]", "rule-jordan"))
        rule = self.one("SELECT fired, last_applied FROM handling_rules WHERE id = 'rule-jordan'")
        self.assertEqual((rule["fired"], rule["last_applied"]), (1, self.now))
        logged = self.one("SELECT * FROM decision_log WHERE actor = 'process' AND item_id = '01-test-morning-01'")
        self.assertIn("rule-jordan fired", logged["reason"])
        # nothing the dropped work would have made exists
        self.assertEqual(self.one("SELECT COUNT(*) FROM commitments WHERE source = '01-test-morning-01'")[0], 0)

    def test_a_rule_that_asks_for_work_is_the_judgements_to_honour(self):
        teach(self.conn, "The Daily Digest", "ready", self.now, "Put half an hour in my list to read it")
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, copy.deepcopy(GOOD), self.now)   # the file has it filed
        self.assertIn("house rule rule-the daily digest says ready", "\n".join(caught.exception.problems))
        honoured = copy.deepcopy(GOOD)
        honoured["items"][2].update(outcome="ready", work=[
            {"kind": "task", "title": "Read the Daily Digest", "domain": "personal"}])
        process.process(self.conn, honoured, self.now)
        p = self.one("SELECT outcome, rule_id FROM proposals WHERE item_id = '01-test-morning-03'")
        self.assertEqual((p["outcome"], p["rule_id"]), ("ready", "rule-the daily digest"))

    def test_scopes(self):
        with self.conn:
            self.conn.execute("UPDATE items SET raw = ? WHERE id = '01-test-morning-02'",
                              (json.dumps({"from": "chris@company.example"}),))
            self.conn.execute(
                "INSERT INTO handling_rules (id, scope, pattern, action, outcome, status, taught_on) "
                "VALUES ('rule-1', 'domain', 'company.example', 'file work mail', 'filed', 'active', ?)", (self.now,))
            self.conn.execute(
                "INSERT INTO handling_rules (id, scope, pattern, action, outcome, status, taught_on) "
                "VALUES ('rule-2', 'subject', 'digest', 'file digests', 'filed', 'active', ?)", (self.now,))
        self.assertEqual(rules.match(self.conn, "01-test-morning-02")["id"], "rule-1")
        self.assertEqual(rules.match(self.conn, "01-test-morning-03")["id"], "rule-2")
        self.assertIsNone(rules.match(self.conn, "01-test-morning-01"))

    def test_from_now_on_from_a_card_and_the_panel(self):
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        pid = self.one("SELECT id FROM proposals WHERE item_id = '01-test-morning-04'")["id"]   # Casey, yours
        with self.assertRaises(decide.Refused):
            decide.from_now_on(self.conn, pid, "shout", self.now)
        said = decide.from_now_on(self.conn, pid, "headsup", self.now)
        self.assertEqual(said, "Just show me mail from Casey (recruiter), draft nothing")
        p = self.one("SELECT outcome, work, rule_id, question_id FROM proposals WHERE id = ?", pid)
        self.assertEqual((p["outcome"], p["work"], p["rule_id"], p["question_id"]), ("headsup", "[]", "rule-1", None))
        self.assertEqual(self.one("SELECT status FROM questions WHERE id = 'question-1'")["status"], "closed")
        rule = self.one("SELECT * FROM handling_rules WHERE id = 'rule-1'")
        self.assertEqual((rule["scope"], rule["pattern"], rule["outcome"], rule["taught_by"], rule["fired"]),
                         ("sender", "Casey (recruiter)", "headsup", pid, 1))
        page = pages.checkin(self.conn)
        self.assertIn("House rule: Just show me mail from Casey (recruiter), draft nothing.", page)
        self.assertNotIn('action="/rule/retire"', page)   # the panel lives on the log page
        self.assertIn('action="/rule/retire"', pages.log(self.conn))
        # a second rule on the same sender retires the first
        decide.from_now_on(self.conn, pid, "file", self.now)
        self.assertEqual(self.one("SELECT status FROM handling_rules WHERE id = 'rule-1'")["status"], "retired")
        self.assertEqual(self.one("SELECT outcome FROM handling_rules WHERE id = 'rule-2'")["outcome"], "filed")
        decide.retire_rule(self.conn, "rule-2", self.now)
        self.assertEqual(self.one("SELECT COUNT(*) FROM handling_rules WHERE status = 'active'")[0], 0)
        # never read again lives in source_senders, and the panel offers the way back
        jordan = self.one("SELECT id FROM proposals WHERE item_id = '01-test-morning-01'")["id"]
        decide.from_now_on(self.conn, jordan, "skip", self.now)
        s = self.one("SELECT * FROM source_senders WHERE sender = 'Jordan' AND source = 'email'")
        self.assertEqual((s["disposition"], s["taught_by"]), ("skip", jordan))
        self.assertEqual(self.one("SELECT outcome FROM proposals WHERE id = ?", jordan)["outcome"], "filed")
        self.assertIn("Never read Jordan again", pages.log(self.conn))
        decide.read_again(self.conn, "email", "Jordan", self.now)
        self.assertEqual(self.one("SELECT disposition FROM source_senders WHERE sender = 'Jordan'")["disposition"], "normal")
        self.assertEqual(self.one("SELECT COUNT(*) FROM actions WHERE action IN ('rule', 'unrule')")[0], 5)


    def test_a_rule_in_the_persons_words_comes_through_a_card(self):
        with self.conn:
            lock.end(self.conn)   # intake set it; a note may not be left mid-run
        note = decide.leave_note(self.conn, "From now on, file the Daily Digest without asking", self.now)
        bad = {"consumed": [], "people": [], "senders": [], "seen": [note], "items": [
            {"id": note, "class": "house-rule", "outcome": "ready", "reason": "You asked.",
             "work": [{"kind": "rule", "scope": "domain", "pattern": "digest.example", "outcome": "skip",
                       "action": "never read the digest"}]}]}
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, bad, self.now)
        self.assertIn("skip is only for a sender", "\n".join(caught.exception.problems))
        good = copy.deepcopy(bad)
        good["items"][0]["work"] = [{"kind": "rule", "scope": "sender", "pattern": "The Daily Digest",
                                     "outcome": "filed", "action": "file the Daily Digest without asking"}]
        # the other three items at the door must be judged too
        for it in GOOD["items"]:
            good["seen"].append(it["id"]); good["items"].append(copy.deepcopy(it))
        process.process(self.conn, good, self.now)
        pid = self.one("SELECT id FROM proposals WHERE item_id = ?", note)["id"]
        page = pages.checkin(self.conn)
        self.assertIn("From now on, <b>file the Daily Digest without asking</b>", page)
        self.assertIn("read, and filed without asking", page)
        self.assertEqual(self.one("SELECT COUNT(*) FROM handling_rules")[0], 0)   # nothing until the yes
        said = decide.approve(self.conn, pid, self.now)
        self.assertIn("from now on, file the Daily Digest without asking", said)
        rule = self.one("SELECT * FROM handling_rules WHERE status = 'active'")
        self.assertEqual((rule["scope"], rule["pattern"], rule["outcome"], rule["taught_by"]),
                         ("sender", "The Daily Digest", "filed", pid))
        # a skip rule lands in the sender list instead
        skip = {"kind": "rule", "scope": "sender", "pattern": "Casey (recruiter)", "outcome": "skip",
                "source": "email", "action": "never read that recruiter"}
        p = self.one("SELECT * FROM proposals WHERE id = ?", pid)
        decide._rule(self.conn, p, skip, self.now)
        s = self.one("SELECT disposition, taught_by FROM source_senders WHERE sender = 'Casey (recruiter)'")
        self.assertEqual((s["disposition"], s["taught_by"]), ("skip", pid))


    def test_a_rule_can_say_on_its_own_and_the_engine_approves_for_you(self):
        teach(self.conn, "Jordan", "auto", self.now, "Send replies to Jordan without asking")
        process.process(self.conn, copy.deepcopy(GOOD), self.now)
        p = self.one("SELECT status, rule_id FROM proposals WHERE item_id = '01-test-morning-01'")
        self.assertEqual((p["status"], p["rule_id"]), ("approved", "rule-jordan"))
        self.assertEqual(self.one("SELECT COUNT(*) FROM items WHERE status = 'sent'")[0], 1)   # the reply went
        row = self.one("SELECT actor, detail FROM actions WHERE action = 'approve'")
        self.assertEqual(row["actor"], "rule")
        self.assertIn("On its own, under rule-jordan", row["detail"])
        # the other cards still wait for a yes
        self.assertEqual(self.one("SELECT COUNT(*) FROM proposals WHERE status = 'pending'")[0], 3)
        self.assertIn("<b>a house rule</b> said yes", pages.log(self.conn))


if __name__ == "__main__":
    unittest.main()
