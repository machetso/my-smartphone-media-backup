"""Google Drive mirror export against an in-memory fake of the Drive v3 API."""

import hashlib
import json
from datetime import datetime, timezone
import re
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.parse
from pathlib import Path

from phonebackup import gdrive


class FakeDrive:
    def __init__(self, quota_limit=None, corrupt=False):
        self.files = {}          # id -> dict(name, mimeType, parents, data)
        self.sessions = {}
        self.n = 0
        self.limit = quota_limit
        self.corrupt = corrupt
        self.lock = threading.Lock()
        self.uploads = 0
        self.copies = 0
        self.shortcuts = 0
        self.moves = 0
        self.t = 1_800_000_000.0             # fake clock for createdTime / modifiedTime

    def clock(self):
        self.t += 1
        return datetime.fromtimestamp(self.t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _id(self):
        self.n += 1
        return f"id{self.n}"

    def __call__(self, method, url, headers, body):
        with self.lock:                     # the export uploads several files at once
            return self._call(method, url, headers, body)

    def _call(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path
        if path.endswith("/about"):
            usage = sum(len(f.get("data", b"")) for f in self.files.values())
            q = {"usage": str(usage)}
            if self.limit is not None:
                q["limit"] = str(self.limit)
            return 200, {}, json.dumps({"user": {"emailAddress": "me@example.com"},
                                        "storageQuota": q}).encode()
        if path == "/drive/v3/files" and method == "GET":
            q = qs.get("q", "")
            out = []
            for fid, f in self.files.items():
                m = re.search(r"name = '([^']*)'", q)
                if m and f["name"] != m.group(1):
                    continue
                m = re.search(r"'([^']*)' in parents", q)
                if m and m.group(1) not in f["parents"]:
                    continue
                if "mimeType = 'application/vnd.google-apps.folder'" in q and f["mimeType"] != gdrive.FOLDER_MIME:
                    continue
                m = re.search(r"appProperties has \{ key='([^']*)' and value='([^']*)' \}", q)
                if m and f.get("appProperties", {}).get(m.group(1)) != m.group(2):
                    continue
                d = {"id": fid, "name": f["name"], "mimeType": f["mimeType"], "parents": f["parents"]}
                for k in ("appProperties", "createdTime", "modifiedTime"):
                    if k in f:
                        d[k] = f[k]
                if "target" in f:
                    d["shortcutDetails"] = {"targetId": f["target"]}
                if "data" in f:
                    d["size"] = str(len(f["data"]))
                    d["sha256Checksum"] = hashlib.sha256(f["data"]).hexdigest()
                out.append(d)
            return 200, {}, json.dumps({"files": out}).encode()
        if path == "/drive/v3/files" and method == "POST":
            meta = json.loads(body)
            fid = self._id()
            self.files[fid] = {"name": meta["name"], "mimeType": meta["mimeType"],
                               "parents": meta.get("parents", ["root"])}
            if "appProperties" in meta:
                now = self.clock()
                self.files[fid].update(appProperties=dict(meta["appProperties"]),
                                       createdTime=now, modifiedTime=now)
            if meta["mimeType"] == gdrive.SHORTCUT_MIME:
                self.files[fid]["target"] = meta["shortcutDetails"]["targetId"]
                self.shortcuts += 1
            return 200, {}, json.dumps({"id": fid}).encode()
        if path == "/upload/drive/v3/files" and method == "POST":
            sid = f"https://upload.example/session/{len(self.sessions)}"
            self.sessions[sid] = {"meta": json.loads(body), "data": b"",
                                  "size": int(headers["X-Upload-Content-Length"])}
            return 200, {"Location": sid}, b""
        if method == "PUT":
            key = url.split("?")[0]
            s = self.sessions[key]
            s["data"] += body or b""
            if len(s["data"]) < s["size"]:
                return 308, {}, b""
            fid = self._id()
            self.uploads += 1
            data = s["data"] + (b"x" if self.corrupt else b"")
            self.files[fid] = {"name": s["meta"]["name"], "mimeType": "image/jpeg",
                               "parents": s["meta"]["parents"], "data": data}
            return 200, {}, json.dumps({"id": fid, "size": str(len(data)),
                                        "sha256Checksum": hashlib.sha256(data).hexdigest()}).encode()
        m = re.fullmatch(r"/drive/v3/files/([^/]+)/copy", path)
        if m and method == "POST":
            src = self.files[m.group(1)]
            meta = json.loads(body)
            fid = self._id()
            self.files[fid] = {"name": meta["name"], "mimeType": src["mimeType"],
                               "parents": meta["parents"], "data": src["data"]}
            self.copies += 1
            return 200, {}, json.dumps({"id": fid, "sha256Checksum":
                                        hashlib.sha256(src["data"]).hexdigest()}).encode()
        m = re.fullmatch(r"/drive/v3/files/([^/]+)", path)
        if m and method == "GET" and qs.get("alt") == "media":
            data = self.files[m.group(1)]["data"]
            rng = headers.get("Range")
            if rng:
                a, b = map(int, rng.split("=")[1].split("-"))
                return 206, {}, data[a:b + 1]
            return 200, {}, data
        if m and method == "PATCH" and "addParents" not in qs:   # metadata update (lock heartbeat)
            f = self.files[m.group(1)]
            f.setdefault("appProperties", {}).update(json.loads(body).get("appProperties", {}))
            f["modifiedTime"] = self.clock()
            return 200, {}, json.dumps({"id": m.group(1)}).encode()
        if m and method == "PATCH":
            f = self.files[m.group(1)]
            assert f["parents"] == [qs["removeParents"]], "moved from the wrong folder"
            f["parents"] = [qs["addParents"]]
            self.moves += 1
            return 200, {}, json.dumps({"id": m.group(1)}).encode()
        if m and method == "DELETE":
            gone = {m.group(1)}
            while True:
                more = {k for k, f in self.files.items() if f["parents"][0] in gone} - gone
                if not more:
                    break
                gone |= more
            for k in gone:
                self.files.pop(k, None)
            return 204, {}, b""
        if method == "DELETE":
            return 204, {}, b""
        return 404, {}, b"unknown " + url.encode()

    def paths(self):
        def rel(f):
            parts = [f["name"]]
            p = f["parents"][0]
            while p in self.files:
                parts.append(self.files[p]["name"])
                p = self.files[p]["parents"][0]
            return "/".join(reversed(parts))
        return {rel(f): f["data"] for f in self.files.values() if "data" in f}

    def links(self):
        """Path of every shortcut -> path of its target."""
        def rel(f):
            parts = [f["name"]]
            p = f["parents"][0]
            while p in self.files:
                parts.append(self.files[p]["name"])
                p = self.files[p]["parents"][0]
            return "/".join(reversed(parts))
        return {rel(f): rel(self.files[f["target"]]) for f in self.files.values()
                if "target" in f and f["target"] in self.files}


def make_backup(base):
    parent = Path(base) / "Pixel 10 Pro - Sam"
    files = {"2026/01.January-photos/PXL_1.jpg": b"a" * 1000,
             "2026/01.January-videos/PXL_2.mp4": b"b" * (gdrive.CHUNK + 5),
             "2025/raw/12.December-raw/PXL_3.dng": b"c" * 10}
    for rel, data in files.items():
        p = parent / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return parent, files


class GDriveExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent, self.data = make_backup(self.tmp.name)
        self.reports = Path(self.tmp.name) / "reports"

    def tearDown(self):
        self.tmp.cleanup()

    def run_export(self, fake):
        d = gdrive.Drive({}, transport=fake)
        return gdrive.perform_drive_export(self.parent, {}, cancel=threading.Event(), drive=d,
                                           report_dir=self.reports)

    def test_mirror_then_only_new(self):
        fake = FakeDrive()
        status, paths, verdict = self.run_export(fake)
        self.assertEqual(status, "COMPLETED")
        self.assertTrue(verdict.startswith("EVERYTHING"), verdict)
        prefix = f"{gdrive.ROOT_NAME}/Pixel 10 Pro - Sam/"
        on_drive = fake.paths()
        for rel, data in self.data.items():
            self.assertEqual(on_drive[prefix + rel], data)
        self.assertTrue(any(k.startswith(prefix + gdrive.REPORTS_FOLDER + "/") for k in on_drive))

        # second run: nothing new → nothing uploaded, no duplicate folders
        n_before = len(fake.files)
        (self.parent / "2026/02.February-photos").mkdir(parents=True)
        (self.parent / "2026/02.February-photos/new.jpg").write_bytes(b"new")
        status, _, verdict = self.run_export(fake)
        self.assertEqual(status, "COMPLETED")
        self.assertIn("1 files", verdict)
        added = len(fake.files) - n_before
        self.assertEqual(added, 2 + 3)       # folder + file, plus 3 report files
        folders = [f for f in fake.files.values() if f["mimeType"] == gdrive.FOLDER_MIME]
        names = [(f["name"], f["parents"][0]) for f in folders]
        self.assertEqual(len(names), len(set(names)), "a folder was created twice")

    def test_conflict_not_overwritten(self):
        fake = FakeDrive()
        self.run_export(fake)
        (self.parent / "2026/01.January-photos/PXL_1.jpg").write_bytes(b"other content")
        status, _, verdict = self.run_export(fake)
        self.assertTrue(verdict.startswith("ATTENTION"))
        self.assertEqual(fake.paths()[f"{gdrive.ROOT_NAME}/Pixel 10 Pro - Sam/2026/01.January-photos/PXL_1.jpg"],
                         b"a" * 1000)

    def test_checksum_mismatch_is_error(self):
        status, _, verdict = self.run_export(FakeDrive(corrupt=True))
        self.assertEqual(status, "COMPLETED WITH ERRORS")

    def test_not_enough_space(self):
        with self.assertRaises(gdrive.DriveError):
            self.run_export(FakeDrive(quota_limit=100))



class DriveLockTest(unittest.TestCase):
    """One writer per Google Drive: a second computer/window is refused, not mixed in."""

    def setUp(self):
        self.fake = FakeDrive()
        self.a = gdrive.Drive({}, transport=self.fake)
        self.b = gdrive.Drive({}, transport=self.fake)
        self.root = self.a.find_or_create_folder(gdrive.ROOT_NAME, None, app_key="root")

    def markers(self):
        return [f for f in self.fake.files.values() if "appProperties" in f
                and f["appProperties"].get(gdrive.LOCK_PROP) == "1"]

    def test_second_writer_is_refused_and_leaves_nothing(self):
        self.a.hold_lock(self.root)
        with self.assertRaises(gdrive.DriveBusy):
            self.b.hold_lock(self.root)
        self.assertEqual(len(self.markers()), 1)
        self.a.release_lock()
        self.assertEqual(self.markers(), [])
        self.b.hold_lock(self.root)                     # free again
        self.b.release_lock()

    def test_reentrant_in_one_client(self):
        self.a.hold_lock(self.root)
        self.a.hold_lock(self.root)
        self.a.release_lock()
        self.assertEqual(len(self.markers()), 1)
        self.a.release_lock()
        self.assertEqual(self.markers(), [])

    def test_left_over_marker_of_a_crash_is_ignored(self):
        self.a.hold_lock(self.root)
        self.a._writer._stop.set()                      # "crash": no more heartbeats, no release
        self.a._writer = None
        self.fake.t += gdrive.LOCK_STALE + 60
        with mock.patch.object(time, "time", lambda: self.fake.t + 1):
            self.b.hold_lock(self.root)
        self.assertEqual(len(self.markers()), 1)
        self.b.release_lock()

    def test_parallel_exports_one_wins(self):
        src = Path(tempfile.mkdtemp()) / "Pixel - Me"
        (src / "Camera").mkdir(parents=True)
        (src / "Camera" / "a.jpg").write_bytes(b"a" * 10)
        self.addCleanup(shutil.rmtree, src.parent, ignore_errors=True)
        self.a.hold_lock(self.root)                     # e.g. the other computer is uploading
        with self.assertRaises(gdrive.DriveBusy):
            gdrive.perform_drive_export(src, {}, drive=self.b, report_dir=src.parent / "r")
        self.a.release_lock()


if __name__ == "__main__":
    unittest.main()
