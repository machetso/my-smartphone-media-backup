"""The window must open (catches a missing method or a broken page before a user does)."""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


class GuiSmokeTest(unittest.TestCase):
    def test_every_used_method_exists(self):
        s = (Path(__file__).resolve().parent.parent / "phonebackup" / "gui.py").read_text(encoding="utf-8")
        defs = set(re.findall(r"^\s+def (\w+)", s, re.M)) | set(re.findall(r"self\.(\w+)\s*=", s))
        missing = sorted(u for u in set(re.findall(r"self\.(_\w+)\b", s)) if u not in defs)
        self.assertEqual(missing, [])

    @unittest.skipUnless(HAVE_QT, "PySide6 not installed")
    def test_window_opens(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d,
                                                                             "APPDATA": d}):
            from PySide6.QtWidgets import QApplication
            from phonebackup import gui
            app = QApplication.instance() or QApplication([])
            with mock.patch.object(gui, "find_adb", lambda cfg: None):
                w = gui.MainWindow()
                try:
                    for page in (w.backup_page, w.more_page, w.home_page):
                        w.pages.setCurrentWidget(page)
                        app.processEvents()
                    self.assertIs(w.pages.currentWidget(), w.home_page)
                finally:
                    w._stop.set()
                    w.close()


    @unittest.skipUnless(HAVE_QT, "PySide6 not installed")
    def test_update_hint_and_drive_hotspot_message(self):
        """New version → a message with the download page; Google Drive + Direct Wi-Fi → the
        explanation instead of a network error (no real network, no real settings)."""
        import time
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d,
                                                                             "APPDATA": d}):
            from PySide6.QtWidgets import QApplication, QMessageBox
            from phonebackup import gui, updatecheck, wireless
            app = QApplication.instance() or QApplication([])
            shown = []

            def fake_exec(box):
                shown.append((box.windowTitle(), box.text()))
                return 0
            url = f"https://github.com/{updatecheck.REPO}/releases/tag/v99.0"
            with mock.patch.object(gui.MainWindow, "_offer_adb_download", lambda self: None), \
                    mock.patch.object(QMessageBox, "exec", fake_exec), \
                    mock.patch.object(wireless, "hotspot_active", lambda: False), \
                    mock.patch.object(updatecheck, "check", lambda cfg: ("99.0", url)):
                w = gui.MainWindow()
                w._check_for_update()
                for _ in range(100):
                    app.processEvents()
                    if shown:
                        break
                    time.sleep(0.02)
                self.assertEqual(shown[0][0], "New version available")
                self.assertIn("99.0", shown[0][1])
                shown.clear()
                with mock.patch.object(wireless, "hotspot_active", lambda: True):
                    self.assertTrue(w._gdrive_blocked_by_hotspot())
                self.assertEqual(shown[0][0], "Google Drive needs the internet")
                self.assertFalse(w._gdrive_blocked_by_hotspot())
                w.close()


if __name__ == "__main__":
    unittest.main()


class FolderSplitTest(unittest.TestCase):
    def test_folders_of_another_phone_are_dropped(self):
        if not HAVE_QT:
            self.skipTest("PySide6 not installed")
        from phonebackup.gui import _split_by_phone
        samsung = ["DCIM/Camera", "DCIM/Lila", "Pictures/Screenshots"]
        chosen = ["DCIM/Camera", "DCIM/Camera/Trip", "Movies/Der Maulwurf", "Pictures/PokemonGO",
                  "DCIM/Lila"]
        keep, drop = _split_by_phone(chosen, samsung)
        self.assertEqual(keep, ["DCIM/Camera", "DCIM/Camera/Trip", "DCIM/Lila"])
        self.assertEqual(drop, ["Movies/Der Maulwurf", "Pictures/PokemonGO"])
