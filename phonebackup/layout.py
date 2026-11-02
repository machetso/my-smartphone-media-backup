"""Destination folder layout:

<base>/<Phone - Owner>/2026/01.January-photos
                           /01.January-videos
                           /raw/01.January-raw
                           /other/pictures|movies|other-files/<original folder>/   (old phone imports)
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


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text):
    """Make a string usable as a file/folder name on Windows and Linux."""
    text = _BAD.sub("_", str(text)).strip().rstrip(". ")
    return text or "Unknown"


def unique_path(path):
    """name.jpg -> name_1.jpg, name_2.jpg ... until free."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    # keep double extensions like .MP.jpg intact
    if stem.lower().endswith(".mp"):
        stem, suffix = stem[:-3], stem[-3:] + suffix
    i = 1
    while True:
        cand = path.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def same_volume(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False
