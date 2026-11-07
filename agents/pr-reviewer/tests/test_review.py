#!/usr/bin/env python3
"""
Tests for claude_review.py — stdlib unittest, no network required.

    python -m unittest discover -s tests -v

The fixture diffs below are synthetic on purpose: they pin the detector to the exact
patterns it claims to catch, so a regression shows up as a failing test instead of a
quietly useless review.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_review as cr  # noqa: E402


def review_diff(diff: str, title: str = "test change"):
    pr = cr.PullRequest(owner="o", repo="r", number=1, title=title, diff=diff,
                        files=cr.parse_diff(diff))
    pr.changed_files = len(pr.files)
    return pr, cr.review_locally(pr)


def diff_for(path: str, added: list[str], removed: list[str] | None = None) -> str:
    removed = removed or []
    lines = [
        f"diff --git a/{path} b/{path}",
        "index 1111111..2222222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -1,{len(removed)} +1,{len(added)} @@",
    ]
    lines += [f"-{l}" for l in removed]
    lines += [f"+{l}" for l in added]
    return "\n".join(lines) + "\n"


class Parsing(unittest.TestCase):
    def test_counts_and_line_numbers(self):
        diff = diff_for("src/app.py", ["print('hi')", "x = 1"], ["old = 2"])
        files = cr.parse_diff(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].path, "src/app.py")
        self.assertEqual(files[0].added, 2)
        self.assertEqual(files[0].removed, 1)
        self.assertEqual([n for n, _ in files[0].added_lines], [1, 2])

    def test_multi_file(self):
        diff = diff_for("a.py", ["x = 1"]) + diff_for("b.ts", ["const y = 2;"])
        self.assertEqual([f.path for f in cr.parse_diff(diff)], ["a.py", "b.ts"])

    def test_binary_flagged(self):
        diff = "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"
        files = cr.parse_diff(diff)
        self.assertTrue(files[0].is_binary)


class Risks(unittest.TestCase):
    def assertFlagged(self, diff: str, needle: str):
        _, review = review_diff(diff)
        joined = " ".join(r.message + " " + r.location for r in review.risks).lower()
        self.assertIn(needle.lower(), joined, f"expected a risk mentioning {needle!r}, got: {joined}")

    def test_hardcoded_secret(self):
        self.assertFlagged(
            diff_for("config/settings.py", ['API_KEY = "sk-live-abcdef1234567890"']),
            "credential",
        )

    def test_private_key(self):
        self.assertFlagged(
            diff_for("deploy/key.pem", ["-----BEGIN RSA PRIVATE KEY-----"]),
            "private key",
        )

    def test_shell_true(self):
        self.assertFlagged(
            diff_for("src/run.py", ["subprocess.run(cmd, shell=True)"]),
            "shell=true",
        )

    def test_eval(self):
        self.assertFlagged(diff_for("src/x.py", ["result = eval(user_input)"]), "eval")

    def test_sql_interpolation(self):
        self.assertFlagged(
            diff_for("src/db.py", ['cursor.execute(f"SELECT * FROM t WHERE id={uid}")']),
            "sql",
        )

    def test_xss_sink(self):
        self.assertFlagged(
            diff_for("web/app.js", ["el.innerHTML = userInput;"]),
            "innerhtml",
        )

    def test_tls_disabled(self):
        self.assertFlagged(
            diff_for("src/client.py", ["requests.get(url, verify=False)"]),
            "tls",
        )

    def test_swallowed_exception(self):
        self.assertFlagged(
            diff_for("src/job.py", ["try:", "    work()", "except Exception:", "    pass"]),
            "swallow",
        )

    def test_env_file(self):
        self.assertFlagged(diff_for(".env", ["SECRET=abc"]), ".env")


class Structure(unittest.TestCase):
    def test_missing_tests_suggested(self):
        _, review = review_diff(diff_for("src/core.py", ["def login():", "    return True"]))
        self.assertTrue(any("test" in s.lower() for s in review.suggestions))

    def test_tests_present_is_acknowledged(self):
        diff = diff_for("src/core.py", ["def login():", "    return True"]) + \
               diff_for("tests/test_core.py", ["def test_login():", "    assert login()"])
        _, review = review_diff(diff)
        self.assertIn("Tests are included", review.summary)

    def test_shrinking_tests_flagged(self):
        diff = diff_for("tests/test_api.py", ["def test_ok():", "    assert True"],
                        ["def test_a():", "    assert a()", "def test_b():", "    assert b()"])
        _, review = review_diff(diff)
        self.assertTrue(any("net-shrinking" in r.message for r in review.risks))

    def test_lockfile_without_manifest(self):
        diff = diff_for("poetry.lock", ["name = 'requests'", "version = '2.32.0'"])
        _, review = review_diff(diff)
        self.assertTrue(any("lockfile" in r.message.lower() for r in review.risks))

    def test_migration_flagged(self):
        _, review = review_diff(diff_for("migrations/0002_drop.sql", ["ALTER TABLE users DROP COLUMN email;"]))
        self.assertTrue(any("schema" in r.message.lower() for r in review.risks))

    def test_binary_flagged(self):
        diff = "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"
        _, review = review_diff(diff)
        self.assertTrue(any("binary" in r.message.lower() for r in review.risks))

    def test_large_diff_lowers_confidence(self):
        added = [f"x{i} = {i}" for i in range(1100)]
        _, review = review_diff(diff_for("src/big.py", added))
        self.assertEqual(review.confidence, "Low")

    def test_small_clean_diff_is_high_confidence(self):
        _, review = review_diff(diff_for("src/tiny.py", ["VALUE = 1"]))
        self.assertEqual(review.confidence, "High")

    def test_docs_are_not_scanned_as_code(self):
        _, review = review_diff(diff_for("README.md", ["call print( value ) to debug", "TODO: write docs"]))
        messages = " ".join(r.message for r in review.risks).lower()
        self.assertNotIn("print()", messages)
        self.assertNotIn("todo", messages)

    def test_no_risk_sentinel_present(self):
        _, review = review_diff(diff_for("src/tiny.py", ["VALUE = 1"]))
        self.assertTrue(review.risks, "the risks section must never be empty")
        self.assertIn("No blocking risk", review.risks[0].message)


class Rendering(unittest.TestCase):
    def test_markdown_has_the_four_required_sections(self):
        pr, review = review_diff(diff_for("src/x.py", ["eval(x)"]))
        md = cr.render_markdown(review, pr)
        for section in ("**Summary of changes**", "**Identified risks**",
                        "**Improvement suggestions**", "**Confidence score:**"):
            self.assertIn(section, md)
        self.assertRegex(md, r"\*\*Confidence score:\*\* (Low|Medium|High)")

    def test_json_shape(self):
        import json
        pr, review = review_diff(diff_for("src/x.py", ["eval(x)"]))
        data = json.loads(cr.render_json(review, pr))
        for key in ("summary", "risks", "suggestions", "confidence", "stats"):
            self.assertIn(key, data)


class Refs(unittest.TestCase):
    def test_parse_url(self):
        self.assertEqual(cr.parse_ref("https://github.com/owner/repo/pull/42"), ("owner", "repo", 42))

    def test_parse_short(self):
        self.assertEqual(cr.parse_ref("owner/repo#42"), ("owner", "repo", 42))

    def test_parse_bad(self):
        with self.assertRaises(SystemExit):
            cr.parse_ref("nonsense")


if __name__ == "__main__":
    unittest.main(verbosity=2)
