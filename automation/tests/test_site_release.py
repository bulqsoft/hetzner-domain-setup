"""Offline tests for the approval-gated staging release worker."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.site_engine import SiteError, issue_approval
from automation.site_release import (
    plan_site_release, publish_approved_site_release, site_release_status
)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.stage = base / "sites" / "client" / "staging"
        bootstrap = self.stage / "releases" / "bootstrap"
        bootstrap.mkdir(parents=True)
        (bootstrap / "index.html").write_text("Protected placeholder", encoding="utf-8")
        (self.stage / "current").symlink_to("releases/bootstrap")
        (self.stage / ".bulq-managed.json").write_text(
            json.dumps({"version": 1, "project": "client", "hostname": "preview.example.org"})
        )
        self.env = patch.dict(os.environ, {
            "BULQ_SITE_ROOT": str(base / "sites"),
            "BULQ_APPROVAL_SECRET": "only-a-unit-test-secret-please-keep-it-long",
            "BULQ_APPROVAL_LEDGER": str(base / "approvals"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.files = {
            "index.html": "<!doctype html><title>Client</title><h1>Created by AI</h1>",
            "assets/site.css": "body { font-family: sans-serif; }",
        }

    def _publish(self, files=None, expected="bootstrap"):
        files = self.files if files is None else files
        plan = plan_site_release("client", files, expected)
        token = issue_approval(plan["plan_id"])
        with patch("automation.site_release.os.geteuid", return_value=1001):
            return publish_approved_site_release("client", files, expected, token)

    def test_plan_does_not_write_and_is_bound_to_contents(self):
        plan = plan_site_release("client", self.files, "bootstrap")
        other = plan_site_release("client", {"index.html": "different"}, "bootstrap")
        self.assertNotEqual(plan["plan_id"], other["plan_id"])
        self.assertTrue(plan["requires_approval"])
        self.assertFalse((self.stage / ".release.lock").exists())
        self.assertEqual(site_release_status("client")["active_revision"], "bootstrap")

    def test_first_and_second_revision_are_atomic(self):
        first = self._publish()
        self.assertEqual(first["previous_revision"], "bootstrap")
        self.assertEqual(site_release_status("client")["active_revision"], first["active_revision"])
        self.assertEqual((self.stage / "current" / "index.html").read_text(), self.files["index.html"])
        self.assertEqual((self.stage / "releases" / "bootstrap" / "index.html").read_text(),
                         "Protected placeholder")
        second = self._publish({"index.html": "<h1>Revised</h1>"}, first["active_revision"])
        self.assertEqual((self.stage / "current" / "index.html").read_text(), "<h1>Revised</h1>")
        self.assertNotEqual(first["active_revision"], second["active_revision"])
        self.assertTrue((self.stage / "releases" / first["active_revision"]).is_dir())

    def test_stale_revision_refused_without_removing_current(self):
        self._publish()
        with self.assertRaisesRegex(SiteError, "Staging changed"):
            self._publish({"index.html": "Another version"}, "bootstrap")
        self.assertEqual((self.stage / "current" / "index.html").read_text(), self.files["index.html"])

    def test_non_managed_directory_and_root_process_rejected(self):
        (self.stage / ".bulq-managed.json").unlink()
        with self.assertRaises(SiteError):
            self._publish()
        (self.stage / ".bulq-managed.json").write_text(
            json.dumps({"version": 1, "project": "client"})
        )
        plan = plan_site_release("client", self.files, "bootstrap")
        with patch("automation.site_release.os.geteuid", return_value=0):
            with self.assertRaisesRegex(SiteError, "must not run as root"):
                publish_approved_site_release("client", self.files, "bootstrap",
                                              issue_approval(plan["plan_id"]))

    def test_invalid_paths_and_oversized_release(self):
        for name in ("../index.html", "/index.html", "assets//evil.css",
                     "assets/.secret", "assets/../../escape.js", "scripts/run.py"):
            with self.subTest(name=name), self.assertRaises(SiteError):
                plan_site_release("client", {"index.html": "ok", name: "bad"}, "bootstrap")
        with self.assertRaises(SiteError):
            plan_site_release("client", {"index.html": "x" * (1024 * 1024 + 1)}, "bootstrap")
        with self.assertRaises(SiteError):
            plan_site_release("client", {"index.html": "ok"}, "../live")

    def test_invalid_approval_and_duplicate_release(self):
        plan = plan_site_release("client", self.files, "bootstrap")
        with patch("automation.site_release.os.geteuid", return_value=1001):
            with self.assertRaises(SiteError):
                publish_approved_site_release("client", self.files, "bootstrap", "bad-token")
        self.assertFalse((self.stage / "releases" / plan["release_id"]).exists())
        self._publish()
        with self.assertRaises(SiteError):
            self._publish(self.files, plan["release_id"])

    def test_malicious_current_symlink_refused(self):
        (self.stage / "current").unlink()
        (self.stage / "current").symlink_to("/etc")
        with self.assertRaises(SiteError):
            self._publish()


if __name__ == "__main__":
    unittest.main()
