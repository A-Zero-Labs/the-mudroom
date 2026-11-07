"""doctor says what is missing on a machine and how to fix it there, before anything starts."""
import unittest
from unittest import mock

from engine import doctor


class DoctorTest(unittest.TestCase):
    def test_this_machine_runs_every_check_and_reports_in_ascii(self):
        text, _ = doctor.report()
        text.encode("ascii")   # a Windows console on an old code page must be able to print it
        for name in ("Python 3.12", "SQLite", "'python' or 'python3'", "Claude Code", "written to", "port"):
            self.assertIn(name, text)

    def test_a_required_failure_means_not_ready(self):
        results = [doctor.Check("Python", True, "3.12"), doctor.Check("Claude Code", False, "not found", "install it")]
        text, ready = doctor.report(results)
        self.assertFalse(ready)
        self.assertIn("[FIX ] Claude Code: not found", text)
        self.assertIn("fix: install it", text)

    def test_a_warning_alone_still_means_ready(self):
        results = [doctor.Check("Python", True, "3.12"), doctor.Check("Port", False, "taken", "close it", required=False)]
        text, ready = doctor.report(results)
        self.assertTrue(ready)
        self.assertIn("[WARN] Port", text)

    def test_the_windows_store_stub_does_not_count_as_python(self):
        stub = r"C:\Users\alex\AppData\Local\Microsoft\WindowsApps\python.exe"
        with mock.patch.object(doctor, "WINDOWS", True), \
                mock.patch.object(doctor.shutil, "which", lambda name: stub), \
                mock.patch.object(doctor, "answers", lambda path: True):
            check = doctor.command_check()
        self.assertFalse(check.ok)
        self.assertIn("App execution aliases", check.fix)
        self.assertIn("winget", check.fix + doctor.install_python())

    def test_missing_claude_says_how_to_install_it(self):
        with mock.patch.object(doctor, "executable", lambda: None):
            check = doctor.claude_check()
        self.assertFalse(check.ok)
        self.assertIn("claude.com/claude-code", check.fix)

    def test_windows_install_advice_uses_winget_and_says_to_reopen(self):
        with mock.patch.object(doctor, "WINDOWS", True):
            advice = doctor.install_python()
        self.assertIn("winget install -e --id Python.Python.3.12", advice)
        self.assertIn("reopen Claude Code", advice)

    def test_windows_without_git_is_not_ready(self):
        with mock.patch.object(doctor, "WINDOWS", True), \
                mock.patch.object(doctor.shutil, "which", lambda name: None), \
                mock.patch.object(doctor, "git_bash_on_disk", lambda: None):
            check = doctor.git_bash_check()
        self.assertFalse(check.ok)
        self.assertTrue(check.required)
        self.assertIn("Git.Git", check.fix)

    def test_git_is_not_asked_for_outside_windows(self):
        with mock.patch.object(doctor, "WINDOWS", False):
            self.assertIsNone(doctor.git_bash_check())


if __name__ == "__main__":
    unittest.main()
