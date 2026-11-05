"""Grandfather-Father-Son backups on Google Drive (fake Drive API): uploads only what is new,
copies on Google's side what a full/differential must contain, restore, cleanup."""

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from phonebackup import gdrive, gdrive_gfs, gfs
from tests.test_gdrive import FakeDrive, make_backup

SET = "Pixel 10 Pro - Sam"


class DriveGfsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.parent, self.data = make_backup(base)
        self.fake = FakeDrive()
        self.drive = gdrive.Drive({}, transport=self.fake)
        p = mock.patch.object(gdrive_gfs, "local_dir", lambda name: base / "local" / name)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, rel, data):
        p = self.parent / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.data[rel] = data

    def export(self, mode):
        u, c = self.fake.uploads, self.fake.shortcuts
        status, _paths, verdict = gdrive_gfs.perform_drive_gfs_export(
            self.parent, {}, mode, cancel=threading.Event(), drive=self.drive,
            report_dir=Path(self.tmp.name) / "reports")
        self.assertEqual(status, "COMPLETED", verdict)
        reports = 3 if not verdict.startswith("NOTHING") else 0
        return self.fake.uploads - u - reports - (1 if reports else 0), self.fake.shortcuts - c

    def runs(self):
        return gfs.active(gdrive_gfs.runs_of(SET, {}, drive=self.drive)[0])

    def restore(self, run_id):
        out = Path(self.tmp.name) / f"restore{run_id}"
        status, _, verdict = gdrive_gfs.perform_restore(SET, run_id, out, {}, drive=self.drive)
        self.assertEqual(status, "COMPLETED", verdict)
        return {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*")
                if p.is_file() and not p.name.startswith("Restore report")}

    def test_cycle(self):
        backup_files = lambda: {r: d for r, d in self.data.items()}
        self.assertEqual(self.export("full"), (3, 0))
        r1 = self.runs()[-1]
        on = self.fake.paths()
        top = f"{gdrive.ROOT_NAME}/{SET}{gdrive_gfs.SUFFIX}"
        for rel, data in self.data.items():
            self.assertEqual(on[f"{top}/{r1.folder}/{rel}"], data)
        self.assertIn(f"{top}/.phonebackup-export/catalog.sqlite", on)

        self.add("2026/02.February-photos/X.jpg", b"x" * 50)
        self.assertEqual(self.export("incremental"), (1, 0))        # only X uploaded
        state_after_x = backup_files()
        r2 = self.runs()[-1]

        self.add("2026/03.March-photos/Y.jpg", b"y" * 70)
        self.assertEqual(self.export("differential"), (1, 1))       # Y uploaded, X linked
        r3 = self.runs()[-1]
        state_after_y = backup_files()

        n_runs = len(self.runs())
        self.assertEqual(self.export("incremental"), (0, 0))        # nothing new: no run
        self.assertEqual(len(self.runs()), n_runs)

        self.assertEqual(self.export("full"), (0, 5))               # everything linked, nothing stored
        r5 = self.runs()[-1]
        self.assertEqual(self.fake.copies, 0)
        _runs, sizes = gdrive_gfs.runs_of(SET, {}, drive=self.drive)
        self.assertLess(sizes[r5.id], 10_000, "a full of shortcuts stores only its reports")
        self.assertGreater(sizes[r1.id], gdrive.CHUNK)

        self.assertEqual(self.restore(r2.id), state_after_x)
        self.assertEqual(self.restore(r3.id), state_after_y)
        self.assertEqual(self.restore(r5.id), state_after_y)

        keep = {"full": 1, "differential": 0, "incremental": 0}
        removed, problems, _freed = gdrive_gfs.remove_runs(SET, {}, [r1.id, r2.id, r3.id], keep,
                                                           drive=self.drive)
        self.assertEqual(problems, [])
        self.assertEqual(self.fake.moves, 5)                          # stored files moved, not lost
        self.assertFalse([k for k in self.fake.links() if f"/{r5.folder}/" in k],
                         "the full export now holds the real files")
        self.assertEqual(removed, [r1.folder, r2.folder, r3.folder])
        on = self.fake.paths()
        self.assertFalse(any(f"/{r1.folder}/" in k for k in on))
        self.assertEqual([r.id for r in self.runs()], [r5.id])
        self.assertEqual(self.restore(r5.id), state_after_y)          # still complete

    def test_switch_from_copy_uploads_nothing_again(self):
        gdrive.perform_drive_export(self.parent, {}, drive=self.drive,
                                    report_dir=Path(self.tmp.name) / "r2")
        # one file changed in the backup after the Copy: that one must be uploaded
        self.add("2026/01.January-photos/PXL_1.jpg", b"changed" * 10)
        self.assertEqual(self.export("full"), (1, 2))       # 2 linked to the Copy, 1 uploaded
        r = self.runs()[-1]
        self.assertEqual(self.restore(r.id), self.data)

    def test_unfinished_export_is_reused_not_uploaded_again(self):
        # an export whose catalog could not be saved: files on Drive, no record of them
        with mock.patch.object(gdrive_gfs.DriveSet, "save_catalog",
                               side_effect=gdrive.DriveError("lost")):
            gdrive_gfs.perform_drive_gfs_export(self.parent, {}, "full", drive=self.drive,
                                                report_dir=Path(self.tmp.name) / "r0")
        self.assertEqual(gdrive_gfs.list_sets(self.drive), [SET])
        self.assertEqual(self.runs(), [])                      # nothing recorded
        self.add("2026/02.February-photos/new.jpg", b"n" * 40)
        self.assertEqual(self.export("full")[0], 1)            # only the new photo uploaded
        self.assertEqual(self.fake.moves, 3)                   # the 3 earlier ones reused
        top = f"{gdrive.ROOT_NAME}/{SET}{gdrive_gfs.SUFFIX}/"
        folders = {k[len(top):].split("/")[0] for k in self.fake.paths() if k.startswith(top)}
        self.assertEqual(len(folders - {".phonebackup-export"}), 1, folders)   # orphan folder gone
        self.assertEqual(self.restore(self.runs()[-1].id), self.data)

    def test_second_window_cannot_break_a_running_export(self):
        self.export("full")
        ds1 = gdrive_gfs.DriveSet(self.drive, SET)
        cat = ds1.catalog()
        gdrive_gfs.runs_of(SET, {}, drive=self.drive)          # e.g. another window reads the list
        cat.add_file(1, "x", 1, 1, "s")                        # still writable
        cat.close()
        ds1.close()

    def test_needs_full_first(self):
        with self.assertRaises(ValueError):
            self.export("incremental")

    def test_list_sets_and_mirror_apart(self):
        self.export("full")
        gdrive.perform_drive_export(self.parent, {}, drive=self.drive,
                                    report_dir=Path(self.tmp.name) / "r2")
        self.assertEqual(gdrive_gfs.list_sets(self.drive), [SET])
        on = self.fake.paths()
        self.assertIn(f"{gdrive.ROOT_NAME}/{SET}/2026/01.January-photos/PXL_1.jpg", on)


if __name__ == "__main__":
    unittest.main()
