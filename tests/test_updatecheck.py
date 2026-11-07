"""Update check: compares versions, ignores drafts/odd answers, never opens foreign links (offline)."""

import json
import unittest

from phonebackup import updatecheck as u


def answer(**kw):
    d = {"tag_name": "v9.9.9", "html_url": f"https://github.com/{u.REPO}/releases/tag/v9.9.9"}
    d.update(kw)
    return lambda url: json.dumps(d).encode()


class UpdateCheckTest(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(u.is_newer("0.9.7", "0.9.6"))
        self.assertTrue(u.is_newer("v0.10.0", "0.9.6"))
        self.assertTrue(u.is_newer("0.9.6.1", "0.9.6"))
        self.assertFalse(u.is_newer("0.9.6", "0.9.6"))
        self.assertFalse(u.is_newer("0.9.5", "0.9.6"))
        self.assertFalse(u.is_newer("latest", "0.9.6"))

    def test_newer_release_is_reported_once_a_day(self):
        cfg = {}
        self.assertEqual(u.check(cfg, answer(), now=1000), ("9.9.9", answer()(0) and
                         f"https://github.com/{u.REPO}/releases/tag/v9.9.9"))
        self.assertFalse(u.due(cfg, now=1000 + 3600))
        self.assertTrue(u.due(cfg, now=1000 + u.EVERY))
        self.assertFalse(u.due({"update_check": False}))

    def test_skipped_drafts_odd_answers_offline(self):
        self.assertIsNone(u.check({"update_skip": "9.9.9"}, answer()))
        self.assertIsNone(u.check({}, answer(prerelease=True)))
        self.assertIsNone(u.check({}, answer(tag_name="nightly")))
        self.assertIsNone(u.check({}, lambda url: b"<html>rate limited</html>"))

        def offline(url):
            raise OSError(101, "Network is unreachable")
        cfg = {}
        self.assertIsNone(u.check(cfg, offline))
        self.assertNotIn("update_checked_at", cfg)        # offline: try again at the next start

    def test_link_from_the_answer_only_to_our_release_page(self):
        self.assertEqual(u.check({}, answer(html_url="https://evil.example/x"))[1], u.RELEASES_URL)


if __name__ == "__main__":
    unittest.main()
