"""Persistent settings (owner name, folders, destinations, ...)."""

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "owner": "",
    "source_folders": ["DCIM/Camera"],
    "destinations": [],          # base folders on external drives, e.g. /media/me/HDD1/PhoneBackups
    "export_targets": [],        # base folders on the second storage
    "adb_path": "",              # empty = search PATH and ./platform-tools
    "adb_wait_seconds": 20,      # how long to wait for the phone to appear via ADB
    "fsync": True,               # force data onto the disk before verifying
    "keep_awake": True,
    "wifi_last_address": "",     # ip:port of the last wireless-debugging connection
    "hotspot_ssid": "",          # direct Wi-Fi (laptop hotspot), generated on first use
    "hotspot_password": "",          # block standby/shutdown while a job runs
}


def config_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "PhoneBackup" / "config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "phonebackup" / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    try:
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"Warning: could not read settings {p}: {e} - using defaults.")
    return cfg


def write_private(p: Path, text: str) -> None:
    """Write a file only this user may read (settings with the hotspot password, the Google
    sign-in): folder 0700, file 0600 – also when an old temp file with other rights is left."""
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    try:
        os.unlink(tmp)                   # a left-over / planted temp file keeps its own rights
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, p)


def save(cfg: dict) -> None:
    write_private(config_path(), json.dumps(cfg, indent=2, ensure_ascii=False))
