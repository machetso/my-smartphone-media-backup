"""Download ADB: unpacking, replacing an older download, refusing unsafe zips (offline)."""

import hashlib
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

    def test_checksum_from_googles_list_is_enforced(self):
        z = self.tmp / "pt.zip"
        make_zip(z, [("platform-tools/adb", FAKE_ADB, 0o755)])
        data = z.read_bytes()
        good = (len(data), hashlib.sha1(data).hexdigest())
        with self.assertRaises(ValueError):
            adbdownload.download_adb(url=z.as_uri(), expect=(good[0], "0" * 40))
        with self.assertRaises(ValueError):
            adbdownload.download_adb(url=z.as_uri(), expect=(good[0] + 1, good[1]))
        self.assertIsNone(adbdownload.installed_adb())          # nothing unpacked
        adbdownload.download_adb(url=z.as_uri(), expect=good)
        self.assertIsNotNone(adbdownload.installed_adb())

    def test_without_url_the_manifest_file_and_checksum_are_used(self):
        z = self.tmp / "platform-tools_r1.0.0-linux.zip"
        make_zip(z, [("platform-tools/adb", FAKE_ADB, 0o755)])
        data = z.read_bytes()
        xml = MANIFEST.format(size=len(data), sha1=hashlib.sha1(data).hexdigest()).encode()
        with mock.patch.object(adbdownload, "_fetch", lambda url, limit: xml), \
                mock.patch.object(adbdownload, "platform_name", lambda: "linux"), \
                mock.patch.object(adbdownload, "REPO_BASE", self.tmp.as_uri() + "/"):
            adbdownload.download_adb()
        self.assertIsNotNone(adbdownload.installed_adb())


MANIFEST = """<?xml version="1.0"?>
<sdk:sdk-repository xmlns:sdk="http://schemas.android.com/sdk/android/repo/repository2/03">
  <channel id="channel-0">stable</channel>
  <channel id="channel-2">dev</channel>
  <remotePackage path="platform-tools">
    <revision><major>2</major><minor>0</minor><micro>0</micro></revision>
    <channelRef ref="channel-2"/>
    <archives><archive><complete><size>1</size><checksum type="sha1">{sha1}</checksum>
      <url>platform-tools_r2.0.0-linux.zip</url></complete><host-os>linux</host-os></archive></archives>
  </remotePackage>
  <remotePackage path="platform-tools">
    <revision><major>1</major><minor>0</minor><micro>0</micro></revision>
    <channelRef ref="channel-0"/>
    <archives>
      <archive><complete><size>{size}</size><checksum type="sha1">{sha1}</checksum>
        <url>platform-tools_r1.0.0-linux.zip</url></complete><host-os>linux</host-os></archive>
      <archive><complete><size>5</size><checksum type="sha1">{sha1}</checksum>
        <url>platform-tools_r1.0.0-win.zip</url></complete><host-os>windows</host-os></archive>
    </archives>
  </remotePackage>
</sdk:sdk-repository>"""


class StableArchive(unittest.TestCase):
    def test_newest_stable_for_this_system(self):
        xml = MANIFEST.format(size=10, sha1="ab" * 20).encode()
        self.assertEqual(adbdownload.stable_archive(xml, "linux"),
                         ("platform-tools_r1.0.0-linux.zip", 10, "ab" * 20, (1, 0, 0)))
        self.assertEqual(adbdownload.stable_archive(xml, "windows")[0], "platform-tools_r1.0.0-win.zip")
        with self.assertRaises(ValueError):
            adbdownload.stable_archive(xml, "darwin")


if __name__ == "__main__":
    unittest.main()
