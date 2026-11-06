"""Import old backups or old phones (one or more folders) into a backup.

Files are sorted into the same Year/MM.Month-photos|videos / raw structure, every file is
hashed at the source and after writing, identical files are stored only once (also against
everything already in the backup), and the source folder is only read - never changed.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .backup import backup_parent_name, perform_backup
from .copier import file_chunks, sha256_file
from .i18n import N_, tr
from .layout import OTHER_KIND, other_dir, relative_dir
from .media import category_for
from .sources import IMPORT_EXCLUDES, FolderSource, SourceFile, _dedupe


def check_import(source_root, backup_parents):
    """Raise ValueError if the combination makes no sense."""
    src = Path(source_root).resolve()
    if not src.is_dir():
        raise ValueError(tr("The folder to import does not exist:\n%s", src))
    if not backup_parents:
        raise ValueError(tr("Choose at least one copy of the backup to import into."))
    names = {Path(p).name for p in backup_parents}
    if len(names) != 1:
        raise ValueError(tr("All chosen copies must belong to the same backup."))
    for p in backup_parents:
        p = Path(p).resolve()
        if src == p or p in src.parents:
            raise ValueError(tr("The folder to import is inside the backup itself."))
        if src in p.parents:
            raise ValueError(tr("The folder to import contains the backup itself - choose the old "
                                "backup folder only, not a folder above the backup."))


def perform_import(source_root, backup_parents, cfg, interactive=True, cancel=None):
    """Returns (status, report paths, file results, verdict) like perform_backup."""
    check_import(source_root, backup_parents)
    root = Path(source_root).resolve()
    parents = [Path(p) for p in backup_parents]
    src = FolderSource(root, kind="Folder import", device_name=root.name, description=str(root),
                       key_prefix=f"import:{root.as_posix()}/", verify_source=True,
                       exclude_dirs=IMPORT_EXCLUDES)
    return perform_backup(src, None, None, [""], [p.parent for p in parents], cfg,
                          interactive=interactive, cancel=cancel, parent_name=parents[0].name,
                          mode="import", source_label=root.name)


# =========================================================================== old phone / several folders
#
# The user picks one or more folders (e.g. a copy of an old phone's internal storage and of its
# SD card). Every folder that directly contains files is listed with its counts; each listed
# folder is imported with its own files only (sub-folders are listed separately), so the user
# decides exactly which folders count. Camera folders are sorted into the normal year/month
# folders, everything else keeps its original folder under <year>/other/pictures|movies|other-files.


CAMERA, OTHER = "camera", "other"

# Folders that never hold the user's own files on a phone (app data, caches, thumbnails, trash).
OLD_PHONE_EXCLUDES = IMPORT_EXCLUDES | {"cache", "caches", "thumbnails", "lost.dir", "found.000"}
_EXCLUDED_PAIRS = {("android", "data"), ("android", "obb")}
JUNK_FILES = {"thumbs.db", "ehthumbs.db", "desktop.ini", "icon\r"}
JUNK_EXT = {".tmp", ".temp", ".part", ".partial", ".crdownload", ".thumbnail", ".thumb"}
MESSENGER_WORDS = ("whatsapp", "telegram", "signal", "viber", "threema", "messenger", "wechat")
SCREENSHOT_WORDS = ("screenshot", "screenrecord", "screen record", "bildschirmfoto")
_DCF_FOLDER = re.compile(r"^\d{3}[a-z0-9_]{5}$")      # camera folders like 100ANDRO, 101MEDIA
# File names as cameras/phones write them (Pixel, Samsung, Android, iPhone, Nikon, Sony, Fuji, ...).
# Messenger copies (IMG-20170520-WA0001.jpg) and screenshots deliberately do not match.
CAMERA_NAME = re.compile(
    r"^(pxl_\d{8}_|(img|vid|mvimg|pano|burst)_?\d{8}[_-]?\d{6}|\d{8}_\d{6}|"
    r"img_\d{4}\b|img_e?\d{4}|mov_\d{4}|_?dsc[_nf]?\d{4}|p\d{7}\b|gopr\d{4}|gh\d{6}|dji_\d{4}|"
    r"cimg\d{4}|sam_\d{4}|wp_\d{8})", re.IGNORECASE)


def is_junk_file(name):
    n = name.lower()
    return n.startswith(".") or n in JUNK_FILES or os.path.splitext(n)[1] in JUNK_EXT


def _excluded_dir(parts_lower):
    if parts_lower and (parts_lower[-1].startswith(".") or parts_lower[-1] in OLD_PHONE_EXCLUDES):
        return True
    return any((a, b) in _EXCLUDED_PAIRS for a, b in zip(parts_lower, parts_lower[1:]))


@dataclass
class FolderInfo:
    root: str           # the folder the user added
    rel: str            # folder inside it ("." = the folder itself)
    photos: int = 0     # incl. RAW
    videos: int = 0
    other: int = 0      # not photo/video (documents, audio, ...)
    camera_named: int = 0  # photos/videos whose file name looks like a camera/phone picture
    junk: int = 0       # system / temporary files (never imported)
    size: int = 0
    kind: str = OTHER   # CAMERA or OTHER (suggestion, the user can change it)
    suggested: bool = False
    note: str = ""      # why it is (not) ticked – shown text (chosen language)

    @property
    def files(self):
        return self.photos + self.videos + self.other


def guess_kind(rel, info, into_existing=False):
    """Fill info.kind / suggested / note for a folder path like 'DCIM/Camera'."""
    parts = [p.lower() for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]
    path = "/".join(parts)
    messenger = any(w in path for w in MESSENGER_WORDS)
    screenshots = any(w in path for w in SCREENSHOT_WORDS)
    has_media = info.photos + info.videos > 0
    # camera folder: DCIM / Camera / 100ANDRO ... or - for self-sorted old backups like
    # "jpgs/August 2023" - when most of its photos/videos carry camera file names (PXL_..., ...)
    named = has_media and info.camera_named * 2 >= info.photos + info.videos
    camera = not (messenger or screenshots) and (
        "dcim" in parts or named or (parts and (parts[-1] == "camera" or _DCF_FOLDER.match(parts[-1]))))
    if into_existing:
        # adding to an existing backup: like before, every photo/video goes into the month folders
        info.kind, info.suggested = CAMERA, has_media
        info.note = "" if has_media else tr("no photos/videos")
        return info
    info.kind = CAMERA if camera else OTHER
    if messenger:
        info.suggested, info.note = False, tr("messenger media (often duplicates and stickers)")
    elif screenshots:
        info.suggested, info.note = False, tr("screenshots")
    else:
        info.suggested = info.files > 0
        info.note = ((tr("camera") if not named or "dcim" in parts else tr("camera (file names)"))
                     if camera else "")
    return info


def scan_folder(root, into_existing=False, cancel=None):
    """List every folder below root that directly contains files (junk folders left out)."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        if cancel is not None and cancel.is_set():
            break
        rel_path = Path(dirpath).relative_to(root)
        rel_parts = [p.lower() for p in rel_path.parts]
        dirnames[:] = sorted(d for d in dirnames if not _excluded_dir(rel_parts + [d.lower()]))
        info = FolderInfo(str(root), rel_path.as_posix() if rel_path.parts else ".")
        for fn in filenames:
            if is_junk_file(fn):
                info.junk += 1
                continue
            cat = category_for(fn)
            if cat == "video":
                info.videos += 1
            elif cat:
                info.photos += 1
            else:
                info.other += 1
            if cat and CAMERA_NAME.match(fn):
                info.camera_named += 1
            try:
                info.size += os.stat(os.path.join(dirpath, fn)).st_size
            except OSError:
                pass
        if info.files:
            out.append(guess_kind(info.rel, info, into_existing))
    return out


class SelectionSource:
    """Files directly inside the chosen folders of one or more source folders (read only)."""

    def __init__(self, selections, device_name="", other_files=True):
        """selections: iterable of (root, rel, kind) - rel "." means the root folder itself."""
        self.items, seen, roots = [], set(), []
        for root, rel, kind in selections:
            root = Path(root).resolve()
            rel = str(rel).replace("\\", "/").strip("/") or "."
            if (root, rel) in seen:
                continue
            seen.add((root, rel))
            self.items.append((root, rel, kind))
            if root not in roots:
                roots.append(root)
        self.roots = roots
        self.root = roots[0] if roots else Path(".")
        self.kind = "Folder import"
        self.device_name = device_name
        self.serial = ""
        self.description = "; ".join(str(r) for r in roots)
        self.folders_text = " + ".join(str(r) for r in roots)
        self.fallback_reason = None
        self.supports_phone_hash = True          # every source file is hashed separately
        self.other_files = other_files
        self.skip_text = (N_("system/temporary file") if other_files      # English, shown with tr()
                          else N_("not a photo/video file, or a system/temporary file"))
        self._info = {}

    def list_files(self, folders=None):
        files, missing = [], []
        for root, rel, kind in self.items:
            base = root if rel == "." else root / rel
            if not base.is_dir():
                missing.append(str(base))
                continue
            original = root.name if rel == "." else rel
            try:
                entries = sorted(os.scandir(base), key=lambda e: e.name)
            except OSError:
                missing.append(str(base))
                continue
            for e in entries:
                if e.name.startswith("."):
                    continue
                try:
                    if not e.is_file():
                        continue
                    st = e.stat()
                except OSError:
                    continue
                r = Path(e.path).as_posix()
                self._info[r] = (kind, original, is_junk_file(e.name))
                files.append(SourceFile(r, st.st_size, int(st.st_mtime), "import:" + r))
        return _dedupe(files), missing

    def category_of(self, sf):
        kind, _original, junk = self._info.get(sf.rel, (OTHER, "", False))
        if junk:
            return None
        cat = category_for(sf.name)
        if kind == CAMERA and cat:
            return cat
        if cat is None:
            return "other-file" if self.other_files else None
        return "other-video" if cat == "video" else "other-photo"

    def placement(self, sf, taken, cat):
        if cat in OTHER_KIND:
            return other_dir(taken, cat, self._info.get(sf.rel, (OTHER, "", False))[1])
        return relative_dir(taken, cat)

    def phone_hashes(self, rels):
        out = {}
        for r in rels:
            try:
                out[r] = sha256_file(Path(r))
            except OSError:
                pass
        return out

    def open_stream(self, sf):
        return file_chunks(Path(sf.rel))

    def is_connected(self):
        return all(r.is_dir() for r in self.roots)

    def close(self):
        pass


def check_selection(selections, backup_parents):
    """Raise ValueError if the chosen folders cannot be imported into these backup folders."""
    if not selections:
        raise ValueError(tr("Tick at least one folder to import."))
    if not backup_parents:
        raise ValueError(tr("Choose at least one destination."))
    for root in {Path(r).resolve() for r, _, _ in selections}:
        if not root.is_dir():
            raise ValueError(tr("The folder to import does not exist:\n%s", root))
        for p in backup_parents:
            p = Path(p).resolve()
            if root == p or p in root.parents:
                raise ValueError(tr("The folder to import is inside the backup itself:\n%s", root))
            if root in p.parents:
                raise ValueError(tr("The folder to import contains the backup itself:\n%s\n"
                                    "Choose the old backup folder only, not a folder above the backup.",
                                    root))


def perform_old_phone_import(selections, phone_name, owner, dest_bases, cfg, other_files=True,
                             interactive=True, cancel=None):
    """Import the chosen folders of an old phone as a backup of its own ('Phone - Owner')."""
    phone_name, owner = phone_name.strip(), owner.strip()
    if not phone_name or not owner:
        raise ValueError(tr("Enter the name of the old phone and the owner."))
    parent_name = backup_parent_name(phone_name, owner)
    check_selection(selections, [Path(b) / parent_name for b in dest_bases])
    src = SelectionSource(selections, device_name=phone_name, other_files=other_files)
    return perform_backup(src, phone_name, owner, [""], [Path(b) for b in dest_bases], cfg,
                          interactive=interactive, cancel=cancel, parent_name=parent_name,
                          mode="import", source_label=f"{phone_name} {owner}")


def perform_selection_import(selections, backup_parents, cfg, other_files=False,
                             interactive=True, cancel=None):
    """Import the chosen folders into an existing backup (all ticked copies of it)."""
    check_selection(selections, backup_parents)
    names = {Path(p).name for p in backup_parents}
    if len(names) != 1:
        raise ValueError(tr("All chosen copies must belong to the same backup."))
    src = SelectionSource(selections, other_files=other_files)
    label = src.roots[0].name if len(src.roots) == 1 else f"{len(src.roots)} folders"   # report file name: English
    parents = [Path(p) for p in backup_parents]
    return perform_backup(src, None, None, [""], [p.parent for p in parents], cfg,
                          interactive=interactive, cancel=cancel, parent_name=parents[0].name,
                          mode="import", source_label=label)


# =========================================================================== correct an earlier import

def resort_camera_files(parent, dry_run=False, cancel=None, camera_names_only=True):
    """Move photos/videos with camera file names from <year>/other/pictures|movies into the normal
    year/month (and raw/) folders of the same backup - for old-phone imports made before camera
    folders were recognised by their file names.

    Files are only renamed on the same drive (content untouched, size checked), the index is
    updated, nothing is deleted. A list of all moves is written next to the reports.
    camera_names_only=False moves every photo/video from other/ (when all of it came from camera folders).
    Returns [(old rel path, new rel path)].
    """
    import csv
    import sqlite3
    from datetime import datetime

    from .index import INTERNAL_DIR
    from .layout import unique_path

    parent = Path(parent)
    db = sqlite3.connect(str(parent / INTERNAL_DIR / "index.sqlite"))
    rows = db.execute("SELECT rel_path, MAX(taken), MAX(size) FROM files "
                      "WHERE category IN ('other-photo', 'other-video') GROUP BY rel_path").fetchall()
    moves = []
    try:
        for rel, taken, size in rows:
            if cancel is not None and cancel.is_set():
                break
            name = Path(rel).name
            cat = category_for(name)
            if not cat or (camera_names_only and not CAMERA_NAME.match(name)):
                continue
            src = parent / rel
            if not src.is_file() or src.stat().st_size != size:
                continue
            dt = datetime.fromisoformat(taken) if taken else datetime.fromtimestamp(src.stat().st_mtime)
            dst = unique_path(parent / relative_dir(dt, cat) / name)
            new_rel = dst.relative_to(parent).as_posix()
            moves.append((rel, new_rel))
            if dry_run:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)                      # same drive: only the directory entry changes
            if dst.stat().st_size != size:
                raise OSError(tr("size changed while moving %s", rel))
            db.execute("UPDATE files SET rel_path=?, category=? WHERE rel_path=?", (new_rel, cat, rel))
            if len(moves) % 200 == 0:
                db.commit()
        db.commit()
    finally:
        db.close()
    if moves and not dry_run:
        # remove the folders under <year>/other that are empty now (folders only, never files)
        for year_other in parent.glob("[0-9][0-9][0-9][0-9]/other"):
            for d in sorted((p for p in year_other.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                try:
                    d.rmdir()
                except OSError:
                    pass
            try:
                year_other.rmdir()
            except OSError:
                pass
        log = parent / f"Resorted camera files {datetime.now():%Y-%m-%d %H-%M}.csv"
        with open(log, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([tr("Old location"), tr("New location")])
            w.writerows(moves)
    return moves
