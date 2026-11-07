"""One-click update: only a correctly signed, newer, matching update is installed; a new
version that does not start is rolled back. Offline – fake GitHub, throw-away folders."""

import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phonebackup import ed25519, selfupdate as su
from phonebackup.updatecheck import REPO

SECRET = bytes(range(32))                               # test key, NOT the release key
PUB = ed25519.public_key(SECRET).hex()
DL = su.DOWNLOAD_PREFIX + "v99.0.0/"


class FakeGitHub:
    """Release v99.0.0 with a program file, the manifest and its signature."""

    def __init__(self, program=b"NEW PROGRAM", sysname="linux", version="99.0.0", sign_with=SECRET,
                 tamper=False, app=REPO):
        name = su.asset_name(version, sysname)
        if sysname == "linux":
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                ti = tarfile.TarInfo(f"{name[:-len('.tar.gz')]}/my-smartphone-media-backup")
                ti.size = len(program)
                tf.addfile(ti, io.BytesIO(program))
            payload = buf.getvalue()
        else:
            payload = program
        self.files = {name: payload}
        manifest = json.dumps({"app": app, "version": version, "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}}}).encode()
        sig = ed25519.sign(sign_with, manifest).hex().encode()
        if tamper:
            manifest = manifest.replace(b'"size"', b'"size" ')
        self.files[su.MANIFEST] = manifest
        self.files[su.SIGNATURE] = sig
        self.release = {"tag_name": "v99.0.0",
                        "assets": [{"name": n, "browser_download_url": DL + n} for n in self.files]}

    def fetch(self, url):
        return self.files[url[len(DL):]]

    def opener(self, req, timeout=0):
        return io.BytesIO(self.fetch(req.full_url))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(su, "PUBLIC_KEY", PUB)
        p.start()
        self.addCleanup(p.stop)

    def test_good_release(self):
        gh = FakeGitHub()
        version, files, urls = su.verified_manifest(gh.release, gh.fetch)
        self.assertEqual(version, "99.0.0")
        self.assertIn(su.asset_name("99.0.0", "linux"), files)

    def test_refused(self):
        cases = {
            "other key": FakeGitHub(sign_with=bytes(32)),
            "changed after signing": FakeGitHub(tamper=True),
            "other program": FakeGitHub(app="evil/repo"),
            "older version": FakeGitHub(version="0.0.1"),
        }
        cases["older version"].release["tag_name"] = "v0.0.1"
        for why, gh in cases.items():
            with self.subTest(why), self.assertRaises(su.UpdateError):
                su.verified_manifest(gh.release, gh.fetch)
        gh = FakeGitHub()
        gh.release["tag_name"] = "v99.0.1"                 # manifest of another release
        with self.assertRaises(su.UpdateError):
            su.verified_manifest(gh.release, gh.fetch)
        gh = FakeGitHub()                                  # files from somewhere else are ignored
        for a in gh.release["assets"]:
            a["browser_download_url"] = "https://evil.example/" + a["name"]
        with self.assertRaises(su.UpdateError):
            su.verified_manifest(gh.release, gh.fetch)



class Ed25519Test(unittest.TestCase):
    def test_rfc8032_vectors(self):
        sk = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
        pk = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        sig = bytes.fromhex("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
                            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
        self.assertEqual(ed25519.public_key(sk), pk)
        self.assertEqual(ed25519.sign(sk, b"\x72"), sig)
        self.assertTrue(ed25519.verify(pk, b"\x72", sig))
        self.assertFalse(ed25519.verify(pk, b"\x73", sig))
        self.assertFalse(ed25519.verify(pk, b"\x72", sig[:32] + bytes(32)))
        self.assertFalse(ed25519.verify(pk, b"\x72", b"short"))

    def test_the_release_key_is_a_real_public_key(self):
        self.assertIsNotNone(ed25519._decompress(bytes.fromhex(su.PUBLIC_KEY)))


class PrepareInstallTest(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(su, "PUBLIC_KEY", PUB),):
            p.start()
            self.addCleanup(p.stop)
        self.dir = Path(tempfile.mkdtemp(prefix="pb-selfupdate-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.exe = self.dir / "my-smartphone-media-backup"
        self.exe.write_bytes(b"OLD PROGRAM")

    def prepare(self, gh, sysname="linux"):
        with mock.patch.object(su, "system", lambda: sysname):
            return su.prepare(self.exe, release=gh.release, fetch=gh.fetch, opener=gh.opener)

    def test_linux_and_windows_files(self):
        version, staged = self.prepare(FakeGitHub(b"NEW LINUX"))
        self.assertEqual(staged.read_bytes(), b"NEW LINUX")
        if not sys.platform.startswith("win"):           # Windows has no "executable" bit
            self.assertTrue(os.stat(staged).st_mode & stat.S_IXUSR)
        _v, staged = self.prepare(FakeGitHub(b"NEW WINDOWS", sysname="windows"), "windows")
        self.assertEqual(staged.read_bytes(), b"NEW WINDOWS")
        self.assertEqual(self.exe.read_bytes(), b"OLD PROGRAM")        # not swapped yet

    def test_download_not_matching_the_signed_list(self):
        gh = FakeGitHub()
        name = su.asset_name("99.0.0", "linux")
        gh.files[name] = gh.files[name][:-1] + b"X"                    # swapped on the way
        with self.assertRaises(su.UpdateError):
            self.prepare(gh)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [self.exe.name])

    def test_install_and_rollback(self):
        _v, staged = self.prepare(FakeGitHub(b"NEW"))
        prev = su.install(self.exe, staged)
        self.assertEqual((self.exe.read_bytes(), prev.read_bytes()), (b"NEW", b"OLD PROGRAM"))
        su.rollback(self.exe, prev)
        self.assertEqual(self.exe.read_bytes(), b"OLD PROGRAM")
        self.assertFalse(prev.exists())


@unittest.skipUnless(sys.platform.startswith("linux"), "uses shell scripts as stand-in programs")
class StartTest(unittest.TestCase):
    """The new version must report that it runs; otherwise the old one comes back."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pb-selfupdate-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.marker = self.dir / "ok"

    def script(self, name, body):
        p = self.dir / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)
        return p

    def test_new_version_starts(self):
        exe = self.script("prog", f'[ -n "${su.MARKER_ENV}" ] && echo ok > "${su.MARKER_ENV}"; sleep 1')
        proc = su.start(exe, {su.MARKER_ENV: str(self.marker)})
        self.assertTrue(su.wait_started(proc, self.marker, timeout=10))

    def test_crashing_version_is_noticed(self):
        exe = self.script("prog", "exit 3")
        proc = su.start(exe, {su.MARKER_ENV: str(self.marker)})
        self.assertFalse(su.wait_started(proc, self.marker, timeout=10))
        hanging = su.start(self.script("hang", "sleep 30"), {})
        self.assertFalse(su.wait_started(hanging, self.marker, timeout=1))
        hanging.kill()


if __name__ == "__main__":
    unittest.main()
