"""Phone app signer check: a fake phone app (other signature) is recognised and refused."""

import unittest
from pathlib import Path
from unittest import mock

from phonebackup import apksig, phoneguard
from phonebackup.sources import AdbSource

DATA = Path(__file__).resolve().parent / "data"
A, B = DATA / "signed_a.apk", DATA / "signed_b.apk"     # same content, two different test keys


class ApkSigTest(unittest.TestCase):
    def test_signing_certificate(self):
        # values from `keytool -list` of the two test keystores
        self.assertEqual(apksig.signer_certs(A),
                         {"c3532e8e3b802deb25f254bc9f0ebbc8b8ed6655c40975857f9c74b94b329e26"})
        self.assertEqual(apksig.signer_certs(B),
                         {"527846e4ba317b62f4065541175c45301031112e963f94410842bd0b4ed7eba3"})
        self.assertTrue(apksig.same_signer(A, A.read_bytes()))
        self.assertFalse(apksig.same_signer(A, B))

    def test_unsigned_or_broken_files(self):
        for data in (b"", b"not a zip at all", A.read_bytes()[:3000], A.read_bytes()[-200:]):
            with self.assertRaises(apksig.ApkSigError):
                apksig.signer_certs(data)


class InstalledAppTest(unittest.TestCase):
    def source(self, pm_out, pulled):
        src = AdbSource.__new__(AdbSource)
        src.adb, src.serial = "adb", "SER"
        src.control = lambda name: (0, pm_out) if name == "companion_path" else (1, "")

        class R:
            returncode = 0

        def fake_run(args, timeout=0):
            if args[3] == "pull":
                Path(args[5]).write_bytes(pulled.read_bytes())
            return R()
        return src, fake_run

    def test_fake_app_is_recognised(self):
        out = "package:/data/app/~~x1=/io.github.machetso.mediabackup-Ab9_=/base.apk\n"
        src, run = self.source(out, B)
        with mock.patch("phonebackup.sources._run", run):
            self.assertFalse(src.companion_signer_matches(A))
        src, run = self.source(out, A)
        with mock.patch("phonebackup.sources._run", run):
            self.assertTrue(src.companion_signer_matches(A))

    def test_odd_paths_are_never_read(self):
        for out in ("package:/sdcard/base.apk", "package:/data/app/../../etc/base.apk",
                    "package:/data/app/x/base.apk; rm -rf /", ""):
            src, run = self.source(out, A)
            called = []
            with mock.patch("phonebackup.sources._run", lambda a, timeout=0: called.append(a)):
                self.assertIsNone(src.companion_signer_matches(A))
            self.assertEqual(called, [])

    def test_guard(self):
        phoneguard.check_companion_apk("/data/app/~~a/com.x-1/base.apk")
        with self.assertRaises(phoneguard.ForbiddenPhoneCommand):
            phoneguard.check_companion_apk("/data/data/com.x/base.apk")


if __name__ == "__main__":
    unittest.main()
