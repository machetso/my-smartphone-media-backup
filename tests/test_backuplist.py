"""Manage backups → Backups: known backups, per-backup drives and folders (user request 2026-11-10)."""
import os
import tempfile
import unittest
from unittest import mock

from phonebackup import backuplist


class BackupListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hdd = os.path.join(self.tmp.name, "HDD", "PhoneBackups")
        self.old = os.path.join(self.hdd, "Sam", "Galaxy S7")
        os.makedirs(self.old)
        self.cfg = {"phones": {"Pixel 10 Pro - Sam": {
            "phone": "Pixel 10 Pro", "owner": "Sam", "destinations": ["/nowhere/A"], "when": "2026-11-09T20:10"}}}
        self.save = mock.patch("phonebackup.config.save").start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def test_known_merges_phone_list_and_found_sets(self):
        found = {"Galaxy S7 - Sam": [self.old]}
        lst = backuplist.known(self.cfg, found)
        self.assertEqual([b["key"] for b in lst], ["Pixel 10 Pro - Sam", "Galaxy S7 - Sam"])
        self.assertEqual(lst[1]["phone"], "Galaxy S7")
        self.assertEqual(lst[1]["drives"], [self.hdd])            # where it was found
        self.cfg["phones_hidden"] = ["Galaxy S7 - Sam"]
        self.assertEqual(len(backuplist.known(self.cfg, found)), 1)
        self.assertTrue(backuplist.known(self.cfg, found, show_hidden=True)[1]["hidden"])

    def test_default_folders_are_the_camera(self):
        self.assertEqual(backuplist.profile(self.cfg, "x")["folders"], ["DCIM/Camera"])
        self.cfg["default_folders"] = ["DCIM/Camera", "Pictures/Screenshots"]
        self.assertEqual(backuplist.profile(self.cfg, "x")["folders"], ["DCIM/Camera", "Pictures/Screenshots"])

    def test_drives_edit_updates_phone_list_and_keeps_other_fields(self):
        key = "Pixel 10 Pro - Sam"
        backuplist.save_profile(self.cfg, key, folders=["DCIM/Camera"], import_roots=["/old"])
        backuplist.save_profile(self.cfg, key, destinations=[self.hdd])
        prof = backuplist.profile(self.cfg, key)
        self.assertEqual(prof["import_roots"], ["/old"])
        self.assertEqual(self.cfg["phones"][key]["destinations"], [self.hdd])   # "Update backup" uses it
        self.assertIn(self.hdd, self.cfg["destinations"])
        self.assertEqual(backuplist.drives(self.cfg, key, self.cfg["phones"][key]), [self.hdd])

    def test_copy_on(self):
        self.assertEqual(backuplist.copy_on(self.hdd, "Galaxy S7", "Sam"), self.old)
        self.assertIsNone(backuplist.copy_on(self.hdd, "Pixel 10 Pro", "Sam"))


if __name__ == "__main__":
    unittest.main()
