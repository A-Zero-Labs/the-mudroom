"""The engine test for the cards: a yes carries out the work, a no ends it, a send-back keeps
the words and has the item judged again. Runs against the throwaway database and the tests'
own judgements, never the demo's week."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from engine import db, decide, lock, process
from engine.agents import nothing_to_do

HERE = Path(__file__).resolve().parent
GOOD = json.loads((HERE / "handover" / "good.json").read_text(encoding="utf-8"))


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = db.DB_PATH
        self.conn = helpers.stage(self.tmp)
        self.now = db.get_state(self.conn, "clock")
        process.process(self.conn, copy.deepcopy(GOOD), self.now)

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def one(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()

    def count(self, sql, *args):
        return self.one(sql, *args)[0]

    def proposal_for(self, item_id):
        return self.one("SELECT * FROM proposals WHERE item_id = ? AND status = 'pending'", (item_id))["id"]

    def test_a_yes_carries_out_the_work_and_logs_each_effect(self):
        pid = self.proposal_for("01-test-morning-01")   # a reply and a loop to hold
        said = decide.approve(self.conn, pid, self.now)
        self.assertTrue(said.startswith("Approved: "))
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "approved")
        loop = self.one("SELECT * FROM commitments WHERE source = '01-test-morning-01'")
        self.assertEqual((loop["owner"], loop["person_id"], loop["due"]), ("me", "jordan", "2026-09-16T12:00"))
        # the reply went out: an interaction the other way, and a row that cannot be undone
        self.assertEqual(self.count(
            "SELECT COUNT(*) FROM interactions WHERE item_id = '01-test-morning-01' AND direction = 'out'"), 1)
        sent = self.one("SELECT * FROM actions WHERE action = 'send'")
        self.assertEqual(sent["reversible"], 0)
        self.assertIn("Wednesday it is", sent["detail"])
        # the copy of the reply is in items, beneath the item it answered, and not at the door
        copy_ = self.one("SELECT * FROM items WHERE status = 'sent'")
        self.assertEqual((copy_["id"], copy_["sender"], copy_["thread"], copy_["source"]),
                         ("sent-1", "Alex", "01-test-morning-01", "email"))
        self.assertTrue(copy_["subject"].startswith("Re: "))
        self.assertEqual(json.loads(copy_["raw"])["to"], "Jordan")
        self.assertTrue(nothing_to_do(self.conn))
        from engine import pages
        page = pages.doorstep(self.conn)
        self.assertIn("Alex <small>(you)</small>", page)
        self.assertIn('class="item sent email" id="sent-1"', page)
        self.assertLess(page.index('id="01-test-morning-01"'), page.index('id="sent-1"'))
        # the yes is the person's row, the effects are the engine's
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE actor = 'alex' AND action = 'approve'"), 1)
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE actor = 'engine' AND action = 'commitment'"), 1)
        # a second yes on the same card is refused
        with self.assertRaises(decide.Refused):
            decide.approve(self.conn, pid, self.now)

    def test_an_update_changes_what_exists_and_keeps_what_it_was(self):
        pid = self.proposal_for("01-test-morning-02")   # close a loop, add a diary entry
        decide.approve(self.conn, pid, self.now)
        loop = self.one("SELECT * FROM commitments WHERE id = 'chris-test-results'")
        self.assertEqual((loop["status"], loop["closed_by"]), ("closed", "01-test-morning-02"))
        event = self.one("SELECT * FROM events WHERE source = '01-test-morning-02'")
        self.assertEqual((event["title"], event["start"], event["end"]),
                         ("Read the test summary", "2026-09-15T09:30", "2026-09-15T09:45"))
        from engine import pages
        self.assertIn('href="/doorstep#01-test-morning-02">from Chris', pages.planner(self.conn))
        before = json.loads(self.one("SELECT detail FROM actions WHERE action = 'update'")["detail"])["before"]
        self.assertEqual(before["status"], "open")

    def test_filing_puts_the_original_away_and_all_at_once_works(self):
        pid = self.proposal_for("01-test-morning-03")
        decide.approve(self.conn, pid, self.now)
        self.assertEqual(self.one("SELECT status FROM items WHERE id = '01-test-morning-03'")["status"], "filed")
        self.assertEqual(decide.file_all(self.conn, self.now), "Filed 0 away.")

    def test_a_no_needs_no_words_and_does_nothing(self):
        pid = self.proposal_for("01-test-morning-01")
        decide.decline(self.conn, pid, self.now)
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "declined")
        self.assertEqual(self.count("SELECT COUNT(*) FROM commitments WHERE source = '01-test-morning-01'"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'decline'"), 1)

    def test_a_yours_card_takes_no_yes(self):
        with self.assertRaises(decide.Refused):
            decide.approve(self.conn, self.proposal_for("01-test-morning-04"), self.now)

    def test_sending_back_needs_words_and_has_the_item_judged_again(self):
        pid = self.proposal_for("01-test-morning-01")
        with self.assertRaises(decide.Refused):
            decide.send_back(self.conn, pid, "  ", self.now)
        self.assertTrue(nothing_to_do(self.conn))
        decide.send_back(self.conn, pid, "Say Thursday, not Wednesday.", self.now)
        row = self.one("SELECT status, sent_back FROM proposals WHERE id = ?", pid)
        self.assertEqual((row["status"], row["sent_back"]), ("sent_back", "Say Thursday, not Wednesday."))
        self.assertFalse(nothing_to_do(self.conn))
        # the next run must judge it again: a file that leaves it out is refused
        empty = {"consumed": [], "people": [], "senders": [], "seen": [], "items": []}
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, empty, self.now)
        self.assertIn("was sent back", "\n".join(caught.exception.problems))
        # and a file that judges it again supersedes the sent-back card
        again = {"consumed": [], "people": [], "senders": [], "seen": ["01-test-morning-01"],
                 "items": [dict(GOOD["items"][0], work=[{"kind": "reply", "body": "Jordan, Thursday. Alex"}])]}
        process.process(self.conn, again, self.now)
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "superseded")
        fresh = self.one("SELECT * FROM proposals WHERE item_id = '01-test-morning-01' AND status = 'pending'")
        self.assertIn("Thursday", fresh["work"])
        self.assertTrue(nothing_to_do(self.conn))


    def test_a_yours_card_answered_is_folded_in_on_the_next_run(self):
        pid = self.proposal_for("01-test-morning-04")
        with self.assertRaises(decide.Refused):
            decide.answer(self.conn, pid, " ", self.now)
        decide.answer(self.conn, pid, "Yes, take the call.", self.now)
        q = self.one("SELECT * FROM questions WHERE id = 'question-1'")
        self.assertEqual((q["status"], q["answer"]), ("answered", "Yes, take the call."))
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "answered")
        self.assertFalse(nothing_to_do(self.conn))
        # the next run consumes the answer and judges the item again; the answered card is superseded
        again = {"consumed": ["question-1"], "people": [],
                 "senders": [{"sender": "Casey (recruiter)", "source": "email", "disposition": "normal",
                              "from": "question-1"}],
                 "seen": ["01-test-morning-04"],
                 "items": [{"id": "01-test-morning-04", "class": "reply-needed", "outcome": "ready",
                            "reason": "You said yes, so a reply is ready.",
                            "work": [{"kind": "reply", "body": "Casey, yes, Thursday works."}]}]}
        process.process(self.conn, again, self.now)
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "superseded")
        self.assertEqual(self.one("SELECT status FROM questions WHERE id = 'question-1'")["status"], "consumed")
        self.assertTrue(nothing_to_do(self.conn))

    def test_done_and_ignore_close_the_question_without_teaching(self):
        pid = self.proposal_for("01-test-morning-04")
        decide.ignore(self.conn, pid, self.now)
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "declined")
        self.assertEqual(self.one("SELECT status FROM questions WHERE id = 'question-1'")["status"], "closed")
        self.assertEqual(self.count("SELECT COUNT(*) FROM source_senders WHERE sender = 'Casey (recruiter)'"), 0)
        self.assertTrue(nothing_to_do(self.conn))
        with self.assertRaises(decide.Refused):
            decide.done(self.conn, self.proposal_for("01-test-morning-01"), self.now)

    def test_a_choose_card_turns_picks_into_tasks_and_loops(self):
        chosen = json.loads((HERE / "handover" / "choose.json").read_text(encoding="utf-8"))
        with self.conn:
            self.conn.execute("UPDATE items SET status = 'staged' WHERE id = '01-test-morning-04'")
        process.process(self.conn, chosen, self.now)
        pid = self.proposal_for("01-test-morning-04")
        with self.assertRaises(decide.Refused):
            decide.choose(self.conn, pid, ["7"], self.now)
        said = decide.choose(self.conn, pid, ["0", "2"], self.now)
        self.assertTrue(said.startswith("Picked: "))
        self.assertEqual(self.one("SELECT title FROM tasks WHERE source = '01-test-morning-04'")["title"],
                         "Send Casey the job description")
        loop = self.one("SELECT * FROM commitments WHERE source = '01-test-morning-04'")
        self.assertEqual((loop["owner"], loop["person_id"], loop["what"]), ("them", "jordan", "Jordan checks the budget"))
        self.assertEqual(self.count("SELECT COUNT(*) FROM tasks WHERE source = '01-test-morning-04'"), 1)
        self.assertEqual(self.one("SELECT status FROM proposals WHERE id = ?", pid)["status"], "approved")


    def test_tick_and_untick_from_the_planner(self):
        with self.assertRaises(decide.Refused):
            decide.tick(self.conn, "no-such-task", self.now)
        said = decide.tick(self.conn, "project-update", self.now)
        self.assertTrue(said.startswith("Done: "))
        t = self.one("SELECT status, done_at FROM tasks WHERE id = 'project-update'")
        self.assertEqual((t["status"], t["done_at"]), ("done", self.now))
        with self.assertRaises(decide.Refused):
            decide.tick(self.conn, "project-update", self.now)
        from engine import pages
        page = pages.planner(self.conn)
        self.assertIn('<li class="task done">', page)
        self.assertLess(page.index("<h3>Today</h3>") if "<h3>Today</h3>" in page else 0,
                        page.index("<h3>Overdue</h3>") if "<h3>Overdue</h3>" in page else 1)
        self.assertIn('action="/task/untick"', page)
        decide.untick(self.conn, "project-update", self.now)
        t = self.one("SELECT status, done_at FROM tasks WHERE id = 'project-update'")
        self.assertEqual((t["status"], t["done_at"]), ("open", None))
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action IN ('tick', 'untick') AND actor = 'alex'"), 2)


    def test_a_note_goes_to_the_door_without_starting_a_run(self):
        with self.assertRaises(decide.Refused):
            decide.leave_note(self.conn, "  ", self.now)
        self.assertTrue(nothing_to_do(self.conn))
        nid = decide.leave_note(self.conn, "Book the dentist for Kim before half term", self.now)
        item = self.one("SELECT * FROM items WHERE id = ?", nid)
        self.assertEqual((item["source"], item["sender"], item["status"], item["staged_at"]),
                         ("capture", "Alex", "staged", self.now))
        self.assertIsNone(lock.held(self.conn))
        self.assertFalse(nothing_to_do(self.conn))
        from engine import pages
        self.assertIn(f'class="item capture" id="{nid}"', pages.doorstep(self.conn))
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'note' AND actor = 'alex'"), 1)
        # the next run must judge it like anything at the door
        empty = {"consumed": [], "people": [], "senders": [], "seen": [], "items": []}
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, empty, self.now)
        self.assertIn(f"{nid} is at the door", "\n".join(caught.exception.problems))

    def test_no_press_lands_while_a_run_is_in_flight(self):
        with self.conn:
            lock.begin(self.conn)
        for press in (lambda: decide.approve(self.conn, self.proposal_for("01-test-morning-01"), self.now),
                      lambda: decide.tick(self.conn, "project-update", self.now),
                      lambda: decide.leave_note(self.conn, "a thought", self.now)):
            with self.assertRaises(decide.Refused) as caught:
                press()
            self.assertIn("in flight", str(caught.exception))
        with self.conn:
            lock.end(self.conn)
        decide.tick(self.conn, "project-update", self.now)


    def test_an_invitation_is_accepted_or_declined_from_its_card(self):
        # the tests' batch has no invitation, so one is staged by hand through intake
        from engine import intake
        intake.register(self.conn, {"source": "calendar", "account": "test", "items": [
            {"id": "invite-1", "source": "calendar", "sender": "Jordan", "subject": "One-to-one (moved)",
             "body": "Thursday instead.", "received_at": self.now,
             "raw": {"when": "Thursday 14:00 to 14:30"}}]}, run=False)
        with self.conn:
            self.conn.execute("INSERT INTO questions (id, subject, question, status) "
                              "VALUES ('q-moved', 'event:one-to-one', 'Still on?', 'open')")
        moved = {"consumed": [], "people": [], "senders": [], "seen": ["invite-1"], "items": [
            {"id": "invite-1", "class": "notice-to-diary", "outcome": "ready",
             "reason": "Jordan moved the one-to-one to Thursday at two.",
             "work": [{"kind": "update", "target": "event:one-to-one",
                       "changes": {"start": "Thursday 14:00", "end": "Thursday 14:30"}},
                      {"kind": "update", "target": "question:q-moved", "changes": {"status": "closed"}}]}]}
        process.process(self.conn, moved, self.now)
        pid = self.proposal_for("invite-1")
        from engine import pages
        page = pages.checkin(self.conn)
        self.assertIn("Jordan <small>(owns the bakery)</small>", page)   # names say who they are to you
        self.assertIn(">Accept<", page)
        self.assertIn("What accepting does", page)
        self.assertIn("Close the question, settled by this", page)
        said = decide.approve(self.conn, pid, self.now)
        self.assertTrue(said.startswith("Accepted: "))
        e = self.one("SELECT start, end FROM events WHERE id = 'one-to-one'")
        self.assertEqual((e["start"], e["end"]), ("2026-09-17T14:00", "2026-09-17T14:30"))
        self.assertEqual(self.one("SELECT status FROM questions WHERE id = 'q-moved'")["status"], "closed")
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'accept'"), 1)
        # a question may only be closed this way, never answered or reopened
        bad = copy.deepcopy(moved)
        bad["items"][0]["work"][1]["changes"] = {"status": "open"}
        with self.conn:
            self.conn.execute("UPDATE items SET status = 'staged' WHERE id = 'invite-1'")
        with self.assertRaises(process.Refused):
            process.process(self.conn, bad, self.now)


    def test_a_fresh_email_is_a_kind_of_work(self):
        wrong = {"consumed": [], "people": [], "senders": [], "seen": ["01-test-morning-01"],
                 "items": [copy.deepcopy(GOOD["items"][0])]}
        wrong["items"][0]["work"] = [{"kind": "email", "to": "nobody", "subject": "Hi", "body": "Hello"}]
        with self.conn:
            self.conn.execute("UPDATE items SET status = 'staged' WHERE id = '01-test-morning-01'")
        with self.assertRaises(process.Refused) as caught:
            process.process(self.conn, wrong, self.now)
        self.assertIn("not a person the engine knows", "\n".join(caught.exception.problems))
        fresh = copy.deepcopy(wrong)
        fresh["items"][0]["work"] = [{"kind": "email", "to": "taylor", "subject": "Capacity check",
                                      "body": "Taylor, where are we on the numbers?\n\nAlex"}]
        process.process(self.conn, fresh, self.now)
        pid = self.proposal_for("01-test-morning-01")
        from engine import pages
        self.assertIn("Send an email to <b>Taylor", pages.checkin(self.conn))
        said = decide.approve(self.conn, pid, self.now)
        self.assertIn("email sent to Taylor", said)
        copy_ = self.one("SELECT * FROM items WHERE status = 'sent'")
        self.assertEqual((copy_["subject"], json.loads(copy_["raw"])["to"], json.loads(copy_["raw"])["fresh"]),
                         ("Capacity check", "Taylor", True))
        self.assertIn("Your email", pages.doorstep(self.conn))
        self.assertEqual(self.count("SELECT COUNT(*) FROM interactions WHERE person_id = 'taylor' AND direction = 'out'"), 1)


    def test_the_checkin_opens_with_what_the_last_run_did(self):
        from engine import pages
        line = pages.since_last_time(self.conn)   # composed, no longer shown on the page
        self.assertIn("Test morning brought 4 items in.", line)
        self.assertIn("2 ready for you, 1 for your input, 1 filed away.", line)
        self.assertNotIn("heads-up.", line)
        self.assertNotIn("Since last time", pages.checkin(self.conn))


    def test_the_log_page_reads_every_row_in_plain_words(self):
        from engine import pages
        decide.approve(self.conn, self.proposal_for("01-test-morning-01"), self.now)
        decide.tick(self.conn, "project-update", self.now)
        page = pages.log(self.conn)
        self.assertIn("<b>you</b> said yes", page)
        self.assertIn("<b>you</b> ticked", page)
        self.assertIn("<b>the door</b> sent", page)
        self.assertIn("cannot be undone", page)
        self.assertIn("<b>the door</b> sorted", page)
        presses = pages.log(self.conn, {"show": ["presses"]})
        self.assertIn("<b>you</b> said yes", presses)
        self.assertNotIn("<b>the door</b>", presses)
        runs = pages.log(self.conn, {"show": ["runs"]})
        self.assertIn("brought in", runs)
        self.assertNotIn("said yes", runs)


    def test_the_panels_show_promises_and_questions_and_take_an_answer(self):
        from engine import pages
        decide.approve(self.conn, self.proposal_for("01-test-morning-01"), self.now)   # you promised Jordan
        with self.conn:
            self.conn.execute("INSERT INTO questions (id, subject, question, status, asked_on) "
                              "VALUES ('q-seed', 'event:one-to-one', 'Still on Wednesday?', 'open', ?)", (self.now,))
        page = pages.checkin(self.conn)
        self.assertIn("You promised Jordan <small>(owns the bakery)</small>: Send the steering pack", page)
        self.assertIn("Chris <small>(on the counter and the till)</small> promised you", page)
        self.assertIn('action="/question/answer"', page)       # the seed question takes its answer here
        self.assertIn('href="#01-test-morning-04"', page)      # the card question points at its card
        with self.assertRaises(decide.Refused):
            decide.answer_question(self.conn, "q-seed", " ", self.now)
        decide.answer_question(self.conn, "q-seed", "Yes, still on.", self.now)
        q = self.one("SELECT status, answer FROM questions WHERE id = 'q-seed'")
        self.assertEqual((q["status"], q["answer"]), ("answered", "Yes, still on."))
        self.assertFalse(nothing_to_do(self.conn))
        self.assertNotIn("<span>Still on Wednesday?</span>", pages.checkin(self.conn))   # gone from the panel


    def test_the_front_door_welcomes_and_the_diagram_has_its_own_page(self):
        from engine import pages
        page = pages.welcome(self.conn)
        self.assertIn("<h1>Boots off.", page)
        self.assertIn('class="room"', page)   # the drawing
        for tile in ("Ready for you", "Needs your input", "Heads-up", "Filed away"):
            self.assertIn(f"<b>{tile}</b>", page)
        self.assertIn('href="/piping"', page)
        from engine import demo
        self.assertIn('<span class="group">Play the demo</span>' if demo.present() else
                      '<span class="group">Your house</span>', page)
        self.assertIn("What's next", pages.whats_next(self.conn))
        self.assertIn('href="/whats-next"', page)   # the second panel points at the pitch, not the command
        # the front door sends you to the Doorstep and brings nothing in; once the demo has left, to the dashboard
        self.assertIn('class="go-button" href="/doorstep"' if demo.present() else 'class="go-button" href="/sorted"', page)
        self.assertNotIn('class="arch"', page)
        self.assertIn('class="arch"', pages.landing(self.conn))


    def test_a_promise_can_be_resolved_by_hand(self):
        from engine import pages
        decide.approve(self.conn, self.proposal_for("01-test-morning-01"), self.now)
        cid = self.one("SELECT id FROM commitments WHERE source = '01-test-morning-01'")["id"]
        self.assertIn('action="/promise/close"', pages.checkin(self.conn))
        with self.assertRaises(decide.Refused):
            decide.close_promise(self.conn, cid, "forgot", self.now)
        said = decide.close_promise(self.conn, cid, "resolved", self.now)
        self.assertTrue(said.startswith("Resolved: "))
        row = self.one("SELECT status, closed_by FROM commitments WHERE id = ?", cid)
        self.assertEqual((row["status"], row["closed_by"]), ("closed", "you"))
        with self.assertRaises(decide.Refused):
            decide.close_promise(self.conn, cid, "resolved", self.now)
        self.assertNotIn(cid, pages.checkin(self.conn))
        self.assertEqual(self.count("SELECT COUNT(*) FROM actions WHERE action = 'promise-resolved'"), 1)


if __name__ == "__main__":
    unittest.main()
