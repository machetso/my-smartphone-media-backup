"""Conversion of old month folders (2026/02.February-photos) to the new layout (2026/26.02)."""

import hashlib
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from phonebackup import export, gdrive, gdrive_gfs, gfs, migrate
from phonebackup.index import BackupIndex
from tests.test_gdrive import FakeDrive

SET = "Sam/Pixel 10 Pro"                                # <Owner>/<Phone> (folder, Google Drive)
KEY = "Pixel 10 Pro - Sam"                              # its name in the settings
CFG = {"fsync": False, migrate.CHOICES: {KEY: []}}        # the user chose: change every folder
KEEP = "2026/02.February-photos"
OLD = {"2026/02.February-photos/PXL_1.jpg": b"a" * 100,
       "2026/02.February-videos/PXL_2.mp4": b"b" * 200,
       "2025/raw/12.December-raw/PXL_3.dng": b"c" * 30,
       "2025/other/pictures/Download/meme.png": b"d" * 10}
NEW = {"2026/26.02/PXL_1.jpg": b"a" * 100,
       "2026/26.02/PXL_2.mp4": b"b" * 200,
       "2025/raw/25.12/PXL_3.dng": b"c" * 30,
       "2025/other/pictures/Download/meme.png": b"d" * 10}


def write(root, files):
    for rel, data in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def files_below(root, skip=(".phonebackup", ".phonebackup-export")):
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and not set(p.relative_to(root).parts) & set(skip)
            and len(p.relative_to(root).parts) > 1}          # not the reports in the top folder


def no_conversion():
    """Patches that keep the old layout (to build an 'old version' state)."""
    return [mock.patch.object(migrate, "ensure_converted", lambda *a, **k: (0, [])),
            mock.patch.object(migrate, "convert_drive_tree", lambda *a, **k: (0, [])),
            mock.patch.object(migrate, "convert_catalog", lambda *a, **k: False)]


class ConvertRelTest(unittest.TestCase):
    def test_paths(self):
        c = migrate.convert_rel
        self.assertEqual(c("2026/02.February-photos/x.jpg"), "2026/26.02/x.jpg")
        self.assertEqual(c("2026/02.February-videos/y.mp4"), "2026/26.02/y.mp4")
        self.assertEqual(c("1999/12.December-photos/z.jpg"), "1999/99.12/z.jpg")
        self.assertEqual(c("2026/raw/01.January-raw/r.dng"), "2026/raw/26.01/r.dng")
        for keep in ("2026/26.02/x.jpg", "2026/other/pictures/a/02.February-photos/x.jpg",
                     "Pictures/Screenshots/a.png", "2026/02.March-photos/x.jpg",
                     "2026/02.February-raw/x.dng", "2026/raw/02.February-photos/x.jpg"):
            self.assertIsNone(c(keep), keep)

    def test_layout(self):
        from phonebackup.layout import relative_dir
        t = datetime(2026, 2, 10)
        self.assertEqual(relative_dir(t, "photo").as_posix(), "2026/26.02")
        self.assertEqual(relative_dir(t, "video").as_posix(), "2026/26.02")
        self.assertEqual(relative_dir(t, "raw").as_posix(), "2026/raw/26.02")


class DiskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.set = Path(self.tmp.name) / "drive" / SET

    def test_simple_backup(self):
        write(self.set, OLD)
        idx = BackupIndex(self.set)
        for i, (rel, data) in enumerate(OLD.items()):
            idx.add(f"DCIM/Camera/{i}", len(data), 0, hashlib.sha256(data).hexdigest(), rel,
                    "photo", datetime(2026, 2, 1), "exif")
        idx.close()
        self.assertTrue(migrate.needs_conversion(self.set))
        self.assertEqual(migrate.ensure_converted(self.set), (0, []))   # not chosen yet: nothing
        self.assertEqual(files_below(self.set), OLD)
        moved, kept = migrate.ensure_converted(self.set, keep=migrate.NO_KEEP)
        self.assertEqual((moved, kept), (3, []))
        self.assertEqual(files_below(self.set), NEW)
        self.assertFalse((self.set / "2026/02.February-photos").exists())
        self.assertFalse((self.set / "2025/raw/12.December-raw").exists())
        idx = BackupIndex(self.set)
        rels = sorted(r for (r,) in idx.db.execute("SELECT rel_path FROM files"))
        self.assertEqual(rels, sorted(NEW))
        self.assertTrue(idx.has("DCIM/Camera/0", 100))           # still counts as backed up
        idx.db.close()
        self.assertFalse(migrate.needs_conversion(self.set))
        self.assertEqual(migrate.ensure_converted(self.set, keep=migrate.NO_KEEP), (0, []))
        self.assertEqual(migrate.effective_keep({}, self.set), migrate.NO_KEEP)  # nothing old left

    def test_taken_place_is_never_overwritten(self):
        write(self.set, {"2026/02.February-photos/x.jpg": b"old",
                         "2026/26.02/x.jpg": b"new"})
        moved, kept = migrate.convert_set(self.set)
        self.assertEqual(moved, 0)
        self.assertEqual(len(kept), 1)
        self.assertEqual((self.set / "2026/02.February-photos/x.jpg").read_bytes(), b"old")
        self.assertEqual((self.set / "2026/26.02/x.jpg").read_bytes(), b"new")

    def test_second_storage_exports_and_restore(self):
        src = Path(self.tmp.name) / "main" / SET
        target = Path(self.tmp.name) / "hdd2"
        write(src, OLD)
        with no_conversion()[0]:
            st, _, _ = export.perform_export(src, target, "full", CFG,
                                             now=datetime(2026, 3, 1))
            self.assertEqual(st, "COMPLETED")
            write(src, {"2026/03.March-photos/new.jpg": b"n"})
            st, _, _ = export.perform_export(src, target, "incremental", CFG)
            self.assertEqual(st, "COMPLETED")
        tparent = target / SET
        self.assertTrue(migrate.needs_conversion(tparent))
        # the next export converts both the backup and every export folder
        st, _, _ = export.perform_export(src, target, "incremental", CFG)
        self.assertEqual(st, "COMPLETED")
        self.assertEqual(files_below(src), {**NEW, "2026/26.03/new.jpg": b"n"})
        cat = export.Catalog(tparent)
        runs = cat.runs()
        self.assertEqual(len(runs), 3)
        self.assertEqual(cat.files_of([runs[2].id]), {}, "nothing exported again")
        self.assertEqual(sorted(cat.files_of([runs[0].id])), sorted(NEW))
        self.assertEqual(list(cat.files_of([runs[1].id])), ["2026/26.03/new.jpg"])
        cat.close()
        self.assertEqual(files_below(tparent / runs[0].folder), NEW)
        out = Path(self.tmp.name) / "restore"
        st, _, _ = export.perform_restore(tparent, runs[1].id, out, CFG)
        self.assertEqual(st, "COMPLETED")
        got = {k: v for k, v in files_below(out).items() if not k.startswith("Restore report")}
        self.assertEqual(got, {**NEW, "2026/26.03/new.jpg": b"n"})

    def test_restore_of_an_unconverted_export_uses_new_layout(self):
        src = Path(self.tmp.name) / "main" / SET
        target = Path(self.tmp.name) / "hdd2"
        write(src, OLD)
        with no_conversion()[0]:
            export.perform_export(src, target, "full", CFG)
        cat = export.Catalog(target / SET)
        rid = cat.runs()[0].id
        cat.close()
        out = Path(self.tmp.name) / "restore"
        st, _, _ = export.perform_restore(target / SET, rid, out, CFG)
        self.assertEqual(st, "COMPLETED")
        got = {k: v for k, v in files_below(out).items() if not k.startswith("Restore report")}
        self.assertEqual(got, NEW)


class DriveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.parent = base / SET
        write(self.parent, OLD)
        self.fake = FakeDrive()
        self.drive = gdrive.Drive({}, transport=self.fake)
        p = mock.patch.object(gdrive_gfs, "local_dir", lambda name: base / "local" / name)
        p.start()
        self.addCleanup(p.stop)
        self.reports = base / "reports"
        self.cfg = dict(CFG)

    def old_state(self, fn):
        patches = no_conversion()
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def mirror(self):
        return gdrive.perform_drive_export(self.parent, self.cfg, cancel=threading.Event(),
                                           drive=self.drive, report_dir=self.reports)

    def gfs_export(self, mode):
        return gdrive_gfs.perform_drive_gfs_export(self.parent, self.cfg, mode, cancel=threading.Event(),
                                                   drive=self.drive, report_dir=self.reports)

    def on_drive(self, top):
        pre = f"{gdrive.ROOT_NAME}/{top}/"
        return {k[len(pre):]: v for k, v in self.fake.paths().items()
                if k.startswith(pre) and not k[len(pre):].startswith(gdrive.REPORTS_FOLDER)}

    def test_mirror(self):
        self.old_state(self.mirror)
        self.assertIn("2026/02.February-photos/PXL_1.jpg", self.on_drive(SET))
        uploads = self.fake.uploads
        status, _, verdict = self.mirror()
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertLessEqual(self.fake.uploads - uploads, 3, "only the 3 reports, no photo again")
        names = [f["name"] for f in self.fake.files.values()]
        self.assertEqual(names.count("PXL_1.jpg"), 1)
        self.assertEqual(self.on_drive(SET), NEW)
        self.assertEqual(files_below(self.parent), NEW)
        names = {f["name"] for f in self.fake.files.values()}
        self.assertFalse(names & {"02.February-photos", "02.February-videos", "12.December-raw"})

    def test_gfs(self):
        self.old_state(lambda: self.gfs_export("full"))
        write(self.parent, {"2026/03.March-photos/new.jpg": b"n"})
        self.old_state(lambda: self.gfs_export("incremental"))
        self.old_state(lambda: self.gfs_export("full"))           # shortcuts to the stored files
        uploads, shortcuts = self.fake.uploads, self.fake.shortcuts
        status, _, verdict = self.gfs_export("incremental")
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertEqual(self.fake.shortcuts, shortcuts)
        top = SET + gdrive_gfs.SUFFIX
        on = self.on_drive(top)
        self.assertFalse([k for k in on if migrate.convert_rel(k.partition("/")[2])], on.keys())
        runs = gfs.active(gdrive_gfs.runs_of(SET, {}, drive=self.drive)[0])
        self.assertEqual(len(runs), 3, "nothing new after the conversion: no fourth export")
        self.assertLessEqual(self.fake.uploads - uploads, 2, "only the catalog, nothing else")
        want = {**NEW, "2026/26.03/new.jpg": b"n"}
        for run in (runs[1], runs[2]):
            out = Path(self.tmp.name) / f"restore{run.id}"
            st, _, verdict = gdrive_gfs.perform_restore(SET, run.id, out, self.cfg, drive=self.drive)
            self.assertEqual(st, "COMPLETED", verdict)
            got = {k: v for k, v in files_below(out).items() if not k.startswith("Restore report")}
            self.assertEqual(got, want)

    def test_mirror_keeps_chosen_folder(self):
        self.old_state(self.mirror)
        self.cfg[migrate.CHOICES] = {KEY: [KEEP]}
        uploads = self.fake.uploads
        status, _, verdict = self.mirror()
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertLessEqual(self.fake.uploads - uploads, 3, "only the 3 reports, no photo again")
        want = dict(NEW)
        want[KEEP + "/PXL_1.jpg"] = want.pop("2026/26.02/PXL_1.jpg")
        self.assertEqual(self.on_drive(SET), want)
        self.assertEqual(files_below(self.parent), want)
        uploads = self.fake.uploads
        self.mirror()                                      # stays as it is
        self.assertEqual(self.on_drive(SET), want)
        self.assertLessEqual(self.fake.uploads - uploads, 3)

    def test_not_chosen_nothing_changes(self):
        self.old_state(self.mirror)
        self.cfg = {}
        status, _, verdict = self.mirror()
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertEqual(files_below(self.parent), OLD)
        self.assertIn("2026/02.February-photos/PXL_1.jpg", self.on_drive(SET))


class KeepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.set = Path(self.tmp.name) / "drive" / SET
        write(self.set, OLD)

    def test_kept_folder_stays(self):
        self.assertEqual(migrate.old_folders(self.set), {
            "2026/02.February-photos": 1, "2026/02.February-videos": 1,
            "2025/raw/12.December-raw": 1})
        self.assertIsNone(migrate.effective_keep({}, self.set))
        cfg = {}
        migrate.set_decision(cfg, KEY, [KEEP])
        keep = migrate.effective_keep(cfg, self.set)
        self.assertEqual(keep, {KEEP})
        self.assertIsNone(migrate.convert_rel(KEEP + "/x.jpg", keep))
        self.assertEqual(migrate.convert_rel("2026/02.February-videos/y.mp4", keep), "2026/26.02/y.mp4")
        moved, kept = migrate.ensure_converted(self.set, keep=keep)
        self.assertEqual((moved, kept), (2, []))
        want = dict(NEW)
        want[KEEP + "/PXL_1.jpg"] = want.pop("2026/26.02/PXL_1.jpg")
        self.assertEqual(files_below(self.set), want)
        self.assertFalse(migrate.needs_conversion(self.set, keep))
        self.assertEqual(migrate.ensure_converted(self.set, keep=keep), (0, []))

    def test_export_keeps_the_same_folders(self):
        target = Path(self.tmp.name) / "hdd2"
        with no_conversion()[0]:
            export.perform_export(self.set, target, "full", CFG)
        cfg = {"fsync": False, migrate.CHOICES: {KEY: [KEEP]}}
        st, _, _ = export.perform_export(self.set, target, "incremental", cfg)
        self.assertEqual(st, "COMPLETED")
        cat = export.Catalog(target / SET)
        runs = cat.runs()
        self.assertEqual(cat.files_of([runs[1].id]), {}, "nothing exported again")
        cat.close()
        self.assertEqual(files_below(target / SET / runs[0].folder), files_below(self.set))
        self.assertTrue((self.set / KEEP / "PXL_1.jpg").is_file())

    def test_terminal_question(self):
        cfg = {}
        with mock.patch.object(migrate.ui, "ask", return_value="1"), \
                mock.patch("phonebackup.config.save") as save:
            self.assertTrue(migrate.ask_cli(cfg, [self.set]))
        save.assert_called_once()
        self.assertEqual(migrate.decision(cfg, KEY), {"2025/raw/12.December-raw"})
        with mock.patch.object(migrate.ui, "ask", side_effect=AssertionError("asked twice")):
            self.assertTrue(migrate.ask_cli(cfg, [self.set]))       # chosen: never asked again
        cfg2 = {}
        with mock.patch.object(migrate.ui, "ask", return_value="q"):
            self.assertFalse(migrate.ask_cli(cfg2, [self.set]))
        self.assertIsNone(migrate.decision(cfg2, KEY))


try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class DialogTest(unittest.TestCase):
    def test_untick_keeps(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from phonebackup.gui_layout import LayoutDialog
        app = QApplication.instance() or QApplication([])  # noqa: F841
        folders = {"2026/02.February-photos": 3, "2026/02.February-videos": 1,
                   "2025/raw/12.December-raw": 2}
        dlg = LayoutDialog(None, SET, folders)
        self.assertEqual(dlg.kept(), [])
        a, b = dlg.items["2026/02.February-photos"], dlg.items["2026/02.February-videos"]
        a.setSelected(True)
        b.setSelected(True)
        a.setCheckState(0, Qt.Unchecked)                    # several selected: all follow
        self.assertEqual(sorted(dlg.kept()), ["2026/02.February-photos", "2026/02.February-videos"])
        dlg._tick_all(True)
        self.assertEqual(dlg.kept(), [])
        dlg._tick_all(False)
        self.assertEqual(len(dlg.kept()), 3)


if __name__ == "__main__":
    unittest.main()
