"""The phones you back up, for the start screen (user request 2026-11-04): one entry per backup
("Galaxy A55 - Kim") with its last run; each phone has its own "Update backup" button.

Stored in the settings as cfg["last_backup"]: which phone, whose, which folders, which
destinations, when and how much. "Update" repeats exactly that backup; only new photos and videos
are copied (the backup skips files that are already there).
No Qt here - the GUI asks `check()` whether the button may be enabled.
"""

import glob
import os
import re
from datetime import datetime

from . import config
from .i18n import tr, trp


def record(cfg, phone, owner, folders, destinations, files, size, status, model="",
           keep_structure=False):
    """model = the phone's own model name (the backup name `phone` may have been typed)."""
    from .backup import backup_parent_name
    entry = {
        "phone": phone, "model": model or phone, "owner": owner, "folders": list(folders),
        "destinations": [str(d) for d in destinations],
        "when": datetime.now().isoformat(timespec="minutes"),
        "files": int(files), "bytes": int(size), "status": status,
        "keep_structure": bool(keep_structure),
    }
    cfg["last_backup"] = entry
    key = backup_parent_name(phone, owner)
    cfg.setdefault("phones", {})[key] = entry
    if key in cfg.get("phones_hidden", []):           # backed up again: back in the list
        cfg["phones_hidden"] = [k for k in cfg["phones_hidden"] if k != key]
    config.save(cfg)


def forget(cfg, keys):
    """Remove phones from the start screen list (backups on the drives stay)."""
    hidden = set(cfg.get("phones_hidden", []))
    for k in keys:
        (cfg.get("phones") or {}).pop(k, None)
        hidden.add(k)
        lb = cfg.get("last_backup")
        if lb and _key(lb) == k:
            cfg.pop("last_backup", None)
    cfg["phones_hidden"] = sorted(hidden)
    config.save(cfg)


def _key(e):
    from .backup import backup_parent_name
    return backup_parent_name(e["phone"], e.get("owner", ""))


def phones(cfg):
    """All phones with a backup, newest backup first."""
    found = [e for e in (cfg.get("phones") or {}).values() if get({"last_backup": e})]
    return sorted(found, key=lambda e: e.get("when", ""), reverse=True)


_FIELDS = ("Smartphone", "Owner", "Status", "Started")


def _read_fields(text):
    """The report fields above, also from a report written in another language (labels are
    translated): {English label: value}."""
    from .phoneid import report_labels
    out = {}
    for en in _FIELDS:
        m = re.search(r"^\s*(?:%s)\s*:\s*(.+?)\s*$" % report_labels(en), text, re.M)
        if m:
            out[en] = m.group(1)
    return out


def discover(cfg):
    """Add backups on the connected drives that the list does not know yet (made before this
    version), read from their newest report. Old-phone imports are not phones to back up."""
    from .backup import backup_parent_name
    from .locations import find_backups
    from .report import english
    known = cfg.setdefault("phones", {})
    hidden = set(cfg.get("phones_hidden", []))
    lb = cfg.get("last_backup")
    if get({"last_backup": lb}) and _key(lb) not in hidden:
        known.setdefault(_key(lb), lb)
    changed = False
    for parent in find_backups(cfg):
        key = os.path.basename(parent)
        if key in known or key in hidden:
            continue
        reports = sorted(glob.glob(os.path.join(glob.escape(parent), "Backup *.txt")),
                         key=os.path.getmtime)
        if not reports:
            continue
        try:
            with open(reports[-1], encoding="utf-8", errors="replace") as f:
                fields = _read_fields(f.read(20000))
        except OSError:
            continue
        if not fields.get("Smartphone"):
            continue
        known[key] = {"phone": fields["Smartphone"], "model": fields["Smartphone"],
                      "owner": fields.get("Owner", ""), "folders": [],
                      "destinations": [os.path.dirname(parent)],
                      "when": fields.get("Started", "").replace(" ", "T")[:16],
                      "files": 0, "bytes": 0, "status": english(fields.get("Status", "")),
                      "keep_structure": False}
        changed = True
    if changed:
        config.save(cfg)


def get(cfg):
    lb = cfg.get("last_backup")
    return lb if isinstance(lb, dict) and lb.get("phone") and lb.get("destinations") else None


def title(lb):
    """"Sam's Pixel 10 Pro" (German / English possessive without the apostrophe-s mess)."""
    owner, phone = (lb.get("owner") or "").strip(), lb.get("phone", "")
    if not owner:
        return phone
    # two templates: names ending in s/x/z/ß take only the apostrophe (English, German)
    if owner[-1].lower() in "sxzß":
        return tr("%1$s' %2$s", owner, phone)
    return tr("%1$s's %2$s", owner, phone)


def _same_phone(a, b):
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


def check(lb, connected_phone, is_dir=os.path.isdir, attached_labels=()):
    """(possible, hint) for the update button.

    connected_phone: model of the connected phone ('' = none). attached_labels: labels of drives
    that are plugged in but not mounted yet (they are mounted when the backup starts).
    """
    if lb is None:
        return False, tr("No backup yet – start with “New backup”.")
    dests = lb["destinations"]
    ready = [d for d in dests if is_dir(d)]
    attached = [d for d in dests if not is_dir(d) and _label(d) in attached_labels]
    problems = []
    if not connected_phone:
        problems.append(tr("Connect %s.", lb['phone']))
    elif not (_same_phone(connected_phone, lb.get("model")) or _same_phone(connected_phone, lb["phone"])):
        problems.append(tr("The connected phone is a %s, the last backup was of a "
                           "%s – use “New backup” for this phone.", connected_phone, lb['phone']))
    if not ready and not attached:
        names = ", ".join(_short(d) for d in dests)
        problems.append(tr("Connect a backup drive (%s).", names))
    if problems:
        return False, " ".join(problems)
    missing = len(dests) - len(ready) - len(attached)
    hint = tr("Ready – copies only the new photos and videos.")
    if missing:
        hint += " " + trp("%d of %d backup drive not connected – it is skipped.",
                          "%d of %d backup drives not connected – they are skipped.",
                          len(dests), missing, len(dests))
    return True, hint


def _short(path):
    p = str(path).rstrip("/\\")
    parts = p.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 1 else p


def _label(path):
    from .locations import drive_label_of
    try:
        return drive_label_of(path)
    except Exception:  # noqa: BLE001
        return None
