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

from . import gfs, ui
from .copier import Cancelled, file_chunks, stream_copy
from .i18n import tr, trp
from .index import INTERNAL_DIR, open_readonly_lookup
from .report import both, unique_basename, write_reports
from .safety import inside, safe_rel, valid_run_folder

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
        try:        # a catalog from a drive / Google Drive is not trusted: no triggers/views run
            self.db.execute("PRAGMA trusted_schema=OFF")
        except sqlite3.Error:
            pass
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT,
                folder TEXT, started TEXT, finished TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS files(run_id INTEGER, rel TEXT, size INTEGER,
                mtime INTEGER, sha256 TEXT, PRIMARY KEY(run_id, rel));""")
        self.db.commit()
        self._last_commit = time.monotonic()

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
        runs = gfs.active(self.runs())
        # incremental: the current state = the restore chain of the newest export
        return self.files_of([r.id for r in gfs.chain(runs, runs[-1].id)]) if runs else {}

    def drop_run(self, run_id):
        """Forget an empty run (nothing was written)."""
        self.db.execute("DELETE FROM files WHERE run_id=?", (run_id,))
        self.db.execute("DELETE FROM runs WHERE id=?", (run_id,))
        self.db.commit()

    def mark_removed(self, run_id):
        self.db.execute("UPDATE runs SET status=? WHERE id=?", (gfs.REMOVED, run_id))
        self.db.commit()

    def new_run(self, mode, folder, started):
        cur = self.db.execute("INSERT INTO runs(type,folder,started,status) VALUES (?,?,?,?)",
                              (mode, folder, started.isoformat(sep=" ", timespec="seconds"), "RUNNING"))
        self.db.commit()
        return cur.lastrowid

    def add_file(self, run_id, rel, size, mtime, sha):
        self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)", (run_id, rel, size, mtime, sha))
        now = time.monotonic()                 # at most one commit (= several fsyncs) per second
        if now - self._last_commit >= 1.0:
            self.db.commit()
            self._last_commit = now

    def finish_run(self, run_id, status):
        self.db.execute("UPDATE runs SET finished=?, status=? WHERE id=?",
                        (datetime.now().isoformat(sep=" ", timespec="seconds"), status, run_id))
        self.db.commit()

    def close(self):
        self.db.commit()          # sqlite3 throws away what is not committed when closing
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


def _verified_copy(src, dst_dir_tmp, final, expected_sha, cfg, prog, cancel=None, overwrite=False):
    """Copy one file with read-back verification. Returns (status, sha).
    Never raises for a single file (a too long name, a disk error … becomes an ERROR row) and,
    unless `overwrite`, never replaces an existing file (e.g. IMG.jpg vs IMG.JPG on exFAT)."""
    final = Path(final)
    if not overwrite and final.exists():
        return both.tr("ERROR: a file with this name is already there (names that differ only in "
                       "upper/lower case?) - not overwritten"), None
    tmp = Path(dst_dir_tmp) / f"{uuid.uuid4().hex}.part"
    try:
        sha, n, (w,) = stream_copy(file_chunks(src), [tmp], fsync=cfg.get("fsync", True),
                                   on_bytes=lambda b: prog.update(add_bytes=b), cancel=cancel)
    except OSError as e:
        return both.tr("ERROR: cannot read source (%s)", e), None
    if w.error or w.sha256 != sha:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return (both.tr("ERROR: write failed: %s", w.error) if w.error
                else both.tr("ERROR: verification failed")), None
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        if not overwrite and final.exists():
            raise FileExistsError(tr("a file with this name is already there - not overwritten"))
        os.replace(tmp, final)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return both.tr("ERROR: cannot write the file (%s)", e), None
    try:
        st = os.stat(src)
        os.utime(final, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    if expected_sha and expected_sha != sha:
        return both.tr("WARNING: copied, but the source file differs from the SHA-256 recorded when "
                       "it was backed up - the source drive may be damaged"), sha
    return both.tr("OK - copied and verified"), sha


def perform_export(source_parent, target_base, mode, cfg, cancel=None, now=None):
    source_parent = Path(source_parent)
    target_parent = Path(target_base) / source_parent.name
    cat = Catalog(target_parent)
    chosen_by = None
    if mode == "auto":                         # Grandfather-Father-Son decides
        mode, why = gfs.choose(cat.runs(), now)
        chosen_by = tr("Grandfather-Father-Son scheme: %s (%s) because %s", tr(gfs.ROLE[mode]),
                       gfs.mode_name(mode), why)
        ui.info(chosen_by)
    baseline = cat.baseline(mode)
    if baseline is None:
        cat.close()
        raise ValueError(tr("A differential or incremental export needs a full export first."))
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

    ui.info(tr("Scanning the backup folder ..."))
    current = scan_backup(source_parent)
    known = open_readonly_lookup(source_parent)
    todo = [(rel, sz, mt) for rel, (sz, mt) in sorted(current.items())
            if rel not in baseline or baseline[rel][0] != sz or baseline[rel][1] != mt]
    total = sum(sz for _, sz, _ in todo)
    ui.info("  " + trp("%d file in the backup, %d to export (%s).", "%d files in the backup, %d to export (%s).",
                       len(current), len(current), len(todo), ui.human_size(total)))
    if todo:
        free = shutil.disk_usage(target_parent).free
        if total > free:
            cat.close()
            raise OSError(tr("not enough space on the target: %s free, %s needed",
                             ui.human_size(free), ui.human_size(total)))

    run_id = cat.new_run(mode, folder, started)
    run_dir.mkdir(parents=True, exist_ok=True)
    prog = ui.Progress(len(todo), total)
    rows, status, errors, warnings = [], "COMPLETED", 0, 0
    by_cat = {}
    try:
        for i, (rel, sz, mt) in enumerate(todo, 1):
            k = known.get(rel)
            expected = k[1] if k and k[0] == sz else None
            token = prog.begin(Path(rel).name)
            try:
                st, sha = _verified_copy(source_parent / rel, tmp, run_dir / rel, expected, cfg, prog, cancel)
            finally:
                prog.end(token)
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
            rows.append([i, Path(rel).name, tr(_category(rel)), ui.human_size(sz), sz, rel, st,
                         sha or "", f"{folder}/{rel}" if sha else ""])
    except (KeyboardInterrupt, Cancelled):
        status = "CANCELLED by user"
    except Exception as e:  # noqa: BLE001 - the run must never stay RUNNING without a report
        status = f"STOPPED - {type(e).__name__}: {e}"
        ui.error(tr("Export stopped: %s", e))
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
    verdict = (both.trp("EVERYTHING EXPORTED CORRECTLY - %d file (%s) verified with SHA-256.",
                        "EVERYTHING EXPORTED CORRECTLY - %d files (%s) verified with SHA-256.",
                        n, n, ui.human_size(b))
               if ok else _attention(status, errors, warnings))
    if mode == "full":
        basis = tr("none (full export of everything)")
    elif mode == "differential":
        basis = tr("last full export: %s", full.folder)
    else:
        basis = tr("the current state since the last full export (%s)", full.folder)

    def files_size(k, size):
        return trp("%d file, %s", "%d files, %s", k, k, ui.human_size(size))

    sections = [
        (tr("General"), [(tr("Export type"), tr("%s – %s", gfs.mode_name(mode), tr(gfs.ROLE[mode]))),
                         (tr("Chosen by"), chosen_by or tr("manual choice")), (tr("Status"), status),
                         (tr("Source (backup folder)"), str(source_parent)),
                         (tr("Target folder of this run"), str(run_dir)),
                         (tr("Compared with"), basis),
                         (tr("Started"), f"{started:%Y-%m-%d %H:%M:%S}"),
                         (tr("Duration"), ui.human_duration(duration)),
                         (tr("Average speed"), tr("%s/s", ui.human_size(b / duration if duration > 0 else 0)))]),
        (tr("Data exported"), [(tr("Total"), files_size(n, b))] +
         [(tr(c.capitalize()), files_size(v[0], v[1])) for c, v in sorted(by_cat.items())] +
         [(tr("Files in backup"), str(len(current))),
          (tr("Unchanged (not exported)"), str(len(current) - len(todo))),
          (tr("Errors"), str(errors)), (tr("Warnings"), str(warnings))]),
    ]
    columns = [tr("Nr"), tr("File"), tr("Type"), tr("Size"), tr("Bytes"), tr("Path in backup"), tr("Status"),
               tr("SHA-256"), tr("Location")]
    # file name English, title inside translated
    base = unique_basename(run_dir, f"Export {source_parent.name} {mode}", started)
    paths = write_reports(run_dir, base, tr("Export (%s) %s - %s", gfs.mode_name(mode), source_parent.name,
                                            f"{started:%Y-%m-%d %H:%M}"),
                          ok, verdict, sections, columns, rows)
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict


def _attention(status, errors, warnings):
    """Verdict of an export that did not go perfectly (English value + shown text)."""
    return both.tr("ATTENTION - %s", both.tr("%s, %s, %s", status,
                                             both.trp("%d error", "%d errors", errors, errors),
                                             both.trp("%d warning", "%d warnings", warnings, warnings)))


def restore_chain(cat, upto_id):
    """Exports needed to restore the state of export `upto_id`. Each file is restored only once
    (from the newest export that contains it)."""
    return gfs.chain(cat.runs(), upto_id)


def remove_runs(target_parent, run_ids, keep=None):
    """Delete retired exports (GFS cleanup, only after the user confirmed). Never deletes an
    export that a remaining export needs. Returns (removed folders, problems – shown text)."""
    target_parent = Path(target_parent).resolve()
    cat = Catalog(target_parent)
    try:
        allowed = {r.id: r for r in gfs.to_retire(cat.runs(), keep)}
        removed, problems = [], []
        for rid in run_ids:
            r = allowed.get(rid)
            if r is None:
                problems.append(tr("export %s is still needed - not removed", rid))
                continue
            folder = (target_parent / str(r.folder)).resolve()
            # only a real run folder, directly in this export folder (the catalog may be tampered)
            if not valid_run_folder(r.folder) or folder.parent != target_parent:
                problems.append(tr("%s: unexpected folder - not removed", r.folder))
                continue
            try:
                if folder.exists():
                    shutil.rmtree(folder)
                cat.mark_removed(rid)
                removed.append(r.folder)
            except OSError as e:
                problems.append(f"{r.folder}: {e}")
        return removed, problems
    finally:
        cat.close()


def folder_size(path):
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.stat(os.path.join(dirpath, fn)).st_size
            except OSError:
                pass
    return total


def perform_restore(target_parent, upto_id, restore_dir, cfg, cancel=None):
    target_parent = Path(target_parent)
    restore_dir = Path(restore_dir)
    cat = Catalog(target_parent)
    chain = restore_chain(cat, upto_id)
    if not chain:
        cat.close()
        raise ValueError(tr("No completed full export found - nothing to restore from."))
    plan, refused = {}, []
    for run in chain:                                  # later runs win
        for rel, (sz, _mt, sha) in cat.files_of([run.id]).items():
            if safe_rel(rel) is None or not valid_run_folder(run.folder):
                refused.append(rel)                    # would leave the restore folder
                continue
            plan[rel] = (run, sz, sha)
    cat.close()
    for rel in refused:
        ui.error(tr("Refused (the catalog points outside the folders): %s", repr(rel)))
    started = datetime.now()
    t0 = time.monotonic()
    tmp = restore_dir / ".restore-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    total = sum(sz for _, sz, _ in plan.values())
    ui.info(trp("Restoring %d file (%s) from: %s", "Restoring %d files (%s) from: %s", len(plan),
                len(plan), ui.human_size(total), " + ".join(r.folder for r in chain)))
    prog = ui.Progress(len(plan), total)
    rows, errors, status = [], 0, "COMPLETED"
    try:
        for i, (rel, (run, sz, sha)) in enumerate(sorted(plan.items()), 1):
            src, dst = inside(target_parent / run.folder, rel), inside(restore_dir, rel)
            if src is None or dst is None:
                st, got = both.tr("ERROR: path outside the export or restore folder - refused"), None
            else:
                st, got = _verified_copy(src, tmp, dst, sha, cfg, prog, cancel, overwrite=True)
            if not st.startswith("OK"):
                errors += 1
            rows.append([i, Path(rel).name, ui.human_size(sz), rel, run.folder, st, got or ""])
            prog.update(files_done=i, current=Path(rel).name)
    except (KeyboardInterrupt, Cancelled):
        status = "CANCELLED by user"
    finally:
        prog.finish()
        shutil.rmtree(tmp, ignore_errors=True)
    errors += len(refused)
    ok = status == "COMPLETED" and not errors
    verdict = (both.trp("RESTORE OK - %d file restored and verified.",
                        "RESTORE OK - %d files restored and verified.", len(rows), len(rows)) if ok
               else both.tr("ATTENTION - %s", both.trp("%s, %d file with problems", "%s, %d files with problems",
                                                       errors, status, errors)))
    sections = [(tr("General"), [(tr("Restored from"), str(target_parent)),
                                 (tr("Used exports"), "\n".join(f"{gfs.mode_name(r.type)}: {r.folder}"
                                                                for r in chain)),
                                 (tr("Restored to"), str(restore_dir)),
                                 (tr("Duration"), ui.human_duration(time.monotonic() - t0)),
                                 (tr("Average speed"),
                                  tr("%s/s", ui.human_size(prog.bytes / max(time.monotonic() - t0, 0.001))))])]
    base = unique_basename(restore_dir, "Restore report", started)          # file name: English
    paths = write_reports(restore_dir, base, tr("Restore %s - %s", target_parent.name,
                                                f"{started:%Y-%m-%d %H:%M}"),
                          ok, verdict, sections,
                          [tr("Nr"), tr("File"), tr("Size"), tr("Path"), tr("Taken from export"), tr("Status"),
                           tr("SHA-256")], rows)
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict
