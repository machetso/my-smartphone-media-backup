"""Start screen: list of phones (one entry per backup), discovered from drives, removable."""
import os
import tempfile
import unittest
from unittest import mock

from phonebackup import lastbackup


class PhoneListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.save = mock.patch("phonebackup.config.save").start()
        self.addCleanup(mock.patch.stopall)
        base = self.tmp.name
        parent = os.path.join(base, "Galaxy A55 - Kim")
        os.makedirs(os.path.join(parent, ".phonebackup"))
        open(os.path.join(parent, ".phonebackup", "index.sqlite"), "w").close()
        with open(os.path.join(parent, "Backup Galaxy A55 Kim 2026-11-04.txt"), "w") as f:
            f.write("  Smartphone       : SM-G780G\n  Owner            : Kim\n"
                    "  Status           : COMPLETED\n  Started          : 2026-11-04 20:56:52\n")
        self.cfg = {"destinations": [base]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_discover_record_forget(self):
        with mock.patch("phonebackup.locations.is_backup_folder", return_value=True):
            lastbackup.discover(self.cfg)
            lastbackup.record(self.cfg, "Pixel 10 Pro", "Sam", ["DCIM/Camera"], [self.tmp.name],
                              5, 100, "COMPLETED")
            names = [lastbackup.title(e) for e in lastbackup.phones(self.cfg)]
            self.assertEqual(names, ["Sam's Pixel 10 Pro", "Kim's Galaxy A55"])
            lastbackup.forget(self.cfg, ["Galaxy A55 - Kim"])
            lastbackup.discover(self.cfg)                       # stays hidden
            self.assertEqual([e["phone"] for e in lastbackup.phones(self.cfg)], ["Pixel 10 Pro"])
            lastbackup.record(self.cfg, "SM-G780G", "Kim", [], [self.tmp.name], 1, 1, "COMPLETED")
            self.assertEqual(len(lastbackup.phones(self.cfg)), 2)   # backed up again: back


if __name__ == "__main__":
    unittest.main()
