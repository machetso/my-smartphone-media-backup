"""Where the files come from.

1. AdbSource          - preferred: fast, available ~1-2 s after plugging in, hashes on the phone.
2. Fallback (MTP):
   - Linux:   GvfsSource (phone mounted by GNOME/gvfs, mounted automatically via `gio`)
   - Windows: WindowsMtpSource (Explorer shell via pywin32)
3. FolderSource       - any folder you type in (card reader, manual mount, test data).
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import phoneguard, ui
from .copier import CHUNK, file_chunks, sha256_file

PHONE_ROOT = "/sdcard"
_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW


@dataclass
class SourceFile:
    rel: str        # path relative to the phone storage root, e.g. "DCIM/Camera/PXL_2026.jpg"
    size: int
    mtime: int
    key: str = ""   # unique id in the backup database (imports: "import:<folder>/<rel>")

    @property
    def source_key(self):
        return self.key or self.rel

    @property
    def name(self):
        return PurePosixPath(self.rel).name


def _hidden(rel):
    return any(part.startswith(".") for part in PurePosixPath(rel).parts)


def _q(s):
    """Quote for the phone's shell."""
    return "'" + s.replace("'", "'\\''") + "'"


# =========================================================================== ADB

def find_adb(cfg):
    exe = "adb.exe" if sys.platform.startswith("win") else "adb"
    if getattr(sys, "frozen", False):       # packaged program: look next to the .exe / binary
        here = Path(sys.executable).resolve().parent
    else:
        here = Path(__file__).resolve().parent.parent
    from .adbdownload import installed_adb
    candidates = [cfg.get("adb_path"), shutil.which("adb"),
                  str(here / "platform-tools" / exe),
                  installed_adb(),                      # downloaded via Settings → Download ADB
                  str(Path.home() / "platform-tools" / exe)]
    if sys.platform.startswith("win"):
        la = os.environ.get("LOCALAPPDATA", "")
        candidates.append(os.path.join(la, "Android", "Sdk", "platform-tools", exe))
    else:
        candidates.append(str(Path.home() / "Android" / "Sdk" / "platform-tools" / exe))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)


def adb_devices(adb):
    out = _run([adb, "devices"], timeout=15).stdout.decode("utf-8", "replace")
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devs.append((parts[0], parts[1]))
    return devs


class AdbSource:
    supports_phone_hash = True

    def __init__(self, adb, serial):
        self.adb = adb
        self.serial = serial
        model = self.shell("getprop ro.product.model").strip()
        self.manufacturer = self.shell("getprop ro.product.manufacturer").strip()
        self.device_name = model or serial
        self.android = self.shell("getprop ro.build.version.release").strip()
        # the phone's own serial number (for Wi-Fi debugging the adb "serial" is only ip:port)
        self.hw_serial = self.shell("getprop ro.serialno").strip() or (
            "" if self.wireless else serial)
        self.fallback_reason = None
        self._has_sha = None
        self._proc = None

    @property
    def wireless(self):
        from .wireless import is_wireless
        return is_wireless(self.serial)

    @property
    def kind(self):
        return "ADB over Wi-Fi" if self.wireless else "ADB"

    @property
    def description(self):
        how = "Wi-Fi (wireless debugging)" if self.wireless else "USB debugging"
        return f"ADB ({how}), serial {self.serial}, Android {self.android}"

    def shell(self, cmd, timeout=120):
        phoneguard.check(cmd)       # read-only commands only, paths inside /sdcard
        r = _run([self.adb, "-s", self.serial, "shell", cmd], timeout=timeout)
        return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")

    # ---- the few fixed control actions (phoneguard.CONTROL) - never built from data
    def control(self, name, timeout=30):
        cmd = phoneguard.check_control(name)
        r = _run([self.adb, "-s", self.serial, "shell", cmd], timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")

    def companion_state(self):
        """'missing' / 'no-permission' (installed, cannot switch debugging yet) / 'outdated'
        (older than the app bundled with this program) / 'ready'."""
        _rc, out = self.control("companion_installed")
        if f"package:{phoneguard.COMPANION_PACKAGE}" not in out.split():
            return "missing"
        _rc, out = self.control("companion_granted")
        granted = re.search(r"android\.permission\.WRITE_SECURE_SETTINGS: granted=true", out)
        if not granted:
            return "no-permission"
        from .companion import APP_VERSION_CODE
        m = re.search(r"versionCode=(\d+)", out)
        return "outdated" if m and int(m.group(1)) < APP_VERSION_CODE else "ready"

    def install_companion(self, apk):
        """Install / update the bundled phone app (only this one file) and give it the right to
        switch USB debugging on. Returns (ok, message)."""
        if Path(apk).name != "MediaBackup.apk" or not Path(apk).is_file():
            raise phoneguard.ForbiddenPhoneCommand("refused: only the bundled phone app may be installed")
        r = _run([self.adb, "-s", self.serial, "install", "-r", str(apk)], timeout=180)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        if r.returncode != 0 or "Success" not in out:
            return False, out.strip().splitlines()[-1] if out.strip() else "install failed"
        rc, out = self.control("companion_grant")
        if rc != 0:
            return False, out.strip() or "permission could not be granted"
        return True, "installed"

    def forward(self, remote_port):
        """adb forward tcp:<free local port> → the phone app's server. Returns the local port or None."""
        try:
            r = _run([self.adb, "-s", self.serial, "forward", "tcp:0", f"tcp:{int(remote_port)}"], timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        out = r.stdout.decode().strip()
        return int(out) if r.returncode == 0 and out.isdigit() else None

    def unforward(self, local_port):
        try:
            _run([self.adb, "-s", self.serial, "forward", "--remove", f"tcp:{int(local_port)}"], timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass

    def switch_off_debugging(self):
        """After a backup: switch USB debugging (and Wireless debugging) off on the phone.
        The connection drops right away, so errors are expected and ignored."""
        # first the connection we are NOT using - switching off our own one cuts the line
        # (tested on a Pixel 10 Pro: USB debugging off keeps Wireless debugging running)
        order = (("usb_debugging_off", "wifi_debugging_off") if self.wireless
                 else ("wifi_debugging_off", "usb_debugging_off"))
        for name in order:
            try:
                self.control(name, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass

    def is_connected(self):
        try:
            r = _run([self.adb, "-s", self.serial, "get-state"], timeout=10)
            return r.stdout.decode().strip() == "device"
        except (OSError, subprocess.SubprocessError):
            return False

    def folder_exists(self, rel):
        return self.shell(f"[ -d {_q(PHONE_ROOT + '/' + rel)} ] && echo YES").strip() == "YES"

    def list_subfolders(self, rel):
        base = PHONE_ROOT + "/" + rel.strip("/")
        out = self.shell(f"find {_q(base)} -mindepth 1 -maxdepth 1 -type d 2>/dev/null")
        res = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith(PHONE_ROOT + "/"):
                r = line[len(PHONE_ROOT) + 1:]
                if not _hidden(r):
                    res.append(r)
        return sorted(res)

    def list_files(self, folders):
        files, missing = [], []
        for rel in folders:
            rel = rel.strip("/")
            if not self.folder_exists(rel):
                missing.append(rel)
                continue
            base = PHONE_ROOT + "/" + rel
            out = self.shell(f"find {_q(base)} -type f -exec stat -c '%s %Y %n' {{}} + 2>/dev/null",
                             timeout=600)
            for line in out.splitlines():
                parts = line.split(" ", 2)
                if len(parts) != 3 or not parts[0].isdigit():
                    continue
                path = parts[2]
                if not path.startswith(PHONE_ROOT + "/"):
                    continue
                r = path[len(PHONE_ROOT) + 1:]
                if not _hidden(r):
                    files.append(SourceFile(r, int(parts[0]), int(parts[1])))
        return _dedupe(files), missing

    # ---- many small files: one "cat a b c" per group instead of one command per file (each
    # command costs ~65 ms; with 220 KB WhatsApp files that was most of the time). The bytes are
    # split by the known sizes and checked against the phone's SHA-256 like every file.
    def prefetch(self, files):
        from .companion import Prefetcher
        if getattr(self, "_prefetch", None) is not None:
            self._prefetch.stop()
        self._prefetch = Prefetcher(self._fetch_group, files, group_files=64,
                                    group_bytes=16 * 1024 * 1024, workers=2,
                                    max_file=4 * 1024 * 1024)

    def _fetch_group(self, group):
        cmd = "cat " + " ".join(_q(PHONE_ROOT + "/" + sf.rel) for sf in group)
        phoneguard.check(cmd)
        r = subprocess.run([self.adb, "-s", self.serial, "shell", "-T", cmd], capture_output=True,
                           timeout=300, creationflags=_NO_WINDOW)
        data, want = r.stdout, sum(sf.size for sf in group)
        if r.returncode != 0 or len(data) != want:
            return {}            # a file changed or is unreadable: stream them one by one
        out, pos = {}, 0
        for sf in group:
            out[sf.rel] = data[pos:pos + sf.size]
            pos += sf.size
        return out

    def has_sha256sum(self):
        if self._has_sha is None:
            self._has_sha = self.shell("command -v sha256sum >/dev/null && echo YES").strip() == "YES"
        return self._has_sha

    def phone_hashes(self, rels):
        """SHA-256 computed on the phone itself. Returns {rel: sha}."""
        if not rels or not self.has_sha256sum():
            return {}
        cmd = "sha256sum " + " ".join(_q(PHONE_ROOT + "/" + r) for r in rels)
        out = self.shell(cmd, timeout=600)
        res = {}
        for line in out.splitlines():
            m = re.match(r"^([0-9a-f]{64})\s+(.*)$", line.strip())
            if m and m.group(2).startswith(PHONE_ROOT + "/"):
                res[m.group(2)[len(PHONE_ROOT) + 1:]] = m.group(1)
        return res

    def open_stream(self, sf):
        pf = getattr(self, "_prefetch", None)
        data = pf.take(sf) if pf is not None else None
        if data is not None:
            for i in range(0, len(data), CHUNK):
                yield data[i:i + CHUNK]
            return
        yield from self._open_stream(sf)

    def _open_stream(self, sf):
        """Yield the file content.

        'adb shell -T cat' (shell protocol, no terminal = binary-safe) measured 5-6x faster than
        'adb exec-out cat' on a Pixel 10 Pro over USB 3 (~50 vs ~8 MB/s). Every file is
        SHA-256-checked against the phone anyway.
        """
        cmd = "cat " + _q(PHONE_ROOT + "/" + sf.rel)
        phoneguard.check(cmd)
        proc = subprocess.Popen(
            [self.adb, "-s", self.serial, "shell", "-T", cmd],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=_NO_WINDOW)
        self._proc = proc
        try:
            while True:
                b = proc.stdout.read(CHUNK)
                if not b:
                    break
                yield b
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.stdout.close()
            proc.wait()
            self._proc = None

    def close(self):
        if getattr(self, "_prefetch", None) is not None:
            self._prefetch.stop()
            self._prefetch = None
        if self._proc and self._proc.poll() is None:
            self._proc.kill()


class PhoneHasher(threading.Thread):
    """Computes SHA-256 on the phone in the background while files are being copied."""

    def __init__(self, source, rels, batch_chars=3000):
        super().__init__(daemon=True)
        self.source = source
        self.rels = list(rels)
        self.batch_chars = batch_chars
        self.results = {}
        self.finished_rels = set()
        self.cond = threading.Condition()
        self._stop_flag = False

    def run(self):
        batch, length = [], 0
        for r in self.rels + [None]:
            if r is not None:
                batch.append(r)
                length += len(r) + 12
            if batch and (r is None or length >= self.batch_chars):
                if self._stop_flag:
                    break
                try:
                    res = self.source.phone_hashes(batch)
                except Exception:  # noqa: BLE001
                    res = {}
                with self.cond:
                    self.results.update(res)
                    self.finished_rels.update(batch)
                    self.cond.notify_all()
                batch, length = [], 0
        with self.cond:
            self.finished_rels.update(self.rels)
            self.cond.notify_all()

    def get(self, rel, timeout=600):
        with self.cond:
            self.cond.wait_for(lambda: rel in self.finished_rels, timeout=timeout)
            return self.results.get(rel)

    def stop(self):
        self._stop_flag = True


def connect_adb(cfg):
    """Return (AdbSource, None) or (None, reason why ADB did not work)."""
    adb = find_adb(cfg)
    if not adb:
        return None, "the 'adb' program was not found (install Android platform-tools, see README)"
    try:
        _run([adb, "start-server"], timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"could not start adb: {e}"
    wait = max(1, int(cfg.get("adb_wait_seconds", 20)))
    ui.info(f"Looking for the phone via ADB (up to {wait} s) - connect it now if not done yet ...")
    from .wireless import auto_connect, remember, usb_first
    try:
        no_phone = not any(st == "device" for _, st in adb_devices(adb))
    except (OSError, subprocess.SubprocessError):
        no_phone = False
    if no_phone:
        addr = auto_connect(adb, cfg.get("wifi_last_address", ""))
        if addr:
            ui.info(f"  Phone found over Wi-Fi ({addr}).")
            remember(cfg, addr)
    deadline = time.monotonic() + wait
    told_unauth = False
    while True:
        try:
            devs = adb_devices(adb)
        except (OSError, subprocess.SubprocessError) as e:
            return None, f"adb error: {e}"
        ready = usb_first([s for s, st in devs if st == "device"])
        if ready:
            serial = ready[0]
            if len(ready) > 1:
                idx = ui.choose("Several phones found - which one", ready)
                serial = ready[idx]
            try:
                return AdbSource(adb, serial), None
            except (OSError, subprocess.SubprocessError) as e:
                return None, f"adb error: {e}"
        if any(st == "unauthorized" for _, st in devs) and not told_unauth:
            ui.warn("  Phone found but not authorised: unlock the phone and confirm "
                    "'Allow USB debugging' (tick 'Always allow from this computer').")
            told_unauth = True
            deadline = max(deadline, time.monotonic() + 60)
        if time.monotonic() > deadline:
            if any(st == "unauthorized" for _, st in devs):
                return None, "the phone did not allow USB debugging for this computer"
            if devs:
                return None, f"phone state is '{devs[0][1]}' (not ready)"
            return None, ("no phone with USB debugging enabled was found (and no paired phone "
                          "with wireless debugging in this Wi-Fi)")
        time.sleep(0.5)


# =========================================================================== folders / MTP

def _dedupe(files):
    seen, out = set(), []
    for f in files:
        if f.rel not in seen:
            seen.add(f.rel)
            out.append(f)
    return out


# Folders that never contain real photos (thumbnail caches, recycle bins, system folders).
IMPORT_EXCLUDES = {"@eadir", "$recycle.bin", "recycler", "system volume information",
                   ".thumbnails", "thumbs", ".trash", ".trashes", ".picasaoriginals",
                   ".spotlight-v100", ".fseventsd", "lost+found"}


class FolderSource:
    """Any directory tree: the phone mounted via MTP, a card reader, or an old backup (import)."""

    def __init__(self, root, kind="Folder", device_name="", description="",
                 key_prefix="", verify_source=False, exclude_dirs=()):
        self.root = Path(root)
        self.kind = kind
        self.device_name = device_name
        self.serial = ""
        self.description = description or str(self.root)
        self.fallback_reason = None
        self.key_prefix = key_prefix
        self.supports_phone_hash = verify_source      # hash every source file separately
        self.exclude_dirs = {d.lower() for d in exclude_dirs}

    def list_subfolders(self, rel):
        base = self.root / rel
        try:
            return sorted(str(PurePosixPath(rel) / e.name) for e in os.scandir(base)
                          if e.is_dir() and not e.name.startswith("."))
        except OSError:
            return []

    def list_files(self, folders):
        files, missing = [], []
        for rel in folders:
            rel = rel.strip("/")
            base = self.root / rel
            if not base.is_dir():
                missing.append(rel)
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames
                                     if not d.startswith(".") and d.lower() not in self.exclude_dirs)
                for fn in sorted(filenames):
                    if fn.startswith("."):
                        continue
                    full = Path(dirpath) / fn
                    try:
                        st = full.stat()
                    except OSError:
                        continue
                    r = full.relative_to(self.root).as_posix()
                    files.append(SourceFile(r, st.st_size, int(st.st_mtime),
                                            self.key_prefix + r if self.key_prefix else ""))
        return _dedupe(files), missing

    def phone_hashes(self, rels):
        """Independent SHA-256 of the source files (only used for imports)."""
        if not self.supports_phone_hash:
            return {}
        out = {}
        for r in rels:
            try:
                out[r] = sha256_file(self.root / r)
            except OSError:
                pass
        return out

    def open_stream(self, sf):
        return file_chunks(self.root / sf.rel)

    def is_connected(self):
        return self.root.is_dir()

    def close(self):
        pass


def _gvfs_name(mount_dir_name):
    name = mount_dir_name.split("=", 1)[-1]
    parts = [p for p in name.split("_") if p]
    if len(parts) > 1 and re.fullmatch(r"[0-9A-Za-z]{8,}", parts[-1]) and re.search(r"\d", parts[-1]):
        parts = parts[:-1]
    return " ".join(parts)


def find_gvfs_mtp():
    """Linux: find (or mount) the phone via gvfs. Returns FolderSource or (None, reason)."""
    if not hasattr(os, "getuid"):
        return None, "not Linux"
    base = Path(f"/run/user/{os.getuid()}/gvfs")

    def scan():
        if not base.is_dir():
            return []
        found = []
        for m in base.glob("mtp:*"):
            try:
                for storage in m.iterdir():
                    if (storage / "DCIM").is_dir():
                        found.append((m, storage))
            except OSError:
                continue
        return found

    found = scan()
    if not found and shutil.which("gio"):
        try:
            out = _run(["gio", "mount", "-li"], timeout=20).stdout.decode("utf-8", "replace")
            for uri in sorted(set(re.findall(r"activation_root=(mtp://\S+)", out))):
                ui.info(f"  Mounting {uri} via MTP (can take a while) ...")
                _run(["gio", "mount", uri], timeout=120)
            for _ in range(60):
                found = scan()
                if found:
                    break
                time.sleep(1)
        except (OSError, subprocess.SubprocessError):
            pass
    if not found:
        return None, ("no phone found via MTP - unlock the phone and choose "
                      "'File transfer' in the USB notification")
    mount, storage = found[0]
    return FolderSource(storage, kind="MTP (fallback)", device_name=_gvfs_name(mount.name),
                        description=f"MTP via gvfs: {storage}"), None


class WindowsMtpSource:
    """Windows: read the phone through the Explorer shell (needs: pip install pywin32)."""
    kind = "MTP (fallback)"
    supports_phone_hash = False

    def __init__(self, shell, storage_folder, device_name):
        self.shell = shell
        self.storage = storage_folder
        self.device_name = device_name
        self.serial = ""
        self.description = f"MTP via Windows Explorer: {device_name}"
        self.fallback_reason = None
        self.staging = None
        self._items = {}

    def _folder(self, rel):
        f = self.storage
        for part in PurePosixPath(rel).parts:
            nxt = None
            for it in f.Items():
                if it.IsFolder and it.Name == part:
                    nxt = it.GetFolder
                    break
            if nxt is None:
                return None
            f = nxt
        return f

    @staticmethod
    def _fname(item):
        try:
            n = item.ExtendedProperty("System.FileName")
            if n:
                return str(n)
        except Exception:  # noqa: BLE001
            pass
        return item.Name

    def list_subfolders(self, rel):
        f = self._folder(rel)
        if f is None:
            return []
        return sorted(str(PurePosixPath(rel) / it.Name) for it in f.Items()
                      if it.IsFolder and not it.Name.startswith("."))

    def list_files(self, folders):
        files, missing = [], []

        def walk(folder, rel):
            for it in folder.Items():
                name = self._fname(it)
                if name.startswith("."):
                    continue
                r = f"{rel}/{name}"
                if it.IsFolder:
                    walk(it.GetFolder, r)
                else:
                    try:
                        mtime = int(it.ModifyDate.timestamp())
                    except Exception:  # noqa: BLE001
                        mtime = 0
                    self._items[r] = it
                    files.append(SourceFile(r, int(it.Size), mtime))

        for rel in folders:
            rel = rel.strip("/")
            f = self._folder(rel)
            if f is None:
                missing.append(rel)
            else:
                walk(f, rel)
        return _dedupe(files), missing

    def phone_hashes(self, rels):
        return {}

    def open_stream(self, sf):
        if not self.staging:
            raise RuntimeError("staging folder not set")
        tmp = Path(self.staging) / uuid.uuid4().hex
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            ns = self.shell.NameSpace(str(tmp))
            ns.CopyHere(self._items[sf.rel], 4 | 16 | 512 | 1024)   # silent, no dialogs
            deadline = time.monotonic() + 120 + sf.size / (1024 * 1024)
            target, last, stable = None, -1, 0
            while time.monotonic() < deadline:
                entries = [p for p in tmp.iterdir() if p.is_file()]
                if entries:
                    target = entries[0]
                    size = target.stat().st_size
                    stable = stable + 1 if size == last else 0
                    last = size
                    if size == sf.size and stable >= 2:
                        try:
                            with open(target, "r+b"):
                                break
                        except OSError:
                            pass
                time.sleep(0.25)
            else:
                raise TimeoutError(f"copy from phone timed out: {sf.rel}")
            yield from file_chunks(target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def is_connected(self):
        return True

    def close(self):
        pass


def find_windows_mtp():
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None, "pywin32 is not installed (run: pip install pywin32)"
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        pc = shell.NameSpace(17)   # "This PC"
        for dev in pc.Items():
            if dev.IsFileSystem:
                continue
            try:
                devf = dev.GetFolder
                storages = list(devf.Items())
            except Exception:  # noqa: BLE001
                continue
            for st in storages:
                if not st.IsFolder:
                    continue
                stf = st.GetFolder
                if any(it.Name == "DCIM" for it in stf.Items()):
                    return WindowsMtpSource(shell, stf, dev.Name), None
    except Exception as e:  # noqa: BLE001
        return None, f"Windows MTP error: {e}"
    return None, ("no phone found via MTP - unlock the phone and choose "
                  "'File transfer' in the USB notification")


# =========================================================================== entry

def connect_source(cfg):
    """ADB first; if that fails, say so clearly and fall back to MTP / a folder."""
    src, reason = connect_adb(cfg)
    if src:
        ui.ok(f"Connected via ADB: {src.manufacturer} {src.device_name} (Android {src.android})")
        return src
    ui.warn("")
    ui.warn("!" * 70)
    ui.warn(f"  ADB is NOT working: {reason}.")
    ui.warn("  -> Using the MTP FALLBACK instead (slower; the hash check then compares")
    ui.warn("     the received data with the written copies, not with the phone itself).")
    ui.warn("!" * 70)
    if sys.platform.startswith("win"):
        mtp, why = find_windows_mtp()
    else:
        mtp, why = find_gvfs_mtp()
    if mtp:
        ui.ok(f"Connected via MTP fallback: {mtp.device_name}")
        mtp.fallback_reason = reason
        return mtp
    ui.error(f"MTP fallback did not work either: {why}")
    path = ui.ask_directory("Choose the folder of the phone storage (the folder that contains DCIM)")
    if path and Path(path).is_dir():
        src = FolderSource(path, kind="Folder (manual)", description=path)
        src.fallback_reason = f"ADB: {reason}; MTP: {why}"
        return src
    return None
