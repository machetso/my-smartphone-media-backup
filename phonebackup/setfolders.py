"""Where a backup lives (user request 2026-11-09): <destination>/<Owner>/<Phone>/YYYY/YY.MM.

Until then a backup was one folder <destination>/<Phone - Owner>/. Such folders are MOVED into the
new place (a rename on the same drive) the first time the program sees them; when the new folder
already exists the contents are merged: identical files are recognised, nothing is overwritten
or deleted, a different file with the same name gets _1, the index rows are taken over.

Names:
  key   "Pixel 10 Pro - Sam"   identity in the settings (phones, profiles, choices) – unchanged
  rel   "Sam/Pixel 10 Pro"     the folder below a destination / export target / Google Drive
"""

import os
import sqlite3
from pathlib import Path

from . import ui
from .i18n import tr

INTERNAL_DIR = ".phonebackup"
EXPORT_DIR = ".phonebackup-export"
GFS_SUFFIX = " (Grandfather-Father-Son)"


def _safe(text):
    from .layout import safe_name
    return safe_name(text)


def key(phone, owner):
    """'Pixel 10 Pro - Sam's – the backup's name in the settings."""
    return _safe(f"{phone} - {owner}")


def rel(phone, owner):
    """'Sam/Pixel 10 Pro' – the backup folder below a destination."""
    return f"{_safe(owner)}/{_safe(phone)}"


def rel_of(set_dir):
    set_dir = Path(set_dir)
    return f"{set_dir.parent.name}/{set_dir.name}"


def key_of(set_dir):
    """Settings name of a backup folder <Owner>/<Phone>."""
    set_dir = Path(set_dir)
    return key(set_dir.name, set_dir.parent.name)


def split_rel(set_rel):
    """'Sam/Pixel 10 Pro' -> ('Pixel 10 Pro', 'Sam')."""
    owner, _, phone = str(set_rel).partition("/")
    return phone, owner


def key_of_rel(set_rel):
    phone, owner = split_rel(set_rel)
    return key(phone, owner)


def shown(set_rel):
    """How a backup is named in lists: 'Sam / Pixel 10 Pro'."""
    phone, owner = split_rel(set_rel)
    return f"{owner} / {phone}"


# ------------------------------------------------------------------ old folders 'Phone - Owner'

def is_set(path):
    p = Path(path)
    return (p / INTERNAL_DIR / "index.sqlite").is_file() or (p / EXPORT_DIR / "catalog.sqlite").is_file()


def split_old(name, cfg=None, folder=None):
    """(phone, owner) of an old folder name 'Pixel 10 Pro - Sam's – from the known phones, the
    folder's newest report, else split at the last ' - '."""
    for e in ((cfg or {}).get("phones") or {}).values():
        if key(e.get("phone", ""), e.get("owner", "")) == name:
            return e["phone"], e.get("owner", "")
    if folder is not None:
        got = _from_report(Path(folder))
        if got and key(*got) == name:
            return got
    phone, sep, owner = name.rpartition(" - ")
    return (phone, owner) if sep and phone and owner else (name, "")


def _from_report(folder):
    from .lastbackup import _read_fields
    try:
        reps = sorted(folder.glob("Backup *.txt"), key=lambda p: p.stat().st_mtime)
        if not reps:
            return None
        f = _read_fields(reps[-1].read_text(encoding="utf-8", errors="replace")[:20000])
    except OSError:
        return None
    if f.get("Smartphone") and f.get("Owner"):
        return f["Smartphone"], f["Owner"]
    return None


def old_sets(base):
    """Backup folders still directly in the destination ('Pixel 10 Pro - Sam')."""
    out = []
    try:
        entries = sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        if e.is_dir() and not e.name.startswith(".") and " - " in e.name and is_set(e.path):
            out.append(Path(e.path))
    return out


def relocate(base, cfg=None):
    """Move old 'Phone - Owner' folders of a destination to Owner/Phone. Returns [(old, new)]."""
    base = Path(base)
    moved = []
    for old in old_sets(base):
        phone, owner = split_old(old.name, cfg, old)
        if not owner:
            continue                                   # cannot tell the owner: left as it is
        new = base / _safe(owner) / _safe(phone)
        try:
            if not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                os.rename(old, new)                    # same drive: only the folder entry moves
                ui.info(tr("Backup folder moved to the new place: %s → %s", old, new))
            else:
                _merge(old, new)
            moved.append((old, new))
        except (OSError, sqlite3.Error) as e:
            ui.warn(tr("Could not move %s to %s (%s) – it stays where it is.", old, new, e))
    return moved


def _merge(old, new):
    """Merge an old backup folder into an existing new one (never overwrites, never deletes)."""
    from .layout import unique_path
    if (old / EXPORT_DIR).is_dir() and (new / EXPORT_DIR).is_dir():
        ui.warn(tr("%s and %s are both Grandfather-Father-Son backups – they cannot be merged, "
                   "%s stays where it is.", old, new, old))
        return
    ui.info(tr("Merging %s into the existing %s …", old, new))
    renamed, left = {}, []
    for dirpath, dirnames, files in os.walk(old):
        rel_dir = Path(dirpath).relative_to(old)
        if rel_dir.parts[:1] in ((INTERNAL_DIR,), (EXPORT_DIR,)):
            dirnames[:] = []
            continue
        for fn in sorted(files):
            src = Path(dirpath) / fn
            r = (rel_dir / fn).as_posix()
            dst = new / r
            if dst.exists():
                if _same_file(src, dst):
                    left.append(str(src))
                    continue
                dst = unique_path(dst)
                renamed[r] = dst.relative_to(new).as_posix()
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
    for d in ((INTERNAL_DIR,), (EXPORT_DIR,)):
        if (old / d[0]).is_dir() and not (new / d[0]).exists():
            os.rename(old / d[0], new / d[0])         # the new folder had none: take it over
    _merge_index(old / INTERNAL_DIR / "index.sqlite", new / INTERNAL_DIR / "index.sqlite", renamed)
    for dirpath, _d, _f in sorted(os.walk(old), reverse=True):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
    if left:
        ui.warn(tr("%d files were already identical in %s and stay in %s (nothing deleted).",
                   len(left), new, old))


def _same_file(a, b):
    from .copier import sha256_file
    try:
        return a.stat().st_size == b.stat().st_size and sha256_file(a) == sha256_file(b)
    except OSError:
        return False


def _merge_index(old_db, new_db, renamed):
    """Take over the rows of the old index (the new one wins for the same phone file)."""
    if not old_db.is_file() or not new_db.is_file() or old_db == new_db:
        return
    db = sqlite3.connect(str(new_db))
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        src = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
        try:
            rows = src.execute("SELECT * FROM files").fetchall()
        finally:
            src.close()
        for row in rows:
            row = list(row)
            row[4] = renamed.get(row[4], row[4])      # rel_path
            db.execute("INSERT OR IGNORE INTO files VALUES (%s)" % ",".join("?" * len(row)), row)
        db.commit()
    finally:
        db.close()


def find_sets(base, cfg=None, export=False):
    """Backup folders <base>/<Owner>/<Phone> (old ones are moved there first)."""
    relocate(base, cfg)
    out = []
    try:
        owners = sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        return out
    for o in owners:
        if not o.is_dir() or o.name.startswith("."):
            continue
        try:
            phones = sorted(os.scandir(o.path), key=lambda e: e.name)
        except OSError:
            continue
        for p in phones:
            if not p.is_dir() or p.name.startswith("."):
                continue
            path = Path(p.path)
            if export:
                if (path / EXPORT_DIR / "catalog.sqlite").is_file():
                    out.append(str(path))
            elif (path / INTERNAL_DIR / "index.sqlite").is_file():
                out.append(str(path))
    return out


# ------------------------------------------------------------------ Google Drive

def relocate_drive(drive, root, phone, owner, suffix=""):
    """Move the old Google Drive folder '<Phone - Owner><suffix>' to '<Owner>/<Phone><suffix>'.
    Returns the id of the owner folder."""
    from .gdrive import FOLDER_MIME, API, _q
    owner_id = drive.find_or_create_folder(_safe(owner), root)
    old_name = key(phone, owner) + suffix
    r = drive.call("GET", f"{API}/files", {
        "q": f"name = {_q(old_name)} and mimeType = '{FOLDER_MIME}' and trashed = false and "
             f"{_q(root)} in parents", "fields": "files(id)", "spaces": "drive"})
    olds = r.get("files") or []
    if not olds:
        return owner_id
    old_id = olds[0]["id"]
    new_name = _safe(phone) + suffix
    r = drive.call("GET", f"{API}/files", {
        "q": f"name = {_q(new_name)} and mimeType = '{FOLDER_MIME}' and trashed = false and "
             f"{_q(owner_id)} in parents", "fields": "files(id)", "spaces": "drive"})
    if not r.get("files"):
        drive.call("PATCH", f"{API}/files/{old_id}",
                   {"addParents": owner_id, "removeParents": root, "fields": "id"},
                   body={"name": new_name})
        ui.info(tr("Google Drive: %s moved to %s", old_name, f"{owner}/{new_name}"))
        return owner_id
    if suffix:                                         # two GFS catalogs cannot be merged
        ui.warn(tr("Google Drive: %s and %s both exist – %s stays where it is.", old_name,
                   f"{owner}/{new_name}", old_name))
        return owner_id
    new_id = r["files"][0]["id"]
    files, folders = drive.list_tree(old_id)
    have, new_folders = drive.list_tree(new_id)
    left = 0
    for rel_path, v in sorted(files.items()):
        if rel_path in have:
            left += 1
            continue
        d = rel_path.rpartition("/")[0]
        drive.move(v["id"], folders[d], drive.ensure_path(new_folders, d))
    if not left:
        drive.trash(old_id)
    ui.info(tr("Google Drive: %s merged into %s", old_name, f"{owner}/{new_name}"))
    return owner_id


def drive_sets(drive, root, suffix=""):
    """'Owner/Phone' of the backups on Google Drive (folders <Owner>/<Phone><suffix>; old
    '<Phone - Owner><suffix>' folders directly in the root are listed too)."""
    from .gdrive import FOLDER_MIME, API, _q
    from .safety import safe_component
    r = drive.call("GET", f"{API}/files", {
        "q": f"mimeType = '{FOLDER_MIME}' and trashed = false", "spaces": "drive", "pageSize": 1000,
        "fields": "files(id,name,parents)"})
    items = r.get("files", [])
    by_id = {f["id"]: f for f in items}
    out = set()
    for f in items:
        parent = (f.get("parents") or [None])[0]
        name = f["name"]
        if suffix and not name.endswith(suffix):
            continue
        base = name[:len(name) - len(suffix)] if suffix else name
        if parent == root:
            if suffix and " - " in base:              # old layout, moved at the next export
                phone, owner = split_old(base)
                if owner and safe_component(phone) and safe_component(owner):
                    out.add(f"{owner}/{phone}")
        elif parent in by_id and (by_id[parent].get("parents") or [None])[0] == root:
            owner = by_id[parent]["name"]
            if safe_component(owner) and safe_component(base):
                out.add(f"{owner}/{base}")
    return sorted(out)

