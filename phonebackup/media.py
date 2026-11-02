"""File categories and capture-date detection (EXIF / video metadata / filename / file date).

Pure standard library - no Pillow or ffmpeg needed.
"""

import os
import re
import struct
from datetime import datetime

PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif", ".avif", ".tif", ".tiff", ".bmp"}
RAW_EXT = {".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf",
           ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mrw", ".raw", ".rwl", ".iiq"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".3g2", ".mkv", ".webm", ".m4v", ".avi", ".mts", ".m2ts",
             ".mpg", ".mpeg", ".wmv", ".flv", ".vob", ".mod", ".tod", ".asf"}

CATEGORY_LABEL = {"photo": "Photos", "video": "Videos", "raw": "RAW"}


def category_for(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in RAW_EXT:
        return "raw"
    if ext in PHOTO_EXT:
        return "photo"          # includes Pixel motion photos (*.MP.jpg)
    if ext in VIDEO_EXT:
        return "video"
    return None


def _plausible(dt):
    return dt is not None and 1990 <= dt.year <= datetime.now().year + 1


# ---------------------------------------------------------------- EXIF / TIFF

def _read_ifd(buf, off, e):
    tags = {}
    if off <= 0 or off + 2 > len(buf):
        return tags
    n = struct.unpack(e + "H", buf[off:off + 2])[0]
    for i in range(min(n, 1000)):
        p = off + 2 + i * 12
        if p + 12 > len(buf):
            break
        tag, typ, cnt = struct.unpack(e + "HHI", buf[p:p + 8])
        tags[tag] = (typ, cnt, buf[p + 8:p + 12])
    return tags


def _ascii(buf, e, entry):
    typ, cnt, val = entry
    if typ != 2:
        return None
    if cnt <= 4:
        raw = val[:cnt]
    else:
        o = struct.unpack(e + "I", val)[0]
        raw = buf[o:o + cnt]
    return raw.split(b"\0")[0].decode("ascii", "ignore").strip()


def _long(e, entry):
    typ, _cnt, val = entry
    if typ == 4 or typ == 13:
        return struct.unpack(e + "I", val)[0]
    if typ == 3:
        return struct.unpack(e + "H", val[:2])[0]
    return None


def _parse_exif_dt(s):
    if not s:
        return None
    try:
        dt = datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return dt if _plausible(dt) else None


def tiff_datetime(buf):
    """Return DateTimeOriginal (or fallbacks) from a TIFF structure."""
    if len(buf) < 8:
        return None
    if buf[:2] == b"II":
        e = "<"
    elif buf[:2] == b"MM":
        e = ">"
    else:
        return None
    if struct.unpack(e + "H", buf[2:4])[0] != 42:
        return None
    ifd0 = _read_ifd(buf, struct.unpack(e + "I", buf[4:8])[0], e)
    if 0x8769 in ifd0:
        exif = _read_ifd(buf, _long(e, ifd0[0x8769]) or 0, e)
        for tag in (0x9003, 0x9004):            # DateTimeOriginal, DateTimeDigitized
            if tag in exif:
                dt = _parse_exif_dt(_ascii(buf, e, exif[tag]))
                if dt:
                    return dt
    for tag in (0x9003, 0x0132):                # some DNGs keep it in IFD0; 0x0132 = DateTime
        if tag in ifd0:
            dt = _parse_exif_dt(_ascii(buf, e, ifd0[tag]))
            if dt:
                return dt
    return None


def _jpeg_exif(path):
    with open(path, "rb") as f:
        data = f.read(512 * 1024)
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:                      # start of scan: no more metadata
            break
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i + 4:i + 2 + seg_len]
        if marker == 0xE1 and seg[:6] == b"Exif\0\0":
            dt = tiff_datetime(seg[6:])
            if dt:
                return dt
        i += 2 + seg_len
    return None


def _scan_exif(path, limit=8 * 1024 * 1024):
    """HEIC/AVIF/WEBP: find an embedded 'Exif' TIFF block by scanning the file head."""
    with open(path, "rb") as f:
        data = f.read(limit)
    start = 0
    while True:
        k = data.find(b"Exif\0\0", start)
        if k < 0:
            break
        dt = tiff_datetime(data[k + 6:])
        if dt:
            return dt
        start = k + 6
    for sig in (b"II*\0", b"MM\0*"):
        k = data.find(sig)
        if k >= 0:
            dt = tiff_datetime(data[k:])
            if dt:
                return dt
    return None


def _tiff_file(path):
    with open(path, "rb") as f:
        data = f.read(8 * 1024 * 1024)
    return tiff_datetime(data)


# ---------------------------------------------------------------- MP4 / MOV

_MP4_EPOCH_OFFSET = 2082844800  # seconds between 1904-01-01 and 1970-01-01


def _boxes(f, start, end):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        h = f.read(16)
        if len(h) < 8:
            return
        size, typ = struct.unpack(">I4s", h[:8])
        hdr = 8
        if size == 1:
            if len(h) < 16:
                return
            size = struct.unpack(">Q", h[8:16])[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            return
        yield typ, pos + hdr, pos + size
        pos += size


def mp4_datetime(path):
    with open(path, "rb") as f:
        end = os.fstat(f.fileno()).st_size
        for typ, s, e in _boxes(f, 0, end):
            if typ != b"moov":
                continue
            for ctyp, cs, _ce in _boxes(f, s, e):
                if ctyp != b"mvhd":
                    continue
                f.seek(cs)
                head = f.read(12)
                if len(head) < 12:
                    return None
                if head[0] == 1:
                    secs = struct.unpack(">Q", head[4:12])[0]
                else:
                    secs = struct.unpack(">I", head[4:8])[0]
                if secs <= _MP4_EPOCH_OFFSET:
                    return None
                try:
                    dt = datetime.fromtimestamp(secs - _MP4_EPOCH_OFFSET)  # stored as UTC -> local time
                except (OverflowError, OSError, ValueError):
                    return None
                return dt if _plausible(dt) else None
    return None


# ---------------------------------------------------------------- filename

_FN_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
    r"(?:[-_ T.]?([01]\d|2[0-3])[-_.]?([0-5]\d)[-_.]?([0-5]\d))?")


def filename_datetime(name):
    for m in _FN_RE.finditer(name):
        y, mo, d, hh, mi, ss = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
        except ValueError:
            continue
        if _plausible(dt):
            return dt
    return None


# ---------------------------------------------------------------- main entry

def detect_date(local_path, name, source_mtime):
    """Return (datetime, how) using: metadata -> filename -> file date."""
    ext = os.path.splitext(name)[1].lower()
    dt = None
    try:
        if ext in (".jpg", ".jpeg"):
            dt = _jpeg_exif(local_path) or _scan_exif(local_path, 1024 * 1024)
        elif ext in (".heic", ".heif", ".avif", ".webp", ".png"):
            dt = _scan_exif(local_path)
        elif ext in RAW_EXT or ext in (".tif", ".tiff"):
            dt = _tiff_file(local_path) or _scan_exif(local_path)
        elif ext in (".mp4", ".mov", ".3gp", ".3g2", ".m4v"):
            dt = mp4_datetime(local_path)
    except (OSError, struct.error, ValueError):
        dt = None
    if dt:
        return dt, "metadata"
    dt = filename_datetime(name)
    if dt:
        return dt, "filename"
    if source_mtime:
        try:
            dt = datetime.fromtimestamp(source_mtime)
            if _plausible(dt):
                return dt, "file date"
        except (OverflowError, OSError, ValueError):
            pass
    return datetime.now(), "unknown (backup date used)"
