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
    "keep_awake": True,          # block standby/shutdown while a job runs
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


def save(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)
