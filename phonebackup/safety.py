"""Checks for data that comes from OUTSIDE the program (security review 2026-11-06).

A catalog (`catalog.sqlite` on an export drive or on Google Drive), folder names on Google Drive
and file names from a phone can be changed by someone else. Before such a value becomes part of
a local path or is deleted, it goes through one of these functions.
"""

import re
from pathlib import Path, PurePosixPath

# an export / GFS run folder: 2026-11-05_13-59-03_full  (optionally _2, _3 … when taken)
RUN_FOLDER = re.compile(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_(full|differential|incremental)(_\d+)?")
_WIN_DRIVE = re.compile(r"^[A-Za-z]:")


def safe_rel(rel):
    """A relative path below a folder ('2026/01.January-photos/x.jpg') or None when it could
    leave that folder: absolute, drive letter, backslash, '..', empty or '.' parts, NUL."""
    if not isinstance(rel, str) or not rel or "\\" in rel or "\0" in rel or _WIN_DRIVE.match(rel):
        return None
    p = PurePosixPath(rel)
    if p.is_absolute() or any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    return p.as_posix()


def inside(base, rel):
    """base/rel as a Path, only if it really stays inside base (also after symlinks); else None."""
    rel = safe_rel(rel)
    if rel is None:
        return None
    base = Path(base)
    target = base / rel
    try:
        target.resolve().relative_to(base.resolve())       # (Python 3.8: no is_relative_to)
    except (OSError, ValueError):
        return None
    return target


def valid_run_folder(name):
    return isinstance(name, str) and RUN_FOLDER.fullmatch(name) is not None


def safe_component(name):
    """A single folder name from outside (e.g. a folder name on Google Drive) – or None."""
    if not isinstance(name, str) or not name.strip() or name in (".", "..") or any(
            c in name for c in "/\\\0:") or name.startswith("."):
        return None
    return name


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value):
    """Spreadsheet programs run cells that start with = + - @ as formulas (CSV injection):
    such texts get a leading apostrophe. Numbers stay numbers."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value
