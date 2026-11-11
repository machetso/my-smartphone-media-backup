"""Connect without a cable: the QR code; the phone app over Bluetooth (user request 2026-11-10)."""
import json
import time
import importlib.util
import unittest
import urllib.parse
import urllib.request
from unittest import mock

from phonebackup import wake

PHONES = [{"phone_id": "a", "secret": "11" * 32, "paired": "2026-11-01 10:00", "fingerprint": "f"},
          {"phone_id": "b", "secret": "22" * 32, "paired": "2026-11-07 10:00", "fingerprint": "f"}]


class WakeTest(unittest.TestCase):
    def test_link(self):
        url = wake.connect_link("pc-1", "192.168.1.5:4000", PHONES, "ab" * 8, 1234)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertTrue(url.startswith("phonebackup://connect?"))
        self.assertEqual(q["a"], ["192.168.1.5:4000"])
        self.assertEqual(q["t"][0].split("."), [wake.connect_token(p["secret"], "ab" * 8, 1234) for p in PHONES])
        self.assertNotIn(PHONES[0]["secret"], url)

    def test_here_once_and_only_from_the_phone(self):
        cfg = {"companion_phones": PHONES}
        got = []
        srv = wake.ConnectServer(cfg, lambda e, a: got.append((e["phone_id"], a)), ip="127.0.0.1").start()
        try:
            url = f"http://{srv.address}/here"

            def post(body):
                req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
                try:
                    return urllib.request.urlopen(req, timeout=5).status
                except urllib.error.HTTPError as e:
                    return e.code

            good = {"n": srv.nonce, "port": 47823,
                    "proof": wake.here_proof(PHONES[1]["secret"], srv.nonce, "127.0.0.1:47823")}
            self.assertEqual(post(dict(good, proof="00" * 16)), 403)          # wrong secret
            self.assertEqual(post(dict(good, n="ff" * 8)), 403)              # other QR code
            self.assertEqual(post(dict(good, port=47824)), 403)             # proof for another port
            self.assertEqual(post(good), 200)
            self.assertEqual(got, [("b", "127.0.0.1:47823")])
            self.assertEqual(post(good), 403)                                # only once
            with mock.patch.object(time, "time", return_value=srv.expiry + 1):
                srv.used = False
                self.assertEqual(srv.check(good, "127.0.0.1"), (None, None))  # expired
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()


class PhoneAppInstallTest(unittest.TestCase):
    def test_bluetooth_sends_only_the_bundled_app(self):
        import tempfile
        from pathlib import Path
        from phonebackup import btsend
        with tempfile.TemporaryDirectory() as d:
            other = Path(d) / "evil.apk"
            other.write_bytes(b"x")
            with self.assertRaises(btsend.BtSendError):
                btsend.send_apk("00:11:22:33:44:55", other, "0.7.0")

    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 not installed")
    def test_reinstall_question_and_versions(self):
        from phonebackup import companion
        from phonebackup.gui_backups import _older
        title, text, details = companion.install_question("reinstall", "Pixel", "X1", "0.7.0", 2_000_000)
        self.assertIn("again", title)
        self.assertIn("back up without the app", details)
        self.assertTrue(_older("0.6.0", "0.7.0"))
        self.assertFalse(_older("0.7.0", "0.7.0"))
        self.assertTrue(_older("0.9.0", "0.10.0"))


class FileTransferAppCopyTest(unittest.TestCase):
    def test_put_file_into_download(self):
        import tempfile
        from pathlib import Path
        from phonebackup.sources import FolderSource
        with tempfile.TemporaryDirectory() as phone, tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "MediaBackup.apk"
            apk.write_bytes(b"apk")
            src = FolderSource(phone, kind="MTP (fallback)")
            self.assertEqual(src.put_file(apk, "Download", "My-Media-Backup-0.7.0.apk"),
                             "Download/My-Media-Backup-0.7.0.apk")
            self.assertEqual((Path(phone) / "Download" / "My-Media-Backup-0.7.0.apk").read_bytes(), b"apk")
