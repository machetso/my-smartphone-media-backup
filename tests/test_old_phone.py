"""Import of an old phone (several folders) as a backup of its own."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebackup.export import _category  # noqa: E402
from phonebackup.importer import (CAMERA, OTHER, perform_old_phone_import,  # noqa: E402
                                  perform_selection_import, resort_camera_files, scan_folder)
from tests.test_all import jpeg_with_exif  # noqa: E402
from tests.test_import import tree_hash  # noqa: E402

CFG = {"fsync": False}
T2017 = datetime(2017, 5, 20, 12).timestamp()


class OldPhoneImport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pboldphone_"))
        self.phone = self.tmp / "Galaxy S7 copy"
        self.sd = self.tmp / "SD card"
        self.hdd = self.tmp / "hdd"
        self.hdd.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, base, rel, data, mtime=T2017):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (mtime, mtime))
        return data

    def make_phone(self):
        cam = self.put(self.phone, "DCIM/Camera/20170520_120000.jpg", jpeg_with_exif("2017:05:20 12:00:00"))
        self.put(self.phone, "DCIM/Camera/20170521_130000.mp4", os.urandom(3000))
        self.put(self.phone, "DCIM/.thumbnails/1.jpg", b"thumb")
        self.put(self.phone, "DCIM/Screenshots/Screenshot_20170601.png", b"\x89PNG shot")
        self.put(self.phone, "Pictures/Instagram/insta.jpg", jpeg_with_exif("2017:06:02 10:00:00", b"i"))
        self.put(self.phone, "Download/meme.png", b"\x89PNG meme")
        self.put(self.phone, "Download/invoice.pdf", b"%PDF-1.4 invoice")
        self.put(self.phone, "Download/Thumbs.db", b"junk")
        self.put(self.phone, "Movies/clip.mp4", os.urandom(2000))
        self.put(self.phone, "WhatsApp/Media/WhatsApp Images/IMG-20170520-WA0001.jpg", cam)  # same as camera
        self.put(self.phone, "Android/data/com.app/files/x.jpg", b"app data")
        self.put(self.phone, "Android/obb/game.obb", b"obb")
        self.put(self.phone, "cache/c.jpg", b"cache")
        self.put(self.sd, "DCIM/100ANDRO/DSC_0001.JPG", jpeg_with_exif("2016:12:24 18:00:00", b"sd"))

    def test_scan_suggestions(self):
        self.make_phone()
        found = {f.rel: f for f in scan_folder(self.phone)}
        self.assertEqual(set(found), {"DCIM/Camera", "DCIM/Screenshots", "Pictures/Instagram",
                                      "Download", "Movies", "WhatsApp/Media/WhatsApp Images"})
        self.assertEqual((found["DCIM/Camera"].kind, found["DCIM/Camera"].suggested), (CAMERA, True))
        self.assertEqual((found["Download"].kind, found["Download"].suggested), (OTHER, True))
        self.assertEqual((found["Download"].photos, found["Download"].other, found["Download"].junk), (1, 1, 1))
        self.assertFalse(found["DCIM/Screenshots"].suggested)
        self.assertEqual(found["DCIM/Screenshots"].kind, OTHER)
        self.assertFalse(found["WhatsApp/Media/WhatsApp Images"].suggested)
        sd = {f.rel: f for f in scan_folder(self.sd)}
        self.assertEqual(sd["DCIM/100ANDRO"].kind, CAMERA)
        existing = {f.rel: f for f in scan_folder(self.phone, into_existing=True)}
        self.assertTrue(all(f.kind == CAMERA for f in existing.values()))
        self.assertTrue(existing["Download"].suggested)             # has a photo
        self.assertTrue(existing["WhatsApp/Media/WhatsApp Images"].suggested)

    def test_old_phone_backup(self):
        self.make_phone()
        before = tree_hash(self.phone), tree_hash(self.sd)
        sel = [(str(f.root), f.rel, f.kind) for f in scan_folder(self.phone) + scan_folder(self.sd)
               if f.suggested or f.rel == "WhatsApp/Media/WhatsApp Images"]
        status, paths, results, verdict = perform_old_phone_import(
            sel, "Galaxy S7", "Sam", [self.hdd], CFG, interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertTrue(verdict.startswith("EVERYTHING"), verdict)
        self.assertEqual((tree_hash(self.phone), tree_hash(self.sd)), before, "source must not change")

        root = self.hdd / "Sam" / "Galaxy S7"
        got = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                     if p.is_file() and ".phonebackup" not in p.parts and not p.name.startswith("Import "))
        self.assertEqual(got, [
            "2016/16.12/DSC_0001.JPG",
            "2017/17.05/20170520_120000.jpg",
            "2017/17.05/20170521_130000.mp4",
            "Download/invoice.pdf",                 # kept folders: 1:1 (user request 2026-11-09)
            "Download/meme.png",
            "Movies/clip.mp4",
            "Pictures/Instagram/insta.jpg",
        ])  # WhatsApp copy of the camera photo is stored once, Thumbs.db / app data / cache never
        self.assertTrue(any(p.name == "Import Galaxy S7 Sam " + f"{datetime.now():%Y-%m-%d}.txt"
                            for p in root.iterdir()))
        report = next(p for p in root.iterdir() if p.suffix == ".txt").read_text(encoding="utf-8")
        self.assertIn("Smartphone", report)
        self.assertIn("Thumbs.db", report)
        self.assertEqual(_category("2017/other/pictures/Download/meme.png"), "other")
        self.assertEqual(_category("2017/17.05/x.jpg"), "photo")

        # running it again adds nothing
        status, _, results, verdict = perform_old_phone_import(
            sel, "Galaxy S7", "Sam", [self.hdd], CFG, interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertEqual(results, [])

    def test_into_existing_skips_other_files(self):
        self.make_phone()
        parent = self.hdd / "Sam" / "Pixel"
        parent.mkdir(parents=True)
        sel = [(str(f.root), f.rel, f.kind) for f in scan_folder(self.phone, into_existing=True) if f.suggested]
        status, _, results, verdict = perform_selection_import(sel, [parent], CFG, interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)
        files = sorted(p.relative_to(parent).as_posix() for p in parent.rglob("*")
                       if p.is_file() and ".phonebackup" not in p.parts and not p.name.startswith("Import "))
        self.assertIn("2017/17.06/insta.jpg", files)
        self.assertFalse(any("invoice" in f or "/other/" in f for f in files))

    def make_self_sorted(self):
        """An old backup sorted by hand: no DCIM, folders named by date ranges."""
        old = self.tmp / "Google Pixel 7 Pro Sam"
        self.put(old, "jpgs/August September 2023/PXL_20230815_101010123.jpg",
                 jpeg_with_exif("2023:08:15 10:10:10", b"a"))
        self.put(old, "jpgs/August September 2023/PXL_20230901_090000000.mp4", os.urandom(1500),
                 mtime=datetime(2023, 9, 1, 9).timestamp())
        self.put(old, "RAW bis 8.5.23/PXL_20230102_111111111.dng", b"II*\x00" + os.urandom(800),
                 mtime=datetime(2023, 1, 2, 11).timestamp())
        self.put(old, "jpgs/Saved/meme.jpg", jpeg_with_exif("2023:03:03 12:00:00", b"m"))
        return old

    def test_self_sorted_old_backup_goes_to_month_folders(self):
        old = self.make_self_sorted()
        found = {f.rel: f for f in scan_folder(old)}
        self.assertEqual(found["jpgs/August September 2023"].kind, CAMERA)
        self.assertEqual(found["RAW bis 8.5.23"].kind, CAMERA)
        self.assertEqual(found["jpgs/Saved"].kind, OTHER)
        sel = [(str(f.root), f.rel, f.kind) for f in found.values() if f.suggested]
        status, _, _, verdict = perform_old_phone_import(sel, "Pixel 7 Pro", "Sam", [self.hdd], CFG,
                                                         interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)
        root = self.hdd / "Sam" / "Pixel 7 Pro"
        got = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                     if p.is_file() and ".phonebackup" not in p.parts and not p.name.startswith("Import "))
        self.assertEqual(got, ["2023/23.08/PXL_20230815_101010123.jpg",
                               "2023/23.09/PXL_20230901_090000000.mp4",
                               "2023/raw/23.01/PXL_20230102_111111111.dng",
                               "jpgs/Saved/meme.jpg"])

    def test_resort_earlier_wrong_import(self):
        old = self.make_self_sorted()
        sel = [(str(f.root), f.rel, OTHER) for f in scan_folder(old)]        # how the old version did it
        from phonebackup import importer
        from phonebackup.layout import OTHER_KIND, other_dir
        legacy = lambda src, sf, taken, cat: (other_dir(taken, cat, src._info[sf.rel][1]) if cat in OTHER_KIND
                                              else importer.relative_dir(taken, cat))
        with mock.patch.object(importer.SelectionSource, "placement", legacy):
            perform_old_phone_import(sel, "Pixel 7 Pro", "Sam", [self.hdd], CFG, interactive=False)
        root = self.hdd / "Sam" / "Pixel 7 Pro"
        self.assertTrue((root / "2023/other/pictures/RAW bis 8.5.23/PXL_20230102_111111111.dng").is_file())
        before = {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file() and "other" in p.parts}
        planned = resort_camera_files(root, dry_run=True)
        self.assertEqual(len(planned), 3)
        self.assertTrue((root / "2023/other/pictures/RAW bis 8.5.23/PXL_20230102_111111111.dng").is_file())
        moves = resort_camera_files(root)
        self.assertEqual(sorted(n for _, n in moves), [
            "2023/23.08/PXL_20230815_101010123.jpg",
            "2023/23.09/PXL_20230901_090000000.mp4",
            "2023/raw/23.01/PXL_20230102_111111111.dng"])
        files = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
                 if p.is_file() and ".phonebackup" not in p.parts and p.suffix not in (".txt", ".html", ".csv")}
        self.assertEqual(sorted(files), sorted([n for _, n in moves] + ["2023/other/pictures/jpgs/Saved/meme.jpg"]))
        for rel, p in files.items():
            self.assertEqual(p.read_bytes(), before[p.name], "content must be unchanged")
        self.assertFalse((root / "2023/other/pictures/RAW bis 8.5.23").exists(), "empty folder left")
        self.assertTrue(any(p.name.startswith("Resorted camera files") for p in root.iterdir()))
        # the index knows the new places: importing again copies nothing
        with mock.patch.object(importer.SelectionSource, "placement", legacy):
            status, _, results, _ = perform_old_phone_import(sel, "Pixel 7 Pro", "Sam", [self.hdd], CFG,
                                                             interactive=False)
        self.assertEqual((status, results), ("COMPLETED", []))
        self.assertEqual(resort_camera_files(root), [])

    def test_old_drive_folders_kept_1to1(self):
        """An old hard drive: one folder tree kept exactly as it is, the rest sorted like a phone."""
        drive = self.tmp / "OldHDD"
        self.put(drive, "Fotos/Urlaub Italien 2019/Tag 1/IMG_20190701_100000.jpg",
                 jpeg_with_exif("2019:07:01 10:00:00", b"t1"))
        self.put(drive, "Fotos/Urlaub Italien 2019/Tag 2/IMG_20190702_100000.jpg",
                 jpeg_with_exif("2019:07:02 10:00:00", b"t2"))
        self.put(drive, "Fotos/Urlaub Italien 2019/notes.txt", b"notes")
        self.put(drive, "Handy alt/IMG_20180505_120000.jpg", jpeg_with_exif("2018:05:05 12:00:00", b"h"))
        found = {f.rel: f for f in scan_folder(drive)}
        keep = {"Fotos/Urlaub Italien 2019", "Fotos/Urlaub Italien 2019/Tag 1",
                "Fotos/Urlaub Italien 2019/Tag 2"}
        sel = [(str(f.root), f.rel, OTHER if f.rel in keep else CAMERA) for f in found.values()]
        status, _, _, verdict = perform_old_phone_import(sel, "Alte Festplatte", "Sam", [self.hdd],
                                                         dict(CFG), interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)
        root = self.hdd / "Sam" / "Alte Festplatte"
        got = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                     if p.is_file() and ".phonebackup" not in p.parts and not p.name.startswith("Import "))
        self.assertEqual(got, ["2018/18.05/IMG_20180505_120000.jpg",
                               "Fotos/Urlaub Italien 2019/Tag 1/IMG_20190701_100000.jpg",
                               "Fotos/Urlaub Italien 2019/Tag 2/IMG_20190702_100000.jpg",
                               "Fotos/Urlaub Italien 2019/notes.txt"])

    def test_kept_old_month_folder_is_never_converted(self):
        """An old backup of this program kept 1:1: its 2019/07.July-photos must stay."""
        from phonebackup import migrate
        old = self.tmp / "Altes Backup"
        self.put(old, "2019/07.July-photos/IMG_20190701_100000.jpg", jpeg_with_exif("2019:07:01 10:00:00", b"a"))
        sel = [(str(f.root), f.rel, OTHER) for f in scan_folder(old)]
        cfg = dict(CFG)
        with mock.patch("phonebackup.config.save"):
            perform_old_phone_import(sel, "Pixel 3", "Sam", [self.hdd], cfg, interactive=False)
        root = self.hdd / "Sam" / "Pixel 3"
        self.assertTrue((root / "2019/07.July-photos/IMG_20190701_100000.jpg").is_file())
        self.assertEqual(migrate.always_kept(cfg, "Pixel 3 - Sam"), {"2019/07.July-photos"})
        self.assertEqual(migrate.to_choose(cfg, root), {}, "not even asked")
        keep = migrate.effective_keep(cfg, root)
        self.assertEqual(migrate.ensure_converted(root, keep=keep), (0, []))
        self.assertTrue((root / "2019/07.July-photos/IMG_20190701_100000.jpg").is_file())

    def test_source_inside_backup_rejected(self):
        self.put(self.hdd / "Sam" / "Galaxy S7", "DCIM/x.jpg", b"x")
        with self.assertRaises(ValueError):
            perform_old_phone_import([(str(self.hdd / "Sam" / "Galaxy S7"), "DCIM", CAMERA)],
                                     "Galaxy S7", "Sam", [self.hdd], CFG, interactive=False)


if __name__ == "__main__":
    unittest.main()
