"""Download Google's official Android SDK Platform-Tools (adb) for this computer.

The platform-tools are not shipped with the app (Google's licence does not allow passing them
on). Instead they are fetched directly from Google on request and unpacked into the app's own
data folder, where find_adb() finds them:

    Linux:   ~/.local/share/phonebackup/platform-tools/adb
    Windows: %LOCALAPPDATA%\\phonebackup\\platform-tools\\adb.exe
    macOS:   ~/Library/Application Support/phonebackup/platform-tools/adb
"""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from . import ui

BASE_URL = "https://dl.google.com/android/repository/platform-tools-latest-{}.zip"
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
            raise ValueError(f"unsafe path in the download: {info.filename}")
        if name.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        mode = (info.external_attr >> 16) & 0o755        # never group/world-writable
        if mode and not sys.platform.startswith("win"):
            os.chmod(dest, mode)


def download_adb(cancel=None, url=None):
    """Download + unpack the platform-tools. Returns (adb path, version text). Raises on error."""
    url = url or BASE_URL.format(platform_name())
    final = data_dir() / "platform-tools"
    final.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="adb-download-", dir=final.parent))
    try:
        zpath = work / "platform-tools.zip"
        ui.info(f"Downloading the Android platform-tools from Google:\n  {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "my-smartphone-media-backup"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(zpath, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_SIZE:
                raise ValueError(f"unexpected download size ({ui.human_size(total)})")
            prog = ui.Progress(1, total)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise RuntimeError("Download cancelled.")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if done > MAX_SIZE:
                    raise ValueError("download is larger than expected - stopped")
                prog.update(add_bytes=len(chunk), current="platform-tools.zip")
            prog.update(files_done=1, force=True)
            prog.finish()
        if total and done != total:
            raise OSError(f"incomplete download ({done} of {total} bytes)")
        if not zipfile.is_zipfile(zpath):
            raise ValueError("the download is not a zip file")
        unpack = work / "unpacked"
        with zipfile.ZipFile(zpath) as zf:
            _safe_extract(zf, unpack)
        adb = unpack / "platform-tools" / adb_exe_name()
        if not adb.is_file():
            raise ValueError("adb was not found in the download")
        version = adb_version(str(adb))
        if not version:
            raise RuntimeError("the downloaded adb does not start on this computer")
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
        ui.ok(f"ADB installed: {path}\n  {version}")
        return path, version
    finally:
        shutil.rmtree(work, ignore_errors=True)
