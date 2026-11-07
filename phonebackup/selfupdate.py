"""One-click update of the ready-made program (Windows .exe / Linux binary) – user request 2026-11-07.

Only after the user clicked "Update now":
1. Read update-manifest.json + its signature from the newest GitHub release and check the
   signature with the project's release key (PUBLIC_KEY, Ed25519). The private key is NOT on
   GitHub (tools/sign_release.py) - a taken-over GitHub account cannot push an update.
2. The manifest must be for this program and a NEWER version (no downgrade to an old, signed but
   vulnerable version). Download the file for this system; size and SHA-256 must match it.
3. Put the new program next to the running one, keep the old one as "<name>.previous", start the
   new one and wait until it reports that its window is open. If it does not (crash, blocked by
   an antivirus program …) the old version is put back and started again.

Running from the source code (python …) is not updated this way – there git is the tool.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from . import __version__, ed25519
from .i18n import tr
from .updatecheck import API_URL, REPO, is_newer, parse_version

PUBLIC_KEY = "bb64e8fac9682ee5d3a5938b2899222bfbbbdbeae4d4c92d8d319621f44dc360"
MANIFEST = "update-manifest.json"
SIGNATURE = MANIFEST + ".sig"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
MAX_PROGRAM = 400 * 1024 * 1024
MARKER_ENV = "PHONEBACKUP_UPDATE_MARKER"      # the new program writes this file once it runs
FAILED_ENV = "PHONEBACKUP_UPDATE_FAILED"      # set when the old version had to be restored
START_TIMEOUT = 120                            # seconds the new version gets to open its window


class UpdateError(Exception):
    pass


def system():
    """'windows' / 'linux' when this system has a ready-made build, else None."""
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return None
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def program():
    """Path of the running ready-made program when it can update itself, else None
    (source code, other system, folder not writable)."""
    if not getattr(sys, "frozen", False) or system() is None:
        return None
    exe = Path(sys.executable).resolve()
    return exe if os.access(exe.parent, os.W_OK) else None


def asset_name(version, sysname=None):
    sysname = sysname or system()
    if sysname == "windows":
        return f"My-Smartphone-Media-Backup-v{version}-windows-x64.exe"
    return f"my-smartphone-media-backup-v{version}-linux-x86_64.tar.gz"


def _get(url, limit, fetch=None):
    if fetch:
        data = fetch(url)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "my-smartphone-media-backup"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError(tr("unexpected download size"))
    return data


def _download(url, dest, size, sha256, on_bytes=None, cancel=None, opener=None):
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(url, headers={"User-Agent": "my-smartphone-media-backup"})
    with (opener or urllib.request.urlopen)(req, timeout=60) as r, open(dest, "wb") as out:
        while True:
            if cancel is not None and cancel.is_set():
                raise UpdateError(tr("Update cancelled."))
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > size:
                raise UpdateError(tr("the download is larger than announced – not used"))
            h.update(chunk)
            out.write(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    if done != size or h.hexdigest() != sha256:
        raise UpdateError(tr("the download does not match the signed list – not used"))


def verified_manifest(release, fetch=None):
    """The signed manifest of a GitHub release (API answer) after all checks → (version, files)."""
    urls = {}
    for a in release.get("assets") or []:
        url = str(a.get("browser_download_url", ""))
        if url.startswith(DOWNLOAD_PREFIX):
            urls[str(a.get("name"))] = url
    if MANIFEST not in urls or SIGNATURE not in urls:
        raise UpdateError(tr("this release has no signed update list – please update by hand"))
    data = _get(urls[MANIFEST], 256 * 1024, fetch)
    try:
        sig = bytes.fromhex(_get(urls[SIGNATURE], 1024, fetch).decode().strip())
    except ValueError:
        sig = b""
    if not ed25519.verify(bytes.fromhex(PUBLIC_KEY), data, sig):
        raise UpdateError(tr("the update is NOT signed with the project's key – not installed"))
    m = json.loads(data)
    version = str(m.get("version", ""))
    tag = str(release.get("tag_name", "")).lstrip("v")
    if m.get("app") != REPO or not parse_version(version) or version != tag:
        raise UpdateError(tr("the signed update list does not fit this release – not installed"))
    if not is_newer(version, __version__):
        raise UpdateError(tr("the update is not newer than this version – not installed"))
    return version, m.get("files") or {}, urls


def latest_release(fetch=None):
    return json.loads(_get(API_URL, 1024 * 1024, fetch))


def prepare(exe, on_bytes=None, cancel=None, release=None, fetch=None, opener=None, on_size=None):
    """Download + verify the newest version for this system and put it next to `exe`
    (not yet in its place). Returns (version, staged file)."""
    exe = Path(exe)
    release = release or latest_release(fetch)
    version, files, urls = verified_manifest(release, fetch)
    name = asset_name(version)
    info = files.get(name)
    if not info or name not in urls or not 0 < int(info.get("size", 0)) <= MAX_PROGRAM:
        raise UpdateError(tr("no update file for this system in the release"))
    part = exe.with_name(f".{exe.name}.download")
    staged = exe.with_name(f".{exe.name}.new")
    for p in (part, staged):
        p.unlink(missing_ok=True)
    if on_size:
        on_size(int(info["size"]))
    try:
        _download(urls[name], part, int(info["size"]), str(info["sha256"]), on_bytes, cancel, opener)
        if system() == "windows":
            os.replace(part, staged)
        else:                                       # the program inside the .tar.gz
            member = f"{name[:-len('.tar.gz')]}/my-smartphone-media-backup"
            with tarfile.open(part, "r:gz") as tf:
                ti = tf.getmember(member)
                if not ti.isfile() or ti.size > MAX_PROGRAM:
                    raise UpdateError(tr("unexpected content in the update file"))
                with tf.extractfile(ti) as src, open(staged, "wb") as out:
                    while True:
                        b = src.read(1024 * 1024)
                        if not b:
                            break
                        out.write(b)
            os.chmod(staged, 0o755)
    except (KeyError, tarfile.TarError) as e:
        staged.unlink(missing_ok=True)
        raise UpdateError(tr("unexpected content in the update file")) from e
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    finally:
        part.unlink(missing_ok=True)
    return version, staged


def previous_of(exe):
    return Path(exe).with_name(Path(exe).name + ".previous")


def install(exe, staged):
    """New program into place; the old one stays as <name>.previous (a running program may be
    renamed on Windows too, just not overwritten)."""
    exe, prev = Path(exe), previous_of(exe)
    try:
        prev.unlink(missing_ok=True)
    except OSError:
        prev = exe.with_name(f"{exe.name}.previous-{int(time.time())}")
    os.replace(exe, prev)
    try:
        os.replace(staged, exe)
    except OSError:
        os.replace(prev, exe)                       # put the old one back right away
        raise
    return prev


def rollback(exe, prev):
    exe = Path(exe)
    try:
        exe.unlink(missing_ok=True)
    except OSError:
        os.replace(exe, exe.with_name(f".{exe.name}.failed-{int(time.time())}"))
    os.replace(prev, exe)


def start(exe, extra_env=None):
    """Start the program as a fresh, independent process."""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # a new onefile instance, not a child of this one
    for k in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL"):
        env.pop(k, None)
    env.pop(MARKER_ENV, None)
    env.pop(FAILED_ENV, None)
    env.update(extra_env or {})
    kw = {"cwd": str(Path(exe).parent), "env": env, "stdin": subprocess.DEVNULL,
          "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x00000008 | 0x00000200        # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen([str(exe)], **kw)


def wait_started(proc, marker, timeout=START_TIMEOUT, sleep=time.sleep):
    """True once the new program wrote `marker`; False if it ended or took too long."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(marker).exists():
            return True
        if proc.poll() is not None:
            return False
        sleep(0.3)
    return False


def report_started():
    """Called by the NEW program once its window is open."""
    marker = os.environ.pop(MARKER_ENV, "")
    if marker:
        try:
            Path(marker).write_text("ok")
        except OSError:
            pass


def clean_previous():
    """At start: remove the kept old version of an update that worked (silently retried)."""
    exe = program()
    if exe is None or os.environ.get(MARKER_ENV):
        return
    for p in exe.parent.glob(exe.name + ".previous*"):
        try:
            p.unlink()
        except OSError:
            pass
