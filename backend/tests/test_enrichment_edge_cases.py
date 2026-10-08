"""Offline edge-case tests for Company Enrichment (no network, no API keys). Run: python -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import settings  # noqa: E402

settings.gemini_api_key = ""  # keep the Gemini fallback out of these tests

import app.services.enrichment_engine as eng  # noqa: E402
from app.services.enrichment_store import name_key  # noqa: E402
from app.services.seller_profiles import valid_profile_id  # noqa: E402

PAGES = [{"url": "https://acme.test", "title": "", "text": "We bolt flanges in refineries."}]


class FakeGroq:
    def __init__(self, content):
        self.content = content
        self.chat = type("C", (), {})()
        self.chat.completions = self

    def create(self, **kw):
        msg = type("M", (), {"content": self.content})()
        return type("R", (), {"choices": [type("Ch", (), {"message": msg})()]})()


def run(content):
    return eng.enrich_company(FakeGroq(content), "acme.test", pages=PAGES, website="https://acme.test")[0]


class AppStarts(unittest.TestCase):
    def test_whole_app_imports(self):
        """A syntax error anywhere stops the server from starting (this once broke a deploy)."""
        import app.main  # noqa: F401


class InputClassification(unittest.TestCase):
    def test_names_with_dots_are_not_urls(self):
        for s in ("E.ON", "Acme.Inc", "St.Gobain", "A.P. Moller"):
            self.assertIsNone(eng.normalize_if_url(s), s)

    def test_real_domains_are_urls(self):
        self.assertEqual(eng.normalize_if_url("shell.com"), "https://shell.com")
        self.assertTrue(eng.normalize_if_url("http://shell.com:8080").startswith("http://shell.com:8080"))

    def test_non_latin_names_keep_a_key(self):
        for s in ("阿美石油公司", "شركة أرامكو", "Газпром"):
            self.assertTrue(name_key(s), s)

    def test_blank_names_have_no_key(self):
        self.assertIsNone(name_key("   "))

    def test_profile_id_types(self):
        self.assertEqual(valid_profile_id(None), "tritorc")
        self.assertEqual(valid_profile_id(" OZAT "), "ozat")
        self.assertIsNone(valid_profile_id(5))
        self.assertIsNone(valid_profile_id(["ozat"]))


class BrokenModelAnswers(unittest.TestCase):
    def test_unreadable_answers_raise_instead_of_saving_junk(self):
        for bad in ('{"company_name": "Acme", "llm_decision": "acc', '"hello"', ""):
            with self.assertRaises(eng.AIAnswerError):
                run(bad)

    def test_wrong_shapes_are_normalised(self):
        data = run(json.dumps({"company_name": "Acme", "key_operations": "bolting",
                               "tritorc_relevance": [{"product": "x"}], "projects_or_recent_activity": [None, 5]}))
        for k in ("key_operations", "projects_or_recent_activity", "tritorc_relevance", "fit_products"):
            self.assertIsInstance(data[k], list, k)
            self.assertTrue(all(isinstance(x, str) for x in data[k]), k)

    def test_models_website_is_never_trusted(self):
        data = run(json.dumps({"company_name": "Acme", "website": "javascript://x", "llm_decision": "accept", "company_category": "end_user"}))
        self.assertEqual(data["website"], "https://acme.test")

    def test_spelling_variants_are_understood(self):
        data = run(json.dumps({"company_name": "Acme", "llm_decision": "ACCEPT ", "company_category": "End_User"}))
        self.assertEqual((data["llm_decision"], data["company_category"]), ("accept", "end_user"))


class SafetyAndFiles(unittest.TestCase):
    def test_private_addresses_are_blocked(self):
        for u in ("http://127.0.0.1/", "http://0x7f000001/", "http://[::ffff:127.0.0.1]/", "file:///etc/passwd", "http://169.254.169.254/"):
            self.assertFalse(eng.is_public_url(u), u)

    def test_files(self):
        self.assertEqual(eng.parse_companies_file("a.csv", b"Company;City\nAcme;Berlin\n"), ["Acme"])
        self.assertEqual(eng.parse_companies_file("a.txt", b"Boeing, Inc.\nAcme\n"), ["Boeing, Inc.", "Acme"])
        self.assertEqual(eng.parse_companies_file("a.csv", b"Acme\nacme\nBeta\n"), ["Acme", "Beta"])
        with self.assertRaises(ValueError):
            eng.parse_companies_file("a.txt", bytes(range(256)))


if __name__ == "__main__":
    unittest.main()
