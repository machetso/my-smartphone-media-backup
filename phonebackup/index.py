"""Per-destination database of what is already backed up (enables incremental backups).

Stored in <backup parent>/.phonebackup/index.sqlite on every destination drive,
so each drive knows its own state (e.g. a newly added second HDD gets everything).
"""

import sqlite3
from datetime import datetime
from pathlib import Path

INTERNAL_DIR = ".phonebackup"


class BackupIndex:
    def __init__(self, parent):
        self.parent = Path(parent)
        d = self.parent / INTERNAL_DIR
        d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(d / "index.sqlite"))
        self.db.execute("""CREATE TABLE IF NOT EXISTS files(
            source_path TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime INTEGER,
            sha256 TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            category TEXT,
            taken TEXT,
            date_source TEXT,
            backed_up_at TEXT,
            PRIMARY KEY(source_path, size))""")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_sha ON files(sha256)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_rel ON files(rel_path)")
        self.db.commit()

    def has(self, source_path, size):
        cur = self.db.execute("SELECT rel_path FROM files WHERE source_path=? AND size=?",
                              (source_path, size))
        row = cur.fetchone()
        if not row:
            return False
        # trust the database only if the file is really still there
        return (self.parent / row[0]).is_file()

    def find_by_sha(self, sha):
        for (rel,) in self.db.execute("SELECT rel_path FROM files WHERE sha256=?", (sha,)):
            if (self.parent / rel).is_file():
                return rel
        return None

    def sha_for_rel(self, rel_path, size):
        row = self.db.execute("SELECT sha256 FROM files WHERE rel_path=? AND size=? LIMIT 1",
                              (rel_path, size)).fetchone()
        return row[0] if row else None

    def add(self, source_path, size, mtime, sha, rel_path, category, taken, date_source):
        self.db.execute(
            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?)",
            (source_path, size, mtime, sha, str(rel_path).replace("\\", "/"), category,
             taken.isoformat(sep=" ", timespec="seconds") if taken else None,
             date_source, datetime.now().isoformat(sep=" ", timespec="seconds")))
        self.db.commit()

    def totals(self):
        """{category: (count, bytes)} of everything in this backup."""
        out = {}
        for cat, cnt, total in self.db.execute(
                "SELECT category, COUNT(DISTINCT rel_path), SUM(size) FROM "
                "(SELECT category, rel_path, MAX(size) AS size FROM files GROUP BY rel_path) "
                "GROUP BY category"):
            out[cat] = (cnt, total or 0)
        return out

    def close(self):
        self.db.close()


def open_readonly_lookup(parent):
    """Map rel_path -> (size, sha256) of an existing backup (used by the export)."""
    p = Path(parent) / INTERNAL_DIR / "index.sqlite"
    out = {}
    if not p.is_file():
        return out
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        for rel, size, sha in db.execute("SELECT rel_path, size, sha256 FROM files"):
            out[rel] = (size, sha)
    finally:
        db.close()
    return out


_totals_cache = {}


def backup_totals(parent):
    """(files, bytes) of a backup folder - instant from its index (each stored file once),
    otherwise by walking the folder. None if the folder is not there. Cached until the index
    changes."""
    parent = Path(parent)
    p = parent / INTERNAL_DIR / "index.sqlite"
    try:
        stamp = p.stat().st_mtime_ns
    except OSError:
        stamp = None
    key = str(parent)
    hit = _totals_cache.get(key)
    if hit and stamp is not None and hit[0] == stamp:
        return hit[1]
    if stamp is not None:
        try:
            db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                n, b = db.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM "
                                  "(SELECT rel_path, MAX(size) AS size FROM files GROUP BY rel_path)").fetchone()
            finally:
                db.close()
            _totals_cache[key] = (stamp, (int(n), int(b)))
            return int(n), int(b)
        except sqlite3.Error:
            pass
    if not parent.is_dir():
        return None
    import os
    n = b = 0
    for dirpath, dirnames, filenames in os.walk(parent):
        dirnames[:] = [d for d in dirnames if not d.startswith(".phonebackup")]
        for fn in filenames:
            try:
                b += os.stat(os.path.join(dirpath, fn)).st_size
                n += 1
            except OSError:
                pass
    return n, b


def describe_totals(t):
    from .i18n import tr, trp
    from .ui import human_size
    if not t:
        return tr("size unknown")
    return trp("%s file · %s", "%s files · %s", t[0], f"{t[0]:,}", human_size(t[1]))
