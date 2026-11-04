"""Start screen (update latest backup), connection modes, USB-debugging guide, control commands."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phonebackup import adbsetup, lastbackup, phoneguard


class LastBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = {}
        with mock.patch("phonebackup.config.save"):
            lastbackup.record(self.cfg, "Sam Handy", "Sam", ["DCIM/Camera"],
                              [self.tmp.name, "/nowhere/HDD2/PhoneBackups"], 12, 3000, "OK",
                              model="Pixel 10 Pro")
        self.lb = lastbackup.get(self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_title(self):
        self.assertEqual(lastbackup.title(self.lb), "Sam's Sam Handy")
        self.assertEqual(lastbackup.title({"owner": "Maria", "phone": "Pixel"}), "Maria's Pixel")

    def test_possible_with_same_model_and_one_drive(self):
        ok, hint = lastbackup.check(self.lb, "pixel 10 pro")
        self.assertTrue(ok)
        self.assertIn("1 of 2", hint)

    def test_needs_phone(self):
        ok, hint = lastbackup.check(self.lb, "")
        self.assertFalse(ok)
        self.assertIn("Connect Sam Handy", hint)

    def test_other_phone(self):
        ok, hint = lastbackup.check(self.lb, "Galaxy S25")
        self.assertFalse(ok)
        self.assertIn("New backup", hint)

    def test_needs_drive(self):
        ok, hint = lastbackup.check(self.lb, "Pixel 10 Pro", is_dir=lambda p: False)
        self.assertFalse(ok)
        self.assertIn("backup drive", hint)

    def test_none(self):
        self.assertEqual(lastbackup.check(None, "x")[0], False)
        self.assertIsNone(lastbackup.get({"last_backup": {"phone": ""}}))


class SetupGuideTest(unittest.TestCase):
    def test_brands(self):
        self.assertEqual(adbsetup.brand_key("Google Pixel 10 Pro"), "google")
        self.assertEqual(adbsetup.brand_key("SM-S931B"), "samsung")
        self.assertEqual(adbsetup.brand_key("Redmi Note 13"), "xiaomi")
        self.assertEqual(adbsetup.brand_key("Fairphone 5"), "other")

    def test_steps_and_search(self):
        steps = adbsetup.guide_steps(adbsetup.GUIDES["samsung"])
        self.assertTrue(any("Auto Blocker" in s for s in steps))
        self.assertTrue(any("Fast Media Backup" in s for s in steps))
        self.assertFalse(any("Fast Media Backup" in s
                             for s in adbsetup.guide_steps(adbsetup.GUIDES["google"], with_app=False)))
        self.assertIn("Pixel+10+Pro", adbsetup.search_url("Pixel 10 Pro"))

    def test_connections(self):
        self.assertEqual(adbsetup.CONNECTIONS[0].key, adbsetup.DEFAULT_CONNECTION)
        fastest = max(adbsetup.CONNECTIONS, key=lambda c: c.mb_s[1])
        self.assertIn(fastest.key, adbsetup.USB_DEBUGGING_MODES)

    def test_detect_linux_sysfs(self):
        with tempfile.TemporaryDirectory() as d:
            for name, vendor, maker, product in (("1-1", "18d1", "Google", "Pixel 10 Pro"),
                                                 ("1-2", "046d", "Logitech", "Mouse")):
                p = Path(d) / name
                p.mkdir()
                (p / "idVendor").write_text(vendor)
                (p / "manufacturer").write_text(maker)
                (p / "product").write_text(product)
            self.assertEqual(adbsetup._linux_usb_phones(d), ["Google Pixel 10 Pro"])


class ControlCommandTest(unittest.TestCase):
    def test_only_fixed_commands(self):
        self.assertEqual(phoneguard.check_control("usb_debugging_off"), "settings put global adb_enabled 0")
        with self.assertRaises(phoneguard.ForbiddenPhoneCommand):
            phoneguard.check_control("settings put global adb_enabled 1")
        # the normal read-only check still refuses settings / pm commands
        for cmd in phoneguard.CONTROL.values():
            if not cmd.startswith(("pm list", "dumpsys")):
                with self.assertRaises(phoneguard.ForbiddenPhoneCommand):
                    phoneguard.check(cmd)

    def test_install_only_bundled_apk(self):
        from phonebackup.sources import AdbSource
        src = AdbSource.__new__(AdbSource)
        src.adb, src.serial = "adb", "x"
        with self.assertRaises(phoneguard.ForbiddenPhoneCommand):
            src.install_companion("/tmp/evil.apk")


if __name__ == "__main__":
    unittest.main()
