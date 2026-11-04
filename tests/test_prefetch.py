"""Fetch-ahead for many small files (companion.Prefetcher; ADB: several files per 'cat')."""
import time
import unittest
from unittest import mock

from phonebackup import phoneguard
from phonebackup.companion import Prefetcher
from phonebackup.sources import AdbSource, SourceFile, _q


def files(n, size=10):
    return [SourceFile(f"DCIM/Camera/{i:03d}.jpg", size, 0) for i in range(n)]


def content(sf):
    return (sf.rel.encode() * 10)[:sf.size]


class PrefetchTest(unittest.TestCase):
    def test_all_files_correct_in_groups(self):
        fs = files(30)
        calls = []

        def fetch(group):
            calls.append(len(group))
            return {sf.rel: content(sf) for sf in group}

        p = Prefetcher(fetch, fs, group_files=8)
        for sf in fs:
            self.assertEqual(p.take(sf), content(sf))
        p.stop()
        self.assertEqual(sorted(calls), [6, 8, 8, 8])

    def test_memory_limit(self):
        fs = files(40, size=50)
        p = Prefetcher(lambda g: {sf.rel: content(sf) for sf in g}, fs)
        p.MAX_BYTES = 200
        time.sleep(0.2)
        for sf in fs:
            self.assertEqual(p.take(sf), content(sf))
        self.assertEqual(p.in_memory, 0)
        p.stop()

    def test_failures_fall_back_to_direct_streaming(self):
        fs = files(4)
        big = SourceFile("DCIM/Camera/big.mp4", Prefetcher.MAX_FILE + 1, 0)

        def fetch(group):
            out = {sf.rel: content(sf) for sf in group}
            out["DCIM/Camera/001.jpg"] = b"short"            # wrong length → not used
            if any(sf.rel.endswith("003.jpg") for sf in group):
                raise OSError("connection dropped")
            return out

        p = Prefetcher(fetch, fs + [big])
        self.assertEqual(p.take(fs[0]), content(fs[0]))
        self.assertIsNone(p.take(fs[1]))
        self.assertEqual(p.take(fs[2]), content(fs[2]))
        self.assertIsNone(p.take(fs[3]))
        self.assertIsNone(p.take(big))
        self.assertIsNone(p.take(fs[0]))                       # once only: a retry streams directly
        p.stop()


class AdbGroupTest(unittest.TestCase):
    def test_one_cat_for_many_files_split_by_size(self):
        fs = [SourceFile("DCIM/a.jpg", 3, 0), SourceFile("Pictures/it's b.png", 5, 0)]
        src = AdbSource.__new__(AdbSource)
        src.adb, src.serial = "adb", "X"
        seen = {}

        def run(args, **kw):
            seen["cmd"] = args[-1]
            return mock.Mock(returncode=0, stdout=b"AAABBBBB")

        with mock.patch("phonebackup.sources.subprocess.run", run):
            out = src._fetch_group(fs)
        self.assertEqual(out, {"DCIM/a.jpg": b"AAA", "Pictures/it's b.png": b"BBBBB"})
        phoneguard.check(seen["cmd"])                          # allowed: read-only cat
        self.assertIn(_q("/sdcard/Pictures/it's b.png"), seen["cmd"])
        with mock.patch("phonebackup.sources.subprocess.run",
                        lambda a, **k: mock.Mock(returncode=0, stdout=b"AAABBB")):
            self.assertEqual(src._fetch_group(fs), {})        # changed file → stream singly

    def test_cat_outside_sdcard_refused(self):
        with self.assertRaises(phoneguard.ForbiddenPhoneCommand):
            phoneguard.check("cat " + _q("/sdcard/a.jpg") + " " + _q("/data/secret"))


if __name__ == "__main__":
    unittest.main()
