"""Backups live in <destination>/<Owner>/<Phone> (user request 2026-11-09); old <Phone - Owner>
folders are moved / merged there, on drives and on Google Drive."""

import hashlib
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from phonebackup import gdrive, gdrive_gfs, gfs, setfolders
from phonebackup.index import BackupIndex
from phonebackup.locations import find_backups
from tests.test_gdrive import FakeDrive

CFG = {"fsync": False, "layout_keep": {"Pixel 10 Pro - Sam": []}}


def put(root, files):
    for rel, data in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def old_backup(base, files):
    """An old-style backup folder 'Pixel 10 Pro - Sam's with an index."""
    d = Path(base) / "Pixel 10 Pro - Sam"
    put(d, files)
    idx = BackupIndex(d)
    for i, (rel, data) in enumerate(files.items()):
        idx.add(f"DCIM/Camera/{i}", len(data), 0, hashlib.sha256(data).hexdigest(), rel, "photo",
                datetime(2026, 2, 1), "exif")
    idx.close()
    return d


def files_below(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".phonebackup" not in p.parts and len(p.relative_to(root).parts) > 1}


class NamesTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(setfolders.rel("Pixel 10 Pro", "Sam"), "Sam/Pixel 10 Pro")
        self.assertEqual(setfolders.key("Pixel 10 Pro", "Sam"), "Pixel 10 Pro - Sam")
        self.assertEqual(setfolders.key_of("/x/Sam/Pixel 10 Pro"), "Pixel 10 Pro - Sam")
        self.assertEqual(setfolders.rel_of("/x/Sam/Pixel 10 Pro"), "Sam/Pixel 10 Pro")
        self.assertEqual(setfolders.split_old("Galaxy S7 - Neo - Sam"), ("Galaxy S7 - Neo", "Sam"))
        cfg = {"phones": {"x": {"phone": "Galaxy", "owner": "Mia - Lou"}}}
        self.assertEqual(setfolders.split_old("Galaxy - Mia - Lou", cfg), ("Galaxy", "Mia - Lou"))


class DriveFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "PhoneBackups"

    def test_old_folder_is_moved(self):
        old_backup(self.base, {"2026/26.02/a.jpg": b"a"})
        found = find_backups({"destinations": [str(self.base)]})
        new = self.base / "Sam" / "Pixel 10 Pro"
        self.assertEqual(found, [str(new)])
        self.assertFalse((self.base / "Pixel 10 Pro - Sam").exists())
        idx = BackupIndex(new)
        self.assertTrue(idx.has("DCIM/Camera/0", 1), "still counts as backed up")
        idx.close()

    def test_merge_into_existing(self):
        old_backup(self.base, {"2026/26.02/a.jpg": b"a", "2026/26.02/b.jpg": b"b-old",
                               "2026/26.03/c.jpg": b"c"})
        new = self.base / "Sam" / "Pixel 10 Pro"
        put(new, {"2026/26.02/a.jpg": b"a", "2026/26.02/b.jpg": b"b-new"})
        BackupIndex(new).close()
        setfolders.relocate(self.base)
        self.assertEqual(files_below(new), {"2026/26.02/a.jpg": b"a", "2026/26.02/b.jpg": b"b-new",
                                            "2026/26.02/b_1.jpg": b"b-old", "2026/26.03/c.jpg": b"c"})
        # identical a.jpg stays in the old folder (nothing deleted), the rest moved
        self.assertEqual(files_below(self.base / "Pixel 10 Pro - Sam"), {"2026/26.02/a.jpg": b"a"})
        idx = BackupIndex(new)
        rels = {r for (r,) in idx.db.execute("SELECT rel_path FROM files")}
        idx.close()
        self.assertEqual(rels, {"2026/26.02/a.jpg", "2026/26.02/b_1.jpg", "2026/26.03/c.jpg"})

    def test_export_target_is_moved_too(self):
        from phonebackup.export import Catalog, perform_export
        src = self.base / "Sam" / "Pixel 10 Pro"
        put(src, {"2026/26.02/a.jpg": b"a"})
        BackupIndex(src).close()
        target = Path(self.tmp.name) / "hdd2"
        perform_export(src, target, "full", CFG)
        new_t = target / "Sam" / "Pixel 10 Pro"
        (target / "Pixel 10 Pro - Sam").parent.mkdir(exist_ok=True)
        new_t.rename(target / "Pixel 10 Pro - Sam")         # as an older version left it
        put(src, {"2026/26.03/b.jpg": b"b"})
        st, _, _ = perform_export(src, target, "incremental", CFG)
        self.assertEqual(st, "COMPLETED")
        self.assertFalse((target / "Pixel 10 Pro - Sam").exists())
        cat = Catalog(new_t)
        runs = cat.runs()
        cat.close()
        self.assertEqual([r.type for r in runs], ["full", "incremental"])


class GoogleDriveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.src = base / "Sam" / "Pixel 10 Pro"
        put(self.src, {"2026/26.02/a.jpg": b"a" * 10, "2026/26.03/b.jpg": b"b" * 20})
        self.fake = FakeDrive()
        self.drive = gdrive.Drive({}, transport=self.fake)
        p = mock.patch.object(gdrive_gfs, "local_dir", lambda name: base / "local" / name)
        p.start()
        self.addCleanup(p.stop)
        self.reports = base / "reports"

    def make_old(self, suffix=""):
        """Rename the Google Drive folder back to the old place '<Phone - Owner><suffix>'."""
        root = next(i for i, f in self.fake.files.items() if f["name"] == gdrive.ROOT_NAME)
        owner = next(i for i, f in self.fake.files.items() if f["name"] == "Sam")
        sid = next(i for i, f in self.fake.files.items() if f["name"] == "Pixel 10 Pro" + suffix)
        self.fake.files[sid].update(name="Pixel 10 Pro - Sam" + suffix, parents=[root])
        self.fake.files.pop(owner)

    def paths(self, top):
        pre = f"{gdrive.ROOT_NAME}/{top}/"
        return sorted(k[len(pre):] for k in self.fake.paths() if k.startswith(pre)
                      and not k[len(pre):].startswith(gdrive.REPORTS_FOLDER))

    def test_mirror_folder_moved_nothing_uploaded(self):
        gdrive.perform_drive_export(self.src, CFG, threading.Event(), self.drive, self.reports)
        self.make_old()
        uploads = self.fake.uploads
        gdrive.perform_drive_export(self.src, CFG, threading.Event(), self.drive, self.reports)
        self.assertLessEqual(self.fake.uploads - uploads, 3, "only the reports")
        self.assertEqual(self.paths("Sam/Pixel 10 Pro"), ["2026/26.02/a.jpg", "2026/26.03/b.jpg"])
        self.assertEqual(self.paths("Pixel 10 Pro - Sam"), [])

    def test_gfs_folder_moved(self):
        gdrive_gfs.perform_drive_gfs_export(self.src, CFG, "full", threading.Event(), self.drive,
                                            self.reports)
        self.make_old(gdrive_gfs.SUFFIX)
        # read-only (restore list) still finds it at the old place
        self.assertEqual(gdrive_gfs.list_sets(self.drive), ["Sam/Pixel 10 Pro"])
        self.assertEqual(len(gdrive_gfs.runs_of("Sam/Pixel 10 Pro", {}, drive=self.drive)[0]), 1)
        put(self.src, {"2026/26.04/c.jpg": b"c"})
        st, _, verdict = gdrive_gfs.perform_drive_gfs_export(
            self.src, CFG, "incremental", threading.Event(), self.drive, self.reports)
        self.assertEqual(st, "COMPLETED", verdict)
        runs = gfs.active(gdrive_gfs.runs_of("Sam/Pixel 10 Pro", {}, drive=self.drive)[0])
        self.assertEqual([r.type for r in runs], ["full", "incremental"])
        top = "Sam/Pixel 10 Pro" + gdrive_gfs.SUFFIX
        self.assertTrue(any(p.endswith("2026/26.04/c.jpg") for p in self.paths(top)))
        self.assertEqual(self.paths("Pixel 10 Pro - Sam" + gdrive_gfs.SUFFIX), [])


if __name__ == "__main__":
    unittest.main()
