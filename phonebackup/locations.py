"""Find drives, existing backups and export sets (shared by the GUI and the terminal version)."""

import os
import shutil
import string
import sys
from pathlib import Path

from .export import has_catalog
from .index import INTERNAL_DIR


def detect_drives():
    """Mounted external/extra drives: [(path, free_bytes)]."""
    found = []
    if sys.platform.startswith("win"):
        import ctypes
        sysdrive = os.environ.get("SystemDrive", "C:").upper()
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if f"{letter}:" == sysdrive or not os.path.exists(root):
                continue
            if ctypes.windll.kernel32.GetDriveTypeW(root) in (2, 3):   # removable / fixed
                found.append(root)
    else:
        user = os.environ.get("USER", "")
        for base in (f"/media/{user}", f"/run/media/{user}", "/media", "/mnt"):
            try:
                for e in os.scandir(base):
                    if e.is_dir() and os.path.ismount(e.path) and e.path not in found:
                        found.append(e.path)
            except OSError:
                continue
    out = []
    for p in found:
        try:
            out.append((p, shutil.disk_usage(p).free))
        except OSError:
            pass
    return out


def free_space(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def is_backup_folder(path):
    return (Path(path) / INTERNAL_DIR / "index.sqlite").is_file()


def find_backups(cfg):
    """Backup parent folders ('Phone - Owner') inside the saved destination folders."""
    out = []
    for base in cfg.get("destinations", []):
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.scandir(base), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.is_dir() and is_backup_folder(e.path):
                out.append(e.path)
    return out


def find_export_sets(cfg):
    """Export sets ('Phone - Owner' with a catalog) inside the saved export targets - and
    Grandfather-Father-Son backups on the backup drives (same layout)."""
    out = []
    for base in list(cfg.get("export_targets", [])) + list(cfg.get("destinations", [])):
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.scandir(base), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.is_dir() and has_catalog(e.path) and e.path not in out:
                out.append(e.path)
    return out


# ---------------------------------------------------------------- unmounted drives (Linux)

MOUNTABLE_FS = {"ntfs", "ntfs3", "exfat", "vfat", "fat32", "ext4", "ext3", "ext2", "btrfs", "xfs",
                "f2fs", "hfsplus", "apfs"}


def detect_unmounted():
    """External (USB/hot-plug) partitions that are not mounted yet.

    Returns [{'device', 'label', 'fstype', 'size'}]. Always empty on Windows
    (Windows gives every drive a letter automatically).
    """
    if sys.platform.startswith("win") or not shutil.which("lsblk"):
        return []
    import json
    import subprocess
    try:
        out = subprocess.run(["lsblk", "-J", "-b", "-o",
                              "NAME,PATH,SIZE,TRAN,FSTYPE,LABEL,MOUNTPOINT,HOTPLUG,TYPE"],
                             capture_output=True, timeout=10).stdout
        tree = json.loads(out or b"{}").get("blockdevices", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    found = []

    def walk(node, external):
        external = external or node.get("tran") == "usb" or bool(node.get("hotplug"))
        mps = node.get("mountpoints") or [node.get("mountpoint")]
        mounted = any(m for m in mps)
        fs = (node.get("fstype") or "").lower()
        if external and fs in MOUNTABLE_FS and not mounted and node.get("type") in ("part", "disk"):
            found.append({"device": node.get("path") or f"/dev/{node['name']}",
                          "label": node.get("label") or "",
                          "fstype": fs, "size": int(node.get("size") or 0)})
        for child in node.get("children") or []:
            walk(child, external)

    for n in tree:
        if not n.get("name", "").startswith(("loop", "zram", "sr")):
            walk(n, False)
    return found


def mount_device(device):
    """Mount like the file manager does (udisksctl, no password). Returns (mountpoint, error)."""
    import re
    import subprocess
    if not shutil.which("udisksctl"):
        return None, "udisksctl is not installed"
    try:
        r = subprocess.run(["udisksctl", "mount", "-b", device, "--no-user-interaction"],
                           capture_output=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    text = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    m = re.search(r" at (.+?)\.?$", text.splitlines()[0] if text else "")
    if r.returncode == 0 and m:
        return m.group(1).strip(), None
    m = re.search(r"already mounted at [`'\"]?(.+?)[`'\"]?\.?$", text, re.M)
    if m:
        return m.group(1).strip(), None
    return None, text or f"udisksctl exit code {r.returncode}"


def drive_label_of(path):
    """'/media/sam/MyDisk/PhoneBackups' -> 'MyDisk' (Linux mount by label), else None."""
    parts = Path(path).parts
    user = os.environ.get("USER", "")
    for prefix in (("/", "media", user), ("/", "run", "media", user)):
        if parts[:len(prefix)] == prefix and len(parts) > len(prefix):
            return parts[len(prefix)]
    return None


def mount_for_paths(paths):
    """Mount unmounted drives whose label matches saved folders. Returns list of messages."""
    msgs = []
    missing = [p for p in paths if not os.path.isdir(p)]
    if not missing:
        return msgs
    unmounted = detect_unmounted()
    for p in missing:
        label = drive_label_of(p)
        for d in unmounted:
            if label and d["label"] == label:
                mp, err = mount_device(d["device"])
                msgs.append(f"Mounted drive '{label}' at {mp}" if mp else
                            f"Could not mount drive '{label}': {err}")
                break
    return msgs


def describe_unmounted(d):
    name = d["label"] or d["device"]
    from .ui import human_size
    return f"{name}  ({human_size(d['size'])}, {d['fstype'].upper()}, {d['device']})"
