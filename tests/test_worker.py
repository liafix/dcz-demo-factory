import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from argparse import Namespace
from factory.worker import Blocked, canonical_key, email_draft_text, render, run, slugify, validate

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic-lead.json"

class PilotTests(unittest.TestCase):
    def lead(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_slug(self):
        self.assertEqual(slugify("Kaderníctvo Krystal"), "kadernictvo-krystal")

    def test_gate_valid_synthetic_dryrun(self):
        self.assertTrue(validate(self.lead(), dry_run=True).startswith("phone:"))

    def test_synthetic_rejected_live(self):
        with self.assertRaises(Blocked): validate(self.lead(), dry_run=False)

    def test_owned_website_rejected(self):
        x = self.lead(); x["verification"]["no_owned_website"]=False
        with self.assertRaises(Blocked): validate(x, dry_run=True)

    def test_incomplete_sources_rejected(self):
        x = self.lead(); x["verification"]["checks"].pop()
        with self.assertRaises(Blocked): validate(x, dry_run=True)

    def test_duplicate_activity_rejected(self):
        x=self.lead(); x["verification"]["activity_signals"][1]=x["verification"]["activity_signals"][0]
        with self.assertRaises(Blocked): validate(x,dry_run=True)

    def test_suppression_rejected(self):
        x=self.lead(); x["suppressed"]=True
        with self.assertRaises(Blocked): validate(x,dry_run=True)

    def test_other_worker_rejected(self):
        x=self.lead(); x["owner_worker"]="OutreachOS"
        with self.assertRaises(Blocked): validate(x,dry_run=True)

    def test_html_is_safe_and_noindex(self):
        x=self.lead(); x["company"]='<script>alert("x")</script>'
        result=render(x)
        self.assertIn("&lt;script&gt;",result)
        self.assertNotIn('<script>alert',result)
        self.assertIn('noindex,nofollow',result)
        self.assertIn('tel:+421000000000',result)

    def test_dry_run_repeat_is_idempotent(self):
        with TemporaryDirectory() as folder:
            args=Namespace(input=str(FIXTURE),stage="dry-run",output=folder,url="")
            a=run(args); b=run(args)
            self.assertEqual(a["source"],b["source"])
            self.assertEqual(a["send_count"],0)
            self.assertEqual(len(list(Path(folder).rglob("index.html"))),1)

    def test_invalid_url_draft(self):
        with self.assertRaises(Blocked): email_draft_text(self.lead(),"http://example.com")

    def test_email_contains_one_cta_and_unofficial_disclaimer(self):
        txt=email_draft_text(self.lead(),"https://dcz-demo-factory.vercel.app/demos/test/")
        self.assertEqual(txt.count("?"),1)
        self.assertIn("neoficiálna",txt)
        self.assertIn("dcz-demo-factory.vercel.app",txt)

if __name__ == "__main__":
    unittest.main()
