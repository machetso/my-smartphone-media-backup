"""Download ADB: unpacking, replacing an older download, refusing unsafe zips (offline)."""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebackup import adbdownload  # noqa: E402

FAKE_ADB = "#!/bin/sh\necho 'Android Debug Bridge version 9.9.9'\n"


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data, mode in members:
            info = zipfile.ZipInfo(name)
            info.external_attr = (mode & 0o777) << 16
            zf.writestr(info, data)


@unittest.skipUnless(sys.platform.startswith("linux"), "uses a shell script as fake adb")
class DownloadAdb(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbadb_"))
        self.patch = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.tmp / "data")})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_download_and_replace(self):
        z = self.tmp / "pt.zip"
        make_zip(z, [("platform-tools/adb", FAKE_ADB, 0o755), ("platform-tools/NOTICE.txt", "n", 0o644),
                     ("other/ignored.txt", "x", 0o644)])
        path, version = adbdownload.download_adb(url=z.as_uri())
        self.assertEqual(version, "Android Debug Bridge version 9.9.9")
        self.assertEqual(path, adbdownload.installed_adb())
        self.assertTrue(os.access(path, os.X_OK))
        self.assertFalse((self.tmp / "data" / "phonebackup" / "other").exists())
        # a second download replaces the first; no temp folders are left behind
        adbdownload.download_adb(url=z.as_uri())
        self.assertEqual(sorted(p.name for p in (self.tmp / "data" / "phonebackup").iterdir()),
                         ["platform-tools"])

    def test_unsafe_or_broken_downloads_are_refused(self):
        bad = self.tmp / "bad.zip"
        make_zip(bad, [("platform-tools/../../evil.sh", "x", 0o755), ("platform-tools/adb", FAKE_ADB, 0o755)])
        with self.assertRaises(ValueError):
            adbdownload.download_adb(url=bad.as_uri())
        self.assertFalse((self.tmp / "evil.sh").exists())
        notzip = self.tmp / "page.zip"
        notzip.write_text("<html>error</html>")
        with self.assertRaises(ValueError):
            adbdownload.download_adb(url=notzip.as_uri())
        noadb = self.tmp / "noadb.zip"
        make_zip(noadb, [("platform-tools/fastboot", "x", 0o755)])
        with self.assertRaises(ValueError):
            adbdownload.download_adb(url=noadb.as_uri())
        self.assertIsNone(adbdownload.installed_adb())


if __name__ == "__main__":
    unittest.main()
