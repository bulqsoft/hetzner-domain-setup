"""Offline safety tests. No DNS, Certbot or server changes are made."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from automation.site_engine import SiteError, issue_approval, plan_site, provision_staging


class StagingEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.auth_file = base / "preview.htpasswd"
        self.auth_file.write_text("test-user:mock-hash\n")
        self.available = base / "nginx-available"
        self.available.mkdir()
        self.enabled = base / "nginx-enabled"
        self.enabled.mkdir()
        self.env = patch.dict(os.environ, {
            "BULQ_ALLOWED_DNS_SUFFIXES": "bulqsoft.com,example.org",
            "BULQ_ALLOWED_SERVER_IPS": "46.224.190.101",
            "BULQ_SITE_ROOT": str(base / "sites"),
            "BULQ_NGINX_AVAILABLE": str(self.available),
            "BULQ_NGINX_ENABLED": str(self.enabled),
            "BULQ_PREVIEW_HTPASSWD": str(self.auth_file),
            "BULQ_CERTBOT_EMAIL": "info@bulqsoft.com",
            "BULQ_APPROVAL_SECRET": "this-is-a-long-demo-key-and-not-a-production-secret",
            "BULQ_APPROVAL_LEDGER": str(base / "approval-ledger"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_non_mutating_plan(self):
        plan = plan_site("sample-client", "staging.bulqsoft.com", "46.224.190.101")
        self.assertEqual(plan["dns_record"]["type"], "A")
        self.assertTrue(plan["requires_approval"])
        self.assertFalse(Path(plan["webroot"]).exists())

    def test_disallowed_domain_and_server(self):
        for host in ("evil.com", "bulqsoft.com", "staging.bulqsoft.com; rm -rf /"):
            with self.subTest(host=host), self.assertRaises(SiteError):
                plan_site("client", host, "46.224.190.101")
        with self.assertRaises(SiteError):
            plan_site("client", "build.bulqsoft.com", "1.1.1.1")

    def test_plan_is_bound_to_exact_domain_and_ip(self):
        plan_a = plan_site("client", "build.bulqsoft.com", "46.224.190.101")
        plan_b = plan_site("client", "preview.bulqsoft.com", "46.224.190.101")
        self.assertNotEqual(plan_a["plan_id"], plan_b["plan_id"])

    def test_valid_approval_and_replay_refused(self):
        plan = plan_site("client", "build.bulqsoft.com", "46.224.190.101")
        token = issue_approval(plan["plan_id"])
        with patch("automation.site_engine.os.geteuid", return_value=0), \
             patch("automation.site_engine._verify_dns"), \
             patch("automation.site_engine._run") as runner:
            result = provision_staging("client", "build.bulqsoft.com", "46.224.190.101", token)
            self.assertTrue(result["protected"])
            self.assertEqual(runner.call_count, 5)
            with self.assertRaises(SiteError):
                provision_staging("client", "build.bulqsoft.com", "46.224.190.101", token)

    def test_bad_signature_does_not_create_files(self):
        plan = plan_site("client", "build.bulqsoft.com", "46.224.190.101")
        token = issue_approval(plan["plan_id"])
        token = token[:-1] + ("a" if token[-1] != "a" else "b")
        with patch("automation.site_engine.os.geteuid", return_value=0), \
             patch("automation.site_engine._verify_dns"):
            with self.assertRaises(SiteError):
                provision_staging("client", "build.bulqsoft.com", "46.224.190.101", token)
        self.assertFalse(Path(plan["webroot"]).exists())

    def test_existing_site_cannot_be_replaced(self):
        plan = plan_site("client", "build.bulqsoft.com", "46.224.190.101")
        Path(plan["webroot"]).mkdir(parents=True)
        token = issue_approval(plan["plan_id"])
        with patch("automation.site_engine.os.geteuid", return_value=0), \
             patch("automation.site_engine._verify_dns"):
            with self.assertRaises(SiteError):
                provision_staging("client", "build.bulqsoft.com", "46.224.190.101", token)

    def test_expired_approval(self):
        plan = plan_site("client", "build.bulqsoft.com", "46.224.190.101")
        token = issue_approval(plan["plan_id"], now=int(time.time()) - 3600)
        with patch("automation.site_engine.os.geteuid", return_value=0), \
             patch("automation.site_engine._verify_dns"):
            with self.assertRaises(SiteError):
                provision_staging("client", "build.bulqsoft.com", "46.224.190.101", token)


if __name__ == "__main__":
    unittest.main()
