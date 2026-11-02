"""Second backup: export a backup folder to another drive as full / differential / incremental
runs, and restore a complete copy from such a chain.

Target layout:
  <target base>/<Phone - Owner>/2026-11-02_14-30-00_full/2026/01.January-photos/...
                               /2026-11-20_09-12-45_incremental/...
                               /2026-12-01_18-03-10_differential/...
                               /.phonebackup-export/catalog.sqlite

full          = everything
differential  = everything new/changed since the last FULL export
incremental   = everything new/changed since the last export of ANY type
"""

import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import ui
from .copier import Cancelled, file_chunks, stream_copy
from .index import INTERNAL_DIR, open_readonly_lookup
from .report import unique_basename, write_reports

EXPORT_DIR = ".phonebackup-export"
MODES = ("full", "differential", "incremental")


@dataclass
class Run:
    id: int
    type: str
    folder: str
    started: str
    finished: str
    status: str


class Catalog:
    def __init__(self, target_parent):
        self.parent = Path(target_parent)
        d = self.parent / EXPORT_DIR
        d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(d / "catalog.sqlite"))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT,
                folder TEXT, started TEXT, finished TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS files(run_id INTEGER, rel TEXT, size INTEGER,
                mtime INTEGER, sha256 TEXT, PRIMARY KEY(run_id, rel));""")
        self.db.commit()

    def runs(self):
        return [Run(*r) for r in self.db.execute(
            "SELECT id,type,folder,started,finished,status FROM runs ORDER BY id")]

    def last_full(self):
        fulls = [r for r in self.runs() if r.type == "full" and r.status == "COMPLETED"]
        return fulls[-1] if fulls else None

    def files_of(self, run_ids):
        out = {}
        for rid in run_ids:
            for rel, size, mtime, sha in self.db.execute(
                    "SELECT rel,size,mtime,sha256 FROM files WHERE run_id=?", (rid,)):
                out[rel] = (size, mtime, sha)
        return out

    def baseline(self, mode):
        """Files the new run can skip. None = not possible (no full export yet)."""
        if mode == "full":
            return {}
        full = self.last_full()
        if full is None:
            return None
        if mode == "differential":
            return self.files_of([full.id])
        return self.files_of([r.id for r in self.runs() if r.id >= full.id])

    def new_run(self, mode, folder, started):
        cur = self.db.execute("INSERT INTO runs(type,folder,started,status) VALUES (?,?,?,?)",
                              (mode, folder, started.isoformat(sep=" ", timespec="seconds"), "RUNNING"))
        self.db.commit()
        return cur.lastrowid

    def add_file(self, run_id, rel, size, mtime, sha):
        self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)", (run_id, rel, size, mtime, sha))
        self.db.commit()

    def finish_run(self, run_id, status):
        self.db.execute("UPDATE runs SET finished=?, status=? WHERE id=?",
                        (datetime.now().isoformat(sep=" ", timespec="seconds"), status, run_id))
        self.db.commit()

    def close(self):
        self.db.close()


def has_catalog(path):
    return (Path(path) / EXPORT_DIR / "catalog.sqlite").is_file()


def scan_backup(parent):
    """All files of a backup folder (without internal data). rel -> (size, mtime)."""
    parent = Path(parent)
    out = {}
    for dirpath, dirnames, filenames in os.walk(parent):
        dirnames[:] = sorted(d for d in dirnames if d not in (INTERNAL_DIR, EXPORT_DIR))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.relative_to(parent).as_posix()] = (st.st_size, int(st.st_mtime))
    return out


def _category(rel):
    r = rel.lower()
    if r.split("/")[1:2] == ["other"]:
        return "other"
    if "/raw/" in r:
        return "raw"
    if "-photos/" in r:
        return "photo"
    if "-videos/" in r:
        return "video"
    return "other"


def _verified_copy(src, dst_dir_tmp, final, expected_sha, cfg, prog, cancel=None):
    """Copy one file with read-back verification. Returns (status, sha)."""
    tmp = Path(dst_dir_tmp) / f"{uuid.uuid4().hex}.part"
    try:
        sha, n, (w,) = stream_copy(file_chunks(src), [tmp], fsync=cfg.get("fsync", True),
                                   on_bytes=lambda b: prog.update(add_bytes=b), cancel=cancel)
    except OSError as e:
        return f"ERROR: cannot read source ({e})", None
    if w.error or w.sha256 != sha:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return f"ERROR: {'write failed: ' + w.error if w.error else 'verification failed'}", None
    final = Path(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, final)
    st = os.stat(src)
    try:
        os.utime(final, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    if expected_sha and expected_sha != sha:
        return ("WARNING: copied, but the source file differs from the SHA-256 recorded when it "
                "was backed up - the source drive may be damaged"), sha
    return "OK - copied and verified", sha


def perform_export(source_parent, target_base, mode, cfg, cancel=None):
    source_parent = Path(source_parent)
    target_parent = Path(target_base) / source_parent.name
    cat = Catalog(target_parent)
    baseline = cat.baseline(mode)
    if baseline is None:
        cat.close()
        raise ValueError("A differential or incremental export needs a full export first.")
    full = cat.last_full()
    started = datetime.now()
    t0 = time.monotonic()
    folder = f"{started:%Y-%m-%d_%H-%M-%S}_{mode}"
    n = 2
    while (target_parent / folder).exists():
        folder = f"{started:%Y-%m-%d_%H-%M-%S}_{mode}_{n}"
        n += 1
    run_dir = target_parent / folder
    tmp = target_parent / EXPORT_DIR / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    ui.info("Scanning the backup folder ...")
    current = scan_backup(source_parent)
    known = open_readonly_lookup(source_parent)
    todo = [(rel, sz, mt) for rel, (sz, mt) in sorted(current.items())
            if rel not in baseline or baseline[rel][0] != sz or baseline[rel][1] != mt]
    total = sum(sz for _, sz, _ in todo)
    ui.info(f"  {len(current)} files in the backup, {len(todo)} to export ({ui.human_size(total)}).")
    if todo:
        free = shutil.disk_usage(target_parent).free
        if total > free:
            cat.close()
            raise OSError(f"not enough space on the target: {ui.human_size(free)} free, "
                          f"{ui.human_size(total)} needed")

    run_id = cat.new_run(mode, folder, started)
    run_dir.mkdir(parents=True, exist_ok=True)
    prog = ui.Progress(len(todo), total)
    rows, status, errors, warnings = [], "COMPLETED", 0, 0
    by_cat = {}
    try:
        for i, (rel, sz, mt) in enumerate(todo, 1):
            k = known.get(rel)
            expected = k[1] if k and k[0] == sz else None
            st, sha = _verified_copy(source_parent / rel, tmp, run_dir / rel, expected, cfg, prog, cancel)
            if sha:
                cat.add_file(run_id, rel, sz, mt, sha)
                c = _category(rel)
                by_cat.setdefault(c, [0, 0])
                by_cat[c][0] += 1
                by_cat[c][1] += sz
            if st.startswith("ERROR"):
                errors += 1
            elif st.startswith("WARNING"):
                warnings += 1
            rows.append([i, Path(rel).name, _category(rel), ui.human_size(sz), sz, rel, st,
                         sha or "", f"{folder}/{rel}" if sha else ""])
            prog.update(files_done=i, current=Path(rel).name)
    except (KeyboardInterrupt, Cancelled):
        status = "CANCELLED by user"
    finally:
        prog.finish()
        shutil.rmtree(tmp, ignore_errors=True)
    if status == "COMPLETED" and errors:
        status = "COMPLETED WITH ERRORS"
    cat.finish_run(run_id, status)
    cat.close()

    duration = time.monotonic() - t0
    ok = status == "COMPLETED" and not warnings
    n = sum(v[0] for v in by_cat.values())
    b = sum(v[1] for v in by_cat.values())
    verdict = (f"EVERYTHING EXPORTED CORRECTLY - {n} files ({ui.human_size(b)}) verified with SHA-256."
               if ok else f"ATTENTION - {status}, {errors} error(s), {warnings} warning(s)")
    if mode == "full":
        basis = "none (full export of everything)"
    elif mode == "differential":
        basis = f"last full export: {full.folder}"
    else:
        basis = f"all exports since the last full export ({full.folder})"
    sections = [
        ("General", [("Export type", mode), ("Status", status),
                     ("Source (backup folder)", str(source_parent)),
                     ("Target folder of this run", str(run_dir)),
                     ("Compared with", basis),
                     ("Started", f"{started:%Y-%m-%d %H:%M:%S}"),
                     ("Duration", ui.human_duration(duration))]),
        ("Data exported", [("Total", f"{n} files, {ui.human_size(b)}")] +
         [(c.capitalize(), f"{v[0]} files, {ui.human_size(v[1])}") for c, v in sorted(by_cat.items())] +
         [("Files in backup", str(len(current))), ("Unchanged (not exported)", str(len(current) - len(todo))),
          ("Errors", str(errors)), ("Warnings", str(warnings))]),
    ]
    columns = ["Nr", "File", "Type", "Size", "Bytes", "Path in backup", "Status", "SHA-256", "Location"]
    base = unique_basename(run_dir, f"Export {source_parent.name} {mode}", started)
    paths = write_reports(run_dir, base, f"Export ({mode}) {source_parent.name} - {started:%Y-%m-%d %H:%M}",
                          ok, verdict, sections, columns, rows)
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict


def restore_chain(cat, upto_id):
    runs = [r for r in cat.runs() if r.id <= upto_id]
    fulls = [r for r in runs if r.type == "full" and r.status == "COMPLETED"]
    if not fulls:
        return []
    full = fulls[-1]
    # Full + every later run. Each file is restored only once (from the newest run that
    # contains it), so this is correct even if a differential run was interrupted.
    return [full] + [r for r in runs if r.id > full.id]


def perform_restore(target_parent, upto_id, restore_dir, cfg, cancel=None):
    target_parent = Path(target_parent)
    restore_dir = Path(restore_dir)
    cat = Catalog(target_parent)
    chain = restore_chain(cat, upto_id)
    if not chain:
        cat.close()
        raise ValueError("No completed full export found - nothing to restore from.")
    plan = {}
    for run in chain:                                  # later runs win
        for rel, (sz, _mt, sha) in cat.files_of([run.id]).items():
            plan[rel] = (run, sz, sha)
    cat.close()
    started = datetime.now()
    t0 = time.monotonic()
    tmp = restore_dir / ".restore-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    total = sum(sz for _, sz, _ in plan.values())
    ui.info(f"Restoring {len(plan)} files ({ui.human_size(total)}) from: "
            + " + ".join(r.folder for r in chain))
    prog = ui.Progress(len(plan), total)
    rows, errors, status = [], 0, "COMPLETED"
    try:
        for i, (rel, (run, sz, sha)) in enumerate(sorted(plan.items()), 1):
            st, got = _verified_copy(target_parent / run.folder / rel, tmp, restore_dir / rel, sha, cfg,
                                     prog, cancel)
            if not st.startswith("OK"):
                errors += 1
            rows.append([i, Path(rel).name, ui.human_size(sz), rel, run.folder, st, got or ""])
            prog.update(files_done=i, current=Path(rel).name)
    except (KeyboardInterrupt, Cancelled):
        status = "CANCELLED by user"
    finally:
        prog.finish()
        shutil.rmtree(tmp, ignore_errors=True)
    ok = status == "COMPLETED" and not errors
    verdict = (f"RESTORE OK - {len(rows)} files restored and verified." if ok
               else f"ATTENTION - {status}, {errors} file(s) with problems")
    sections = [("General", [("Restored from", str(target_parent)),
                             ("Used exports", "\n".join(f"{r.type}: {r.folder}" for r in chain)),
                             ("Restored to", str(restore_dir)),
                             ("Duration", ui.human_duration(time.monotonic() - t0))])]
    base = unique_basename(restore_dir, "Restore report", started)
    paths = write_reports(restore_dir, base, f"Restore {target_parent.name} - {started:%Y-%m-%d %H:%M}",
                          ok, verdict, sections,
                          ["Nr", "File", "Size", "Path", "Taken from export", "Status", "SHA-256"], rows)
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict
