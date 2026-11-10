"""The known backups for "Manage backups → Backups" (user request 2026-11-10). No Qt here.

A backup ("Pixel 10 Pro - Sam") is known from the phone list (cfg["phones"], the start screen)
and/or from its folders <Owner>/<Phone> on the saved backup drives. Per backup the settings keep
a profile in cfg["backup_profiles"][key]:

  folders          standard folders on the phone ("Update backup" on the start screen uses them)
  keep_structure   other folders than Camera keep the phone's folder structure
  destinations     the backup drives of this backup (base folders, e.g. /media/me/HDD/PhoneBackups)
  import_roots     folders to import from (old drives, old phone copies)
  import_choices   {root: {folder: "camera" | "other"}} – which folders and how they are sorted
"""

import os
from pathlib import Path

from . import config, setfolders

CAMERA_FOLDER = "DCIM/Camera"


def default_folders(cfg):
    """Standard folders for a backup without its own list (program settings; DCIM/Camera)."""
    return list(cfg.get("default_folders") or [CAMERA_FOLDER])


def profile(cfg, key):
    """The backup's profile with every field filled in (not saved)."""
    prof = dict((cfg.get("backup_profiles") or {}).get(key) or {})
    prof.setdefault("folders", default_folders(cfg))
    prof.setdefault("keep_structure", False)
    prof.setdefault("import_roots", [])
    prof.setdefault("import_choices", {})
    return prof


def save_profile(cfg, key, **fields):
    prof = cfg.setdefault("backup_profiles", {}).setdefault(key, {})
    prof.update(fields)
    if "destinations" in fields and key in (cfg.get("phones") or {}):
        cfg["phones"][key]["destinations"] = list(fields["destinations"])   # "Update backup" uses them
    if "destinations" in fields:
        known = list(cfg.get("destinations", []))
        known += [d for d in fields["destinations"] if d not in known]
        cfg["destinations"] = known
    config.save(cfg)


def known(cfg, found_sets, show_hidden=False):
    """[{key, phone, owner, entry, copies, drives, hidden}] – the phone list plus the backups found
    on the drives. found_sets: {key: [set folders]} (gui._backup_sets / locations.find_backups)."""
    hidden = set(cfg.get("phones_hidden", []))
    phones = cfg.get("phones") or {}
    keys = list(phones) + [k for k in found_sets if k not in phones]
    out = []
    for k in keys:
        if k in hidden and not show_hidden:
            continue
        e = phones.get(k)
        copies = list(found_sets.get(k, []))
        if e:
            phone, owner = e.get("phone", ""), e.get("owner", "")
        elif copies:
            phone, owner = Path(copies[0]).name, Path(copies[0]).parent.name
        else:
            continue
        out.append({"key": k, "phone": phone, "owner": owner, "entry": e, "copies": copies,
                    "drives": drives(cfg, k, e, copies), "hidden": k in hidden})
    out.sort(key=lambda b: ((b["entry"] or {}).get("when", ""), b["key"]), reverse=True)
    return out


def drives(cfg, key, entry=None, copies=()):
    """The backup drives of a backup: its own list, else the phone list's, else where it was found."""
    prof = (cfg.get("backup_profiles") or {}).get(key) or {}
    if prof.get("destinations"):
        lst = list(prof["destinations"])
    elif entry and entry.get("destinations"):
        lst = list(entry["destinations"])
    else:
        lst = []
    for c in copies:                       # a copy on a drive that is not in the list yet
        base = str(Path(c).parent.parent)
        if base not in lst and not prof.get("destinations"):
            lst.append(base)
    return lst


def copy_on(base, phone, owner):
    """The backup's folder on a backup drive (None if the drive has no copy of it)."""
    p = Path(base) / setfolders.rel(phone, owner)
    return str(p) if os.path.isdir(p) else None


def unhide(cfg, keys):
    cfg["phones_hidden"] = [k for k in cfg.get("phones_hidden", []) if k not in set(keys)]
    config.save(cfg)
