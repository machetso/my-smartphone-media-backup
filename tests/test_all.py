"""End-to-end tests with a fake phone folder.  Run:  python -m unittest discover tests"""

import os
import shutil
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebackup import media  # noqa: E402
from phonebackup.backup import perform_backup  # noqa: E402
from phonebackup.copier import stream_copy  # noqa: E402
from phonebackup.export import Catalog, perform_export, perform_restore  # noqa: E402
from phonebackup.sources import FolderSource  # noqa: E402

CFG = {"fsync": False}


def tiff_with_date(date_str, exif_ifd=True):
    """Minimal little-endian TIFF with DateTimeOriginal (in Exif IFD) or DateTime (IFD0)."""
    dt = date_str.encode() + b"\0"                       # 20 bytes
    if exif_ifd:
        # header(8) IFD0 @8: 1 entry (8769 -> 26) ; ExifIFD @26: 1 entry (9003 -> 44) ; data @44
        ifd0 = struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, 26) + struct.pack("<I", 0)
        exif = struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, 20, 44) + struct.pack("<I", 0)
        return b"II*\0" + struct.pack("<I", 8) + ifd0 + exif + dt
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHII", 0x0132, 2, 20, 26) + struct.pack("<I", 0)
    return b"II*\0" + struct.pack("<I", 8) + ifd0 + dt


def jpeg_with_exif(date_str, payload=b""):
    app1 = b"Exif\0\0" + tiff_with_date(date_str)
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 +
            b"\xff\xda\x00\x02" + payload + os.urandom(2000) + b"\xff\xd9")


def mp4_with_date(dt_utc):
    secs = int(dt_utc.timestamp()) + 2082844800
    mvhd_body = b"\0\0\0\0" + struct.pack(">II", secs, secs) + b"\0" * 88
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"isom\0\0\0\0"
    mdat_data = os.urandom(300_000)
    mdat = struct.pack(">I4s", 8 + len(mdat_data), b"mdat") + mdat_data
    return ftyp + mdat + moov                               # moov at the end, like Android


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbtest_"))
        self.phone = self.tmp / "phone"
        self.cam = self.phone / "DCIM" / "Camera"
        self.cam.mkdir(parents=True)
        self.d1, self.d2 = self.tmp / "hdd1", self.tmp / "hdd2"
        self.d1.mkdir()
        self.d2.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data, mtime=None):
        p = self.phone / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if mtime:
            os.utime(p, (mtime, mtime))
        return p

    def run_backup(self, folders=("DCIM/Camera",), dests=None):
        src = FolderSource(self.phone, device_name="Pixel 10 Pro")
        return perform_backup(src, "Pixel 10 Pro", "Sam Test", list(folders),
                              [str(d) for d in (dests or [self.d1, self.d2])], CFG, interactive=False)

    def test_full_flow(self):
        video_utc = datetime(2024, 12, 24, 17, 0, 0, tzinfo=timezone.utc)
        video_local = datetime.fromtimestamp(video_utc.timestamp())
        self.write("DCIM/Camera/IMG_0001.jpg", jpeg_with_exif("2025:03:15 10:20:30"))
        self.write("DCIM/Camera/VID_A.mp4", mp4_with_date(video_utc))
        self.write("DCIM/Camera/RAW_1.dng", tiff_with_date("2026:01:05 08:00:00", exif_ifd=False) + os.urandom(5000))
        self.write("DCIM/Camera/Screenshot_20260210-101010.png", b"\x89PNG\r\n\x1a\n" + os.urandom(800))
        self.write("DCIM/Camera/PXL_20261102_143000123.MP.jpg", b"\xff\xd8" + os.urandom(3000))
        self.write("DCIM/Camera/noinfo.heic", os.urandom(1500), mtime=datetime(2023, 7, 1, 12).timestamp())
        self.write("DCIM/Camera/.trashed-1-x.jpg", os.urandom(100))
        self.write("DCIM/Camera/notes.txt", b"hello")

        status, paths, results, _ = self.run_backup()
        self.assertEqual(status, "COMPLETED")
        self.assertEqual(len(results), 6)
        self.assertTrue(all(r.ok for r in results), [r.per_dest for r in results])

        parent1 = self.d1 / "Sam Test" / "Pixel 10 Pro"      # <Owner>/<Phone>
        parent2 = self.d2 / "Sam Test" / "Pixel 10 Pro"
        exp = [
            "2025/25.03/IMG_0001.jpg",
            f"{video_local.year}/{video_local.year % 100:02d}.{video_local.month:02d}/VID_A.mp4",
            "2026/raw/26.01/RAW_1.dng",
            "2026/26.02/Screenshot_20260210-101010.png",
            "2026/26.11/PXL_20261102_143000123.MP.jpg",
            "2023/23.07/noinfo.heic",
        ]
        for rel in exp:
            for parent in (parent1, parent2):
                self.assertTrue((parent / rel).is_file(), f"missing {parent / rel}")
                self.assertEqual((parent / rel).read_bytes(), (self.cam / Path(rel).name).read_bytes())
        # only month folders that received files exist (no empty folders), no space after the dot
        self.assertEqual(sorted(p.name for p in (parent1 / "2025").iterdir()), ["25.03"])
        self.assertFalse((parent1 / "2026" / "26.03").exists())
        empty = [p for p in parent1.rglob("*") if p.is_dir() and not any(p.iterdir())
                 and ".phonebackup" not in p.parts]
        self.assertEqual(empty, [])
        # report in the parent folder, named as requested
        names = sorted(p.name for p in (parent1 / "Logs").iterdir() if p.is_file())
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertIn(f"Backup Pixel 10 Pro Sam Test {today}.txt", names)
        self.assertIn(f"Backup Pixel 10 Pro Sam Test {today}.html", names)
        self.assertIn(f"Backup Pixel 10 Pro Sam Test {today}.csv", names)
        txt = (parent1 / "Logs" / f"Backup Pixel 10 Pro Sam Test {today}.txt").read_text(encoding="utf-8")
        self.assertIn("EVERYTHING COPIED CORRECTLY", txt)
        self.assertIn("skipped (not a photo/video file)", txt)
        self.assertNotIn(".trashed", txt)

        # ---- incremental: nothing new
        status, paths, results, _ = self.run_backup()
        self.assertEqual(results, [])
        # second report on the same day gets the time added
        self.assertEqual(len([p for p in (parent1 / "Logs").glob("Backup *.txt")]), 2)

        # ---- new files: same name/other content in another folder, identical copy under new name
        self.write("DCIM/Other/IMG_0001.jpg", jpeg_with_exif("2025:03:15 11:00:00", b"different"))
        shutil.copy(self.cam / "VID_A.mp4", self.cam / "VID_A_copy.mp4")
        self.write("DCIM/Camera/IMG_0002.jpg", jpeg_with_exif("2025:03:16 09:00:00"))
        status, paths, results, _ = self.run_backup(folders=("DCIM/Camera", "DCIM/Other"))
        self.assertEqual(status, "COMPLETED")
        by_name = {r.sf.rel: r for r in results}
        self.assertEqual(len(results), 3)
        st, loc = by_name["DCIM/Other/IMG_0001.jpg"].per_dest["Destination 1"]
        self.assertIn("renamed", st)
        self.assertEqual(loc, "2025/25.03/IMG_0001_1.jpg")
        st, loc = by_name["DCIM/Camera/VID_A_copy.mp4"].per_dest["Destination 1"]
        self.assertTrue(st.startswith("DUPLICATE"), st)

        # ---- new second drive gets everything, first drive nothing
        d3 = self.tmp / "hdd3"
        d3.mkdir()
        status, paths, results, _ = self.run_backup(folders=("DCIM/Camera", "DCIM/Other"), dests=[self.d1, d3])
        self.assertTrue(all("Destination 1" not in r.per_dest for r in results))
        self.assertEqual(len(results), 9)

        # ---- export chain + restore
        exp_base = self.tmp / "second"
        exp_base.mkdir()
        perform_export(parent1, exp_base, "full", CFG)
        self.write("DCIM/Camera/IMG_0003.jpg", jpeg_with_exif("2025:04:01 09:00:00"))
        self.run_backup()
        st, _, _ = perform_export(parent1, exp_base, "incremental", CFG)
        self.assertEqual(st, "COMPLETED")
        self.write("DCIM/Camera/IMG_0004.jpg", jpeg_with_exif("2025:05:01 09:00:00"))
        self.run_backup()
        perform_export(parent1, exp_base, "incremental", CFG)
        st, _, _ = perform_export(parent1, exp_base, "differential", CFG)
        self.assertEqual(st, "COMPLETED")
        tparent = exp_base / "Sam Test" / parent1.name
        cat = Catalog(tparent)
        runs = cat.runs()
        diff_files = cat.files_of([runs[-1].id])
        incr_files = cat.files_of([runs[-2].id])
        cat.close()
        self.assertTrue(any(k.endswith("IMG_0003.jpg") for k in diff_files))
        self.assertTrue(any(k.endswith("IMG_0004.jpg") for k in diff_files))
        self.assertFalse(any(k.endswith("IMG_0003.jpg") for k in incr_files))

        restore = self.tmp / "restored"
        st, _, _ = perform_restore(tparent, runs[-1].id, restore, CFG)
        self.assertEqual(st, "COMPLETED")
        for p in parent1.rglob("*"):
            if p.is_file() and ".phonebackup" not in p.parts:
                rel = p.relative_to(parent1)
                if rel.parts[0].startswith("Backup "):
                    continue        # reports written after the last export
                self.assertEqual((restore / rel).read_bytes(), p.read_bytes(), str(rel))




class Units(unittest.TestCase):
    def test_filename_dates(self):
        self.assertEqual(media.filename_datetime("PXL_20261102_143000123.jpg"), datetime(2026, 11, 2, 14, 30, 0))
        self.assertEqual(media.filename_datetime("IMG-20250101-WA0001.jpg"), datetime(2025, 1, 1))
        self.assertIsNone(media.filename_datetime("DSC_1234.jpg"))

    def test_categories(self):
        self.assertEqual(media.category_for("a.DNG"), "raw")
        self.assertEqual(media.category_for("PXL_1.MP.jpg"), "photo")
        self.assertEqual(media.category_for("v.MP4"), "video")
        self.assertIsNone(media.category_for("x.txt"))

    def test_writer_error_does_not_block(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            blocker = tmp / "file"
            blocker.write_text("x")
            good, bad = tmp / "ok.bin", blocker / "sub" / "bad.bin"   # parent is a file -> error
            data = [os.urandom(1024 * 1024) for _ in range(40)]
            sha, n, (r1, r2) = stream_copy(iter(data), [good, bad], fsync=False)
            self.assertEqual(r1.sha256, sha)
            self.assertIsNotNone(r2.error)
            self.assertEqual(n, 40 * 1024 * 1024)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
