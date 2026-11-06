"""Backup plan per backup drive (user request 2026-11-05): "simple" or "gfs".

simple  one growing folder per phone: <base>/<Phone - Owner>/2026/01.January-photos/... (as always)
gfs     Grandfather-Father-Son, the same layout as the second storage export:
        <base>/<Phone - Owner>/2026-11-05_10-00-00_full/2026/01.January-photos/...
                              /2026-11-20_18-30-00_incremental/...
                              /.phonebackup-export/catalog.sqlite   (runs + files)
                              /.phonebackup/index.sqlite            (what is backed up)
        The type of each backup is chosen by gfs.choose (full every 3 months, differential every
        month, incremental in between). New phone files go into the run folder; a full or
        differential run also gets the earlier files it must contain, copied on the same drive and
        verified - so photos deleted from the phone stay in every full. Restore + cleanup work like
        for the second storage.

Both plans can be mixed in one backup (e.g. simple on one drive, GFS on another).
"""

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import gfs, ui
from .backup import Dest
from .copier import Cancelled
from .export import EXPORT_DIR, Catalog, _verified_copy, has_catalog
from .index import INTERNAL_DIR, BackupIndex

SIMPLE, GFS = "simple", "gfs"
NAMES = {SIMPLE: "Simple", GFS: "Grandfather-Father-Son"}
DESCRIPTION = {
    SIMPLE: "one folder that grows – only new photos and videos are added",
    GFS: "dated full / differential / incremental backups (full every 3 months, differential "
         "monthly, incremental in between) – older states can be restored",
}


class PlanError(Exception):
    pass


def plan_of(cfg, base):
    return (cfg.get("dest_plans") or {}).get(str(base), SIMPLE)


def set_plan(cfg, base, plan):
    plans = dict(cfg.get("dest_plans") or {})
    if plan == SIMPLE:
        plans.pop(str(base), None)
    else:
        plans[str(base)] = plan
    cfg["dest_plans"] = plans


def folder_plan(set_dir):
    """Plan of an existing backup folder ('Phone - Owner'), None if there is none yet."""
    set_dir = Path(set_dir)
    if has_catalog(set_dir):
        return GFS
    if (set_dir / INTERNAL_DIR / "index.sqlite").is_file():
        return SIMPLE
    return None


def check_switch(base, parent_name, plan):
    """Error text when the drive already holds this phone's backup with the other plan."""
    have = folder_plan(Path(base) / parent_name)
    if have and have != plan:
        return (f"“{Path(base) / parent_name}” already holds a {NAMES[have].lower()} backup of this "
                f"phone. A {NAMES[plan]} backup needs its own folder – add another folder on the "
                f"drive (e.g. “PhoneBackups-GFS”) for it, or keep the plan “{NAMES[have]}”.")
    return None


class GfsIndex(BackupIndex):
    """Backup index of a GFS folder: a file counts as backed up when it is in the current state
    (the restore chain of the newest run, plus what this run wrote)."""

    def __init__(self, set_dir, state):
        super().__init__(set_dir)
        self.state = state

    def _there(self, rel):
        s = self.state.get(rel)
        return bool(s) and Path(s[0]).is_file()

    def has(self, source_path, size):
        row = self.db.execute("SELECT rel_path FROM files WHERE source_path=? AND size=?",
                              (source_path, size)).fetchone()
        return bool(row) and self._there(row[0])

    def find_by_sha(self, sha):
        for (rel,) in self.db.execute("SELECT rel_path FROM files WHERE sha256=?", (sha,)):
            if self._there(rel):
                return rel
        return None


@dataclass(eq=False)
class GfsDest(Dest):
    set_dir: Path = None
    cat: Catalog = None
    run_id: int = 0
    run_folder: str = ""
    mode: str = ""
    why: str = ""
    state: dict = field(default_factory=dict)        # rel -> (path, size, mtime, sha, run_id)
    prev_state: dict = field(default_factory=dict)
    last_full_id: int = None
    written_rels: set = field(default_factory=set)
    carried: int = 0
    carried_bytes: int = 0
    run_dropped: bool = False
    plan = GFS

    @property
    def home(self):
        return self.set_dir

    @property
    def report_dir(self):
        return self.set_dir if self.run_dropped else self.parent

    def existing(self, final):
        final = Path(final)
        if final.exists():
            return final
        try:
            rel = final.relative_to(self.parent).as_posix()
        except ValueError:
            return None
        s = self.state.get(rel)
        return Path(s[0]) if s and Path(s[0]).exists() else None

    def on_written(self, rel, size, mtime, sha):
        self.cat.add_file(self.run_id, rel, size, mtime, sha)
        self.state[rel] = (str(self.parent / rel), size, mtime, sha, self.run_id)
        self.written_rels.add(rel)

    def carry_list(self):
        """Earlier files this run must also contain (full: everything, differential: everything
        since the last full)."""
        if self.mode == "full":
            items = self.prev_state.items()
        elif self.mode == "differential":
            items = [(r, v) for r, v in self.prev_state.items() if v[4] != self.last_full_id]
        else:
            return []
        return [(r, v) for r, v in sorted(items) if r not in self.written_rels]

    def describe(self):
        return f"{NAMES[GFS]} – {gfs.ROLE[self.mode]} ({self.mode}): {self.why}"


def open_gfs(label, base, parent_name, started, now=None):
    set_dir = Path(base) / parent_name
    set_dir.mkdir(parents=True, exist_ok=True)
    cat = Catalog(set_dir)
    runs = gfs.active(cat.runs())
    mode, why = gfs.choose(runs, now or started)
    state, last_full = {}, None
    if runs:
        chain = gfs.chain(runs, runs[-1].id)
        last_full = chain[0].id if chain and chain[0].type == "full" else None
        for run in chain:
            for rel, (size, mtime, sha) in cat.files_of([run.id]).items():
                state[rel] = (str(set_dir / run.folder / rel), size, mtime, sha, run.id)
    folder = f"{started:%Y-%m-%d_%H-%M-%S}_{mode}"
    n = 2
    while (set_dir / folder).exists():
        folder = f"{started:%Y-%m-%d_%H-%M-%S}_{mode}_{n}"
        n += 1
    run_id = cat.new_run(mode, folder, started)
    d = GfsDest(label, Path(base), set_dir / folder, GfsIndex(set_dir, state), set_dir=set_dir,
                cat=cat, run_id=run_id, run_folder=folder, mode=mode, why=why, state=state,
                prev_state=dict(state), last_full_id=last_full)
    ui.info(f"  {label}: {d.describe()}")
    return d


def carry_bytes(d):
    return sum(v[1] for _, v in d.carry_list()) if isinstance(d, GfsDest) else 0


def finish_gfs(d, status, cfg, cancel=None):
    """After the phone files: copy the earlier files a full/differential run must contain, then
    close the run. Returns the (possibly changed) status for this destination."""
    if not d.alive:
        d.cat.finish_run(d.run_id, f"ABORTED ({d.problem})")
        return status
    todo = d.carry_list() if status == "COMPLETED" else []
    if todo:
        total = sum(v[1] for _, v in todo)
        ui.info(f"  {d.label}: building the {d.mode} backup – copying {len(todo)} earlier files "
                f"({ui.human_size(total)}) on the drive …")
        tmp = d.tmp
        tmp.mkdir(parents=True, exist_ok=True)
        phone_transfer = ui.last_transfer          # the summary shows the phone transfer
        prog = ui.Progress(len(todo), total)
        try:
            for rel, (src, size, mtime, sha, _rid) in todo:
                if cancel is not None and cancel.is_set():
                    status = "CANCELLED by user"
                    break
                token = prog.begin(Path(rel).name)
                try:
                    st, got = _verified_copy(src, tmp, d.parent / rel, sha, cfg, prog, cancel)
                finally:
                    prog.end(token)
                if got:
                    d.cat.add_file(d.run_id, rel, size, mtime, got)
                    d.carried += 1
                    d.carried_bytes += size
                if st.startswith("ERROR"):
                    d.errors += 1
                    ui.error(f"  {rel}: {st}")
        except Cancelled:
            status = "CANCELLED by user"
        except Exception as e:  # noqa: BLE001 - close the run and write the report anyway
            status = f"STOPPED - {type(e).__name__}: {e}"
            ui.error(f"  {d.label}: {status}")
        finally:
            prog.finish()
            ui.last_transfer = phone_transfer
            shutil.rmtree(tmp, ignore_errors=True)
    if d.mode == "incremental" and not d.written_rels and status == "COMPLETED" and not d.errors:
        d.cat.drop_run(d.run_id)          # nothing new: no empty incremental folder
        d.run_dropped = True
        ui.info(f"  {d.label}: nothing new – no new incremental backup needed.")
    else:
        run_status = status if not d.errors or status != "COMPLETED" else "COMPLETED WITH ERRORS"
        d.cat.finish_run(d.run_id, run_status)
    return status


def close(d):
    if isinstance(d, GfsDest):
        d.cat.close()
