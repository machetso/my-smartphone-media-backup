"""Nothing is installed on a phone without asking first (user request 2026-11-05)."""

import re
import unittest
from pathlib import Path

from phonebackup import companion

ROOT = Path(__file__).resolve().parent.parent


class InstallConsentTest(unittest.TestCase):
    def test_every_install_is_asked_first(self):
        guis = ("gui.py", "gui_backups.py")          # gui_backups: Settings → "Install / update over USB cable"
        for name in guis:
            src = (ROOT / "phonebackup" / name).read_text(encoding="utf-8")
            calls = [m.start() for m in re.finditer(r"\.install_companion\(", src)]
            self.assertTrue(calls, name)
            for pos in calls:
                before = src[max(0, pos - 2500):pos]
                self.assertIn("ui.ask_install(", before, f"install without asking first ({name})")
        gui = (ROOT / "phonebackup" / "gui.py").read_text(encoding="utf-8")
        self.assertIn('box.setDefaultButton(no)', gui)          # "No" is the default answer
        # the only exception (user decision 2026-11-10): the user chose "update automatically" for
        # exactly this phone (its serial) in that same question before
        self.assertIn('if src.serial in self.cfg.get("companion_auto", []):', gui)
        self.assertIn('lst = self.cfg.setdefault("companion_auto", [])', gui)
        self.assertEqual(gui.count('"companion_auto"'), 2)       # only: set in the question, read once
        for f in (ROOT / "phonebackup").glob("*.py"):
            if f.name not in guis + ("sources.py",):
                self.assertNotIn("install_companion(", f.read_text(encoding="utf-8"), f.name)

    def test_question_explains_everything(self):
        for state in ("missing", "outdated", "no-permission"):
            title, text, details = companion.install_question(state, "Samsung SM-G780G", "RF8", "0.3.1",
                                                              1_600_000)
            self.assertIn("SM-G780G", text)
            self.assertIn(companion.APP_VERSION_NAME, text)
            for must in ("Why", ):
                self.assertIn(must, text)
            for must in ("1.6 MB", "WRITE_SECURE_SETTINGS", "nothing is downloaded", "Uninstall",
                         "cannot do", "back up without the app"):
                self.assertIn(must, details)
            # declining is always possible and the cable backup goes on without the app (user 2026-11-10)
            self.assertIn("Without the app", text)
            self.assertIn("works anyway", text)
        self.assertIn("0.3.1", companion.install_question("outdated", "P", "S", "0.3.1", 1)[1])

    def test_bundled_version_matches_the_phone_app_build(self):
        gradle = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
        self.assertIn(f'versionName = "{companion.APP_VERSION_NAME}"', gradle)
        self.assertIn(f"versionCode = {companion.APP_VERSION_CODE}", gradle)


if __name__ == "__main__":
    unittest.main()
