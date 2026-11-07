"""Download Google's official Android SDK Platform-Tools (adb) for this computer.

The platform-tools are not shipped with the app (Google's licence does not allow passing them
on). Instead they are fetched directly from Google on request and unpacked into the app's own
data folder, where find_adb() finds them:

    Linux:   ~/.local/share/phonebackup/platform-tools/adb
    Windows: %LOCALAPPDATA%\\phonebackup\\platform-tools\\adb.exe
    macOS:   ~/Library/Application Support/phonebackup/platform-tools/adb

Which file: Google's SDK repository manifest (the list Android Studio's SDK manager uses) names
the current STABLE platform-tools zip for each system with its size and SHA-1. Exactly that file
is downloaded and checked against both before anything is unpacked.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import ui
from .i18n import tr

REPO_BASE = "https://dl.google.com/android/repository/"
MANIFEST_URL = REPO_BASE + "repository2-3.xml"
MANIFEST_MAX = 20 * 1024 * 1024
HOST_OS = {"linux": "linux", "darwin": "macosx", "windows": "windows"}
LICENSE_URL = "https://developer.android.com/tools/releases/platform-tools"
MAX_SIZE = 200 * 1024 * 1024          # the zip is ~7-15 MB; anything huge is not what we expect


def platform_name():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def data_dir():
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "phonebackup"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def stable_archive(manifest, platform=None):
    """(file name, size, sha1, version) of the newest STABLE platform-tools zip for this system,
    from Google's repository manifest (bytes). Raises ValueError if it is not in there."""
    host = HOST_OS[platform or platform_name()]
    root = ET.fromstring(manifest)
    stable = {c.get("id") for c in root.iter() if _local(c.tag) == "channel" and (c.text or "").strip() == "stable"}
    best = None
    for pkg in root.iter():
        if _local(pkg.tag) != "remotePackage" or pkg.get("path") != "platform-tools":
            continue
        ch = next((e.get("ref") for e in pkg if _local(e.tag) == "channelRef"), "channel-0")
        if ch not in (stable or {"channel-0"}):
            continue
        rev = next((e for e in pkg if _local(e.tag) == "revision"), None)
        if rev is None:
            continue
        nums = {_local(e.tag): int(e.text or 0) for e in rev if (e.text or "").strip().isdigit()}
        version = (nums.get("major", 0), nums.get("minor", 0), nums.get("micro", 0))
        for arc in (e for e in pkg.iter() if _local(e.tag) == "archive"):
            hos = next((e.text for e in arc.iter() if _local(e.tag) == "host-os"), None)
            comp = next((e for e in arc if _local(e.tag) == "complete"), None)
            if hos != host or comp is None:
                continue
            f = {_local(e.tag): e for e in comp}
            if not {"url", "size", "checksum"} <= f.keys() or f["checksum"].get("type") != "sha1":
                continue
            name = (f["url"].text or "").strip()
            sha1 = (f["checksum"].text or "").strip().lower()
            if "/" in name or not name.endswith(".zip") or len(sha1) != 40:
                continue
            if best is None or version > best[3]:
                best = (name, int(f["size"].text), sha1, version)
    if best is None:
        raise ValueError(tr("the platform-tools for this computer are not in Google's list"))
    return best


def _fetch(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": "my-smartphone-media-backup"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(tr("download is larger than expected - stopped"))
    return data


def adb_exe_name():
    return "adb.exe" if sys.platform.startswith("win") else "adb"


def installed_adb():
    """Path of a previously downloaded adb, or None."""
    p = data_dir() / "platform-tools" / adb_exe_name()
    return str(p) if p.is_file() else None


def adb_version(adb):
    """First line of 'adb version' (e.g. 'Android Debug Bridge version 1.0.41'), '' if it fails."""
    try:
        out = subprocess.run([adb, "version"], capture_output=True, timeout=20,
                             creationflags=0x08000000 if sys.platform.startswith("win") else 0)
        return out.stdout.decode("utf-8", "replace").strip().splitlines()[0] if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _safe_extract(zf, target):
    """Extract only platform-tools/..., refusing absolute paths and '..' (zip-slip)."""
    target = Path(target).resolve()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if not name.startswith("platform-tools/"):
            continue
        dest = (target / name).resolve()
        if target not in dest.parents and dest != target:
            raise ValueError(tr("unsafe path in the download: %s", info.filename))
        if name.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        mode = (info.external_attr >> 16) & 0o755        # never group/world-writable
        if mode and not sys.platform.startswith("win"):
            os.chmod(dest, mode)


def download_adb(cancel=None, url=None, expect=None):
    """Download + unpack the platform-tools. Returns (adb path, version text). Raises on error.
    expect = (size, sha1) the zip must have; without url both come from Google's manifest."""
    if url is None:
        ui.info(tr("Asking Google for the current platform-tools …"))
        name, size, sha1, _v = stable_archive(_fetch(MANIFEST_URL, MANIFEST_MAX))
        url, expect = REPO_BASE + name, (size, sha1)
    final = data_dir() / "platform-tools"
    final.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="adb-download-", dir=final.parent))
    try:
        zpath = work / "platform-tools.zip"
        ui.info(tr("Downloading the Android platform-tools from Google:") + f"\n  {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "my-smartphone-media-backup"})
        digest = hashlib.sha1()           # Google's manifest gives SHA-1 (+ size) – both are checked
        with urllib.request.urlopen(req, timeout=60) as resp, open(zpath, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_SIZE:
                raise ValueError(tr("unexpected download size (%s)", ui.human_size(total)))
            prog = ui.Progress(1, total)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise RuntimeError(tr("Download cancelled."))
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > MAX_SIZE:
                    raise ValueError(tr("download is larger than expected - stopped"))
                prog.update(add_bytes=len(chunk), current="platform-tools.zip")
            prog.update(files_done=1, force=True)
            prog.finish()
        if total and done != total:
            raise OSError(tr("incomplete download (%d of %d bytes)", done, total))
        if expect is not None and (done != expect[0] or digest.hexdigest() != expect[1]):
            raise ValueError(tr("the download does not match Google's checksum - not used"))
        if not zipfile.is_zipfile(zpath):
            raise ValueError(tr("the download is not a zip file"))
        unpack = work / "unpacked"
        with zipfile.ZipFile(zpath) as zf:
            _safe_extract(zf, unpack)
        adb = unpack / "platform-tools" / adb_exe_name()
        if not adb.is_file():
            raise ValueError(tr("%s was not found in the download", "adb"))
        version = adb_version(str(adb))
        if not version:
            raise RuntimeError(tr("the downloaded %s does not start on this computer", "adb"))
        # replace an older download only now that the new one works
        old = None
        if final.exists():
            prev = final / adb_exe_name()
            if prev.is_file():          # a running adb server would lock the old files (Windows)
                try:
                    subprocess.run([str(prev), "kill-server"], capture_output=True, timeout=20,
                                   creationflags=0x08000000 if sys.platform.startswith("win") else 0)
                except (OSError, subprocess.SubprocessError):
                    pass
            old = final.with_name(f"platform-tools.old-{os.getpid()}")
            os.replace(final, old)
        os.replace(unpack / "platform-tools", final)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
        path = str(final / adb_exe_name())
        ui.ok(tr("ADB installed: %s", path) + f"\n  {version}")
        return path, version
    finally:
        shutil.rmtree(work, ignore_errors=True)
