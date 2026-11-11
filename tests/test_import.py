"""Import of an old, messy backup folder into an existing backup."""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebackup.backup import perform_backup  # noqa: E402
from phonebackup.importer import check_import, perform_import  # noqa: E402
from phonebackup.sources import FolderSource  # noqa: E402
from tests.test_all import jpeg_with_exif, tiff_with_date  # noqa: E402

CFG = {"fsync": False}


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
            h.update(str(int(p.stat().st_mtime)).encode())
    return h.hexdigest()


class ImportOldBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbimport_"))
        self.phone = self.tmp / "phone"
        self.old = self.tmp / "old backup 2019"
        self.d1, self.d2 = self.tmp / "hdd1", self.tmp / "hdd2"
        for d in (self.d1, self.d2):
            d.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, base, rel, data, mtime=None):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if mtime:
            os.utime(p, (mtime, mtime))
        return data

    def test_import(self):
        phone_img = self.put(self.phone, "DCIM/Camera/IMG_A.jpg", jpeg_with_exif("2025:03:15 10:00:00"))
        src = FolderSource(self.phone, device_name="Pixel 10 Pro")
        perform_backup(src, "Pixel 10 Pro", "Sam", ["DCIM/Camera"], [self.d1, self.d2], CFG, interactive=False)
        parents = [self.d1 / "Sam" / "Pixel 10 Pro", self.d2 / "Sam" / "Pixel 10 Pro"]

        holiday = self.put(self.old, "2019 Urlaub/DSC_0001.JPG", jpeg_with_exif("2019:07:14 12:00:00"))
        self.put(self.old, "2019 Urlaub/copy/DSC_0001.JPG", holiday)                       # duplicate in source
        self.put(self.old, "Misc/IMG_A_copy.jpg", phone_img)                               # already in backup
        self.put(self.old, "Misc/DSC_0001.JPG", jpeg_with_exif("2019:07:14 13:00:00", b"other"))  # name clash
        self.put(self.old, "Misc/scan.tif", tiff_with_date("2010:05:01 09:00:00") + os.urandom(500))
        self.put(self.old, "Videos/00001.MTS", os.urandom(4000), mtime=datetime(2015, 8, 20, 12).timestamp())
        self.put(self.old, "RAW/_DSC1234.NEF", tiff_with_date("2018:02:02 08:00:00", exif_ifd=False) + os.urandom(900))
        self.put(self.old, "Docs/letter.pdf", b"%PDF-1.4 test")
        self.put(self.old, "@eaDir/DSC_0001.JPG/SYNOPHOTO_THUMB_XL.jpg", jpeg_with_exif("2019:07:14 12:00:00", b"t"))
        self.put(self.old, "$RECYCLE.BIN/x.jpg", jpeg_with_exif("2001:01:01 12:00:00", b"r"))
        before = tree_hash(self.old)

        status, paths, results, verdict = perform_import(self.old, parents, CFG, interactive=False)
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertTrue(verdict.startswith("EVERYTHING"), verdict)
        self.assertEqual(tree_hash(self.old), before, "source folder must not be changed")

        by = {r.sf.rel: r for r in results}
        self.assertEqual(len(results), 7)                                    # no @eaDir / recycle bin
        self.assertNotIn("@eaDir/DSC_0001.JPG/SYNOPHOTO_THUMB_XL.jpg", by)
        self.assertTrue(all(r.transfer_check.startswith("OK (SHA-256 at source") for r in results))

        def dest(rel):
            return by[rel].per_dest["Destination 1"]

        self.assertEqual(dest("2019 Urlaub/DSC_0001.JPG"), ("OK - copied and verified", "2019/19.07/DSC_0001.JPG"))
        self.assertTrue(dest("2019 Urlaub/copy/DSC_0001.JPG")[0].startswith("DUPLICATE"))
        self.assertEqual(dest("Misc/IMG_A_copy.jpg")[1], "2025/25.03/IMG_A.jpg")
        self.assertTrue(dest("Misc/IMG_A_copy.jpg")[0].startswith("DUPLICATE"))
        self.assertEqual(dest("Misc/DSC_0001.JPG")[1], "2019/19.07/DSC_0001_1.JPG")
        self.assertEqual(dest("Misc/scan.tif")[1], "2010/10.05/scan.tif")
        self.assertEqual(dest("Videos/00001.MTS")[1], "2015/15.08/00001.MTS")
        self.assertEqual(by["Videos/00001.MTS"].date_source, "file date")
        self.assertEqual(dest("RAW/_DSC1234.NEF")[1], "2018/raw/18.02/_DSC1234.NEF")

        for parent in parents:
            files = sorted(p.relative_to(parent).as_posix() for p in parent.rglob("*")
                           if p.is_file() and ".phonebackup" not in p.parts and not p.name.startswith(("Backup ", "Import ")))
            self.assertEqual(files, [
                "2010/10.05/scan.tif", "2015/15.08/00001.MTS",
                "2018/raw/18.02/_DSC1234.NEF", "2019/19.07/DSC_0001.JPG",
                "2019/19.07/DSC_0001_1.JPG", "2025/25.03/IMG_A.jpg"])
            today = datetime.now().strftime("%Y-%m-%d")
            txt = (parent / "Logs" / f"Import old backup 2019 {today}.txt").read_text(encoding="utf-8")
            self.assertIn("Imported folder", txt)
            self.assertIn("letter.pdf", txt)
            self.assertIn("skipped (not a photo/video file)", txt)
            empty = [p for p in parent.rglob("*") if p.is_dir() and not any(p.iterdir())]
            self.assertEqual(empty, [])

        # running the same import again copies nothing
        status, _, results, _ = perform_import(self.old, parents, CFG, interactive=False)
        self.assertEqual((status, results), ("COMPLETED", []))

        # nonsense combinations are refused
        with self.assertRaises(ValueError):
            check_import(parents[0] / "2019", parents)
        with self.assertRaises(ValueError):
            check_import(self.tmp, parents)


if __name__ == "__main__":
    unittest.main()
