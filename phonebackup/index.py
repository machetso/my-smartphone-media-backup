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
