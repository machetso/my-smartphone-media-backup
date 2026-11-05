"""Destination folder layout:

<base>/<Phone - Owner>/2026/01.January-photos
                           /01.January-videos
                           /raw/01.January-raw
                           /other/pictures|movies|other-files/<original folder>/   (old phone imports)
                    /Pictures/Screenshots/…      ("keep folder structure" for non-camera folders)
"""

import os
import re
from pathlib import Path

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

KIND = {"photo": "photos", "video": "videos", "raw": "raw"}
OTHER_KIND = {"other-photo": "pictures", "other-video": "movies", "other-file": "other-files"}


def month_folder(month, category):
    return f"{month:02d}.{MONTHS[month - 1]}-{KIND[category]}"


def relative_dir(dt, category):
    """Folder (relative to the backup parent folder) for a file taken at dt."""
    year = f"{dt.year:04d}"
    if category == "raw":
        return Path(year) / "raw" / month_folder(dt.month, "raw")
    return Path(year) / month_folder(dt.month, category)


def other_dir(dt, category, original_folder):
    """Non-camera files of an old phone: <year>/other/pictures|movies|other-files/<original folder>.

    original_folder is a relative path like "WhatsApp/Media/WhatsApp Images" (any separator).
    """
    d = Path(f"{dt.year:04d}") / "other" / OTHER_KIND[category]
    for part in str(original_folder).replace("\\", "/").split("/"):
        if part not in ("", ".", ".."):
            d = d / safe_name(part)
    return d


def is_camera_folder(folder):
    """The phone's camera folder: DCIM/Camera (and its sub-folders) or DCIM/100ANDRO-style folders.
    Screenshots in DCIM/Screenshots (Samsung) are not camera pictures."""
    parts = [p for p in str(folder).replace("\\", "/").split("/") if p]
    if len(parts) < 2 or parts[0].upper() != "DCIM":
        return False
    sub = parts[1].lower()
    return sub == "camera" or bool(re.fullmatch(r"\d{3}[a-z_]*", sub))


def structure_dir(rel):
    """Keep the phone's folders: 'Pictures/Screenshots/x.png' → Pictures/Screenshots."""
    d = Path()
    for part in str(rel).replace("\\", "/").split("/")[:-1]:
        if part not in ("", ".", ".."):
            d = d / safe_name(part)
    return d


def keep_structure_placement(folders):
    """placement(sf, taken, cat) for perform_backup: files in the chosen non-camera folders keep
    their folder path, everything else goes into the year/month folders."""
    keep = [f.strip("/") for f in folders if f.strip("/") and not is_camera_folder(f)]

    def placement(sf, taken, cat):
        rel = sf.rel.replace("\\", "/")
        if any(rel == k or rel.startswith(k + "/") for k in keep):
            return structure_dir(rel)
        return relative_dir(taken, cat)

    return placement


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text):
    """Make a string usable as a file/folder name on Windows and Linux."""
    text = _BAD.sub("_", str(text)).strip().rstrip(". ")
    return text or "Unknown"


def unique_path(path, taken=None):
    """name.jpg -> name_1.jpg, name_2.jpg ... until free. taken(path) -> bool (default: exists)."""
    path = Path(path)
    taken = taken or (lambda p: p.exists())
    if not taken(path):
        return path
    stem, suffix = path.stem, path.suffix
    # keep double extensions like .MP.jpg intact
    if stem.lower().endswith(".mp"):
        stem, suffix = stem[:-3], stem[-3:] + suffix
    i = 1
    while True:
        cand = path.with_name(f"{stem}_{i}{suffix}")
        if not taken(cand):
            return cand
        i += 1


def same_volume(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False
