"""Security review 2026-11-06: every fix has a test that fails without it."""

import http.client
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest

from phonebackup import setfolders
from pathlib import Path
from unittest import mock

from phonebackup import config, export, gdrive, gdrive_gfs, media, report, safety, wireless
from phonebackup.export import EXPORT_DIR, Catalog
from tests.test_gdrive import FakeDrive, make_backup


class SafetyHelpersTest(unittest.TestCase):
    def test_safe_rel(self):
        for good in ("a.jpg", "2026/26.01/x.jpg", "a b/ü.jpg"):
            self.assertEqual(safety.safe_rel(good), good)
        for bad in ("", "/etc/passwd", "../x", "a/../../x", "a//b", "./a", "a\\b", "C:/x", "c:x",
                    "a\0b", None, 5):
            self.assertIsNone(safety.safe_rel(bad), repr(bad))

    def test_inside_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / "base"
            base.mkdir()
            (base / "link").symlink_to(t)                  # points out of base
            self.assertIsNone(safety.inside(base, "link/evil.txt"))
            self.assertEqual(safety.inside(base, "ok/x.jpg"), base / "ok/x.jpg")

    def test_run_folder_and_component(self):
        self.assertTrue(safety.valid_run_folder("2026-11-05_13-59-03_full"))
        self.assertTrue(safety.valid_run_folder("2026-11-05_13-59-03_incremental_2"))
        for bad in ("x/../.phonebackup", ".phonebackup", "2026-11-05_13-59-03_full/..", "full", ""):
            self.assertFalse(safety.valid_run_folder(bad), bad)
        self.assertIsNone(safety.safe_component("../../home/u"))
        self.assertIsNone(safety.safe_component("a/b"))
        self.assertEqual(safety.safe_component("Pixel 10 Pro - Sam"), "Pixel 10 Pro - Sam")

    def test_csv_formula_injection(self):
        with tempfile.TemporaryDirectory() as t:
            paths = report.write_reports(Path(t), "r", "T", True, "ok", [],
                                         ["Nr", "File"], [[1, '=HYPERLINK("http://x")'], [2, "IMG.jpg"],
                                                          [3, "-2+3"], [4, "@SUM(A1)"]])
            csv_text = next(p for p in paths if p.suffix == ".csv").read_text(encoding="utf-8-sig")
        self.assertIn("'=HYPERLINK", csv_text)
        self.assertIn("'-2+3", csv_text)
        self.assertIn("'@SUM", csv_text)
        self.assertIn("2;IMG.jpg", csv_text)


class TamperedCatalogTest(unittest.TestCase):
    """A catalog on the export drive that someone changed must not write or delete elsewhere."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "backup" / "Sam" / "Pixel"
        f = self.src / "2026" / "26.01" / "a.jpg"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"photo")
        self.target = self.tmp / "second"
        self.target.mkdir()
        status, _, _ = export.perform_export(self.src, self.target, "full", {"fsync": False})
        self.assertEqual(status, "COMPLETED")
        self.parent = self.target / "Sam" / self.src.name
        self.db = self.parent / EXPORT_DIR / "catalog.sqlite"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sql(self, q, *a):
        db = sqlite3.connect(str(self.db))
        db.execute(q, a)
        db.commit()
        db.close()

    def test_restore_refuses_paths_outside(self):
        victim = self.tmp / "victim.txt"
        self.sql("UPDATE files SET rel=?", "../../victim.txt")
        out = self.tmp / "restore"
        status, _, verdict = export.perform_restore(self.parent, 1, out, {"fsync": False})
        self.assertFalse(victim.exists())
        self.assertTrue(verdict.startswith("ATTENTION"), verdict)
        self.sql("UPDATE files SET rel=?", str(self.tmp / "abs.txt"))
        export.perform_restore(self.parent, 1, out, {"fsync": False})
        self.assertFalse((self.tmp / "abs.txt").exists())

    def test_cleanup_refuses_crafted_folder(self):
        internal = self.parent / ".phonebackup"
        internal.mkdir()
        (internal / "index.sqlite").write_bytes(b"x")
        self.sql("UPDATE runs SET folder=?", "x/../.phonebackup")
        with mock.patch.object(export.gfs, "to_retire", lambda runs, keep=None: list(runs)):
            removed, problems = export.remove_runs(self.parent, [1])
        self.assertEqual(removed, [])
        self.assertTrue((internal / "index.sqlite").exists())
        self.assertTrue(problems)


class VerifiedCopyTest(unittest.TestCase):
    def test_never_overwrites_and_never_raises(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            src = t / "IMG.jpg"
            src.write_bytes(b"new")
            dst = t / "out" / "IMG.JPG"
            dst.parent.mkdir()
            dst.write_bytes(b"old")
            st, sha = export._verified_copy(src, t, dst, None, {"fsync": False}, mock.MagicMock())
            self.assertTrue(st.startswith("ERROR"), st)
            self.assertEqual(dst.read_bytes(), b"old")
            blocker = t / "file"
            blocker.write_bytes(b"x")                     # a FILE where a folder is needed
            st, sha = export._verified_copy(src, t, blocker / "sub" / "a.jpg", None, {"fsync": False},
                                            mock.MagicMock())
            self.assertTrue(st.startswith("ERROR"), st)
            self.assertEqual([p.name for p in t.glob("*.part")], [])


class DriveTamperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.parent, _ = make_backup(base)
        self.fake = FakeDrive()
        self.drive = gdrive.Drive({}, transport=self.fake)
        p = mock.patch.object(gdrive_gfs, "local_dir", lambda name: base / "local" / name)
        p.start()
        self.addCleanup(p.stop)
        gdrive_gfs.perform_drive_gfs_export(self.parent, {}, "full", drive=self.drive,
                                            report_dir=base / "r")
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def tamper(self, *sql):
        cat_id = next(i for i, f in self.fake.files.items() if f["name"] == "catalog.sqlite")
        p = self.base / "cat.sqlite"
        p.write_bytes(self.fake.files[cat_id]["data"])
        db = sqlite3.connect(str(p))
        for q in sql:
            db.execute(q)
        db.commit()
        db.close()
        self.fake.files[cat_id]["data"] = p.read_bytes()

    def test_restore_refuses_paths_outside(self):
        self.tamper("UPDATE files SET rel='../../escaped.jpg' WHERE rowid=(SELECT MIN(rowid) FROM files)")
        out = self.base / "restore"
        status, _, verdict = gdrive_gfs.perform_restore(setfolders.rel_of(self.parent), 1, out, {}, drive=self.drive)
        self.assertFalse((self.base / "escaped.jpg").exists())
        self.assertFalse(any(self.base.glob("**/escaped.jpg")))
        self.assertTrue(verdict.startswith("ATTENTION"), verdict)

    def test_catalog_with_trigger_is_refused(self):
        self.tamper("CREATE TRIGGER t AFTER INSERT ON runs BEGIN DELETE FROM files; END")
        with self.assertRaises(gdrive.DriveError):
            gdrive_gfs.runs_of(setfolders.rel_of(self.parent), {}, drive=self.drive)



class DriveFolderNameTest(unittest.TestCase):
    def test_folder_names_from_drive_cannot_leave_the_data_folder(self):
        for bad in ("../../x", "a/../..", ".hidden", "", "Sam/.x", "../Pixel"):
            with self.assertRaises(gdrive.DriveError):
                gdrive_gfs.local_dir(bad)
        self.assertEqual(gdrive_gfs.local_dir("Sam/Pixel").parts[-2:], ("Sam", "Pixel"))


class CraftedMediaTest(unittest.TestCase):
    def test_exif_marker_flood_is_fast(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.heic"
            p.write_bytes(b"Exif\0\0" * (8 * 1024 * 1024 // 6))
            t0 = time.monotonic()
            self.assertIsNone(media._scan_exif(p))
            self.assertLess(time.monotonic() - t0, 2)


class PrivateFilesTest(unittest.TestCase):
    @unittest.skipIf(sys.platform.startswith("win"), "POSIX permissions")
    def test_settings_and_token_are_private_even_with_a_planted_temp_file(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "cfg" / "config.json"
            p.parent.mkdir()
            planted = p.with_suffix(".tmp")
            planted.write_text("x")
            os.chmod(planted, 0o666)
            config.write_private(p, '{"a": 1}')
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(json.loads(p.read_text()), {"a": 1})


class SettingsCopyTest(unittest.TestCase):
    def test_daily_copy_before_overwrite(self):
        p = config.config_path()
        config.save({"destinations": ["/media/x"]})
        config.save({})                                    # e.g. something wipes the settings
        copies = sorted((p.parent / "backups").glob("config-*.json"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(json.loads(copies[0].read_text())["destinations"], ["/media/x"])


class SetupServerTest(unittest.TestCase):
    def setUp(self):
        from phonebackup import companion
        self.got = []
        with mock.patch.object(companion, "local_ips", lambda: ["127.0.0.1"]):
            self.s = companion.SetupServer({}, self.got.append, port=0)
        self.s.start()
        self.addCleanup(self.s.stop)
        self.token = self.s.token

    def post(self, body, length=None):
        c = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=5)
        data = json.dumps(body).encode()
        c.putrequest("POST", "/pair")
        c.putheader("Content-Length", str(len(data) if length is None else length))
        c.endheaders()
        c.send(data)
        r = c.getresponse()
        c.close()
        return r.status

    def test_negative_length_and_second_request(self):
        good = {"token": self.token, "fingerprint": "a" * 64, "port": 47823, "nonce": "ab" * 16}
        self.assertEqual(self.post(good, length=-1), 400)
        with mock.patch.object(type(self.s), "reveal", lambda s, r: None):
            self.assertEqual(self.post(good), 200)
        evil = dict(good, fingerprint="b" * 64)
        self.assertEqual(self.post(evil), 409)          # the shown code is never replaced
        self.assertEqual(len(self.got), 1)

    def test_old_phone_app_without_nonce_is_told_to_update(self):
        self.assertEqual(self.post({"token": self.token, "fingerprint": "a" * 64, "port": 1}), 426)
        self.assertTrue(self.got[0].outdated)
        self.assertEqual(self.got[0].code, "")             # no code shown for it

    def test_bound_to_the_qr_address_only(self):
        self.assertEqual(self.s.httpd.server_address[0], "127.0.0.1")


class HotspotPasswordTest(unittest.TestCase):
    def test_password_never_in_a_command_line(self):
        argvs, stdins = [], []

        class R:
            returncode, stdout, stderr = 0, b"", b""

        def fake_run(args, input=None, **kw):
            argvs.append(list(args))
            stdins.append(input or b"")
            return R()

        with mock.patch.object(wireless.subprocess, "run", fake_run), \
                mock.patch.object(wireless, "_run", lambda a, timeout=0: fake_run(a)), \
                mock.patch.object(wireless.shutil, "which", lambda n: "/usr/bin/nmcli"), \
                mock.patch.object(wireless, "wifi_interface", lambda: "wlan0"), \
                mock.patch.object(wireless.sys, "platform", "linux"):
            ok, _ = wireless.start_hotspot("PhoneBackup-AB12", "s3cretpassw0")
        self.assertTrue(ok)
        self.assertFalse(any("s3cretpassw0" in a for argv in argvs for a in argv))
        self.assertTrue(any(b"psk s3cretpassw0" in i for i in stdins))
        self.assertIn(["nmcli", "connection", "up", wireless.HOTSPOT_CON], argvs)
        with self.assertRaises(ValueError):
            wireless._hotspot_profile("wlan0", "x", "pw\nset ipv4.method auto", "")


class WifiAutoConnectTest(unittest.TestCase):
    def test_only_known_phones(self):
        svc = [wireless.MdnsService("adb-EVIL123-AbCdEf", wireless.CONNECT, "10.0.0.66:5555"),
               wireless.MdnsService("adb-GOOD456-XyZ123", wireless.CONNECT, "10.0.0.7:41111")]
        tried = []
        with mock.patch.object(wireless, "mdns_services", lambda adb: svc), \
                mock.patch.object(wireless, "connect", lambda adb, a: (tried.append(a), (True, ""))[1]):
            self.assertEqual(wireless.auto_connect("adb", "", ["GOOD456"]), "10.0.0.7:41111")
            self.assertNotIn("10.0.0.66:5555", tried)
            tried.clear()
            self.assertEqual(wireless.auto_connect("adb", "", []), "")
            self.assertEqual(tried, [])
        self.assertEqual(wireless.service_serial("adb-5A111FDCH0014T-AbCdEf"), "5A111FDCH0014T")


if __name__ == "__main__":
    unittest.main()
