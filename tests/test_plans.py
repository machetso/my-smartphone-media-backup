"""Backup plans: simple on one drive and Grandfather-Father-Son on another in the same backup."""

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from phonebackup import gfs, plans
from phonebackup.backup import perform_backup
from phonebackup.export import EXPORT_DIR, Catalog, perform_restore
from phonebackup.sources import FolderSource
from tests.test_all import jpeg_with_exif

SET = "Pixel 10 Pro - Sam Test"


class PlansTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbplan_"))
        self.cam = self.tmp / "phone" / "DCIM" / "Camera"
        self.cam.mkdir(parents=True)
        self.simple, self.gfsdrive = self.tmp / "hdd1", self.tmp / "hdd2"
        self.simple.mkdir()
        self.gfsdrive.mkdir()
        self.cfg = {"fsync": False}
        plans.set_plan(self.cfg, str(self.gfsdrive), plans.GFS)
        self.content = {}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def photo(self, name, day):
        data = jpeg_with_exif(f"2026:0{day}:1{day} 10:00:00", payload=name.encode())
        (self.cam / name).write_bytes(data)
        self.content[name] = hashlib.sha256(data).hexdigest()

    def backup(self):
        src = FolderSource(self.tmp / "phone", device_name="Pixel 10 Pro")
        status, _paths, _res, verdict = perform_backup(
            src, "Pixel 10 Pro", "Sam Test", ["DCIM/Camera"],
            [str(self.simple), str(self.gfsdrive)], self.cfg, interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)

    def runs(self):
        cat = Catalog(self.gfsdrive / SET)
        try:
            return [(r, cat.files_of([r.id])) for r in gfs.active(cat.runs())]
        finally:
            cat.close()

    def age(self, days_by_id):
        db = sqlite3.connect(str(self.gfsdrive / SET / EXPORT_DIR / "catalog.sqlite"))
        for rid, days in days_by_id.items():
            when = (datetime.now() - timedelta(days=days)).isoformat(sep=" ", timespec="seconds")
            db.execute("UPDATE runs SET started=? WHERE id=?", (when, rid))
        db.commit()
        db.close()

    @staticmethod
    def names(files):
        return sorted(Path(r).name for r in files)

    def test_simple_and_gfs_side_by_side(self):
        self.photo("A.jpg", 1)
        self.photo("B.jpg", 2)
        self.backup()
        (r1, f1), = self.runs()
        self.assertEqual(r1.type, "full")
        self.assertEqual(self.names(f1), ["A.jpg", "B.jpg"])
        self.assertTrue((self.simple / SET / "2026").is_dir(), "simple drive: one growing folder")
        self.assertFalse((self.simple / SET / EXPORT_DIR).exists())

        # one month later: father (differential) with only what is new since the full
        self.age({r1.id: 40})
        (self.cam / "A.jpg").unlink()                       # deleted on the phone
        self.photo("C.jpg", 3)
        self.backup()
        r2, f2 = self.runs()[-1]
        self.assertEqual(r2.type, "differential")
        self.assertEqual(self.names(f2), ["C.jpg"])

        # a few days later: son (incremental)
        self.photo("D.jpg", 4)
        self.backup()
        r3, f3 = self.runs()[-1]
        self.assertEqual(r3.type, "incremental")
        self.assertEqual(self.names(f3), ["D.jpg"])

        # nothing new: no empty incremental folder
        before = sorted(p.name for p in (self.gfsdrive / SET).iterdir())
        self.backup()
        self.assertEqual(len(self.runs()), 3)
        self.assertEqual(sorted(p.name for p in (self.gfsdrive / SET).iterdir())[:len(before)], before)

        # differential again after another month: everything since the full (C, D) + new E
        self.age({r1.id: 80, r2.id: 40, r3.id: 35})
        self.photo("E.jpg", 5)
        self.backup()
        r4, f4 = self.runs()[-1]
        self.assertEqual(r4.type, "differential")
        self.assertEqual(self.names(f4), ["C.jpg", "D.jpg", "E.jpg"])

        # 3 months: grandfather (full) - also A, deleted from the phone long ago
        self.age({r1.id: 100, r2.id: 60, r3.id: 55, r4.id: 20})
        (self.cam / "B.jpg").unlink()
        self.photo("F.jpg", 6)
        self.backup()
        r5, f5 = self.runs()[-1]
        self.assertEqual(r5.type, "full")
        self.assertEqual(self.names(f5), ["A.jpg", "B.jpg", "C.jpg", "D.jpg", "E.jpg", "F.jpg"])
        for rel, (_size, _mt, sha) in f5.items():          # really copied into the full folder
            p = self.gfsdrive / SET / r5.folder / rel
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), sha)

        # simple drive has everything ever backed up, in one folder
        self.assertEqual(sorted(p.name for p in (self.simple / SET).rglob("*.jpg")),
                         ["A.jpg", "B.jpg", "C.jpg", "D.jpg", "E.jpg", "F.jpg"])

        # restore of the GFS drive = all photos, identical
        out = self.tmp / "restored"
        perform_restore(self.gfsdrive / SET, r5.id, out, self.cfg)
        got = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob("*.jpg")}
        self.assertEqual(got, self.content)

    def test_same_name_other_content_in_earlier_backup_is_renamed(self):
        self.photo("A.jpg", 1)
        self.backup()
        self.photo("X.jpg", 2)
        self.backup()                                        # incremental with X
        (self.cam / "A.jpg").write_bytes(jpeg_with_exif("2026:01:11 10:00:00", payload=b"other content, other size"))
        self.backup()
        last, files = self.runs()[-1]
        self.assertEqual(self.names(files), ["A_1.jpg"])     # A.jpg is taken in the full

    def test_existing_folder_keeps_its_plan(self):
        self.photo("A.jpg", 1)
        plans.set_plan(self.cfg, str(self.gfsdrive), plans.SIMPLE)
        self.backup()                                        # simple folder on hdd2
        plans.set_plan(self.cfg, str(self.gfsdrive), plans.GFS)
        self.photo("B.jpg", 2)
        self.backup()                                        # stays simple, no run folders
        self.assertEqual(plans.folder_plan(self.gfsdrive / SET), plans.SIMPLE)
        self.assertTrue(plans.check_switch(self.gfsdrive, SET, plans.GFS))


if __name__ == "__main__":
    unittest.main()
