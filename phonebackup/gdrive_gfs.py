"""Grandfather-Father-Son backups on Google Drive (user request 2026-11-05).

Google Drive can be used in two ways (the user chooses per export):
  mirror   a copy of the backup – only new files are uploaded (gdrive.perform_drive_export)
  GFS      dated full / differential / incremental backups like on a second HDD (this module)

Layout on Google Drive (separate from the mirror, both can exist side by side):
  My Drive/My Smartphone Media Backup/<Phone - Owner> (Grandfather-Father-Son)/
        2026-11-05_10-00-00_full/2026/01.January-photos/...
        2026-11-20_18-30-00_incremental/...
        .phonebackup-export/catalog.sqlite     (runs + files, the same catalog as on a HDD)

- The type of each export is chosen by gfs.choose (or by hand), restore chains and cleanup are the
  same as on a HDD (gfs.chain / gfs.to_retire).
- Every photo/video is STORED ONCE (user decision 2026-11-05: shortcuts). New or changed files are
  uploaded into the export where they first appear. Files a full/differential export must also
  contain are SHORTCUTS to the stored file (no upload, no extra storage, seconds); the stored file's
  SHA-256 (computed by Google) is checked against the catalog first.
- Cleanup never loses a file a remaining export needs: before an old export folder is deleted,
  every stored file in it that a remaining export links to is MOVED into that export (replacing
  the shortcut; the file id stays, so all other shortcuts keep working).
- Restore follows the shortcuts (downloads the stored file).
- The catalog is worked on in a local copy and uploaded after every change; Google Drive's copy is
  the reference (the next export downloads it first), so any computer can continue.
- Files that are already in the Copy (mirror) of the same backup on Google Drive are linked too
  (after the SHA-256 matched) – switching from Copy to Grandfather-Father-Son takes minutes. Those
  exports then rely on the Copy, which the app never deletes.
- Each run of the app works on its OWN copy of the catalog (a second window or computer can never
  replace it underneath – that broke an export on 2026-11-05).
- An export that stopped before its catalog was saved left its files without a record ("orphan"
  export folder). The next export reuses them: files with the same path, size and SHA-256 as in
  the backup are MOVED into the new export instead of uploaded again; the orphan folder is removed
  when nothing is left in it but its own reports.
- Nothing is deleted except retired exports after the user confirmed the cleanup.
"""

import hashlib
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import gfs, ui
from .copier import Cancelled, file_chunks
from .export import EXPORT_DIR, Catalog, _category, scan_backup
from .gdrive import (FOLDER_MIME, ROOT_NAME, STATUS_FULL, STATUS_SIGNIN_LOST, UPLOAD_WORKERS, Drive,
                     DriveError, DriveFull, NotSignedIn, _q, API, attention, category_label,
                     files_size)
from .i18n import N_, tr, trp
from .index import open_readonly_lookup
from .report import both, unique_basename, write_reports
from .safety import inside, safe_component, safe_rel, valid_run_folder

SUFFIX = " (Grandfather-Father-Son)"
CAT_REL = f"{EXPORT_DIR}/catalog.sqlite"
PREFIX = "gdrive-gfs:"                       # restore list entries: "gdrive-gfs:<Phone - Owner>"


class NoGfsBackup(DriveError):
    """There is no Grandfather-Father-Son backup of this phone on Google Drive (yet)."""
    code = "no_gfs_backup"


_MODES = (N_("full"), N_("differential"), N_("incremental"))          # shown as tr(mode)


def _role(mode):
    """'Grandfather (full)' in the chosen language."""
    return tr("%s (%s)", tr(gfs.ROLE[mode]), tr(mode))


def folder_name(set_name):
    return set_name + SUFFIX


def local_dir(set_name) -> Path:
    from .adbdownload import data_dir
    if safe_component(set_name) is None:          # a folder name from Google Drive: untrusted
        raise DriveError(tr("Unusable backup name on Google Drive: %s", repr(set_name)), "bad_name")
    return Path(data_dir()) / "gdrive-gfs" / set_name


def reports_dir(set_name) -> Path:
    from .gdrive import reports_dir as rd
    return rd(folder_name(set_name))


class DriveSet:
    """One phone's GFS folder on Google Drive + the local working copy of its catalog."""

    def __init__(self, drive, set_name, create=True):
        self.drive, self.name = drive, set_name
        root = drive.find_or_create_folder(ROOT_NAME, None, app_key="root")
        self.root = root
        if create:
            self.id = drive.find_or_create_folder(folder_name(set_name), root)
        else:
            r = drive.call("GET", f"{API}/files", {
                "q": f"name = {_q(folder_name(set_name))} and mimeType = '{FOLDER_MIME}' and "
                     f"trashed = false and {_q(root)} in parents", "fields": "files(id)",
                "spaces": "drive"})
            if not r.get("files"):
                raise NoGfsBackup(tr("No Grandfather-Father-Son backup of %s on Google Drive.", set_name))
            self.id = r["files"][0]["id"]
        self.remote, self.folders = drive.list_tree(self.id)
        base = local_dir(set_name)
        _clean_old_work(base)
        # own working copy – never shared with another window/computer
        self.local = base / f"work-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        cat_file = self.local / CAT_REL
        cat_file.parent.mkdir(parents=True, exist_ok=True)
        r = self.remote.get(CAT_REL)
        if r:                                        # Google Drive's catalog is the reference
            drive.download(r["id"], cat_file, r["size"])
            _check_catalog(cat_file)

    def catalog(self):
        return Catalog(self.local)

    def close(self):
        shutil.rmtree(self.local, ignore_errors=True)

    def orphans(self, known_folders):
        """Export folders on Google Drive that the catalog does not know (an export that stopped
        before its catalog was saved): {folder: {rel: entry}} with only real files."""
        out = {}
        for key, v in self.remote.items():
            top, _, rel = key.partition("/")
            if rel and "target" not in v and top not in known_folders and not top.startswith("."):
                out.setdefault(top, {})[rel] = v
        return out

    def save_catalog(self):
        """Upload the catalog (new file first, then the old one is removed)."""
        old = self.remote.get(CAT_REL)
        pid = self.drive.ensure_path(self.folders, EXPORT_DIR)
        fid, _sha, _g = self.drive.upload(self.local / CAT_REL, pid, "catalog.sqlite")
        if old and old["id"] != fid:
            self.drive.delete(old["id"])
        self.remote[CAT_REL] = {"id": fid, "size": (self.local / CAT_REL).stat().st_size, "sha256": ""}

    def mirror_files(self):
        """Files of the Copy (mirror) of the same backup: rel -> {"id","size","sha256"}."""
        r = self.drive.call("GET", f"{API}/files", {
            "q": f"name = {_q(self.name)} and mimeType = '{FOLDER_MIME}' and trashed = false and "
                 f"{_q(self.root)} in parents", "fields": "files(id)", "spaces": "drive"})
        if not r.get("files"):
            return {}
        return self.drive.list_tree(r["files"][0]["id"])[0]

    def file_id(self, run_folder, rel):
        """Id of the STORED file behind run_folder/rel (a shortcut is followed)."""
        r = self.remote.get(f"{run_folder}/{rel}")
        if not r:
            return None
        return r.get("target") or r["id"]

    def mirror(self):
        if not hasattr(self, "_mirror"):
            self._mirror = self.mirror_files()
        return self._mirror

    def stored_sha(self, file_id):
        """Google's SHA-256 of a stored file (in this GFS folder or in the Copy), None = gone."""
        if not hasattr(self, "_by_id"):
            self._by_id = {v["id"]: v for v in list(self.remote.values()) + list(self.mirror().values())
                           if "target" not in v}
        v = self._by_id.get(file_id)
        return v["sha256"] if v else None

    def stored_bytes(self, run_folder):
        """Storage really used by one export folder (shortcuts use none)."""
        pre = run_folder + "/"
        return sum(v["size"] for k, v in self.remote.items() if k.startswith(pre) and "target" not in v)


def _check_catalog(path):
    """The catalog comes from Google Drive: it must be an intact SQLite file with the expected
    tables, nothing else (no triggers / views that could run code-like SQL)."""
    import sqlite3
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            db.execute("PRAGMA trusted_schema=OFF")
            ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            kinds = {(t, n) for t, n in db.execute("SELECT type, name FROM sqlite_master")}
        finally:
            db.close()
    except sqlite3.Error as e:
        raise DriveError(tr("The catalog on Google Drive is damaged: %s", e), "catalog") from e
    if not ok or any(t in ("trigger", "view") for t, _ in kinds) or not {
            ("table", "runs"), ("table", "files")} <= kinds:
        raise DriveError(tr("The catalog on Google Drive is damaged or was changed – not used."),
                         "catalog")


def _clean_old_work(base):
    """Remove working copies left by app runs that ended long ago (older than 2 days)."""
    try:
        for d in base.iterdir():
            if d.name.startswith("work-") and time.time() - d.stat().st_mtime > 2 * 86400:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def list_sets(drive):
    """Names ('Phone - Owner') of the GFS backups on Google Drive."""
    root = drive.find_or_create_folder(ROOT_NAME, None, app_key="root")
    r = drive.call("GET", f"{API}/files", {
        "q": f"mimeType = '{FOLDER_MIME}' and trashed = false and {_q(root)} in parents",
        "fields": "files(name)", "spaces": "drive", "pageSize": 1000})
    return sorted(n for n in (f["name"][:-len(SUFFIX)] for f in r.get("files", [])
                              if f["name"].endswith(SUFFIX)) if safe_component(n))


def runs_of(set_name, cfg, drive=None):
    """(runs, storage used per run id) of a GFS backup on Google Drive."""
    ds = DriveSet(drive or Drive(cfg), set_name, create=False)
    cat = ds.catalog()
    try:
        runs = cat.runs()
        sizes = {r.id: ds.stored_bytes(r.folder) for r in runs}
        return runs, sizes
    finally:
        cat.close()
        ds.close()


def _state(cat):
    """Current state = restore chain of the newest export: rel -> (size, mtime, sha, run)."""
    runs = gfs.active(cat.runs())
    if not runs:
        return {}, None
    chain = gfs.chain(runs, runs[-1].id)
    state = {}
    for run in chain:
        for rel, (size, mtime, sha) in cat.files_of([run.id]).items():
            state[rel] = (size, mtime, sha, run)
    full = chain[0] if chain and chain[0].type == "full" else None
    return state, full


def plan_items(mode, current, state, full_files):
    """What the new export must contain: [(rel, size, mtime, action)], action 'upload' or 'link'.
    current: rel -> (size, mtime) of the backup; state: see _state; full_files: rel -> (size,
    mtime, sha) of the last full export."""
    def same(rel):
        s = state.get(rel)
        return s is not None and rel in current and (s[0], s[1]) == current[rel]

    def version(rel):
        return current[rel] if rel in current else state[rel][:2]

    everything = set(current) | set(state)
    if mode == "full":
        rels = everything
    elif mode == "differential":
        rels = {r for r in everything
                if r not in full_files or (full_files[r][0], full_files[r][1]) != version(r)}
    else:
        rels = {r for r in current if not same(r)}
    items = []
    for rel in sorted(rels):
        if rel in current and not same(rel):
            items.append((rel, current[rel][0], current[rel][1], "upload"))
        else:
            s = state[rel]
            items.append((rel, s[0], s[1], "link"))
    return items


def _perform_drive_gfs_export(_sets, source_parent, cfg, mode="auto", cancel=None, drive=None,
                             report_dir=None, now=None):
    """Grandfather-Father-Son export of a backup folder to Google Drive.
    Returns (status, report paths, verdict)."""
    source_parent = Path(source_parent)
    name = source_parent.name
    drive = drive or Drive(cfg)
    started = datetime.now()
    t0 = time.monotonic()
    acct = drive.account()
    ui.info(tr("Google Drive: %s", acct["email"]))
    ui.info(tr("Reading the Grandfather-Father-Son backups on Google Drive …"))
    ds = DriveSet(drive, name)
    _sets.append(ds)
    cat = ds.catalog()
    chosen_by = None
    if mode == "auto":
        mode, why = gfs.choose(cat.runs(), now)
        chosen_by = tr("Grandfather-Father-Son scheme: %s because %s", _role(mode), why)
        ui.info(chosen_by)
    state, full = _state(cat)
    if mode != "full" and full is None:
        cat.close()
        raise ValueError(tr("A differential or incremental export needs a full export first."))
    full_files = cat.files_of([full.id]) if full else {}

    ui.info(tr("Scanning the backup folder …"))
    current = scan_backup(source_parent)
    known = open_readonly_lookup(source_parent)
    items = plan_items(mode, current, state, full_files)
    missing = {it[0] for it in items if it[3] == "link"
               and ds.stored_sha(ds.file_id(state[it[0]][3].folder, it[0]) or "") is None}
    if missing:                    # deleted on Google Drive by hand: upload again when possible
        items = [(r, s, m, ("upload" if r in current else "lost") if r in missing else a)
                 for r, s, m, a in items]
    mirror = ds.mirror() if any(it[3] == "upload" for it in items) else {}
    if mirror:                     # already in the Copy on Google Drive: link to it, if identical
        items = [(r, s, m, "mirror" if a == "upload" and mirror.get(r, {}).get("size") == s
                  and mirror[r].get("sha256") else a) for r, s, m, a in items]
        n_m = sum(1 for it in items if it[3] == "mirror")
        if n_m:
            ui.info("  " + trp("%d of them is already in the Copy on Google Drive – linked there "
                               "instead of uploaded (when the SHA-256 matches).",
                               "%d of them are already in the Copy on Google Drive – linked there "
                               "instead of uploaded (when the SHA-256 matches).", n_m, n_m))
    orphan = {}                    # rel -> (folder, entry): files of an interrupted earlier export
    for of, files in sorted(ds.orphans({r.folder for r in cat.runs()}).items()):
        for rel, v in files.items():
            orphan[rel] = (of, v)
    if orphan:
        items = [(r, s, m, "adopt" if a in ("upload", "mirror") and r in orphan
                  and orphan[r][1]["size"] == s and orphan[r][1]["sha256"] else a)
                 for r, s, m, a in items]
        n_o = sum(1 for it in items if it[3] == "adopt")
        if n_o:
            ui.info("  " + trp("%d of them was already uploaded by an earlier export that did not "
                               "finish – it is reused (moved, not uploaded again) when the SHA-256 "
                               "matches.",
                               "%d of them were already uploaded by an earlier export that did not "
                               "finish – they are reused (moved, not uploaded again) when the SHA-256 "
                               "matches.", n_o, n_o))
    up = [it for it in items if it[3] in ("upload", "mirror", "adopt")]
    cp = [it for it in items if it[3] == "link"]
    up_bytes = sum(it[1] for it in up)
    cp_bytes = sum(it[1] for it in cp)
    ui.info("  " + trp("%s: %d file – %d to upload (%s), %d already stored on Google Drive – "
                       "linked (shortcuts, no extra space).",
                       "%s: %d files – %d to upload (%s), %d already stored on Google Drive – "
                       "linked (shortcuts, no extra space).", len(items), _role(mode), len(items),
                       len(up), ui.human_size(up_bytes), len(cp)))
    if mode == "incremental" and not items:
        cat.close()
        verdict = both.tr("NOTHING NEW - every file of the backup is already in the Google Drive backups.")
        ui.ok(verdict)
        return "COMPLETED", [], verdict
    if acct["free"] is not None and up_bytes > acct["free"]:
        cat.close()
        raise DriveError(tr("Not enough space on Google Drive: %s free, %s needed.",
                            ui.human_size(acct["free"]), ui.human_size(up_bytes)), "no_space")

    folder = f"{started:%Y-%m-%d_%H-%M-%S}_{mode}"
    n = 2
    while folder in ds.folders:
        folder = f"{started:%Y-%m-%d_%H-%M-%S}_{mode}_{n}"
        n += 1
    run_id = cat.new_run(mode, folder, started)
    prog = ui.Progress(len(items), up_bytes + cp_bytes)
    stop = threading.Event()
    fatal = []
    adopted = set()

    def one(nr, rel, sz, mt, action):
        if stop.is_set() or (cancel is not None and cancel.is_set()):
            return None
        folder_rel, _, fname = rel.rpartition("/")
        token = prog.begin(fname)
        sha, done = "", False
        try:
            if action == "lost":
                return [nr, fname, tr(_category(rel)), ui.human_size(sz), sz, rel,
                        "ERROR: no longer on Google Drive and not in the backup – cannot be added", "",
                        action, mt]
            pid = drive.ensure_path(ds.folders, f"{folder}/{folder_rel}" if folder_rel else folder)
            if action == "adopt":
                k = known.get(rel)
                sha = k[1] if k and k[0] == sz else None
                if not sha:
                    h = hashlib.sha256()
                    for b in file_chunks(source_parent / rel):
                        h.update(b)
                    sha = h.hexdigest()
                of, v = orphan[rel]
                if v["sha256"] == sha:
                    drive.move(v["id"], ds.folders[f"{of}/{folder_rel}" if folder_rel else of], pid)
                    adopted.add((of, rel))
                    prog.update(add_bytes=sz)
                    st = "OK - reused from an earlier unfinished upload (moved, SHA-256 checked)"
                    done = True
                    return [nr, fname, tr(_category(rel)), ui.human_size(sz), sz, rel, st, sha, "adopt",
                            mt]
                action = "upload"                    # other data there: upload
            if action == "mirror":
                k = known.get(rel)
                sha = k[1] if k and k[0] == sz else None
                if not sha:                          # not in the index: read the backup file
                    h = hashlib.sha256()
                    for b in file_chunks(source_parent / rel):
                        h.update(b)
                    sha = h.hexdigest()
                m = mirror[rel]
                if m["sha256"] == sha:
                    drive.shortcut(m["id"], pid, fname)
                    prog.update(add_bytes=sz)
                    st = "OK - linked to the file in the Copy on Google Drive (SHA-256 checked)"
                    done = True
                    return [nr, fname, tr(_category(rel)), ui.human_size(sz), sz, rel, st, sha, "link",
                            mt]
                action = "upload"                    # the Copy holds other data: upload
            if action == "upload":
                k = known.get(rel)
                expected = k[1] if k and k[0] == sz else None
                _, sha, gsha = drive.upload(source_parent / rel, pid, fname,
                                            on_bytes=lambda b: prog.update(add_bytes=b), cancel=cancel)
                if gsha and gsha != sha:
                    st = "ERROR: Google Drive stored different data (SHA-256 mismatch)"
                elif expected and expected != sha:
                    st = ("WARNING: uploaded, but the backup file differs from the SHA-256 recorded "
                          "when it was backed up - the backup drive may be damaged")
                else:
                    st = "OK - uploaded and verified"
            else:
                s = state[rel]
                fid = ds.file_id(s[3].folder, rel)
                sha = s[2]
                gsha = ds.stored_sha(fid)
                if gsha and gsha != sha:
                    st = "ERROR: the stored file on Google Drive differs (SHA-256 mismatch) - not linked"
                else:
                    drive.shortcut(fid, pid, fname)
                    st = f"OK - linked to the stored file (SHA-256 checked, from {s[3].folder})"
                prog.update(add_bytes=sz)
            done = True
        except Cancelled:
            stop.set()
            return None
        except NotSignedIn as e:
            fatal.append(e)
            stop.set()
            return None
        except (DriveError, OSError) as e:
            st = f"ERROR: {e}"
            if isinstance(e, DriveFull):
                fatal.append(STATUS_FULL)
                stop.set()
        finally:
            prog.end(token, done=done)
        return [nr, fname, tr(_category(rel)), ui.human_size(sz), sz, rel, st, sha, action, mt]

    rows, errors, warnings, by_cat = [], 0, 0, {}
    status = "COMPLETED"
    try:
        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            futures = [pool.submit(one, nr, *it) for nr, it in enumerate(items, 1)]
            for f in futures:
                row = f.result()
                if row is None:
                    continue
                st, sz, rel, sha, mt = row[6], row[4], row[5], row[7], row[9]
                if st.startswith("ERROR"):
                    errors += 1
                else:
                    if st.startswith("WARNING"):
                        warnings += 1
                    cat.add_file(run_id, rel, sz, mt, sha)       # catalog only in this thread
                    c = _category(rel)
                    by_cat.setdefault(c, [0, 0, 0])
                    by_cat[c][0] += 1
                    by_cat[c][1] += sz
                    if row[8] == "upload":
                        by_cat[c][2] += sz
                rows.append(row[:8] + [{"upload": tr("uploaded"), "adopt": tr("reused (moved)")}.get(
                    row[8], tr("linked (shortcut)"))])
    finally:
        prog.finish()
        if any(isinstance(e, NotSignedIn) for e in fatal):
            status = STATUS_SIGNIN_LOST
        elif cancel is not None and cancel.is_set():
            status = "CANCELLED by user"
        elif fatal:
            status = fatal[0]
        if status == "COMPLETED" and errors:
            status = "COMPLETED WITH ERRORS"
        cat.finish_run(run_id, status)
        cat.close()
        cat_problem = None
        # unfinished earlier export folders that are now empty (all reused): remove them
        for of in sorted({o for o, _ in adopted}):
            left = [r for r in ds.orphans(set()).get(of, {}) if (of, r) not in adopted
                    and not ("/" not in r and r.startswith("Google Drive "))]      # its reports
            if not left and of in ds.folders:
                try:
                    drive.delete(ds.folders[of])
                    ui.info("  " + tr("Removed the empty folder of the unfinished export %s.", of))
                except DriveError as e:
                    ui.warn(f"  {of}: {e}")
            elif left:
                ui.warn("  " + trp("%s: %d file of the unfinished export was not reused and is kept.",
                                   "%s: %d files of the unfinished export were not reused and are "
                                   "kept.", len(left), of, len(left)))
        try:
            ds.save_catalog()
        except (DriveError, OSError) as e:
            cat_problem = tr("the catalog could not be saved on Google Drive (%s)", e)
            ui.error(tr("Google Drive: %s", cat_problem))

    duration = time.monotonic() - t0
    if cat_problem:
        warnings += 1
    ok = status == "COMPLETED" and not warnings
    n = sum(v[0] for v in by_cat.values())
    b = sum(v[1] for v in by_cat.values())
    ub = sum(v[2] for v in by_cat.values())
    verdict = (both.trp("EVERYTHING EXPORTED CORRECTLY - %s export on Google Drive: %d file (%s) verified "
                   "with SHA-256.",
                   "EVERYTHING EXPORTED CORRECTLY - %s export on Google Drive: %d files (%s) verified "
                   "with SHA-256.", n, _role(mode), n, ui.human_size(b)) if ok else
               attention(status, errors, warnings))
    if mode == "full":
        basis = tr("none (full export of everything)")
    elif mode == "differential":
        basis = tr("last full export: %s", full.folder)
    else:
        basis = tr("the current state since the last full export (%s)", full.folder)
    sections = [
        (tr("General"), [(tr("Export type"), tr("Google Drive – %s (%s)", tr(mode), tr(gfs.ROLE[mode]))),
                         (tr("Chosen by"), chosen_by or tr("manual choice")),
                         (tr("Status"), tr(status)),
                         (tr("Google account"), acct["email"]),
                         (tr("Source (backup folder)"), str(source_parent)),
                         (tr("Target on Google Drive"),
                          f"My Drive/{ROOT_NAME}/{folder_name(name)}/{folder}"),
                         (tr("Compared with"), basis),
                         (tr("Started"), f"{started:%Y-%m-%d %H:%M:%S}"),
                         (tr("Duration"), ui.human_duration(duration)),
                         (tr("Average upload speed"),
                          tr("%s/s", ui.human_size(ub / duration if duration > 0 else 0)))]
         + ([(tr("Catalog"), tr("PROBLEM: %s", cat_problem))] if cat_problem else [])),
        (tr("Data exported"), [(tr("Total"), files_size(n, b)),
                               (tr("Uploaded"), ui.human_size(ub)),
                               (tr("Linked (shortcuts, no extra space)"), ui.human_size(b - ub))] +
         [(category_label(c), files_size(v[0], v[1])) for c, v in sorted(by_cat.items())] +
         [(tr("Files in backup"), str(len(current))), (tr("Errors"), str(errors)),
          (tr("Warnings"), str(warnings))]),
    ]
    columns = [tr("Nr"), tr("File"), tr("Type"), tr("Size"), tr("Bytes"), tr("Path in backup"),
               tr("Status"), tr("SHA-256"), tr("How")]
    rdir = Path(report_dir) if report_dir else reports_dir(name)
    base = unique_basename(rdir, f"Google Drive {mode} export {name}", started)
    paths = write_reports(rdir, base, tr("Google Drive %s export %s - %s", tr(mode), name,
                                         f"{started:%Y-%m-%d %H:%M}"),
                          ok, verdict, sections, columns, rows)
    try:                                         # the report also goes into the run folder
        pid = drive.ensure_path(ds.folders, folder)
        for p in paths:
            drive.upload(p, pid, p.name)
    except (DriveError, OSError, Cancelled) as e:
        ui.warn(tr("Report could not be uploaded to Google Drive: %s", e))
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict


def _remove_runs(_sets, set_name, cfg, run_ids, keep=None, drive=None):
    """GFS cleanup on Google Drive (after the user confirmed): deletes retired export folders.
    Never one a remaining export needs; stored files that a remaining export links to are moved
    into that export first. Returns (removed folders, problems, bytes freed)."""
    ds = DriveSet(drive or Drive(cfg), set_name, create=False)
    _sets.append(ds)
    cat = ds.catalog()
    removed, problems, freed = [], [], 0
    try:
        runs = cat.runs()
        allowed = {r.id: r for r in gfs.to_retire(runs, keep)}
        going = {allowed[i].folder for i in run_ids if i in allowed}
        order = {r.folder: r.id for r in runs}
        # shortcuts in the exports that stay: stored file id -> [(key, run id)]
        links = {}
        for key, v in ds.remote.items():
            top = key.split("/", 1)[0]
            if "target" in v and top in order and top not in going:
                links.setdefault(v["target"], []).append((key, order[top]))
        for rid in run_ids:
            r = allowed.get(rid)
            if r is None:
                problems.append(tr("export %s is still needed - not removed", rid))
                continue
            if not valid_run_folder(r.folder):           # the catalog may be tampered
                problems.append(tr("%s: unexpected folder - not removed", r.folder))
                continue
            try:
                moved = 0
                pre = r.folder + "/"
                for key, v in sorted(ds.remote.items()):
                    if not key.startswith(pre) or "target" in v:
                        continue
                    users = links.get(v["id"])
                    if not users:
                        freed += v["size"]
                        continue
                    # still needed: move it to the newest export that links to it
                    dest_key, _ = max(users, key=lambda u: u[1])
                    shortcut = ds.remote[dest_key]
                    ds.drive.move(v["id"], ds.folders[key.rpartition("/")[0]],
                                  ds.folders[dest_key.rpartition("/")[0]])
                    ds.drive.delete(shortcut["id"])
                    ds.remote[dest_key] = v
                    links[v["id"]] = [u for u in users if u[0] != dest_key]
                    moved += 1
                fid = ds.folders.get(r.folder)
                if fid:
                    ds.drive.delete(fid)
                for key in [k for k in ds.remote if k.startswith(pre)]:
                    del ds.remote[key]
                cat.mark_removed(rid)
                removed.append(r.folder)
                if moved:
                    ui.info("  " + trp("%s: %d file that newer exports still use was moved into "
                                       "them (not deleted).",
                                       "%s: %d files that newer exports still use were moved into "
                                       "them (not deleted).", moved, r.folder, moved))
            except DriveError as e:
                problems.append(f"{r.folder}: {e}")
    finally:
        cat.close()
        if removed:
            ds.save_catalog()
    return removed, problems, freed


def _perform_restore(_sets, set_name, upto_id, restore_dir, cfg, cancel=None, drive=None):
    """Download the state of one GFS export from Google Drive into a folder (verified)."""
    restore_dir = Path(restore_dir)
    drive = drive or Drive(cfg)
    ds = DriveSet(drive, set_name, create=False)
    _sets.append(ds)
    cat = ds.catalog()
    chain = gfs.chain(cat.runs(), upto_id)
    if not chain:
        cat.close()
        raise ValueError(tr("No completed full export found - nothing to restore from."))
    plan, refused = {}, []
    for run in chain:                                  # later runs win
        for rel, (sz, mt, sha) in cat.files_of([run.id]).items():
            if safe_rel(rel) is None or not valid_run_folder(run.folder):
                refused.append(rel)                    # the catalog points outside the folders
                continue
            plan[rel] = (run, sz, mt, sha)
    cat.close()
    for rel in refused:
        ui.error(tr("Refused (the catalog points outside the restore folder): %s", repr(rel)))
    started = datetime.now()
    t0 = time.monotonic()
    tmp = restore_dir / ".restore-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    total = sum(v[1] for v in plan.values())
    ui.info(trp("Restoring %d file (%s) from Google Drive: %s",
                "Restoring %d files (%s) from Google Drive: %s", len(plan), len(plan),
                ui.human_size(total), " + ".join(r.folder for r in chain)))
    prog = ui.Progress(len(plan), total)
    rows, errors, status = [], 0, "COMPLETED"
    try:
        for i, (rel, (run, sz, mt, sha)) in enumerate(sorted(plan.items()), 1):
            token = prog.begin(Path(rel).name)
            part = tmp / f"{i}.part"
            try:
                fid = ds.file_id(run.folder, rel)          # a shortcut is followed
                if not fid:
                    raise DriveError(tr("missing on Google Drive"), "missing")
                got = drive.download(fid, part, sz, on_bytes=lambda b: prog.update(add_bytes=b),
                                     cancel=cancel)
                final = inside(restore_dir, rel)
                if got != sha:
                    st = "ERROR: downloaded data differs (SHA-256 mismatch)"
                    part.unlink()
                elif final is None:
                    st = "ERROR: path outside the restore folder - refused"
                    part.unlink()
                else:
                    final.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(part, final)
                    os.utime(final, (mt, mt))
                    st = "OK - downloaded and verified"
            except (DriveError, OSError) as e:          # one file never stops the restore
                got, st = "", f"ERROR: {e}"
                try:
                    part.unlink()
                except OSError:
                    pass
            finally:
                prog.end(token)
            if not st.startswith("OK"):
                errors += 1
            rows.append([i, Path(rel).name, ui.human_size(sz), rel, run.folder, st, got or ""])
    except (KeyboardInterrupt, Cancelled):
        status = "CANCELLED by user"
    finally:
        prog.finish()
        shutil.rmtree(tmp, ignore_errors=True)
    errors += len(refused)
    ok = status == "COMPLETED" and not errors
    verdict = (both.trp("RESTORE OK - %d file downloaded from Google Drive and verified.",
                   "RESTORE OK - %d files downloaded from Google Drive and verified.",
                   len(rows), len(rows)) if ok
               else tr("ATTENTION - %s, %s", tr(status),
                       trp("%d file with problems", "%d files with problems", errors, errors)))
    dur = time.monotonic() - t0
    sections = [(tr("General"), [
        (tr("Restored from"), tr("Google Drive: %s", f"My Drive/{ROOT_NAME}/{folder_name(set_name)}")),
        (tr("Used exports"), "\n".join(f"{tr(r.type)}: {r.folder}" for r in chain)),
        (tr("Restored to"), str(restore_dir)),
        (tr("Duration"), ui.human_duration(dur)),
        (tr("Average speed"), tr("%s/s", ui.human_size(prog.bytes / max(dur, 0.001))))])]
    base = unique_basename(restore_dir, "Restore report", started)
    paths = write_reports(restore_dir, base,
                          tr("Restore %s from Google Drive - %s", set_name, f"{started:%Y-%m-%d %H:%M}"),
                          ok, verdict, sections,
                          [tr("Nr"), tr("File"), tr("Size"), tr("Path"), tr("Taken from export"),
                           tr("Status"), tr("SHA-256")], rows)
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict


def _closing(fn):
    def run(*args, **kw):
        sets = []
        try:
            return fn(sets, *args, **kw)
        finally:
            for ds in sets:
                ds.close()
    run.__name__ = fn.__name__.lstrip("_")
    run.__doc__ = fn.__doc__
    return run


perform_drive_gfs_export = _closing(_perform_drive_gfs_export)
remove_runs = _closing(_remove_runs)
perform_restore = _closing(_perform_restore)
