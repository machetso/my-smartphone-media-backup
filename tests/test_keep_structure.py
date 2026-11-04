"""Option "keep the phone's folder structure" for folders other than the camera folder."""
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from phonebackup.backup import perform_backup
from phonebackup.layout import is_camera_folder, keep_structure_placement
from phonebackup.sources import FolderSource

CFG = {"fsync": False}


class PlacementTest(unittest.TestCase):
    def test_camera_folders(self):
        for f in ("DCIM/Camera", "DCIM/Camera/", "DCIM/100ANDRO", "dcim/camera"):
            self.assertTrue(is_camera_folder(f), f)
        for f in ("DCIM/Screenshots", "Pictures/Screenshots", "DCIM", "Movies"):
            self.assertFalse(is_camera_folder(f), f)

    def test_placement(self):
        p = keep_structure_placement(["DCIM/Camera", "Pictures/Screenshots", "Movies"])
        t = datetime(2026, 3, 5)
        sf = lambda rel: SimpleNamespace(rel=rel)  # noqa: E731
        self.assertEqual(p(sf("DCIM/Camera/a.jpg"), t, "photo").as_posix(), "2026/03.March-photos")
        self.assertEqual(p(sf("Pictures/Screenshots/b.png"), t, "photo").as_posix(), "Pictures/Screenshots")
        self.assertEqual(p(sf("Movies/Trip/Day 1/c.mp4"), t, "video").as_posix(), "Movies/Trip/Day 1")
        self.assertEqual(p(sf("Pictures/Other/d.jpg"), t, "photo").as_posix(), "2026/03.March-photos")


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbkeep_"))
        self.phone, self.dest = self.tmp / "phone", self.tmp / "hdd"
        self.dest.mkdir()
        mt = datetime(2025, 7, 1, 12).timestamp()
        for rel, data in (("DCIM/Camera/IMG_1.jpg", b"\xff\xd8camera" + os.urandom(500)),
                          ("Pictures/Screenshots/Shot_1.png", b"\x89PNG\r\n\x1a\nshot" + os.urandom(500)),
                          ("Movies/Trip/clip.mp4", b"\0\0\0\x18ftypmp42" + os.urandom(500))):
            p = self.phone / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            os.utime(p, (mt, mt))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_backup(self, keep):
        src = FolderSource(self.phone, device_name="Pixel 10 Pro")
        return perform_backup(src, "Pixel 10 Pro", "Sam", ["DCIM/Camera", "Pictures/Screenshots", "Movies"],
                              [str(self.dest)], CFG, interactive=False, keep_structure=keep)

    def files(self):
        root = self.dest / "Pixel 10 Pro - Sam"
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                      if p.is_file() and not p.relative_to(root).parts[0].startswith(".")
                      and p.suffix in (".jpg", ".png", ".mp4"))

    def test_keep_structure(self):
        status, _paths, _res, verdict = self.run_backup(True)
        self.assertEqual(status, "COMPLETED", verdict)
        self.assertEqual(self.files(), ["2025/07.July-photos/IMG_1.jpg", "Movies/Trip/clip.mp4",
                                        "Pictures/Screenshots/Shot_1.png"])

    def test_default_sorts_everything(self):
        self.run_backup(False)
        self.assertTrue(all(f.startswith("2025/") for f in self.files()), self.files())


if __name__ == "__main__":
    unittest.main()
