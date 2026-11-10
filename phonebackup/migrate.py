"""Convert backups from the old month folders to the new ones (user decision 2026-11-09).

old  2026/02.February-photos/x.jpg      new  2026/26.02/x.jpg      (photos + videos together)
     2026/02.February-videos/y.mp4           2026/26.02/y.mp4
     2026/raw/02.February-raw/z.dng          2026/raw/26.02/z.dng

Only folders with exactly these old names are changed – "keep folder structure" folders
(Pictures/Screenshots/…), <year>/other/… of old-phone imports and folders the user made are never
touched.

The user CHOOSES first (user request 2026-11-09): before the first conversion of a backup
('Phone - Owner') the program lists its old month folders; unticked folders keep their old name
and structure for good. The choice is stored in the settings (cfg "layout_keep":
{backup name: [old folders kept]}) and used for every copy of that backup. Without a choice
nothing is converted (unless the backup has no old folders left, e.g. converted elsewhere).

Where it happens (automatically, before the backup folder is used):
  - a backup folder on a drive (simple plan): files are MOVED on the same drive (a rename –
    nothing is copied or deleted) and .phonebackup/index.sqlite gets the new paths;
  - a Grandfather-Father-Son folder (GFS plan or second storage on a drive): the same inside
    every dated export folder, and .phonebackup-export/catalog.sqlite gets the new paths;
  - Google Drive (Copy and Grandfather-Father-Son): files are moved to the new folders (their id
    stays, so shortcuts keep working), the catalog is updated; empty old folders go to the trash.

convert_rel() is a pure function of the path and the kept folders, so every copy (drive 1,
drive 2, Google Drive, every catalog) gets exactly the same new paths. Every step can be repeated:
an interrupted conversion simply continues the next time. A file is never overwritten – if the new
place is already taken, the file stays where it is and is reported.
"""

import os
import re
import sqlite3
from pathlib import Path

from . import ui
from .i18n import tr, trp
from .layout import MONTHS
from .setfolders import key_of

_MONTH = "|".join(MONTHS)
_OLD_MEDIA = re.compile(rf"^((\d{{4}})/(\d{{2}})\.({_MONTH})-(photos|videos))(/.+)$")
_OLD_RAW = re.compile(rf"^((\d{{4}})/raw/(\d{{2}})\.({_MONTH})-raw)(/.+)$")
_OLD_DIR = re.compile(rf"^(\d{{2}})\.({_MONTH})-(photos|videos|raw)$")

INDEX_REL = Path(".phonebackup") / "index.sqlite"
CATALOG_REL = Path(".phonebackup-export") / "catalog.sqlite"
CHOICES = "layout_keep"              # cfg: {backup name: [old month folders that are kept]}
ALWAYS = "layout_keep_always"        # cfg: {backup name: [kept import folders that look like old ones]}

NO_KEEP = frozenset()


# ------------------------------------------------------------------ the user's choice

def always_kept(cfg, set_name):
    """Folders that are never converted: imported with "Keep folder as it is" although their
    path looks like an old month folder (e.g. an old backup of this program kept 1:1)."""
    return frozenset(((cfg or {}).get(ALWAYS) or {}).get(str(set_name)) or ())


def protect(cfg, set_name, folders):
    """Never convert these folders of this backup (stored in the settings)."""
    from . import config
    allk = dict(cfg.get(ALWAYS) or {})
    allk[str(set_name)] = sorted(set(allk.get(str(set_name)) or ()) | set(folders))
    cfg[ALWAYS] = allk
    try:
        config.save(cfg)
    except OSError:
        pass


def decision(cfg, set_name):
    """Old month folders the user keeps (frozenset), None when not chosen yet."""
    v = ((cfg or {}).get(CHOICES) or {}).get(str(set_name))
    return None if v is None else frozenset(v) | always_kept(cfg, set_name)


def to_choose(cfg, set_dir):
    """{old month folder: files} the user still has to decide about (no choice yet)."""
    set_dir = Path(set_dir)
    if decision(cfg, key_of(set_dir)) is not None:
        return {}
    skip = always_kept(cfg, key_of(set_dir))
    return {k: v for k, v in old_folders(set_dir).items() if k not in skip}


def set_decision(cfg, set_name, keep):
    choices = dict(cfg.get(CHOICES) or {})
    choices[str(set_name)] = sorted(keep)
    cfg[CHOICES] = choices


def effective_keep(cfg, set_dir):
    """What to keep for this backup: the user's choice; without one 'nothing' when the folder
    has no old month folders anyway (converted elsewhere), else None = do not convert yet."""
    keep = decision(cfg, key_of(set_dir))
    if keep is not None:
        return keep
    return always_kept(cfg, key_of(set_dir)) if not to_choose(cfg, set_dir) else None


# ------------------------------------------------------------------ paths

def _month_ok(mm, name):
    return 1 <= int(mm) <= 12 and MONTHS[int(mm) - 1] == name


def old_dir_of(rel):
    """'2026/02.February-photos' for a path inside an old month folder, else None."""
    rel = str(rel).replace("\\", "/")
    for rx in (_OLD_MEDIA, _OLD_RAW):
        m = rx.match(rel)
        if m and _month_ok(m.group(3), m.group(4)):
            return m.group(1)
    return None


def convert_rel(rel, keep=NO_KEEP):
    """New path for an old-layout path ('2026/02.February-photos/x.jpg' -> '2026/26.02/x.jpg'),
    None when the path is not in an old month folder or in one the user keeps."""
    rel = str(rel).replace("\\", "/")
    m = _OLD_MEDIA.match(rel)
    raw = False
    if not (m and _month_ok(m.group(3), m.group(4))):
        m = _OLD_RAW.match(rel)
        raw = True
        if not (m and _month_ok(m.group(3), m.group(4))):
            return None
    if m.group(1) in keep:
        return None
    y = m.group(2)
    rest = m.group(m.lastindex)                 # "/x.jpg" (the last group of either pattern)
    return f"{y}/{'raw/' if raw else ''}{y[2:]}.{m.group(3)}{rest}"


def is_old_dir(rel_dir):
    """'2026/02.February-photos' or '2026/raw/02.February-raw'."""
    return old_dir_of(str(rel_dir).replace("\\", "/").rstrip("/") + "/x") is not None


# ------------------------------------------------------------------ drives

def _old_dirs(root, keep=NO_KEEP):
    """Old month folders directly below root/<year>/ and root/<year>/raw/ (without kept ones)."""
    root = Path(root)
    out = []
    try:
        years = [p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name)]
    except OSError:
        return out
    for y in sorted(years):
        for sub in (y, y / "raw"):
            try:
                for d in sorted(sub.iterdir()):
                    rel = d.relative_to(root).as_posix()
                    if d.is_dir() and _OLD_DIR.match(d.name) and is_old_dir(rel) and rel not in keep:
                        out.append(d)
            except OSError:
                continue
    return out


def _roots(set_dir):
    """Folders holding a year/month structure: the backup folder itself, or each export folder."""
    set_dir = Path(set_dir)
    roots = [set_dir]
    cat = set_dir / CATALOG_REL
    if cat.is_file():
        try:
            db = sqlite3.connect(f"file:{cat}?mode=ro", uri=True)
            try:
                folders = [f for (f,) in db.execute("SELECT folder FROM runs")]
            finally:
                db.close()
        except sqlite3.Error:
            folders = []
        for f in folders:
            if f and "/" not in f and "\\" not in f and not f.startswith("."):
                roots.append(set_dir / f)
    return roots


def old_folders(set_dir):
    """{old month folder ('2026/02.February-photos'): number of files} of a backup folder (for a
    Grandfather-Father-Son folder: of all its export folders together)."""
    out = {}
    set_dir = Path(set_dir)
    if not set_dir.is_dir():
        return out
    for r in _roots(set_dir):
        for d in _old_dirs(r):
            n = sum(len(files) for _dp, _dn, files in os.walk(d))
            rel = d.relative_to(r).as_posix()
            out[rel] = out.get(rel, 0) + n
    return out


def needs_conversion(set_dir, keep=NO_KEEP):
    """True when the backup folder (or one of its export folders) still has old month folders
    that are not kept, or a database still lists such old paths."""
    set_dir = Path(set_dir)
    if not set_dir.is_dir():
        return False
    if any(_old_dirs(r, keep) for r in _roots(set_dir)):
        return True
    for db_rel, col in ((INDEX_REL, "rel_path"), (CATALOG_REL, "rel")):
        if _db_has_old(set_dir / db_rel, col, keep):
            return True
    return False


def _db_has_old(path, col, keep):
    if not path.is_file():
        return False
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return any(convert_rel(r, keep) for (r,) in db.execute(f"SELECT {col} FROM files"))
        finally:
            db.close()
    except sqlite3.Error:
        return False


def _move_tree(root, stats, keep):
    """Move the files of the old month folders below root into the new ones."""
    root = Path(root)
    for old in _old_dirs(root, keep):
        for dirpath, _dirs, files in os.walk(old):
            for fn in sorted(files):
                src = Path(dirpath) / fn
                rel = src.relative_to(root).as_posix()
                dst = root / convert_rel(rel, keep)
                if dst.exists():
                    stats["kept"].append(str(src))
                    continue
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(src, dst)               # same drive: a rename, nothing is copied
                    stats["moved"] += 1
                except OSError as e:
                    stats["kept"].append(f"{src} ({e})")
        for dirpath, _dirs, _files in sorted(os.walk(old), reverse=True):
            try:
                os.rmdir(dirpath)                     # only empty folders
            except OSError:
                pass


def _update_db(path, table_sql, exists, keep):
    """Give database rows the new path when the file is no longer at the old place."""
    if not path.is_file():
        return
    db = sqlite3.connect(str(path))
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        select, update = table_sql
        for row in db.execute(select).fetchall():
            *key, rel = row
            new = convert_rel(rel, keep)
            if new and not exists(*key, rel):
                db.execute(update, (new, *key, rel))
        db.commit()
    finally:
        db.close()


def convert_set(set_dir, keep=NO_KEEP):
    """Convert one backup folder ('Phone - Owner') on a drive. Returns (moved, kept paths)."""
    set_dir = Path(set_dir)
    stats = {"moved": 0, "kept": []}
    roots = _roots(set_dir)
    for r in roots:
        _move_tree(r, stats, keep)
    run_dir = {}
    cat = set_dir / CATALOG_REL
    if cat.is_file():
        db = sqlite3.connect(f"file:{cat}?mode=ro", uri=True)
        try:
            run_dir = {rid: set_dir / f for rid, f in db.execute("SELECT id, folder FROM runs")}
        finally:
            db.close()
        _update_db(cat, ("SELECT run_id, rel FROM files",
                         "UPDATE OR IGNORE files SET rel=? WHERE run_id=? AND rel=?"),
                   lambda rid, rel: rid in run_dir and (run_dir[rid] / rel).exists(), keep)
    # the index: rel_path is relative to the backup folder (simple) or to the export folder (GFS)
    _update_db(set_dir / INDEX_REL,
               ("SELECT source_path, size, rel_path FROM files",
                "UPDATE files SET rel_path=? WHERE source_path=? AND size=? AND rel_path=?"),
               lambda _s, _z, rel: any((r / rel).exists() for r in roots), keep)
    return stats["moved"], stats["kept"]


def ensure_converted(set_dir, label="", keep=None):
    """Convert a backup folder if it still has old month folders that are not kept (shows what
    it does). keep=None: the user has not chosen yet – nothing is changed."""
    set_dir = Path(set_dir)
    try:
        if keep is None:
            if old_folders(set_dir):         # (a note only – never true for kept import folders)
                ui.warn(tr("%s: the month folders still have the old names. They are changed after "
                           "you chose which ones keep their structure (asked before the next backup "
                           "or export).", label or set_dir))
            return 0, []
        if not needs_conversion(set_dir, keep):
            return 0, []
    except OSError:
        return 0, []
    ui.info(tr("%s: changing the folders to the new layout (e.g. 2026/26.02) …", label or set_dir))
    try:
        moved, kept = convert_set(set_dir, keep)
    except (OSError, sqlite3.Error) as e:   # the backup goes on; the next start continues
        ui.warn("  " + tr("The folders could not be changed to the new layout (%s) – the backup "
                          "goes on, the next start tries again.", e))
        return 0, []
    ui.info("  " + trp("%d file moved into the new folders.", "%d files moved into the new folders.",
                       moved, moved))
    for k in kept:
        ui.warn("  " + tr("Not moved (the new place is already taken): %s", k))
    return moved, kept


# ------------------------------------------------------------------ Google Drive

def convert_drive_tree(drive, files, folders, nested=False, keep=NO_KEEP):
    """Move old-layout files on Google Drive into the new folders.

    files/folders come from Drive.list_tree and are UPDATED in place. nested=True: the first path
    part is an export folder (Grandfather-Father-Son). Returns (moved, kept rels)."""
    moved, kept = 0, []
    for rel in sorted(files):
        head, inner = ("", rel)
        if nested:
            top, _, inner = rel.partition("/")
            if not inner or top.startswith("."):
                continue
            head = top + "/"
        new_inner = convert_rel(inner, keep)
        if not new_inner:
            continue
        new = head + new_inner
        if new in files:
            kept.append(rel)
            continue
        old_folder = rel.rpartition("/")[0]
        new_folder = new.rpartition("/")[0]
        pid = drive.ensure_path(folders, new_folder)
        drive.move(files[rel]["id"], folders[old_folder], pid)
        files[new] = files.pop(rel)
        moved += 1
    # empty old month folders go to the Google Drive trash (deepest first); kept ones stay
    for frel in sorted(folders, key=lambda f: -f.count("/")):
        inner = frel.partition("/")[2] if nested else frel
        if not inner or not is_old_dir(inner) or inner in keep:
            continue
        pre = frel + "/"
        if any(k.startswith(pre) for k in files) or any(f.startswith(pre) for f in folders):
            continue
        drive.trash(folders.pop(frel))
    return moved, kept


def convert_catalog(cat_path, keep=NO_KEEP):
    """New paths in a catalog (Google Drive: the files were moved before). True if changed."""
    db = sqlite3.connect(str(cat_path))
    changed = False
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        for run_id, rel in db.execute("SELECT run_id, rel FROM files").fetchall():
            new = convert_rel(rel, keep)
            if new:
                db.execute("UPDATE OR IGNORE files SET rel=? WHERE run_id=? AND rel=?",
                           (new, run_id, rel))
                changed = True
        db.commit()
    finally:
        db.close()
    return changed


def report_drive(moved, kept, what):
    if moved or kept:
        ui.info(tr("%s: changing the folders to the new layout (e.g. 2026/26.02) …", what))
        ui.info("  " + trp("%d file moved into the new folders.", "%d files moved into the new folders.",
                           moved, moved))
    for k in kept:
        ui.warn("  " + tr("Not moved (the new place is already taken): %s", k))


# ------------------------------------------------------------------ terminal version

def ask_cli(cfg, set_dirs):
    """Terminal version: before the first conversion ask which old month folders are kept.
    Returns False when the user cancels."""
    from . import config
    found = {}
    for sd in set_dirs:
        sd = Path(sd)
        for rel, n in to_choose(cfg, sd).items():
            have = found.setdefault(key_of(sd), {})
            have[rel] = max(have.get(rel, 0), n)
    for name, folders in found.items():
        rels = sorted(folders)
        ui.title(tr("New month folders for %s", name))
        ui.info(tr("The month folders get new names (e.g. 2026/02.February-photos → 2026/26.02, "
                   "photos and videos together). Folders you keep stay exactly as they are."))
        for i, rel in enumerate(rels, 1):
            ui.info(f"  {i:3d}. {rel}  " + trp("(%d file)", "(%d files)", folders[rel], folders[rel]))
        answer = ui.ask(tr("Numbers of the folders that KEEP their old name (e.g. 1,3-5; "
                           "Enter = change all, q = not now)"), default="", allow_empty=True)
        if answer.strip().lower() == "q":
            return False
        nums = ui.parse_numbers(answer, len(rels)) if answer.strip() else []
        set_decision(cfg, name, [rels[n - 1] for n in nums or []])
        config.save(cfg)
    return True
