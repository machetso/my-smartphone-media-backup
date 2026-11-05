"""Nothing is installed on a phone without asking first (user request 2026-11-05)."""

import re
import unittest
from pathlib import Path

from phonebackup import companion

ROOT = Path(__file__).resolve().parent.parent


class InstallConsentTest(unittest.TestCase):
    def test_every_install_is_asked_first(self):
        src = (ROOT / "phonebackup" / "gui.py").read_text()
        calls = [m.start() for m in re.finditer(r"\.install_companion\(", src)]
        self.assertTrue(calls)
        for pos in calls:
            before = src[max(0, pos - 2500):pos]
            self.assertIn("ui.ask_install(", before, "install without asking first")
        for f in (ROOT / "phonebackup").glob("*.py"):
            if f.name not in ("gui.py", "sources.py"):
                self.assertNotIn("install_companion(", f.read_text(), f.name)

    def test_question_explains_everything(self):
        for state in ("missing", "outdated", "no-permission"):
            title, text, details = companion.install_question(state, "Samsung SM-G780G", "RF8", "0.3.1",
                                                              1_600_000)
            self.assertIn("SM-G780G", text)
            self.assertIn(companion.APP_VERSION_NAME, text)
            for must in ("Why", ):
                self.assertIn(must, text)
            for must in ("1.6 MB", "WRITE_SECURE_SETTINGS", "nothing is downloaded", "Uninstall",
                         "cannot do", "Not now"):
                self.assertIn(must, details)
        self.assertIn("0.3.1", companion.install_question("outdated", "P", "S", "0.3.1", 1)[1])

    def test_bundled_version_matches_the_phone_app_build(self):
        gradle = (ROOT / "android" / "app" / "build.gradle.kts").read_text()
        self.assertIn(f'versionName = "{companion.APP_VERSION_NAME}"', gradle)
        self.assertIn(f"versionCode = {companion.APP_VERSION_CODE}", gradle)


if __name__ == "__main__":
    unittest.main()
